import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.app import create_app
from backend.db import connect
from backend.seed import generate
from backend.validation import validate_database


class AppSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.temp.name) / 'demo.sqlite3'
        cls.report = generate(cls.db)
        cls.app = create_app(cls.db)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_seed_is_reproducible_and_has_expected_scale(self):
        other = Path(self.temp.name) / 'second.sqlite3'
        generate(other)
        with closing(connect(self.db)) as a, closing(connect(other)) as b:
            self.assertEqual('\n'.join(a.iterdump()), '\n'.join(b.iterdump()))
            self.assertEqual(a.execute('SELECT COUNT(*) FROM order_lines').fetchone()[0], 2000)
            self.assertEqual(a.execute('SELECT COUNT(*) FROM products').fetchone()[0], 20)
            self.assertGreater(a.execute('SELECT COUNT(*) FROM refunds').fetchone()[0], 100)
            self.assertEqual(validate_database(a)['status'], 'passed')

    def test_existing_file_is_preserved(self):
        before = self.db.read_bytes()
        with self.assertRaises(FileExistsError):
            generate(self.db)
        self.assertEqual(before, self.db.read_bytes())

    def test_queries_use_readonly_connection(self):
        with closing(connect(self.db)) as conn, self.assertRaises(sqlite3.OperationalError):
            conn.execute('DELETE FROM products')

    def test_health_meta_and_dashboard(self):
        self.assertTrue(self.client.get('/api/health').json['is_simulated'])
        meta = self.client.get('/api/meta').json
        self.assertEqual(meta['counts']['order_lines'], 2000)
        result = self.client.get('/api/dashboard?start=2026-08-24&end=2026-08-30')
        self.assertEqual(result.status_code, 200)
        self.assertGreater(result.json['summary']['sales_cents'], 0)
        self.assertIsNone(result.json['summary']['contribution_cents'])
        self.assertGreater(result.json['summary']['missing_cost_lines'], 0)
        self.assertEqual(len(result.json['daily']), 7)

    def test_all_four_scenarios_are_observable(self):
        def summary(pid, start='2026-08-24', end='2026-08-30'):
            return self.client.get(f'/api/dashboard?start={start}&end={end}&product_id={pid}').json['summary']
        promo = summary('P001')
        self.assertEqual(promo['sales_cents'], promo['quantity'] * 4720)
        expensive = summary('P003')
        self.assertEqual(expensive['cost_cents'], expensive['quantity'] * 7900)
        self.assertGreater(summary('P002')['cross_period_refund_cents'], 0)
        self.assertIsNone(summary('P020')['contribution_cents'])
        self.assertIsNotNone(summary('P020', '2026-08-17', '2026-08-23')['contribution_cents'])

    def test_api_rejects_missing_unknown_duplicate_and_injection(self):
        for query in ['', '?start=2026-08-24', '?start=2026-08-24&end=2026-08-30&sql=DELETE', '?start=2026-08-24&start=2026-08-25&end=2026-08-30', '?start=2026-08-24&end=2026-08-30&product_id=%27%20OR%201=1--', '?start=2026-08-24&end=2026-08-30&product_id=']:
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/dashboard' + query).status_code, 400)

    def test_no_write_endpoint(self):
        self.assertEqual(self.client.post('/api/dashboard').status_code, 405)
