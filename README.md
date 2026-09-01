# 商析 AI——电商经营复盘助手

管理类硕士的个人求职展示项目，面向 AI 应用、数据运营与业务数字化岗位。包含三个独立数据分支：**模拟订单看板**、**吉宏股份 2022—2025 年公开财报汇总**、**用户上传交易表（来源未核验）**。没有真实客户或商用效果，不连接真实店铺，不接模型，不伪造 AI 解读。

第二阶段已加入 Excel / CSV 公开财报导入、预览校验、冲突拒绝、独立数据库和来源追溯。入口为首页侧栏「公开财报导入」，或 `http://127.0.0.1:5000/public-financials`。这是公开汇总数据导入分支，不是内部订单导入；[完整操作与验收](docs/第二阶段_公开财报导入.md)。

本次新增订单明细、退款明细、商品成本 `.xlsx/.csv` 导入，支持错误行定位、业务键去重、整份回滚、缺失成本警告与后续补齐。打开 **http://127.0.0.1:5000/imports**，按「校验并预览 → 确认导入 → 导入数据看板」操作。[格式、示例与验收步骤](docs/第二步_交易表导入.md)。公司财报不是订单数据，请勿交叉导入。

技术：React + TypeScript + Vite / Python + Flask / SQLite。没有多智能体、向量数据库或复杂后端框架。金额使用整数分，查询连接只读；公开财报及交易表确认导入接口分别写独立库。Excel 读取使用 openpyxl 和 defusedxml，新增依赖已锁定。

## Windows 启动

本机已完成环境安装、数据生成和前端构建。以后只需在 PowerShell 执行：

```powershell
cd D:\gametest\commerce-insight
.\start.cmd
```

浏览器访问 **http://127.0.0.1:5000**。保持终端打开，按 Ctrl+C 停止。只监听 127.0.0.1，不对局域网或公网开放。若提示端口占用，先检查是否已经运行了本项目；不要直接终止不认识的进程。

新电脑首次安装（已验证 Python 3.10.2、Node.js 24.11.1；推荐使用相同主版本，Vite 要求 Node 20.19+ 或 22.12+）：

```powershell
cd D:\gametest\commerce-insight
.\setup.cmd
.\start.cmd
```

`setup.cmd` 下载公开依赖到项目虚拟环境及 node_modules，运行构建和测试，不购买服务。需要已安装 Python 和 Node.js/npm 并加入 PATH；无需激活 PowerShell 脚本或更改执行策略。后端依赖锁定在 `backend/requirements-lock.txt`，前端锁定在 `frontend/package-lock.json`。已有数据库始终保留，不会自动重置。

手动安装等价步骤：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
.\.venv\Scripts\python.exe -m backend.seed
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m backend.app
```

`backend.seed` 在数据库已存在时会明确拒绝写入，这是保护行为。需要验证复现时，可用 `--db data\another-demo.sqlite3` 生成新的文件；该命令不会切换看板数据源。若网络不可用且依赖未缓存，安装会失败，须恢复网络后重试，不需要 API Key。

## 开发模式与测试

终端 1：

```powershell
cd D:\gametest\commerce-insight
.\.venv\Scripts\python.exe -m backend.app
```

终端 2（前端热更新）：

```powershell
cd D:\gametest\commerce-insight\frontend
npm.cmd run dev
```

开发时访问 http://127.0.0.1:5173；Vite 将 `/api` 代理到 5000，避免额外 CORS 配置。`npm run preview` 仅预览静态页面、不代理 API，本项目演示请用 `start.cmd`。编辑后端需要重启；编辑前端后若使用 5000 的构建模式，需要重新 `npm.cmd run build` 并刷新浏览器。

```powershell
cd D:\gametest\commerce-insight
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
cd frontend
npm.cmd run build
```

测试只使用内存或临时 SQLite，不修改演示数据。Python 用标准库 unittest，无额外测试框架。

## 看板操作

1. 默认显示 2026-08-24～08-30，与 08-17～08-23 比较；这是固定模拟数据的最后一周，不是随电脑时间滚动的日期。
2. 改日期或商品后点击「应用筛选」。快捷按钮立即查询，可保留当前商品选择。
3. 默认有 9 条成本缺失明细，整体商品成本与贡献利润显示「不可计算」。筛选 P001 可查看完整利润；P020 演示成本缺口，P002 演示跨期退款和负贡献。
4. 趋势图悬停查看金额，或展开「每日明细」读取精确数据。商品排名可在表格内滚动；手机端表格可以横向滚动。
5. 展开「人为设置的经营变化场景」可检查生成规则。AI 解读只显示「后续接入」。模拟看板不上传或修改订单；第二阶段公开财报页面单独支持文件下载、预览与导入。

## 文件导航与建议阅读顺序

```text
commerce-insight/
  docs/一页需求文档.md         一页式需求、范围和验收条件
  docs/需求与指标口径.md       详细业务口径与边界处理
  docs/数据库与数据字典.md     字段、约束、关联和接口协议
  docs/学习与验收.md           三个知识点、验收步骤、真实测试记录
  backend/schema.sql           表结构与索引
  backend/seed.py              固定种子与四个模拟场景
  backend/validation.py        业务数据校验
  backend/metrics.py           核心指标与环比计算
  backend/app.py               Flask API 与静态页面服务
  backend/public_financials.py 公开财报解析、校验、原子导入与核验
  backend/transaction_files.py 交易 Excel/CSV 读取与行级校验
  backend/transaction_store.py 交易去重、成本补齐与事务
  backend/transaction_imports.py 交易导入 API 与独立看板 API
  docs/第二步_交易表导入.md    导入协议、数据字典、学习与验收
  data/public-jihong/          Excel、三份 CSV、来源和口径清单
  frontend/src/PublicFinancials.tsx  公开财报导入工作台
  frontend/src/TransactionImports.tsx 交易表导入工作台
  backend/tests/               核心逻辑、API、生成器测试
  frontend/src/types.ts        后端响应的 TypeScript 类型
  frontend/src/format.ts       金额展示、日期偏移、请求封装
  frontend/src/Trend.tsx        仅用 SVG 展示后端每日数值
  frontend/src/main.tsx        筛选、卡片、排名、口径和错误状态
  frontend/src/style.css       桌面与移动布局
  data/demo.sqlite3            生成的模拟数据库，不提交
  setup.cmd / start.cmd        Windows 安装与本地启动
```

先看指标文档，再读 `metrics.py` 的 `aggregate → finalize → dashboard`，最后看 tests 中对应的用例。演示不依赖外部图片、字体、模型服务或店铺账号。`.gitignore` 排除数据库、虚拟环境、node_modules、构建产物和所有 `.env` 文件；请勿提交任何真实数据或密钥。

## 阶段边界

已实现：模拟生成与校验、只读经营看板；独立公开财报导入与来源追溯；独立订单/退款/商品成本文件导入、错误行反馈、去重、缺失成本补齐及导入看板；自动化测试和启动说明。尚未实现：AI 解读、经营周报人工审核与导出。商品贡献利润不是净利润；退款不冲回采购成本；模拟场景不能作为真实经营因果证据。仅有导入批次与行级追溯，不提供生产级多用户权限、安全审计或部署能力。

后续设计只保留原则：模型只能调用经过参数校验的预定义只读工具；数值由程序计算；禁止执行模型任意 SQL/Python/命令；输出要能追溯；上传文字不具备指令权限；API Key 只允许放服务端环境变量。等待本阶段验收后再扩展。
