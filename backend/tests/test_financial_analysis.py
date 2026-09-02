import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.financial_analysis import build_evidence
from backend.public_financials import PACKAGE, identity, read_upload


class FakeAIClient:
    def __init__(self, bad_reference=False):
        self.calls = []
        self.bad_reference = bad_reference

    def generate(self, evidence, api_key, model):
        self.calls.append((evidence, api_key, model))
        reference = 'UNKNOWN' if self.bad_reference else 'MET-REVENUE'
        return {
            'core_summary': [{'text': '收入来自程序计算的结构化证据。', 'evidence_ids': ['MET-REVENUE']}, {'text': '利润结论需要人工复核。', 'evidence_ids': ['MET-NET_PROFIT_PARENT']}],
            'year_over_year': [{'text': '营业收入同比变化见程序证据。', 'evidence_ids': [reference]}],
            'profit_cash_flow': [{'text': '现金流与利润差额不能直接解释为单一原因。', 'evidence_ids': ['CASH-PROFIT-GAP']}],
            'concentration': [{'text': '最大业务占比需要结合集中度证据判断。', 'evidence_ids': ['BUS-CONCENTRATION']}],
            'risks': [{'title': '数据边界', 'detail': '缺少营运资本明细，不能判断现金流差异的具体原因。', 'evidence_ids': ['RISK-SCOPE']}],
        }, {'response_id': 'resp_test', 'model': model, 'usage': {'input_tokens': 10, 'output_tokens': 10}}


class FinancialAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.public_db = Path(self.temp.name) / 'public.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def facts(self):
        facts = []
        for kind in ('annual', 'business'):
            rows, errors = read_upload((PACKAGE / f'{kind}_data.csv').read_bytes(), f'{kind}.csv', kind)
            self.assertEqual(errors, [])
            facts.extend(rows)
        return facts

    def seed(self):
        facts = self.facts()
        with sqlite3.connect(self.public_db) as conn:
            conn.execute('CREATE TABLE facts (fact_key TEXT PRIMARY KEY, value_cents INTEGER NOT NULL, payload TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            conn.executemany('INSERT INTO facts(fact_key,value_cents,payload) VALUES(?,?,?)', [(identity(f), f['value_cents'], json.dumps(f, ensure_ascii=False, sort_keys=True)) for f in facts])

    def test_program_calculates_2025_evidence_and_sources(self):
        manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
        result = build_evidence(self.facts(), '002803.SZ', '2025', manifest)
        metrics = {item['key']: item for item in result['core_metrics']}
        self.assertEqual(metrics['revenue']['value_cents'], 672161213017)
        self.assertEqual(metrics['revenue']['yoy_percent'], '21.56')
        self.assertEqual(metrics['net_profit_parent']['yoy_percent'], '52.16')
        self.assertEqual(metrics['operating_cash_flow']['yoy_percent'], '-32.45')
        self.assertEqual(metrics['gross_margin']['value_percent'], '46.92')
        self.assertEqual(result['profit_cash_flow']['gap_cents'], -1561212089)
        self.assertEqual(result['concentration']['top_business']['label'], '电商业务')
        self.assertEqual(result['concentration']['top_business']['share_percent'], '65.06')
        self.assertTrue(result['concentration']['reconciled'])
        self.assertTrue(all(source['url'].startswith('https://static.cninfo.com.cn/') for source in result['sources']))
        self.assertEqual(len(result['evidence_hash']), 64)

    def test_options_require_complete_import_and_evidence_params_are_strict(self):
        client = create_app(public_db_path=self.public_db).test_client()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(client.get('/api/financial-analysis/options').json['companies'][0]['years'], [])
            self.seed()
            result = client.get('/api/financial-analysis/options').json
        self.assertEqual(result['companies'][0]['years'], ['2022', '2023', '2024', '2025'])
        self.assertFalse(result['ai_configured'])
        self.assertEqual(client.get('/api/financial-analysis/evidence?company_code=002803.SZ&year=2025').status_code, 200)
        self.assertEqual(client.get('/api/financial-analysis/evidence?company_code=002803.SZ').status_code, 400)
        self.assertEqual(client.get('/api/financial-analysis/evidence?company_code=OTHER&year=2025').status_code, 400)
        self.assertEqual(client.get('/api/financial-analysis/evidence?company_code=002803.SZ&year=2026').status_code, 400)

    def test_without_key_returns_evidence_but_never_fake_ai(self):
        self.seed()
        fake = FakeAIClient()
        client = create_app(public_db_path=self.public_db, ai_client=fake).test_client()
        with patch.dict(os.environ, {}, clear=True):
            response = client.post('/api/financial-analysis/generate', json={'company_code': '002803.SZ', 'year': '2025'}, headers={'X-Analysis-Request': 'commerce-insight'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['code'], 'ai_not_configured')
        self.assertIn('evidence', response.json)
        self.assertNotIn('narrative', response.json)
        self.assertEqual(fake.calls, [])

    def test_configured_generation_is_structured_and_traced(self):
        self.seed()
        fake = FakeAIClient()
        client = create_app(public_db_path=self.public_db, ai_client=fake).test_client()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'server-test-key', 'OPENAI_MODEL': 'gpt-5.4-mini'}, clear=True):
            response = client.post('/api/financial-analysis/generate', json={'company_code': '002803.SZ', 'year': '2025'}, headers={'X-Analysis-Request': 'commerce-insight'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['review_status'], 'pending')
        self.assertEqual(response.json['trace']['response_id'], 'resp_test')
        self.assertEqual(response.json['trace']['evidence_hash'], response.json['evidence']['evidence_hash'])
        self.assertEqual(fake.calls[0][1:], ('server-test-key', 'gpt-5.4-mini'))
        self.assertNotIn('notes', json.dumps(fake.calls[0][0]))

    def test_invalid_model_reference_is_rejected(self):
        self.seed()
        client = create_app(public_db_path=self.public_db, ai_client=FakeAIClient(bad_reference=True)).test_client()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'server-test-key'}, clear=True):
            response = client.post('/api/financial-analysis/generate', json={'company_code': '002803.SZ', 'year': '2025'}, headers={'X-Analysis-Request': 'commerce-insight'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json['code'], 'ai_generation_failed')

    def test_generate_request_protection(self):
        self.seed()
        client = create_app(public_db_path=self.public_db, ai_client=FakeAIClient()).test_client()
        payload = {'company_code': '002803.SZ', 'year': '2025'}
        self.assertEqual(client.post('/api/financial-analysis/generate', json=payload).status_code, 403)
        self.assertEqual(client.post('/api/financial-analysis/generate', json=payload, headers={'X-Analysis-Request': 'commerce-insight', 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(client.post('/api/financial-analysis/generate', json={**payload, 'extra': True}, headers={'X-Analysis-Request': 'commerce-insight'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
