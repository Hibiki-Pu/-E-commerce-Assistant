"""固定种子、固定观察期，生成 2000 条模拟订单明细；拒绝覆盖已有数据库。"""
import argparse
import random
from datetime import date, timedelta
from pathlib import Path

from .db import DEFAULT_DB, ROOT, connect
from .validation import validate_database

SEED = 20260830
START, END = date(2026, 6, 2), date(2026, 8, 30)
CATALOG = [
    ('轻量随行杯', '日用生活', 5900, 2400), ('桌面收纳盒', '家居收纳', 3900, 1600),
    ('便携手冲壶', '咖啡器具', 12900, 6100), ('棉麻餐垫', '日用生活', 2900, 1000),
    ('玻璃冷萃瓶', '咖啡器具', 8900, 3900), ('折叠收纳筐', '家居收纳', 6900, 2900),
    ('极简笔记本', '办公文具', 2500, 900), ('原木手机架', '办公文具', 4500, 1800),
    ('硅胶隔热垫', '日用生活', 1900, 650), ('帆布手提袋', '日用生活', 4900, 2000),
    ('咖啡滤纸套装', '咖啡器具', 2200, 800), ('不锈钢量勺', '咖啡器具', 3500, 1200),
    ('磁吸便签板', '办公文具', 5500, 2300), ('透明文件袋', '办公文具', 1500, 500),
    ('衣柜分隔板', '家居收纳', 4200, 1700), ('抽屉整理格', '家居收纳', 3200, 1200),
    ('旅行分装瓶', '日用生活', 2800, 1000), ('软木杯垫套装', '日用生活', 2600, 850),
    ('桌面理线夹', '办公文具', 1800, 550), ('陶瓷马克杯', '日用生活', 6500, 2800),
]


def generate(path=DEFAULT_DB, seed=SEED):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 排他创建：即使重复启动也不会清空用户已有文件。
    with path.open('xb'):
        pass
    conn = connect(path, readonly=False)
    rng = random.Random(seed)
    try:
        conn.executescript((ROOT / 'backend/schema.sql').read_text(encoding='utf-8'))
        conn.execute('INSERT INTO dataset_meta VALUES (1,?,?,?,?,?,1)',
                     ('模拟数据 · 个人求职展示', 'CNY', START.isoformat(), END.isoformat(), seed))
        for i, (name, category, price, cost) in enumerate(CATALOG, 1):
            pid = f'P{i:03}'
            conn.execute('INSERT INTO products(id,name,category) VALUES (?,?,?)', (pid, name, category))
            conn.execute('INSERT INTO product_costs(product_id,effective_from,unit_cost_cents) VALUES (?,?,?)', (pid, START.isoformat(), cost))
        conn.execute("INSERT INTO product_costs(product_id,effective_from,unit_cost_cents) VALUES ('P003','2026-08-17',7900)")
        conn.execute("INSERT INTO product_costs(product_id,effective_from,unit_cost_cents) VALUES ('P020','2026-08-24',NULL)")
        scenarios = [
            ('2026-08-17', '2026-08-30', '随行杯促销放量', '人为提高 P001 的抽样权重，并将其实付单价打八折；最后两周整体订单抽样权重上调。用于观察销售与贡献利润的不同变化。'),
            ('2026-08-17', '2026-08-30', '手冲壶采购成本上涨', 'P003 的模拟单位采购成本从 61 元调整到 79 元，售价规则不变；历史订单成本快照保持不变。'),
            ('2026-08-24', '2026-08-28', '收纳盒集中跨期退款', '对 P002 在 08-10 至 08-23 的订单设置集中成功退款，按原实付的 50% 退款。该原因是生成规则，不是真实售后结论。'),
            ('2026-08-24', '2026-08-30', '马克杯成本待补充', 'P020 在 08-24 起的成本版本设为未知，用于展示数据缺口；相关商品和整体贡献利润必须显示不可计算。'),
        ]
        conn.executemany('INSERT INTO scenarios(start_date,end_date,title,description) VALUES (?,?,?,?)', scenarios)
        dates = [START + timedelta(days=i) for i in range(90)]
        date_weights = [1.45 if d >= date(2026, 8, 17) else 1 for d in dates]
        # 先保证每日有明细，再按权重抽样；随机数实例独立，不依赖系统时间。
        order_dates = dates + rng.choices(dates, weights=date_weights, k=1910)
        order_dates.sort()
        refund_index = 0
        for i, day in enumerate(order_dates, 1):
            weights = [8 if p == 0 and day >= date(2026, 8, 17) else 2 if p < 4 else 1 for p in range(20)]
            index = rng.choices(range(20), weights=weights)[0]
            pid = f'P{index+1:03}'
            _, _, price, cost = CATALOG[index]
            quantity = rng.choices([1, 2, 3], [8, 2, 1])[0]
            status = rng.choices(['completed', 'shipped', 'paid', 'cancelled', 'pending'], [80, 8, 5, 4, 3])[0]
            active = status not in ('cancelled', 'pending')
            if index == 0 and day >= date(2026, 8, 17):
                price = price * 80 // 100
            if index == 2 and day >= date(2026, 8, 17):
                cost = 7900
            if index == 19 and day >= date(2026, 8, 24):
                cost = None
            amount = price * quantity if active else 0
            line_id = f'L{i:05}'
            conn.execute('''INSERT INTO order_lines(id,order_id,product_id,paid_date,status,quantity,paid_amount_cents,unit_cost_cents)
                VALUES (?,?,?,?,?,?,?,?)''', (line_id, f'DEMO-{(i+1)//2:05}', pid, day.isoformat() if active else None, status, quantity, amount, cost if active else None))
            if not active:
                continue
            spike = index == 1 and date(2026, 8, 10) <= day <= date(2026, 8, 23)
            if spike:
                refund_day = date(2026, 8, 24) + timedelta(days=rng.randrange(5))
                refund_amount, refund_status = amount // 2, 'success'
            elif rng.random() < .11:
                refund_day = day + timedelta(days=rng.randint(1, 12))
                refund_amount = amount if rng.random() < .4 else amount // 2
                refund_status = rng.choices(['success', 'processing', 'failed'], [8, 1, 1])[0]
            else:
                continue
            if refund_day > END:
                continue
            refund_index += 1
            conn.execute('INSERT INTO refunds(id,order_line_id,refund_date,status,amount_cents) VALUES (?,?,?,?,?)',
                         (f'R{refund_index:05}', line_id, refund_day.isoformat(), refund_status, refund_amount))
            if refund_status == 'success' and refund_amount == amount:
                conn.execute("UPDATE order_lines SET status='refunded' WHERE id=?", (line_id,))
        report = validate_database(conn)
        conn.commit()
        return report
    except Exception:
        conn.rollback()
        conn.close()
        path.unlink()  # 仅清理由本次排他创建、且生成失败的文件。
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成模拟经营数据；绝不覆盖已有文件')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        print('SIMULATED DATA:', generate(args.db))
    except FileExistsError:
        parser.exit(1, '目标数据库已存在，未作任何修改。请用 --db 指向项目内一个新文件。\n')
