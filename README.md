# 主数据清洗与黄金记录平台

面向多源主数据的匹配识别、冲突消解、合并清洗与黄金记录管理的主数据治理平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
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
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 来源系统注册 | `source_system` | 来源系统 | 系统编号、系统名称、系统类型 |
| 实体模型定义 | `entity_model` | 实体模型 | 模型编号、模型名称、业务域 |
| 匹配规则引擎 | `match_rule` | 匹配规则 | 规则编号、实体模型、匹配字段 |
| 疑似重复簇 | `dup_cluster` | 重复簇 | 簇编号、实体模型、簇大小 |
| 合并追溯日志 | `merge_log` | 合并记录 | 记录编号、黄金ID、来源记录 |
| 黄金记录管理 | `golden_record` | 黄金记录 | 黄金ID、实体模型、关联来源 |
| 字段标准化清洗 | `field_cleanse` | 清洗规则 | 规则编号、实体模型、目标字段 |
| 优胜策略配置 | `survivorship_rule` | 优胜策略 | 策略编号、实体模型、选择字段 |
| 数据入库规则 | `data_import_rule` | 入库规则 | 规则编号、来源系统、实体模型 |
| 批次导入管理 | `import_batch` | 导入批次 | 批次编号、来源系统、实体模型 |
| 记录级血缘 | `record_lineage` | 血缘记录 | 血缘编号、黄金ID、来源记录 |
| 主数据分发同步 | `mdm_sync` | 同步配置 | 配置编号、黄金实体、目标系统 |
| 黄金记录版本 | `mdm_version` | 版本记录 | 版本编号、黄金ID、版本号 |
| 自动匹配任务 | `auto_match_job` | 匹配任务 | 任务编号、实体模型、匹配规则 |
| 主数据质量统计 | `mdm_quality` | 质量统计 | 统计编号、实体模型、完备率 |
| 参考数据管理 | `mdm_reference` | 参考数据 | 数据编号、数据类别、标准编码 |
| 主数据查询接口 | `mdm_api` | 查询接口 | 接口编号、实体模型、查询字段 |
| 主数据治理看板 | `mdm_dashboard` | 看板配置 | 看板编号、看板名称、监控实体 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 按黄金版本回溯血缘

审计批次需要复核历史批次当时的字段来源，而不是现时血缘。记录级血缘页提供
“按黄金版本回溯血缘”面板，后端对应 `backend/app/routers/lineage.py`：

```bash
# 先看核对范围（JSON），再下载 CSV
curl "http://127.0.0.1:8000/api/record_lineage/version-export?golden_id=GR-customer-0001&version=1&format=json"
curl -OJ "http://127.0.0.1:8000/api/record_lineage/version-export?golden_id=GR-customer-0001&version=1"
# 已生成的导出批次（审计下载后核对）
curl "http://127.0.0.1:8000/api/record_lineage/version-exports?golden_id=GR-customer-0001"
```

导出规则：

- 黄金记录版本提供历史字段的时间与版本依据，窗口起点为版本时间，
  终点为同一黄金ID下更早被接替的那个时间点；没有后继版本则为“持续有效”。
- 记录级血缘按生效时间落入窗口才纳入；晚于窗口才加入的来源（例如后来接入的
  客服工单）只出现在“窗口外血缘”和来源系统时间线里，不会混进更早的导出。
- 同一字段同一来源的历次变换按时间原样保留；版本时点仍在生效的那条作为取值。
- 旧原始值或变换证据缺失时，CSV 顶部“核对范围”会列出缺失项并写明可核对字段，
  审计可据此签收或继续补证；历史记录本身不做补写、不做删改。

演示数据：`GR-customer-0001` 的 `1.0` 版本含两项复核（`复核-2026-02`、
`复核-2026-03`），旧电话有两次变换可追溯，旧地址只有原始值、缺变换证据，
客服工单来源在 `2026-10-01` 才出现，因此不会出现在 `1.0` / `2.0` 的历史导出里。

领域：数据工程
子方向：数仓与数据湖
