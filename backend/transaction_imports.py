"""本地导入 API。模板仅是应用测试示例，与任何公司财报无关。"""
import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, jsonify, request, Response

from .db import connect
from .metrics import dashboard
from .transaction_files import FIELDS, MAX_BYTES, parse_upload
from .transaction_store import DEFAULT_IMPORT_DB, apply_rows, initialize, save_provenance, work_copy

EXAMPLES = {
    'orders': [
        ['SIM-L001', 'SIM-O001', 'SIM-P001', '模拟随行杯', '2026-08-24', '已完成', 2, '118.00'],
        ['SIM-L002', 'SIM-O001', 'SIM-P002', '模拟收纳盒', '2026-08-24', '已完成', 1, '39.00'],
    ],
    'refunds': [['SIM-R001', 'SIM-L001', '2026-08-25', '成功', '29.50']],
    'costs': [['SIM-P001', '2026-08-01', '24.00'], ['SIM-P002', '2026-08-01', '']],
    'costs_complete': [['SIM-P001', '2026-08-01', '24.00'], ['SIM-P002', '2026-08-01', '16.00']],
    'orders_errors': [
        ['SIM-BAD1', 'SIM-O002', 'SIM-P001', '模拟随行杯', '2026-02-30', '已完成', 1, '59.00'],
        ['SIM-BAD2', '', 'SIM-P001', '模拟随行杯', '2026-08-24', '已完成', 1, '59.001'],
    ],
}


def register_transaction_imports(app, db_path=DEFAULT_IMPORT_DB):
    db_path = Path(db_path)
    bp = Blueprint('transaction_imports', __name__)

    @bp.get('/api/imports/meta')
    def meta():
        if not db_path.exists():
            return jsonify(ready=False, counts={'order_lines': 0, 'refunds': 0, 'product_costs': 0, 'products': 0}, batches=[])
        with closing(connect(db_path)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='dataset_meta'").fetchone():
                return jsonify(ready=False, counts={}, batches=[])
            row = conn.execute('SELECT * FROM dataset_meta').fetchone()
            if not row:
                return jsonify(ready=False, counts={}, batches=[])
            result = dict(row)
            result.update(ready=True, is_simulated=False, source='user_upload_unverified', validation_status='passed', scenarios=[])
            result['products'] = [dict(r) for r in conn.execute('SELECT id,name,category FROM products ORDER BY id')]
            result['counts'] = {t: conn.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('products', 'order_lines', 'refunds', 'product_costs')}
            result['missing_cost_lines'] = conn.execute("SELECT COUNT(*) FROM order_lines WHERE status IN ('paid','shipped','completed','refunded') AND unit_cost_cents IS NULL").fetchone()[0]
            result['batches'] = [dict(r) for r in conn.execute('SELECT id,kind,filename,sha256,imported_at FROM import_batches ORDER BY id DESC LIMIT 50')]
            return jsonify(result)

    @bp.get('/api/imports/dashboard')
    def get_dashboard():
        if set(request.args) - {'start', 'end', 'product_id'} or any(len(request.args.getlist(k)) != 1 for k in request.args):
            return jsonify(error='存在未知或重复查询参数'), 400
        if not request.args.get('start') or not request.args.get('end'):
            return jsonify(error='必须提供开始日期和结束日期'), 400
        if not db_path.exists():
            return jsonify(error='尚未导入交易数据，请先打开交易表导入页面'), 409
        try:
            with closing(connect(db_path)) as conn:
                if not conn.execute('SELECT 1 FROM dataset_meta').fetchone():
                    return jsonify(error='尚未导入交易数据'), 409
                result = dashboard(conn, request.args['start'], request.args['end'], request.args.get('product_id'))
                result.update(is_simulated=False, source='user_upload_unverified')
                return jsonify(result)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.get('/api/imports/examples/<name>')
    def example(name):
        if name not in EXAMPLES:
            return jsonify(error='文件不存在'), 404
        kind = name.split('_')[0]
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(FIELDS[kind].values())
        writer.writerows(EXAMPLES[name])
        return Response(out.getvalue().encode('utf-8-sig'), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename="SIMULATED_{name}.csv"'})

    @bp.post('/api/imports/<action>')
    def upload(action):
        if request.headers.get('X-Import-Request') != 'commerce-insight':
            return jsonify(error='请从本地导入页面提交'), 403
        origin = request.headers.get('Origin')
        if origin and origin not in {request.host_url.rstrip('/'), 'http://127.0.0.1:5173', 'http://localhost:5173'}:
            return jsonify(error='不接受跨站导入请求'), 403
        if action not in ('preview', 'commit'):
            return jsonify(error='未知导入操作'), 404
        required = {'kind', 'start', 'end'}
        if set(request.form) != required or any(len(request.form.getlist(k)) != 1 for k in required) or set(request.files) != {'file'} or len(request.files.getlist('file')) != 1:
            return jsonify(error='必须提交单个 file、kind、start 和 end'), 400
        file = request.files['file']
        content = file.read(MAX_BYTES + 1)
        filename = (file.filename or '').replace('\\', '/').split('/')[-1][:200]
        kind, start, end = (request.form[k] for k in ('kind', 'start', 'end'))
        try:
            rows, errors, warnings, info = parse_upload(content, filename, kind)
            digest = hashlib.sha256(content).hexdigest()
            info.update(filename=filename, kind=kind, sha256=digest)
            # 预览及提交前预检只修改内存副本；无效文件不创建新数据库。
            with closing(work_copy(db_path)) as scratch:
                _, result = apply_rows(scratch, kind, rows, errors, warnings, start, end, info)
            if action == 'preview' or not result['valid']:
                return jsonify(result), 200 if result['valid'] else 422
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(connect(db_path, readonly=False)) as conn:
                initialize(conn)
                conn.execute('BEGIN IMMEDIATE')
                changed, result = apply_rows(conn, kind, rows, errors, warnings, start, end, info)
                if not result['valid']:
                    conn.rollback()
                    return jsonify(result), 422
                result['inserted'] = result['new_rows']
                if changed:
                    result['batch_id'] = save_provenance(conn, kind, changed, result, filename, digest)
                    conn.commit()
                else:
                    conn.rollback()  # 重复文件是纯 no-op，连历史表都不重复新增。
                return jsonify(result)
        except ValueError as exc:
            return jsonify(error=str(exc), valid=False, errors=[{'row': None, 'field': '文件/参数', 'message': str(exc)}]), 400
        except sqlite3.Error:
            app.logger.exception('Transaction import database error')
            return jsonify(error='导入数据库读写失败，请重试；事务未提交，模拟和财报库不受影响'), 503

    app.register_blueprint(bp)
