"""整数分聚合；比率使用 Decimal。订单和退款分别聚合，避免一对多重复。"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from .validation import strict_date

METRIC_KEYS = ('sales_cents', 'refund_cents', 'cost_cents', 'contribution_cents')


def bucket():
    return dict(sales_cents=0, refund_cents=0, known_cost_cents=0,
                missing_cost_lines=0, paid_lines=0, quantity=0, cross_period_refund_cents=0)


def add_order(target, row):
    target['sales_cents'] += row['paid_amount_cents']
    target['paid_lines'] += 1
    target['quantity'] += row['quantity']
    if row['unit_cost_cents'] is None:
        target['missing_cost_lines'] += 1
    else:
        target['known_cost_cents'] += row['unit_cost_cents'] * row['quantity']


def add_refund(target, row, start, end):
    target['refund_cents'] += row['amount_cents']
    if not start <= row['paid_date'] <= end:
        target['cross_period_refund_cents'] += row['amount_cents']


def finalize(target):
    complete = target['missing_cost_lines'] == 0
    target['cost_cents'] = target['known_cost_cents'] if complete else None
    target['contribution_cents'] = target['sales_cents'] - target['refund_cents'] - target['known_cost_cents'] if complete else None
    return target


def change(current, previous, available=True):
    if not available:
        return {'percent': None, 'reason': '前期超出数据范围'}
    if current is None or previous is None:
        return {'percent': None, 'reason': '成本不完整'}
    if previous == 0:
        return {'percent': None, 'reason': '前期为零'}
    rate = (Decimal(current - previous) * 100 / abs(Decimal(previous))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'percent': str(rate), 'reason': '前期为负，按绝对值作分母' if previous < 0 else None}


def aggregate(conn, start, end, product_id=None):
    total, days, products = bucket(), {}, {}
    cursor = strict_date(start)
    while cursor <= strict_date(end):
        days[cursor.isoformat()] = bucket()
        cursor += timedelta(days=1)
    # 仅固定的只读语句；用户输入始终绑定参数。
    for row in conn.execute('''SELECT * FROM order_lines
        WHERE paid_date BETWEEN ? AND ?
        AND status IN ('paid','shipped','completed','refunded')
        AND (? IS NULL OR product_id = ?)''', (start, end, product_id, product_id)):
        product = products.setdefault(row['product_id'], bucket())
        for target in (total, days[row['paid_date']], product):
            add_order(target, row)
    for row in conn.execute('''SELECT r.*, o.product_id, o.paid_date
        FROM refunds r JOIN order_lines o ON o.id = r.order_line_id
        WHERE r.refund_date BETWEEN ? AND ? AND r.status = 'success'
        AND o.status IN ('paid','shipped','completed','refunded')
        AND (? IS NULL OR o.product_id = ?)''', (start, end, product_id, product_id)):
        product = products.setdefault(row['product_id'], bucket())
        # daily 的跨期定义以当天为范围，total/products 以整个筛选期为范围。
        add_refund(total, row, start, end)
        add_refund(product, row, start, end)
        add_refund(days[row['refund_date']], row, row['refund_date'], row['refund_date'])
    names = {row['id']: dict(row) for row in conn.execute('SELECT * FROM products')}
    ranking = [dict(product_id=pid, name=names[pid]['name'], category=names[pid]['category'], **finalize(values)) for pid, values in products.items()]
    ranking.sort(key=lambda r: (r['contribution_cents'] is None, -(r['contribution_cents'] or 0), r['product_id']))
    return {'summary': finalize(total), 'daily': [dict(date=day, **finalize(values)) for day, values in days.items()], 'products': ranking}


def dashboard(conn, start, end, product_id=None):
    meta = conn.execute('SELECT * FROM dataset_meta').fetchone()
    first, last = strict_date(start), strict_date(end)
    if first > last:
        raise ValueError('开始日期不能晚于结束日期')
    if (last - first).days >= 90:
        raise ValueError('单次查询最多 90 天')
    if start < meta['start_date'] or end > meta['end_date']:
        raise ValueError('日期超出模拟数据覆盖范围')
    if product_id is not None and not conn.execute('SELECT 1 FROM products WHERE id=?', (product_id,)).fetchone():
        raise ValueError('商品不存在')
    length = (last - first).days + 1
    previous_end = first - timedelta(days=1)
    previous_start = first - timedelta(days=length)
    available = previous_start.isoformat() >= meta['start_date']
    result = aggregate(conn, start, end, product_id)
    previous = aggregate(conn, previous_start.isoformat(), previous_end.isoformat(), product_id)['summary'] if available else None
    result.update(is_simulated=True, currency='CNY', period={'start': start, 'end': end, 'days': length},
                  comparison={'start': previous_start.isoformat(), 'end': previous_end.isoformat(), 'available': available,
                              'label': '周环比' if length == 7 else '等长上期比较', 'summary': previous},
                  changes={key: change(result['summary'][key], previous[key] if previous else None, available) for key in METRIC_KEYS})
    return result
