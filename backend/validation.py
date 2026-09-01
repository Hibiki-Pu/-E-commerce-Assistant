"""生成和服务启动共用校验；不接受模型生成代码或任意 SQL。"""
from datetime import date

VALID_STATUSES = ('paid', 'shipped', 'completed', 'refunded')


def strict_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('日期必须为 YYYY-MM-DD 格式') from None
    if parsed.isoformat() != value:
        raise ValueError('日期必须为 YYYY-MM-DD 格式')
    return parsed


def validate_database(conn):
    errors = []
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        errors.append('数据库完整性检查失败')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        errors.append('存在无效外键')
    meta = conn.execute('SELECT * FROM dataset_meta WHERE id=1').fetchone()
    if not meta:
        raise ValueError('缺少数据集信息')
    start, end = strict_date(meta['start_date']), strict_date(meta['end_date'])
    if start > end or (end - start).days >= 90:
        errors.append('观察期必须在 1 至 90 天内')
    costs = {}
    for row in conn.execute('SELECT * FROM product_costs ORDER BY effective_from'):
        strict_date(row['effective_from'])
        costs.setdefault(row['product_id'], []).append(row)
    lines = {r['id']: r for r in conn.execute('SELECT * FROM order_lines')}
    for row in lines.values():
        if row['status'] not in VALID_STATUSES:
            continue
        paid = strict_date(row['paid_date'])
        if not start <= paid <= end:
            errors.append(f"{row['id']} 支付日不在观察期内")
        applicable = [c for c in costs.get(row['product_id'], []) if c['effective_from'] <= row['paid_date']]
        expected = applicable[-1]['unit_cost_cents'] if applicable else None
        if row['unit_cost_cents'] != expected:
            errors.append(f"{row['id']} 成本快照与支付日成本版本不一致")
    totals = {}
    for row in conn.execute('SELECT * FROM refunds'):
        refunded = strict_date(row['refund_date'])
        line = lines.get(row['order_line_id'])
        if not line or line['status'] not in VALID_STATUSES:
            errors.append(f"{row['id']} 退款必须关联有效支付明细")
            continue
        if refunded < strict_date(line['paid_date']) or not start <= refunded <= end:
            errors.append(f"{row['id']} 退款日期无效")
        if row['status'] == 'success':
            totals[line['id']] = totals.get(line['id'], 0) + row['amount_cents']
    for line_id, amount in totals.items():
        if amount > lines[line_id]['paid_amount_cents']:
            errors.append(f'{line_id} 成功退款累计超过实付金额')
    for row in conn.execute('SELECT * FROM scenarios'):
        if not start <= strict_date(row['start_date']) <= strict_date(row['end_date']) <= end:
            errors.append('模拟场景日期无效')
    if errors:
        raise ValueError('；'.join(errors[:10]))
    return {'status': 'passed', 'order_lines': len(lines), 'refunds': conn.execute('SELECT COUNT(*) FROM refunds').fetchone()[0]}
