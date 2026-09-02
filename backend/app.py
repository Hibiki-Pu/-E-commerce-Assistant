from contextlib import closing

from flask import Flask, jsonify, request, send_from_directory

from .db import DEFAULT_DB, ROOT, connect
from .metrics import dashboard
from .financial_analysis import register_financial_analysis
from .public_financials import DEFAULT_PUBLIC_DB, register_public_financials
from .transaction_imports import register_transaction_imports
from .transaction_store import DEFAULT_IMPORT_DB
from .validation import validate_database


def create_app(db_path=DEFAULT_DB, public_db_path=DEFAULT_PUBLIC_DB, import_db_path=DEFAULT_IMPORT_DB, ai_client=None):
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    # 数据异常要在启动时显式暴露，不静默生成或覆盖。
    with closing(connect(db_path)) as conn:
        validate_database(conn)
    register_public_financials(app, public_db_path)
    register_financial_analysis(app, public_db_path, ai_client)
    register_transaction_imports(app, import_db_path)

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', is_simulated=True, stage=3, public_financials=True, transaction_imports=True, financial_analysis=True)

    @app.get('/api/meta')
    def meta():
        with closing(connect(db_path)) as conn:
            result = dict(conn.execute('SELECT * FROM dataset_meta').fetchone())
            result['products'] = [dict(r) for r in conn.execute('SELECT id,name,category FROM products ORDER BY id')]
            result['scenarios'] = [dict(r) for r in conn.execute('SELECT * FROM scenarios ORDER BY id')]
            result['counts'] = {table: conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                                for table in ('products', 'order_lines', 'refunds', 'product_costs')}
            result['missing_cost_lines'] = conn.execute("SELECT COUNT(*) FROM order_lines WHERE status IN ('paid','shipped','completed','refunded') AND unit_cost_cents IS NULL").fetchone()[0]
            result['validation_status'] = 'passed'
            return jsonify(result)

    @app.get('/api/dashboard')
    def get_dashboard():
        allowed = {'start', 'end', 'product_id'}
        if set(request.args) - allowed or any(len(request.args.getlist(k)) != 1 for k in request.args):
            return jsonify(error='存在未知或重复查询参数'), 400
        if not request.args.get('start') or not request.args.get('end'):
            return jsonify(error='必须提供开始日期和结束日期'), 400
        try:
            with closing(connect(db_path)) as conn:
                return jsonify(dashboard(conn, request.args['start'], request.args['end'], request.args.get('product_id')))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    @app.get('/public-financials')
    @app.get('/imports')
    @app.get('/imported')
    @app.get('/financial-analysis')
    def index():
        if not (ROOT / 'frontend/dist/index.html').exists():
            return '请先在 frontend 运行 npm run build，或使用 Vite 开发模式。', 503
        return send_from_directory(ROOT / 'frontend/dist', 'index.html')

    @app.get('/assets/<path:filename>')
    def assets(filename):
        return send_from_directory(ROOT / 'frontend/dist/assets', filename)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, debug=False)
