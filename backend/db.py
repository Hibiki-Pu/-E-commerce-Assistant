import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / 'data' / 'demo.sqlite3'


def connect(path=DEFAULT_DB, readonly=True):
    path = Path(path).resolve()
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) if readonly else sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    if readonly:
        conn.execute('PRAGMA query_only = ON')
        conn.execute('BEGIN')  # 同一次指标查询的多条 SELECT 读取同一份提交快照。
    return conn
