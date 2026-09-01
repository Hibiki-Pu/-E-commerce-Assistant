import csv
import hashlib
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

from werkzeug.test import EnvironBuilder

from backend.app import create_app
from backend.db import DEFAULT_DB, connect
from backend.public_financials import PACKAGE
from backend.transaction_files import FIELDS, parse_upload
from backend.transaction_imports import EXAMPLES


def csv_bytes(kind, rows, headers=None, encoding='utf-8-sig'):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(headers or FIELDS[kind].values())
    writer.writerows(rows)
    return out.getvalue().encode(encoding)


def xlsx_fixture(kind, rows, custom_cells=None):
    """最小 OOXML 测试夹具（不是交付工作簿），覆盖共享解析及真实 Excel 日期。"""
    body = []
    for n, row in enumerate([list(FIELDS[kind].values())] + rows, 1):
        cells = []
        for i, value in enumerate(row):
            address = chr(65 + i) + str(n)
            replacement = (custom_cells or {}).get(address)
            cells.append(replacement or f'<c r="{address}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        body.append(f'<row r="{n}">' + ''.join(cells) + '</row>')
    buf = io.BytesIO()
    with ZipFile(buf, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="测试" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:A1"/><sheetData>' + ''.join(body) + '</sheetData></worksheet>')
        z.writestr('xl/styles.xml', '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><name val="Calibri"/><sz val="11"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    return buf.getvalue()


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'transactions.sqlite3'
        self.app = create_app(import_db_path=self.db)
        self.client = self.app.test_client()
        self.original = hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(self.original, hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest())
        self.temp.cleanup()

    def post(self, kind='orders', rows=None, action='commit', content=None, filename='test.csv', **kwargs):
        if content is None:
            content = csv_bytes(kind, EXAMPLES[kind] if rows is None else rows)
        with closing(EnvironBuilder(path='/api/imports/' + action, method='POST',
                     data={'kind': kind, 'start': kwargs.get('start', '2026-08-01'), 'end': kwargs.get('end', '2026-08-30'), 'file': (io.BytesIO(content), filename)},
                     headers=kwargs.get('headers', {'X-Import-Request': 'commerce-insight'}))) as builder:
            env = builder.get_environ()
            try:
                return self.client.open(env)
            finally:
                env['wsgi.input'].close()

    def dashboard(self):
        return self.client.get('/api/imports/dashboard?start=2026-08-24&end=2026-08-30').json

    def test_preview_never_writes_and_reports_missing_cost(self):
        response = self.post(action='preview')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['new_rows'], 2)
        self.assertEqual([w['row'] for w in response.json['warnings']], [2, 3])
        self.assertFalse(self.db.exists())

    def test_reimport_and_same_order_different_lines(self):
        self.assertEqual(self.post().json['inserted'], 2)
        before = self.dashboard()['summary']
        response = self.post(filename='renamed.csv')
        self.assertEqual((response.json['inserted'], response.json['duplicate_count']), (0, 2))
        self.assertEqual(self.dashboard()['summary'], before)
        self.assertEqual(before['sales_cents'], 15700)
        self.assertEqual(len(self.client.get('/api/imports/meta').json['batches']), 1)

    def test_missing_cost_then_backfill_preserves_zero_distinction(self):
        self.post()
        self.post(kind='refunds')
        self.assertIsNone(self.dashboard()['summary']['contribution_cents'])
        self.post(kind='costs')
        self.assertIsNone(self.dashboard()['summary']['cost_cents'])
        response = self.post(kind='costs', rows=EXAMPLES['costs_complete'])
        self.assertEqual((response.json['updated_cost_rows'], response.json['backfilled_order_lines']), (1, 1))
        result = self.dashboard()['summary']
        self.assertEqual((result['sales_cents'], result['refund_cents'], result['cost_cents'], result['contribution_cents']), (15700, 2950, 6400, 6350))
        self.assertEqual(self.post(kind='refunds').json['inserted'], 0)

    def test_costs_first_then_orders_and_zero_cost(self):
        self.post(kind='costs', rows=[['SIM-P001', '2026-08-01', '0'], ['SIM-P002', '2026-08-01', '16']])
        self.assertEqual(self.post().json['missing_cost_lines'], 0)
        self.assertEqual(self.dashboard()['summary']['cost_cents'], 1600)

    def test_duplicate_in_file_and_conflict_rollback(self):
        order = EXAMPLES['orders'][0]
        response = self.post(rows=[order, order])
        self.assertEqual((response.json['inserted'], response.json['duplicate_count']), (1, 1))
        conflict = list(order); conflict[-1] = '119.00'
        before = self.db.read_bytes()
        response = self.post(rows=[EXAMPLES['orders'][1], conflict])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json['errors'][0]['row'], 3)
        self.assertEqual(before, self.db.read_bytes())

    def test_all_errors_and_original_blank_row_numbers(self):
        valid = EXAMPLES['orders'][0]
        response = self.post(rows=[valid, [], *EXAMPLES['orders_errors']])
        self.assertEqual(response.status_code, 422)
        self.assertEqual({e['row'] for e in response.json['errors']}, {4, 5})
        self.assertGreaterEqual(response.json['error_count'], 3)
        self.assertEqual(response.json['warnings'][0]['row'], 3)
        self.assertFalse(self.db.exists())

    def test_duplicate_after_invalid_row_keeps_source_number(self):
        self.post()
        response = self.post(rows=[EXAMPLES['orders_errors'][0], [], EXAMPLES['orders'][0]])
        self.assertEqual(response.json['duplicates'][0]['row'], 4)

    def test_bad_headers_reordered_aliases_and_gb_encoding(self):
        response = self.post(content=csv_bytes('orders', [EXAMPLES['orders'][0]], headers=['错列'] * 8))
        self.assertEqual(response.status_code, 422)
        self.assertTrue(all(e['row'] == 1 for e in response.json['errors']))
        response = self.post(content=csv_bytes('orders', [list(reversed(EXAMPLES['orders'][0]))], headers=list(reversed(FIELDS['orders'])), encoding='gb18030'))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['encoding'], 'GB18030')

    def test_refund_unknown_prior_date_overage_and_atomicity(self):
        self.assertEqual(self.post(kind='refunds').status_code, 422)
        self.post()
        for day, amount in [('2026-08-23', '20'), ('2026-08-25', '119'), ('2026-08-31', '20')]:
            with self.subTest(day=day, amount=amount):
                self.assertEqual(self.post(kind='refunds', rows=[['R', 'SIM-L001', day, '成功', amount]]).status_code, 422)
        response = self.post(kind='refunds', rows=[['R1', 'SIM-L001', '2026-08-25', '成功', '80'], ['R2', 'SIM-L001', '2026-08-25', '成功', '40']])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json['errors'][0]['row'], 3)
        self.assertEqual(self.dashboard()['summary']['refund_cents'], 0)

    def test_new_cost_version_cannot_rewrite_known_history(self):
        self.post(kind='costs', rows=EXAMPLES['costs_complete'])
        self.post()
        response = self.post(kind='costs', rows=[['SIM-P001', '2026-08-20', '30']])
        self.assertEqual(response.status_code, 422)
        self.assertIn('SIM-L001', response.json['errors'][0]['message'])
        self.assertEqual(self.dashboard()['summary']['cost_cents'], 6400)

    def test_commits_revalidate_stale_preview(self):
        self.assertEqual(self.post(action='preview').status_code, 200)
        self.post()
        result = self.post()
        self.assertEqual((result.json['inserted'], result.json['duplicate_count']), (0, 2))

    def test_excel_csv_parity_and_dimension_underreport(self):
        content = xlsx_fixture('orders', EXAMPLES['orders'])
        xlsx_rows, errs, _, _ = parse_upload(content, 'test.xlsx', 'orders')
        csv_rows, _, _, _ = parse_upload(csv_bytes('orders', EXAMPLES['orders']), 'test.csv', 'orders')
        self.assertEqual(errs, [])
        self.assertEqual(xlsx_rows, csv_rows)
        self.assertEqual(self.post(content=content, filename='a.xlsx').json['inserted'], 2)
        self.assertEqual(self.post().json['duplicate_count'], 2)

    def test_excel_formula_and_numeric_identifiers_are_errors(self):
        content = xlsx_fixture('orders', EXAMPLES['orders'], {'H2': '<c r="H2"><f>59*2</f><v>118</v></c>', 'A3': '<c r="A3"><v>12345678901234567</v></c>'})
        result = self.post(content=content, filename='test.xlsx')
        self.assertEqual(result.status_code, 422)
        self.assertEqual({e['row'] for e in result.json['errors']}, {2, 3})

    def test_excel_numeric_date_and_numeric_amount(self):
        content = xlsx_fixture('orders', [EXAMPLES['orders'][0]], {
            'E2': '<c r="E2" s="1"><v>46258.5</v></c>',
            'G2': '<c r="G2"><v>2</v></c>', 'H2': '<c r="H2"><v>118</v></c>',
        })
        response = self.post(content=content, filename='dates.xlsx')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['samples'][0]['paid_date'], '2026-08-24')
        self.assertEqual(self.dashboard()['summary']['sales_cents'], 11800)

    def test_excel_costs_and_refunds(self):
        self.assertEqual(self.post(kind='costs', content=xlsx_fixture('costs', EXAMPLES['costs_complete']), filename='costs.xlsx').status_code, 200)
        self.post()
        self.assertEqual(self.post(kind='refunds', content=xlsx_fixture('refunds', EXAMPLES['refunds']), filename='refunds.xlsx').status_code, 200)
        self.assertEqual(self.dashboard()['summary']['contribution_cents'], 6350)

    def test_all_errors_are_returned_not_truncated(self):
        response = self.post(rows=[['', '', '', '', 'bad', 'bad', '0', 'bad'] for _ in range(120)])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json['error_count'], 960)
        self.assertEqual(response.json['errors'][-1]['row'], 121)
        self.assertFalse(self.db.exists())

    def test_large_cost_refuses_loss_of_cent_precision(self):
        self.post(kind='costs', rows=[['SIM-P001', '2026-08-01', '100000000']])
        row = list(EXAMPLES['orders'][0]); row[6] = '999999'
        result = self.post(rows=[row])
        self.assertEqual(result.status_code, 422)
        self.assertEqual(result.json['errors'][-1]['field'], '金额总量')
        self.assertEqual(self.client.get('/api/imports/meta').json['counts']['order_lines'], 0)

    def test_multiline_csv_error_uses_starting_physical_line(self):
        row = list(EXAMPLES['orders'][0]); row[3] = '商品\n名称'
        response = self.post(rows=[row, EXAMPLES['orders_errors'][0]])
        self.assertEqual({e['row'] for e in response.json['errors']}, {2, 4})

    def test_existing_financial_file_is_not_orders(self):
        result = self.post(content=(PACKAGE / 'annual_data.csv').read_bytes())
        self.assertEqual(result.status_code, 422)
        self.assertFalse(self.db.exists())
        result = self.post(content=(PACKAGE / 'jihong_public_financials.xlsx').read_bytes(), filename='company.xlsx')
        self.assertEqual(result.status_code, 400)
        self.assertIn('订单明细', result.json['error'])

    def test_amounts_dates_status_and_empty_files(self):
        for index, value in [(4, '08/24/2026'), (4, '2026-08-32'), (5, '未知'), (6, '0'), (7, 'NaN'), (7, '-1'), (7, '1e3'), (7, '0.001'), (0, '')]:
            row = list(EXAMPLES['orders'][0]); row[index] = value
            with self.subTest(index=index, value=value):
                self.assertEqual(self.post(rows=[row]).status_code, 422)
        self.assertEqual(self.post(rows=[]).status_code, 422)
        self.assertEqual(self.post(rows=[[], []]).status_code, 422)
        self.assertEqual(self.post(content=b'bad', filename='x.xls').status_code, 400)

    def test_chinese_timestamps_and_unpaid_order(self):
        row = list(EXAMPLES['orders'][0]); row[4] = '2026/08/24 23:59:59'
        self.assertEqual(self.post(rows=[row]).status_code, 200)
        unpaid = ['L3', 'O3', 'P3', '待支付商品', '', '待支付', '1', '0']
        self.assertEqual(self.post(rows=[unpaid]).status_code, 200)
        self.assertEqual(self.dashboard()['summary']['paid_lines'], 1)

    def test_import_request_security_and_fixed_scope(self):
        self.assertEqual(self.post(headers={}).status_code, 403)
        self.assertEqual(self.post(headers={'X-Import-Request': 'commerce-insight', 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.post(start='2026-08-30', end='2026-08-01').status_code, 400)
        self.post()
        self.assertEqual(self.post(start='2026-08-02').status_code, 400)
        self.assertEqual(self.client.get('/api/imports/dashboard?start=2026-08-01&end=2026-08-30&product_id=%27OR1=1').status_code, 400)

    def test_parallel_duplicate_commits_do_not_double_count(self):
        def run(_):
            with self.app.test_client() as client:
                return client.post('/api/imports/commit', data={'kind': 'orders', 'start': '2026-08-01', 'end': '2026-08-30', 'file': (io.BytesIO(csv_bytes('orders', EXAMPLES['orders'])), 'same.csv')}, headers={'X-Import-Request': 'commerce-insight'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual([r.status_code for r in results], [200, 200], [r.json for r in results])
        self.assertEqual(sum(r.json['inserted'] for r in results), 2)
        self.assertEqual(self.dashboard()['summary']['sales_cents'], 15700)
