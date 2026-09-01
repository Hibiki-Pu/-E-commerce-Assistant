import sqlite3
import unittest

from backend.db import ROOT
from backend.metrics import aggregate, change, dashboard
from backend.validation import strict_date, validate_database


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript((ROOT / 'backend/schema.sql').read_text(encoding='utf-8'))
        self.conn.execute("INSERT INTO dataset_meta VALUES (1,'模拟','CNY','2026-08-01','2026-08-30',1,1)")
        self.conn.executemany('INSERT INTO products(id,name,category) VALUES (?,?,?)', [('A', '测试商品甲', '测试'), ('B', '测试商品乙', '测试')])
        self.conn.execute("INSERT INTO product_costs(product_id,effective_from,unit_cost_cents) VALUES ('A','2026-08-01',30)")

    def tearDown(self):
        self.conn.close()

    def order(self, id='L1', product='A', day='2026-08-24', status='completed', quantity=1, amount=100, cost=30):
        self.conn.execute('INSERT INTO order_lines(id,order_id,product_id,paid_date,status,quantity,paid_amount_cents,unit_cost_cents) VALUES (?,?,?,?,?,?,?,?)', (id, 'O1', product, day, status, quantity, amount, cost))

    def refund(self, id='R1', line='L1', day='2026-08-25', amount=20, status='success'):
        self.conn.execute('INSERT INTO refunds(id,order_line_id,refund_date,status,amount_cents) VALUES (?,?,?,?,?)', (id, line, day, status, amount))

    def summary(self, start='2026-08-24', end='2026-08-30', product=None):
        return aggregate(self.conn, start, end, product)['summary']

    def test_integer_cents_and_quantity(self):
        self.order(amount=101, quantity=3, cost=17)
        self.refund(amount=19)
        summary = self.summary()
        self.assertEqual((summary['sales_cents'], summary['cost_cents'], summary['contribution_cents']), (101, 51, 31))

    def test_paid_statuses_only(self):
        for i, status in enumerate(('completed', 'paid', 'shipped', 'refunded')):
            self.order(id=str(i), status=status)
        self.order(id='pending', status='pending', day=None, amount=0, cost=None)
        self.order(id='cancelled', status='cancelled', day=None, amount=0, cost=None)
        self.assertEqual(self.summary()['sales_cents'], 400)
        self.assertEqual(self.summary()['missing_cost_lines'], 0)

    def test_many_refunds_do_not_duplicate_sales_or_cost(self):
        self.order(status='refunded')
        self.refund(amount=30)
        self.refund(id='R2', amount=70)
        self.refund(id='R3', amount=40, status='failed')
        self.refund(id='R4', amount=40, status='processing')
        result = self.summary()
        self.assertEqual((result['sales_cents'], result['refund_cents'], result['cost_cents'], result['contribution_cents']), (100, 100, 30, -30))

    def test_cross_period_refund_does_not_rewrite_sales(self):
        self.order(day='2026-08-20')
        self.refund(amount=100)
        now, before = self.summary(), self.summary('2026-08-17', '2026-08-23')
        self.assertEqual((now['sales_cents'], now['cross_period_refund_cents'], now['contribution_cents']), (0, 100, -100))
        self.assertEqual((before['sales_cents'], before['refund_cents'], before['cost_cents']), (100, 0, 30))

    def test_missing_cost_is_not_zero_and_only_affects_scope(self):
        self.order()
        self.order(id='L2', product='B', cost=None)
        self.assertIsNone(self.summary()['contribution_cents'])
        self.assertIsNone(self.summary()['cost_cents'])
        self.assertEqual(self.summary()['known_cost_cents'], 30)
        self.assertEqual(self.summary(product='A')['contribution_cents'], 70)
        self.assertEqual(self.summary()['missing_cost_lines'], 1)

    def test_confirmed_zero_cost_is_valid(self):
        self.order(cost=0)
        self.assertEqual(self.summary()['contribution_cents'], 100)

    def test_missing_daily_profit_is_null_and_ranked_after_negative(self):
        self.order(day='2026-08-24', amount=20, cost=30)
        self.order(id='L2', product='B', day='2026-08-25', cost=None)
        result = aggregate(self.conn, '2026-08-24', '2026-08-30')
        self.assertEqual(result['daily'][0]['contribution_cents'], -10)
        self.assertIsNone(result['daily'][1]['contribution_cents'])
        self.assertEqual(result['daily'][2]['contribution_cents'], 0)
        self.assertEqual([p['product_id'] for p in result['products']], ['A', 'B'])

    def test_missing_previous_cost_disables_profit_comparison_only(self):
        self.order(day='2026-08-20', cost=None)
        self.order(id='L2')
        result = dashboard(self.conn, '2026-08-24', '2026-08-30')
        self.assertEqual(result['changes']['sales_cents']['percent'], '0.00')
        self.assertEqual(result['changes']['contribution_cents']['reason'], '成本不完整')

    def test_product_filter_applies_to_refunds(self):
        self.order()
        self.order(id='L2', product='B', amount=200)
        self.refund(line='L2', amount=90)
        self.assertEqual(self.summary(product='A')['refund_cents'], 0)
        self.assertEqual(self.summary(product='B')['refund_cents'], 90)

    def test_empty_range_in_coverage_has_daily_zeros(self):
        result = aggregate(self.conn, '2026-08-24', '2026-08-30')
        self.assertEqual(len(result['daily']), 7)
        self.assertEqual(result['summary']['contribution_cents'], 0)
        self.assertEqual(result['products'], [])

    def test_inclusive_dates(self):
        self.order(day='2026-08-24')
        self.order(id='L2', day='2026-08-30')
        self.assertEqual(self.summary()['sales_cents'], 200)

    def test_daily_and_product_reconciliation(self):
        self.order()
        self.order(id='L2', day='2026-08-26', product='B')
        self.refund()
        result = aggregate(self.conn, '2026-08-24', '2026-08-30')
        for key in ('sales_cents', 'refund_cents', 'known_cost_cents', 'contribution_cents'):
            self.assertEqual(sum(row[key] for row in result['daily']), result['summary'][key])
            self.assertEqual(sum(row[key] for row in result['products']), result['summary'][key])

    def test_comparison_uses_equal_length_previous_window(self):
        self.order(day='2026-08-20', amount=200)
        self.order(id='L2', amount=300)
        result = dashboard(self.conn, '2026-08-24', '2026-08-30')
        self.assertEqual(result['comparison']['start'], '2026-08-17')
        self.assertEqual(result['changes']['sales_cents']['percent'], '50.00')
        self.assertEqual(dashboard(self.conn, '2026-08-24', '2026-08-26')['comparison']['label'], '等长上期比较')

    def test_incomplete_previous_coverage_is_unavailable(self):
        result = dashboard(self.conn, '2026-08-01', '2026-08-07')
        self.assertIsNone(result['comparison']['summary'])
        self.assertEqual(result['changes']['sales_cents']['reason'], '前期超出数据范围')

    def test_change_zero_missing_negative_and_rounding(self):
        self.assertEqual(change(100, 0), {'percent': None, 'reason': '前期为零'})
        self.assertEqual(change(0, 0)['percent'], None)
        self.assertEqual(change(None, 100)['reason'], '成本不完整')
        self.assertEqual(change(50, -100)['percent'], '150.00')
        self.assertEqual(change(-50, -100)['percent'], '50.00')
        self.assertEqual(change(2, 3)['percent'], '-33.33')

    def test_reject_invalid_dates_and_product(self):
        for start, end, product in [('2026-8-24', '2026-08-30', None), ('2026-02-30', '2026-08-30', None), ('2026-08-25', '2026-08-24', None), ('2026-07-30', '2026-08-30', None), ('2026-08-24', '2026-08-30', "A' OR 1=1--")]:
            with self.subTest(start=start, end=end, product=product), self.assertRaises(ValueError):
                dashboard(self.conn, start, end, product)

    def test_validation_rejects_over_refund(self):
        self.order()
        self.refund(amount=80)
        self.refund(id='R2', amount=30)
        with self.assertRaisesRegex(ValueError, '超过实付'):
            validate_database(self.conn)

    def test_validation_rejects_refund_before_payment(self):
        self.order()
        self.refund(day='2026-08-23')
        with self.assertRaisesRegex(ValueError, '退款日期无效'):
            validate_database(self.conn)

    def test_validation_rejects_unpaid_refund(self):
        self.order(status='pending', day=None, amount=0, cost=None)
        self.refund()
        with self.assertRaisesRegex(ValueError, '有效支付'):
            validate_database(self.conn)

    def test_validation_rejects_cost_snapshot_mismatch(self):
        self.order(cost=99)
        with self.assertRaisesRegex(ValueError, '成本快照'):
            validate_database(self.conn)

    def test_cost_version_uses_payment_date(self):
        self.conn.execute("INSERT INTO product_costs(product_id,effective_from,unit_cost_cents) VALUES ('A','2026-08-25',60)")
        self.order(day='2026-08-24', cost=30)
        self.order(id='L2', day='2026-08-26', cost=60)
        self.assertEqual(validate_database(self.conn)['status'], 'passed')
        self.assertEqual(self.summary()['cost_cents'], 90)

    def test_database_enforces_foreign_key_integer_and_simulation(self):
        for kwargs in [dict(product='UNKNOWN'), dict(amount=1.5), dict(quantity=0), dict(cost=-1)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(sqlite3.IntegrityError):
                self.order(**kwargs)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO products VALUES ('C','真实','测试',0)")
