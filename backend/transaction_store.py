"""交易导入暂存与事务：先在内存库验证，确认后持锁重新验证再提交。"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .db import ROOT, connect
from .transaction_files import issue
from .validation import strict_date, VALID_STATUSES

DEFAULT_IMPORT_DB = ROOT / 'data' / 'imported_transactions.sqlite3'
TABLES = {'orders': 'order_lines', 'refunds': 'refunds', 'costs': 'product_costs'}


def initialize(conn):
    # 原模拟库不迁移。独立导入库复用相同关系、金额约束，来源标记为未核验的上传数据。
    schema = (ROOT / 'backend/schema.sql').read_text(encoding='utf-8')
    schema = schema.replace('DEFAULT 1 CHECK (is_simulated = 1)', 'DEFAULT 0 CHECK (is_simulated = 0)')
    schema = schema.replace('CHECK (is_simulated = 1)', 'CHECK (is_simulated = 0)')
    schema = schema.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ').replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ')
    conn.executescript('BEGIN IMMEDIATE;\n' + schema)
    conn.execute('''CREATE TABLE IF NOT EXISTS import_batches (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, filename TEXT NOT NULL,
        sha256 TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        report TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS import_rows (
        kind TEXT NOT NULL, business_key TEXT NOT NULL, payload TEXT NOT NULL,
        batch_id INTEGER NOT NULL REFERENCES import_batches(id), source_row INTEGER NOT NULL,
        PRIMARY KEY(kind, business_key))''')
    conn.commit()


def work_copy(path):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    if Path(path).exists():
        with closing(connect(path)) as source:
            source.backup(conn)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='import_rows'").fetchone():
        initialize(conn)
    return conn


def key_for(kind, row):
    values = [row['product_id'], row['effective_from']] if kind == 'costs' else [row['order_line_id'] if kind == 'orders' else row['refund_id']]
    return json.dumps(values, ensure_ascii=False)


def payload(row):
    return {k: v for k, v in row.items() if not k.startswith('_')}


def applicable_cost(conn, product, day):
    row = conn.execute('SELECT unit_cost_cents FROM product_costs WHERE product_id=? AND effective_from<=? ORDER BY effective_from DESC LIMIT 1', (product, day)).fetchone()
    return row[0] if row else None


def product(conn, pid, name=None):
    stored = conn.execute('SELECT name FROM products WHERE id=?', (pid,)).fetchone()
    if stored and name and stored['name'] not in (pid, name):
        raise ValueError('同一商品编码对应不同名称，禁止静默覆盖：' + pid)
    if not stored:
        conn.execute('INSERT INTO products(id,name,category) VALUES (?,?,?)', (pid, name or pid, '未分类'))
    elif name and stored['name'] == pid:
        conn.execute('UPDATE products SET name=? WHERE id=?', (name, pid))


def apply_rows(conn, kind, rows, base_errors, base_warnings, start, end, info, batch_id=0):
    """调用方必须回滚无效结果。返回所有错误/重复/警告，不截断。"""
    first, last = strict_date(start), strict_date(end)
    if first > last or (last - first).days >= 90:
        raise ValueError('观察期必须是包含首尾的 1 至 90 天')
    meta = conn.execute('SELECT * FROM dataset_meta').fetchone()
    if meta and (meta['start_date'], meta['end_date']) != (start, end):
        raise ValueError('该单店铺导入库观察期已固定，必须使用 ' + meta['start_date'] + ' 至 ' + meta['end_date'])
    if not meta:
        conn.execute('INSERT INTO dataset_meta VALUES (1,?,?,?,?,?,0)', ('用户导入 · 来源未核验', 'CNY', start, end, 0))
    errors, warnings, duplicates, additions, updates = list(base_errors), list(base_warnings), [], [], []
    existing = {r['business_key']: dict(r) for r in conn.execute('SELECT * FROM import_rows WHERE kind=?', (kind,))}
    for row in rows:
        key, value = key_for(kind, row), payload(row)
        stored = existing.get(key)
        if stored:
            previous = json.loads(stored['payload'])
            if previous == value:
                duplicates.append(issue(row['_row'], '业务主键', f"内容相同，明确跳过；原批次 {stored['batch_id']} 第 {stored['source_row']} 行"))
                continue
            can_fill = kind == 'costs' and previous['unit_cost_cents'] is None and value['unit_cost_cents'] is not None
            if not can_fill:
                errors.append(issue(row['_row'], '业务主键', f"相同主键内容冲突，整份拒绝；原批次 {stored['batch_id']} 第 {stored['source_row']} 行"))
                continue
            updates.append(row)
        else:
            additions.append(row)
        existing[key] = {'payload': json.dumps(value, ensure_ascii=False), 'batch_id': batch_id, 'source_row': row['_row']}
    changed = additions + updates
    for row in changed:
        number = row['_row']
        try:
            if kind == 'orders':
                if row['paid_date'] and not start <= row['paid_date'] <= end:
                    raise ValueError('支付日期超出所声明的观察期')
                product(conn, row['product_id'], row['product_name'])
                cost = applicable_cost(conn, row['product_id'], row['paid_date']) if row['paid_date'] else None
                conn.execute('''INSERT INTO order_lines(id,order_id,product_id,paid_date,status,quantity,paid_amount_cents,unit_cost_cents)
                    VALUES (?,?,?,?,?,?,?,?)''', (row['order_line_id'], row['order_id'], row['product_id'], row['paid_date'], row['status'], row['quantity'], row['paid_amount_cents'], cost))
                if cost is None and row['status'] in VALID_STATUSES:
                    warnings.append(issue(number, '商品成本', '支付日没有可用成本：已保留未知，相关利润不可计算'))
            elif kind == 'costs':
                if row['effective_from'] > end:
                    raise ValueError('成本生效日在观察期结束之后')
                product(conn, row['product_id'])
                conn.execute('''INSERT INTO product_costs(product_id,effective_from,unit_cost_cents) VALUES (?,?,?)
                    ON CONFLICT(product_id,effective_from) DO UPDATE SET unit_cost_cents=excluded.unit_cost_cents''', (row['product_id'], row['effective_from'], row['unit_cost_cents']))
                if row['unit_cost_cents'] is None:
                    warnings.append(issue(number, '单位成本', '空值保留为未知，绝不补零；可再次上传同一版本补齐'))
            else:
                order = conn.execute('SELECT * FROM order_lines WHERE id=?', (row['order_line_id'],)).fetchone()
                if not order or order['status'] not in VALID_STATUSES:
                    raise ValueError('找不到已支付订单明细，请先导入订单；未支付/取消订单不能退款')
                if not start <= row['refund_date'] <= end or row['refund_date'] < order['paid_date']:
                    raise ValueError('退款日期早于支付日或超出观察期')
                cumulative = conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM refunds WHERE order_line_id=? AND status='success'", (row['order_line_id'],)).fetchone()[0]
                if row['amount_cents'] > order['paid_amount_cents'] or (row['status'] == 'success' and cumulative + row['amount_cents'] > order['paid_amount_cents']):
                    raise ValueError('退款金额或累计成功退款超过明细实付金额')
                conn.execute('INSERT INTO refunds(id,order_line_id,refund_date,status,amount_cents) VALUES (?,?,?,?,?)', (row['refund_id'], row['order_line_id'], row['refund_date'], row['status'], row['amount_cents']))
        except ValueError as exc:
            errors.append(issue(number, '业务规则', str(exc)))
    backfilled = 0
    if kind == 'costs':
        for order in conn.execute("SELECT * FROM order_lines WHERE status IN ('paid','shipped','completed','refunded')").fetchall():
            cost = applicable_cost(conn, order['product_id'], order['paid_date'])
            if order['unit_cost_cents'] is not None and order['unit_cost_cents'] != cost:
                affected = [r for r in changed if r['product_id'] == order['product_id'] and r['effective_from'] <= order['paid_date']]
                for row in affected:
                    errors.append(issue(row['_row'], '单位成本', '新成本版本会改写已有已知成本快照，禁止自动重算历史订单：' + order['id']))
            elif order['unit_cost_cents'] is None and cost is not None:
                conn.execute('UPDATE order_lines SET unit_cost_cents=? WHERE id=?', (cost, order['id']))
                backfilled += 1
    missing = conn.execute("SELECT COUNT(*) FROM order_lines WHERE status IN ('paid','shipped','completed','refunded') AND unit_cost_cents IS NULL").fetchone()[0]
    # JSON 传整数给浏览器：在入库前限制总量，避免 JS 超过安全整数而失去分精度。
    activity = 0
    for line in conn.execute("SELECT * FROM order_lines WHERE status IN ('paid','shipped','completed','refunded')"):
        activity += line['paid_amount_cents']
        if line['unit_cost_cents'] is not None:
            activity += line['unit_cost_cents'] * line['quantity']
    activity += sum(r[0] for r in conn.execute("SELECT amount_cents FROM refunds WHERE status='success'"))
    if activity > 2**53 - 1:
        errors.append(issue(None, '金额总量', '总金额超过浏览器可精确表示的整数分范围，整份拒绝；不做近似计算'))
    if not rows and not errors:
        errors.append(issue(2, '整行', '没有可导入的数据行'))
    result = dict(info, valid=not errors, errors=errors, warnings=warnings, duplicates=duplicates,
                  error_count=len(errors), duplicate_count=len(duplicates), new_rows=len(additions),
                  updated_cost_rows=len(updates), backfilled_order_lines=backfilled,
                  missing_cost_lines=missing, samples=rows[:5], inserted=0)
    return changed, result


def save_provenance(conn, kind, changed, result, filename, digest):
    batch = conn.execute('INSERT INTO import_batches(kind,filename,sha256,report) VALUES (?,?,?,?)',
                         (kind, filename, digest, json.dumps(result, ensure_ascii=False))).lastrowid
    for row in changed:
        conn.execute('''INSERT INTO import_rows(kind,business_key,payload,batch_id,source_row) VALUES (?,?,?,?,?)
            ON CONFLICT(kind,business_key) DO UPDATE SET payload=excluded.payload,batch_id=excluded.batch_id,source_row=excluded.source_row''',
                     (kind, key_for(kind, row), json.dumps(payload(row), ensure_ascii=False), batch, row['_row']))
    return batch
