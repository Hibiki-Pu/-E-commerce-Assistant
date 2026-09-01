"""第二阶段：公开财报汇总导入。与模拟订单库隔离；金额以整数分保存。"""
import csv
import io
import json
import re
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from .db import ROOT

FIELDS = 'period business_unit metric value dataset_type company_code currency unit source_report_year source_page source_url basis data_kind notes'.split()
METRICS = dict(zip(
    'revenue cost_of_revenue selling_expense admin_expense rd_expense finance_expense operating_profit net_profit net_profit_parent net_profit_parent_excl operating_cash_flow'.split(),
    ['营业收入', '营业成本', '销售费用', '管理费用', '研发费用', '财务费用', '营业利润', '合并净利润', '归母净利润', '扣非归母净利润', '经营现金流量净额']))
QUARTER_METRICS = {'revenue', 'net_profit_parent', 'net_profit_parent_excl', 'operating_cash_flow'}
BUSINESSES = {'all': '公司整体', 'packaging': '包装业务', 'ecommerce': '电商业务', 'other': '其他业务', 'legacy_internet': '互联网业务（旧分类）', 'supply_chain': '供应链业务'}
TYPES = {'annual', 'quarterly', 'business'}
PACKAGE = ROOT / 'data/public-jihong'
DEFAULT_PUBLIC_DB = ROOT / 'data/public_financials.sqlite3'
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def xml(data):
    # 不提取 ZIP 到磁盘；禁用任何 DTD/实体声明，包括非 UTF-8 XML。
    if b'<!DOCTYPE' in data.upper().replace(b'\x00', b'') or b'<!ENTITY' in data.upper().replace(b'\x00', b''):
        raise ValueError('Excel XML 不允许 DTD 或实体声明')
    return ET.fromstring(data)


def xlsx_rows(content, sheet_name):
    """只读取原始数据工作表，不计算或信任公式。无新增运行依赖。"""
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            info = archive.infolist()
            if len(info) > 500 or sum(i.file_size for i in info) > 20 * 1024 * 1024:
                raise ValueError('Excel 解压后超过安全限额')
            if len({i.filename for i in info}) != len(info):
                raise ValueError('Excel 存在重复 ZIP 条目')
            book = xml(archive.read('xl/workbook.xml'))
            rels = xml(archive.read('xl/_rels/workbook.xml.rels'))
            targets = {r.attrib['Id']: r.attrib.get('Target', '') for r in rels if r.attrib.get('TargetMode') != 'External'}
            selected = next((s for s in book.findall('m:sheets/m:sheet', NS) if s.attrib['name'] == sheet_name), None)
            if selected is None:
                raise ValueError('Excel 缺少工作表：' + sheet_name)
            rid = selected.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = targets.get(rid, '')
            member = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            if '..' in member.split('/') or not member.startswith('xl/worksheets/'):
                raise ValueError('Excel 工作表路径异常')
            shared = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                shared = [''.join(si.itertext()) for si in xml(archive.read('xl/sharedStrings.xml'))]
            table = xml(archive.read(member))
            output = []
            row_ids = set()
            for row in table.findall('m:sheetData/m:row', NS):
                row_id = row.attrib.get('r')
                if row_id in row_ids:
                    raise ValueError('Excel 含重复行号')
                row_ids.add(row_id)
                values = [''] * len(FIELDS)
                seen = set()
                for cell in row.findall('m:c', NS):
                    address = cell.attrib.get('r', '')
                    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', address)
                    if not match or match[2] != row_id or address in seen:
                        raise ValueError('Excel 单元格坐标异常')
                    seen.add(address)
                    column = 0
                    for char in match[1]:
                        column = column * 26 + ord(char) - 64
                    if cell.find('m:f', NS) is not None:
                        raise ValueError('原始数据工作表不接受公式，请粘贴为数值')
                    kind = cell.attrib.get('t')
                    if kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//m:t', NS))
                    else:
                        value = cell.findtext('m:v', default='', namespaces=NS)
                        if kind == 's':
                            index = int(value)
                            if not 0 <= index < len(shared):
                                raise ValueError('Excel 共享字符串索引异常')
                            value = shared[index]
                        elif kind not in (None, 'n', 'str') and value:
                            raise ValueError('数据单元格只接受文本和数字')
                    if column > len(FIELDS):
                        if value:
                            raise ValueError('Excel 原始数据存在额外列')
                    else:
                        values[column - 1] = value
                if any(values):
                    output.append(values)
                    if len(output) > MAX_ROWS + 1:
                        raise ValueError('数据超过 5000 行上限')
            return output
    except (BadZipFile, KeyError, ET.ParseError, IndexError, RuntimeError, OSError) as exc:
        raise ValueError('无法读取 Excel，请使用数据包中的标准 .xlsx 文件') from exc


def read_upload(content, filename, dataset_type):
    if dataset_type not in TYPES:
        raise ValueError('请选择 annual、quarterly 或 business 数据类型')
    if not content or len(content) > MAX_BYTES:
        raise ValueError('文件为空或超过 5 MB')
    suffix = Path(filename).suffix.lower()
    if suffix == '.csv':
        try:
            reader = csv.reader(io.StringIO(content.decode('utf-8-sig')), strict=True)
            rows = []
            for row in reader:
                if any(row):
                    rows.append(row)
                if len(rows) > MAX_ROWS + 1:
                    raise ValueError('数据超过 5000 行上限')
        except (UnicodeError, csv.Error) as exc:
            raise ValueError('CSV 必须为 UTF-8 编码，且符合标准 CSV 格式') from exc
    elif suffix == '.xlsx':
        rows = xlsx_rows(content, dataset_type + '_data')
    else:
        raise ValueError('仅支持 .csv 和 .xlsx，不支持旧版 .xls')
    if not rows or rows[0] != FIELDS:
        raise ValueError('列名或列顺序不符，请使用数据包中的 14 列标准表头')
    if len(rows) == 1:
        raise ValueError('文件没有数据行')
    facts, errors = [], []
    for number, row in enumerate(rows[1:], 2):
        try:
            if len(row) != len(FIELDS):
                raise ValueError('列数应为 14')
            fact = dict(zip(FIELDS, row))
            validate_fact(fact, dataset_type)
            facts.append(fact)
        except ValueError as exc:
            errors.append({'row': number, 'message': str(exc)})
    return facts, errors


def validate_fact(fact, dataset_type):
    for name, value in fact.items():
        if name != 'notes' and not value:
            raise ValueError(name + ' 不能为空；缺失数据不能用零代替')
        if len(value) > 2000 or '\x00' in value or value != value.strip():
            raise ValueError(name + ' 含多余空白或超长/非法文本')
    fixed = {'dataset_type': dataset_type, 'company_code': '002803.SZ', 'currency': 'CNY', 'unit': 'yuan', 'basis': 'as_reported', 'data_kind': 'public_report'}
    for key, value in fixed.items():
        if fact[key] != value:
            raise ValueError(key + ' 必须为 ' + value)
    pattern = r'202[2-5]-Q[1-4]' if dataset_type == 'quarterly' else r'202[2-5]'
    if not re.fullmatch(pattern, fact['period']) or fact['source_report_year'] != fact['period'][:4]:
        raise ValueError('期间必须在 2022–2025 年，原披露年份必须与期间一致')
    allowed = QUARTER_METRICS if dataset_type == 'quarterly' else {'revenue', 'cost_of_revenue'} if dataset_type == 'business' else set(METRICS)
    if fact['metric'] not in allowed:
        raise ValueError('该数据类型不支持此 metric')
    business = fact['business_unit']
    business_allowed = {'packaging', 'legacy_internet', 'supply_chain'} if fact['period'][:4] == '2022' else {'packaging', 'ecommerce', 'other'}
    if (dataset_type != 'business' and business != 'all') or (dataset_type == 'business' and business not in business_allowed):
        raise ValueError('业务分类与年份/数据类型不匹配；2022 互联网业务不能改成电商业务')
    if not re.fullmatch(r'[1-9][0-9]{0,3}', fact['source_page']):
        raise ValueError('source_page 必须为从 1 开始的 PDF 页码')
    url = urlsplit(fact['source_url'])
    if url.scheme != 'https' or url.netloc != 'static.cninfo.com.cn' or not re.fullmatch(r'/finalpage/[0-9-]+/[0-9]+\.PDF', url.path) or url.query or url.fragment:
        raise ValueError('source_url 必须为巨潮资讯官方 PDF 链接')
    try:
        if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]{1,2})?', fact['value']):
            raise ValueError('value 必须为不含千分位的金额，最多 2 位小数')
        value = Decimal(fact['value'])
        if abs(value) > Decimal('1000000000000'):
            raise ValueError('金额超出本数据集安全范围')
        if fact['metric'] in {'revenue', 'cost_of_revenue', 'selling_expense', 'admin_expense', 'rd_expense'} and value < 0:
            raise ValueError('收入、成本及该费用不能为负数')
        fact['value'] = format(value, '.2f')
        fact['value_cents'] = int(value * 100)
    except InvalidOperation as exc:
        raise ValueError('金额格式错误') from exc


def identity(fact):
    return '|'.join(str(fact[k]) for k in ('dataset_type', 'company_code', 'period', 'business_unit', 'metric', 'basis'))


def reconcile(facts):
    lookup = {identity(f): f['value_cents'] for f in facts}
    def get(kind, period, unit, metric):
        return lookup.get('|'.join((kind, '002803.SZ', period, unit, metric, 'as_reported')))
    checks = []
    for year in ('2022', '2023', '2024', '2025'):
        for kind, metrics in [('quarterly', sorted(QUARTER_METRICS)), ('business', ['revenue', 'cost_of_revenue'])]:
            units = ['legacy_internet', 'packaging', 'supply_chain'] if year == '2022' else ['packaging', 'ecommerce', 'other']
            for metric in metrics:
                annual = get('annual', year, 'all', metric)
                parts = [get(kind, year + '-Q' + str(q), 'all', metric) for q in range(1, 5)] if kind == 'quarterly' else [get(kind, year, unit, metric) for unit in units]
                complete = annual is not None and all(p is not None for p in parts)
                difference = sum(parts) - annual if complete else None
                checks.append({'period': year, 'kind': kind, 'metric': metric, 'difference_cents': difference, 'status': 'pending' if not complete else 'passed' if difference == 0 else 'failed'})
    return checks


def existing_facts(db_path):
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        return [json.loads(row[0]) for row in conn.execute('SELECT payload FROM facts ORDER BY fact_key')]


def prepare(facts, stored, errors):
    lookup = {identity(f): f for f in stored}
    added, duplicates = [], 0
    errors = list(errors)
    for number, fact in enumerate(facts, 2):
        key = identity(fact)
        if key in lookup:
            if lookup[key] == fact:
                duplicates += 1
            else:
                errors.append({'row': number, 'message': '同一事实已存在不同金额或来源，禁止覆盖：' + key})
        else:
            lookup[key] = fact
            added.append(fact)
    checks = reconcile(lookup.values())
    for check in checks:
        if check['status'] == 'failed':
            errors.append({'row': None, 'message': f"{check['period']} {check['kind']} {METRICS[check['metric']]} 与年度值不一致，差额 {Decimal(check['difference_cents']) / 100:.2f} 元"})
    return added, {'valid': not errors, 'rows': len(facts), 'new_rows': len(added), 'duplicates': duplicates, 'errors': errors[:100], 'error_count': len(errors), 'samples': facts[:6], 'checks': checks}


def register_public_financials(app, db_path=DEFAULT_PUBLIC_DB):
    db_path = Path(db_path)
    blueprint = Blueprint('public_financials', __name__)
    app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES + 128 * 1024

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify(error='文件超过 5 MB 上传限制'), 413

    @blueprint.get('/api/public-financials')
    def overview():
        if request.args:
            return jsonify(error='此接口不接受查询参数'), 400
        manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
        facts = existing_facts(db_path)
        return jsonify(facts=facts, checks=reconcile(facts), manifest=manifest, metrics=METRICS, business_units=BUSINESSES)

    @blueprint.get('/api/public-financials/files/<name>')
    def download(name):
        if name not in {'annual_data.csv', 'quarterly_data.csv', 'business_data.csv', 'jihong_public_financials.xlsx', 'manifest.json'}:
            return jsonify(error='文件不存在'), 404
        return send_from_directory(PACKAGE, name, as_attachment=True)

    @blueprint.post('/api/public-financials/<action>')
    def upload(action):
        # 自定义头阻止跨站简单表单写入；不开放 CORS。允许 Vite 同源开发代理。
        if request.headers.get('X-Import-Request') != 'commerce-insight':
            return jsonify(error='请从本地导入页面提交'), 403
        origin = request.headers.get('Origin')
        if origin and origin not in {request.host_url.rstrip('/'), 'http://127.0.0.1:5173', 'http://localhost:5173'}:
            return jsonify(error='不接受跨站导入请求'), 403
        if action not in {'preview', 'commit'}:
            return jsonify(error='未知操作'), 404
        if set(request.form) != {'dataset_type'} or len(request.form.getlist('dataset_type')) != 1 or set(request.files) != {'file'} or len(request.files.getlist('file')) != 1:
            return jsonify(error='必须提交单个 file 和 dataset_type'), 400
        file = request.files['file']
        try:
            facts, errors = read_upload(file.read(MAX_BYTES + 1), file.filename or '', request.form['dataset_type'])
            if errors:
                return jsonify(valid=False, rows=len(facts) + len(errors), new_rows=0, duplicates=0, errors=errors[:100], error_count=len(errors), samples=facts[:6], checks=[]), 422
            if action == 'preview':
                _, result = prepare(facts, existing_facts(db_path), errors)
                return jsonify(result), 200 if result['valid'] else 422
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(db_path, timeout=10)) as conn:
                # 重新核验，不信任预览结果；所有行一次性提交或回滚。
                conn.execute('CREATE TABLE IF NOT EXISTS facts (fact_key TEXT PRIMARY KEY, value_cents INTEGER NOT NULL, payload TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
                conn.execute('BEGIN IMMEDIATE')
                stored = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM facts')]
                added, result = prepare(facts, stored, errors)
                if not result['valid']:
                    conn.rollback()
                    return jsonify(result), 422
                conn.executemany('INSERT INTO facts(fact_key,value_cents,payload) VALUES(?,?,?)', [(identity(f), f['value_cents'], json.dumps(f, ensure_ascii=False, sort_keys=True)) for f in added])
                conn.commit()
                result['inserted'] = len(added)
                return jsonify(result)
        except (ValueError, OverflowError) as exc:
            return jsonify(error=str(exc)), 400
        except sqlite3.Error:
            app.logger.exception('Public financial import database failure')
            return jsonify(error='财报数据库读写失败，请检查磁盘或稍后重试；原模拟订单库未修改'), 503

    app.register_blueprint(blueprint)
