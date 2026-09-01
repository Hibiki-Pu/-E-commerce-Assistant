import csv
import hashlib
import io
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from werkzeug.test import EnvironBuilder

from backend.app import create_app
from backend.db import DEFAULT_DB
from backend.public_financials import FIELDS, PACKAGE, read_upload


class PublicFinancialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.public_db = Path(self.temp.name) / 'public.sqlite3'
        self.client = create_app(public_db_path=self.public_db).test_client()
        self.original_hash = hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest(), self.original_hash)
        self.temp.cleanup()

    def content(self, kind='annual'):
        return (PACKAGE / (kind + '_data.csv')).read_bytes()

    def post(self, content=None, kind='annual', action='preview', filename='data.csv', headers=None):
        with closing(EnvironBuilder(path='/api/public-financials/' + action, method='POST',
                            data={'dataset_type': kind, 'file': (io.BytesIO(content if content is not None else self.content(kind)), filename)},
                            headers=headers if headers is not None else {'X-Import-Request': 'commerce-insight'})) as builder:
            environ = builder.get_environ()
            try:
                return self.client.open(environ)
            finally:
                environ['wsgi.input'].close()

    def mutate(self, key, value):
        rows = list(csv.reader(io.StringIO(self.content().decode('utf-8-sig'))))
        rows[1][FIELDS.index(key)] = value
        output = io.StringIO(newline='')
        csv.writer(output).writerows(rows)
        return output.getvalue().encode('utf-8-sig')

    def test_preview_is_read_only_and_matches_csv_xlsx(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['rows'], 44)
        self.assertFalse(self.public_db.exists())
        workbook = (PACKAGE / 'jihong_public_financials.xlsx').read_bytes()
        for kind, count in [('annual', 44), ('quarterly', 64), ('business', 24)]:
            with self.subTest(kind=kind):
                csv_facts, csv_errors = read_upload(self.content(kind), 'test.csv', kind)
                xlsx_facts, xlsx_errors = read_upload(workbook, 'test.xlsx', kind)
                self.assertEqual(csv_facts, xlsx_facts)
                self.assertEqual(len(csv_facts), count)
                self.assertEqual(csv_errors + xlsx_errors, [])

    def test_import_all_132_and_reconcile_24(self):
        workbook = (PACKAGE / 'jihong_public_financials.xlsx').read_bytes()
        for kind, count in [('annual', 44), ('quarterly', 64), ('business', 24)]:
            result = self.post(workbook, kind, 'commit', 'test.xlsx')
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(result.json['inserted'], count)
        result = self.client.get('/api/public-financials').json
        self.assertEqual(len(result['facts']), 132)
        self.assertEqual(len(result['checks']), 24)
        self.assertTrue(all(check['status'] == 'passed' for check in result['checks']))
        self.assertEqual(self.post(action='commit').json['inserted'], 0)
        self.assertEqual(self.post().json['duplicates'], 44)

    def test_invalid_row_rejects_whole_batch(self):
        for key, value in [('value', '1,000.00'), ('value', '0.001'), ('value', ''), ('value', 'NaN'), ('value', '=1+2'), ('value', '1e8'), ('value', '1000000000001'), ('period', '2026'), ('source_report_year', '2025'), ('source_page', '0'), ('company_code', 'UNKNOWN'), ('source_url', 'https://evil.example/1.pdf'), ('unit', '万元'), ('dataset_type', 'quarterly')]:
            with self.subTest(key=key, value=value):
                result = self.post(self.mutate(key, value), action='commit')
                self.assertEqual(result.status_code, 422)
                self.assertEqual(result.json['errors'][0]['row'], 2)
                self.assertFalse(self.public_db.exists())

    def test_conflict_is_atomic_and_preserves_source(self):
        self.assertEqual(self.post(action='commit').status_code, 200)
        before = self.public_db.read_bytes()
        result = self.post(self.mutate('value', '100.00'), action='commit')
        self.assertEqual(result.status_code, 422)
        self.assertEqual(before, self.public_db.read_bytes())
        self.assertEqual(len(self.client.get('/api/public-financials').json['facts']), 44)

    def test_reconciliation_rejects_wrong_quarter(self):
        self.post(action='commit')
        rows = list(csv.reader(io.StringIO(self.content('quarterly').decode('utf-8-sig'))))
        rows[1][FIELDS.index('value')] = '1.00'
        output = io.StringIO(newline='')
        csv.writer(output).writerows(rows)
        result = self.post(output.getvalue().encode('utf-8-sig'), kind='quarterly', action='commit')
        self.assertEqual(result.status_code, 422)
        self.assertIn('与年度值不一致', result.json['errors'][0]['message'])
        self.assertEqual(len(self.client.get('/api/public-financials').json['facts']), 44)

    def test_headers_empty_encoding_and_size(self):
        for content, filename in [(b'', 'data.csv'), (b'wrong,header\n1,2', 'data.csv'), ('中文'.encode('gbk'), 'data.csv'), (b'x', 'data.xls'), (b'notzip', 'data.xlsx')]:
            with self.subTest(filename=filename, content=content):
                self.assertEqual(self.post(content, filename=filename).status_code, 400)
        response = self.post(b'x' * (6 * 1024 * 1024))
        self.assertEqual(response.status_code, 413)
        response.close()

    def test_request_protection_and_download_allowlist(self):
        self.assertEqual(self.post(headers={}).status_code, 403)
        self.assertEqual(self.post(headers={'X-Import-Request': 'commerce-insight', 'Origin': 'https://untrusted.example'}).status_code, 403)
        self.assertEqual(self.post(headers={'X-Import-Request': 'commerce-insight', 'Origin': 'http://127.0.0.1:5173'}).status_code, 200)
        self.assertEqual(self.client.get('/api/public-financials/files/demo.sqlite3').status_code, 404)
        response = self.client.get('/api/public-financials/files/annual_data.csv')
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertFalse(self.public_db.exists())

    def test_excel_formula_and_oversized_archive_rejected(self):
        original = (PACKAGE / 'jihong_public_financials.xlsx').read_bytes()
        with ZipFile(io.BytesIO(original)) as archive:
            entries = {info.filename: archive.read(info) for info in archive.infolist()}
        # 只构造内存测试 ZIP，不生成/修改交付工作簿。
        replacements = 0
        for name, data in entries.items():
            if name.startswith('xl/worksheets/sheet'):
                replacements += data.count(b'<x:v>5375883625.69</x:v>')
                entries[name] = data.replace(b'<x:v>5375883625.69</x:v>', b'<x:f>1+2</x:f><x:v>3</x:v>')
        self.assertGreater(replacements, 0)
        content = io.BytesIO()
        with ZipFile(content, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        response = self.post(content.getvalue(), filename='test.xlsx')
        self.assertEqual(response.status_code, 400)
        self.assertIn('不接受公式', response.json['error'])
        oversized = io.BytesIO()
        with ZipFile(oversized, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('large.xml', b'x' * (21 * 1024 * 1024))
        self.assertEqual(self.post(oversized.getvalue(), filename='oversized.xlsx').status_code, 400)

    def test_missing_facts_stay_pending(self):
        result = self.client.get('/api/public-financials').json
        self.assertEqual(result['facts'], [])
        self.assertTrue(all(c['status'] == 'pending' for c in result['checks']))
        self.post(action='commit')
        result = self.client.get('/api/public-financials').json
        self.assertEqual(len(result['facts']), 44)
        self.assertTrue(all(c['status'] == 'pending' for c in result['checks']))


if __name__ == '__main__':
    unittest.main()
