# 数据洞察与自助分析平台

面向业务分析师的自助式数据洞察平台。覆盖数据集市构建、自助SQL查询、可视化拖拽分析、分析看板协作、指标异动归因、分析模型沉淀、查询优化建议与数据故事编排的完整洞察链路。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据集市构建 | `mart` | 集市定义 | 集市编号、集市名称、数据源表 |
| 自助SQL查询 | `sqlpad` | 查询脚本 | 脚本编号、脚本名称、SQL语句 |
| 拖拽可视化 | `vizdrag` | 可视化方案 | 方案编号、方案名称、数据源绑定 |
| 看板协作管理 | `collab` | 协作看板 | 看板编号、看板名称、协作成员 |
| 指标异动归因 | `anomaly` | 异动记录 | 记录编号、指标名称、异动方向 |
| 分析模型沉淀 | `model` | 模型注册 | 模型编号、模型类型、训练数据、评估指标、模型版本、负责人 |
| 查询优化建议 | `opt` | 优化建议 | 建议编号、目标查询、优化类型 |
| 数据故事编排 | `story` | 故事模板 | 模板编号、故事标题、分析主题 |
| 数据准备流水线 | `etl` | 准备任务 | 任务编号、任务名称、输入源 |
| 数据目录检索 | `catalog` | 目录条目 | 条目编号、数据集名称、业务域、数据集编号（字段清单引用模型注册同一份） |
| 数据采样管理 | `sample` | 采样配置 | 配置编号、数据源名称、采样算法 |
| 同环比分析 | `compare` | 对比方案 | 方案编号、对比指标、基准周期 |
| 分析导出中心 | `export` | 导出任务 | 任务编号、数据源名称、导出格式 |
| 分析告警规则 | `alarm` | 告警规则 | 规则编号、监控指标、告警条件 |
| 数据定时刷新 | `refresh` | 刷新策略 | 策略编号、目标数据集、刷新周期 |
| 查询审计日志 | `audit` | 审计记录 | 记录编号、查询语句、执行人 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 模型注册与部署预检

分析模型沉淀不再只有编号、名称和类型，而是围绕「训练数据 + 评估指标 + 模型版本」做注册与部署前核对：

- `GET /api/model/registry`：模型注册清单，按模型编号分组列出每个版本的训练数据字段清单、
  评估指标、预检结论与是否生效。
- `GET /api/model/{id}/precheck`：部署预检，结论三档——`可部署` / `需补充证据` / `拒绝部署`。
  类型门槛：分类需 AUC、准确率 ≥ 0.85；回归需 RMSE ≤ 1.0、R2 ≥ 0.80；聚类需轮廓系数 ≥ 0.45。
  指标缺失或状态仍是草稿时转「需补充证据」；指标低于门槛、训练数据不可用、部署路径非法时「拒绝部署」。
- `POST /api/model/{id}/actions`：`部署模型`、`下线模型`、`归档模型`、`变更归属`。
- 同一「模型编号 + 模型版本」重复登记只更新原记录，不新增副本。
- 同一模型的部署按模型编号串行化，任何时刻只有一个版本「是否生效」为真；部署失败会把评估指标
  回退到上一份评估指标快照，原生效版本保持不变。
- `GET /api/model/deployments`：发布流水，记录执行人、归属负责人与评估指标快照；变更归属只影响
  后续操作，历史发布仍按原责任人留档。

### 权限与身份

模型部署只允许归属负责人执行；数据目录成员不能改写模型版本；普通查看者拿到只读注册信息。
身份通过请求头 `X-Operator` / `X-Role` 声明，中文值需 URL 编码（前端已自动处理）：

```bash
curl -H 'X-Operator: %E8%B5%B5%E5%90%AF%E6%98%8E' -H 'X-Role: %E6%A8%A1%E5%9E%8B%E8%B4%9F%E8%B4%A3%E4%BA%BA' \
  http://127.0.0.1:8000/api/model/1/precheck
```

角色取值：`模型负责人`、`数据目录成员`、`普通查看者`（也接受 `owner` / `catalog` / `viewer`）。

### 训练数据字段清单

`backend/app/services/datasets.py` 维护唯一一份训练数据字段清单。模型注册清单里的「训练数据」
和数据目录条目的「字段清单」都从这里解析：目录条目只保存数据集编号，不再各存一份字段，
`GET /api/catalog/field-manifests` 可直接查看共用清单。

### 测试

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```

领域：数据工程
子方向：数仓与数据湖
