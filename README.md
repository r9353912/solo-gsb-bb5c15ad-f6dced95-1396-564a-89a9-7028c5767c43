# 事件证据链审计台 (Event Evidence-Chain Audit Desk)

多来源 JSON 事件记录导入、时钟偏差校正、可解释时间线重建与冲突链定位的一体化审计台。

后端 **Python · FastAPI · SQLite**，前端**原生 HTML / CSS / JavaScript**（无框架、无构建步骤），
一条 `docker compose up` 即完成依赖安装、数据库初始化与服务启动。

---

## 它解决什么问题

取证 / 审计场景下，日志来自网关、应用服务器、手机端、第三方平台等不同来源，
**每个来源的时钟都有偏差、漂移和不确定度**。直接按纸面时间戳排序会得到误导性的时间线。

本系统为每条记录维护一个**真实时间区间与可信度**，把"a 必须先于 b"这类因果/合规约束
建模为有向边，通过区间运算与约束传播：

1. 标出**不可能顺序**（即使取最有利的时间区间，后验顺序仍不成立）；
2. 结合传递路径定位**闭合矛盾链**；
3. 用 Tarjan SCC 检出**因果环**；
4. 对区间互相重叠、先后无法唯一判定的事件标出**时间歧义组**；
5. 审计员**调整任一来源的偏差假设后即时重算**，观察冲突消失 / 转移 / 新冲突暴露的全过程；
6. 对任一来源做**偏移敏感性扫描**：解析求出 gap 穿越 0 的临界 offset，把扫描范围切成
   边状态稳定的连续区间，逐段重算并报告不可能边 / 冲突链相对当前结果的新增与消失；
7. 一键**全局时序可行性检查**：把全部事件区间与全部有效约束联立求解（差分约束），
   可行时给出每个事件的最早可行时刻作为见证，无解时给出一条带事件 ID、约束 ID 与
   两端冲突界限的矛盾路径——包括"每条边单独可行、整条路径无解"的隐蔽情形；
8. 无解时的**约束撤销建议**：沿矛盾路径搜索需撤销的最少人工/导入约束
   （source_order 时序边与事件区间不可撤销），每个候选用原求解器复核并附撤销后的
   全量可行见证；至多展示 5 个同样最少的方案，预览不写入数据库。

---

## 快速开始

### Docker Compose（推荐）

**单条启动命令**（依赖安装、数据库初始化、示例载入全部在启动时自动完成）：

```bash
docker compose up --build
```

- 页面：`http://localhost:8000`
- API（含交互式文档）：`http://localhost:8000/api/...` 与 `http://localhost:8000/docs`

容器启动时自动：

- 安装 `requirements.txt` 中的依赖；
- 在持久化卷 `/data` 中初始化 SQLite（建表）；
- 库为空时载入内置的示例案件 `LOGIN-ANOMALY-2026-0918`（`LOAD_SAMPLE=0` 可关闭）。

数据通过命名卷 `audit-data` 持久化，容器重建不丢失。

### 本地直接运行

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 数据库默认写入 ./data/audit.db，首启同样自动建表并载入示例
```

### 跑测试

```bash
python tests/test_engine.py      # 纯标准库，覆盖时间解析 / 冲突 / 因果环 / 假设调整全流程
python tests/test_scenarios.py   # 纯标准库，覆盖方案快照 CRUD / 对比差异（冲突/歧义/边/时间线逆序对）
python tests/test_sensitivity.py # 纯标准库，覆盖偏移敏感性：临界点解析 / offset 抵消 / 区间差异 / 输入校验
python tests/test_feasibility.py # 纯标准库，覆盖全局时序可行性：DAG 传播 / 环交集 / 矛盾路径 / 5000 事件无递归
python tests/test_retraction.py  # 纯标准库，覆盖约束撤销建议：最少撤销 / 多解 / 平行边 / 保护与预算限制
```

---

## 30 秒上手示例审计（页面引导）

系统内置一起"异地登录"取证案件。建议按下面三步体验偏差假设的影响：

| 步骤 | 操作 | 现象 |
|---|---|---|
| 1 | 打开页面，查看初始状态 | `C001` 报 `a1(登录提交) → m1(MFA 推送)` 顺序不可能：按纸面时间 MFA 推送早于登录提交 80 秒 |
| 2 | 将 `app-server` 的 **offset 改为 60**、`mobile-app` 的 **offset 改为 -30**，输入即重算 | `C001` 消失；暴露 `C001(g3 → a3)`：应用方声称的"强制登出后才导出"为假，导出实际发生在登出前 70 秒；同时 `m2/g2` 出现时间歧义组 |
| 3 | 将 `mobile-app` 的 **不确定度从 5 收窄到 1**（模拟拿到 MFA 服务端精确回执），点"保存假设" | 歧义消除，时间线变为唯一、因果自洽的顺序，冲突仅剩合规造假一条 |

满意后点击右上 **⬇ 导出审计结果**，得到包含全部假设、区间、冲突解释链与统计的 JSON 证据包。

### 进一步：两套假设方案对比

1. 在左栏把来源假设调整到一种立场（例如"纸面时间戳全可信"），点右上 **⚖ 方案对比** →
   **💾 保存当前假设为方案**，命名为「纸面假设」；
2. 关闭抽屉，按上表第 2、3 步调整 offset / 不确定度，再次打开抽屉并存为「校正后假设」；
3. 在抽屉顶部把 **A 选「纸面假设」、B 选「校正后假设」**，点 **▶ 对比重算**。

并排展示的差异包括：

- **冲突链 / 歧义组**：B 相对 A 的**新增**（红）、**消失**（绿）、**持续**（黄，双卡并排）；
- **顺序边状态变化**：每条约束 `🔴不可能 → 🟢支持` 的翻转及间隔区间 `[gap_lo, gap_hi]` 变化；
- **时间线排序变化**：估计时刻位次的交换对与漂移（逆序对，O(n log n) 计算，5000 事件可用）；
- **假设参数差异**：逐来源列出 offset / drift / uncertainty / reliability 的 A→B 取值。

差异卡片上的任意事件节点都可点击，关闭抽屉并在主时间线滚动高亮定位该事件；
点 **⬇ 导出对比 JSON** 得到 `assumption-scenario-comparison` 证据包
（含两侧完整假设、全部差异明细与两套完整时间线排列 `order_a / order_b`）。

方案保存在服务端命名卷中、与案件数据一同持久化；它是**自包含快照**：
保存后即使再改动已确认的来源假设，旧方案的重算结果也不会变化。
「当前生效假设（含未保存调整）」可随时作为对比的一侧，无需先命名。

### 进一步：偏移敏感性扫描（📈）

想知道"某个来源的 offset 假设到底多敏感、冲突在哪一秒翻转"？点右上 **📈 偏移敏感性**：

1. 选择来源、输入 offset 扫描上下界（默认当前生效值 ±120s），点 **▶ 扫描**；
2. 后端利用区间模型对 offset 的线性性**解析求解**（非暴力采样）：该来源事件参与的每条
   跨来源约束边最多贡献 2 个临界点（`gap_lo = 0` 与 `gap_hi = 0` 的穿越点），把扫描范围切成
   **边状态稳定的连续区间**；两端同属该来源的边 offset 整体平移相互抵消，**不制造临界点**
   （单列"offset 抵消边"）；
3. 每段取代表值（当前 offset 所在段直接取当前值）调用现有推理全量重算，逐段给出
   **不可能边与冲突链相对当前结果的新增 / 消失 / 持续**（按与编号无关的签名配对）；
4. 点击任意区间段（或"✍ 采用中点"按钮）：把该段**中点**写入该来源的**未保存** offset
   并立即触发主时间线重算——与手动在左栏改值完全等价，可继续调整或"💾 保存假设"。

上下界无效（下界 ≥ 上界 / 非数值 / 非有限值）返回 400，来源不存在返回 404；
范围内无临界点时返回单一稳定区间并附明确提示；临界点过多（>24 个）时提示缩小范围，
避免逐段重算拖慢交互。扫描会携带页面未保存的其它来源假设作为上下文。

### 进一步：全局时序可行性检查（🧭）

冲突定位回答"哪里矛盾"，全局时序可行性回答另一个更严格的问题：**在当前时钟假设下，
能不能为每个事件各取一个闭区间内的时刻，使全部约束同时成立？** 点右上 **🧭 全局时序可行性**：

1. 后端以页面当前（**含未保存调整**）的时钟假设，把**全部事件**的真实时间区间与
   **全部有效约束**（含 source_order 时序边与不可能的边）联立成差分约束系统：
   每个事件取闭区间内一个时刻，边 `a→b` 要求 `t_b ≥ t_a`（允许同刻）；
   **不受页面筛选影响**，且为只读检查——不改写任何事件或假设；
2. 求解用迭代版 Tarjan 强连通分量 + Kahn 拓扑最长路（全程无递归，5000 事件约 0.4 秒）：
   环（非平凡分量）内事件必须取同一时刻，因此环可行 ⟺ 环内区间有公共交集；
   每个事件的**最早可行时刻** = max(自身区间下界, 所有前驱的最早可行时刻)；
3. **可行**：页面列出每个事件的最早可行时刻（即一组满足全部约束的具体取值，就是见证），
   附区间余量与环标记，支持关键字过滤与分批展开，点击任意事件回到主时间线定位；
4. **无解**：返回一条**矛盾路径**——从某事件的区间下界出发，下界沿路径逐段传递，
   最终在终点事件处越过其区间上界。路径标注每个事件 ID、每条边的约束 ID、
   该边单独是否可行，以及两端的冲突界限（起点下界 vs 终点上界）与超出量；
   当路径上**每条边单独都可行**（典型：环内区间无公共交集、或长链下界累积）时，
   页面会明确提示"各边单独可行而整条路径无解"，这类矛盾用逐边检查永远发现不了。

调整假设后点抽屉内 **⟳ 重新检查** 即可用新假设重算；检查不会保存任何假设。

### 进一步：约束撤销建议（🪓，从可行性抽屉进入）

全局联立无解时，可行性抽屉的矛盾路径下方会出现**约束撤销建议**区块
（页面 `http://localhost:8000` → 右上 **🧭 全局时序可行性** → 无解时点
**▶ 搜索撤销方案**；API 为 `POST /api/retraction-suggestions`）。它回答：
**最少撤销哪些人工录入或导入的约束，全量联立就能恢复可行？**

1. **可撤销范围**：只有人工/导入约束（`causal` / `claimed` 等非系统 kind）参与候选；
   `source_order` 时序边与事件时间区间是观测事实，**不可撤销**；
   页面**未保存的时钟假设**（overrides）参与每一次候选复核；
2. **搜索方式**：沿矛盾路径做冲突驱动搜索——任何可行修复都必须命中当前矛盾路径
   （至少打断其中一跳），撤销后仍无解时把新矛盾路径上的可撤销约束并入候选池，
   按撤销 1 条、2 条、3 条逐层枚举，**每个候选都用原求解器复核**；
   首个产出方案的层即最少撤销条数，该层方案同样最少；
3. **结果**：至多展示 **5 个同样最少的方案**，每个方案列出约束 ID、端点
   （from → to，可点击定位）与**撤销后的全量可行见证**（每个事件的最早可行时刻，
   折叠展示、可展开）；搜索限定**最多撤销 3 条、最多 2000 次求解**，
   触限时结果明确标为**未完成**（`complete=false`），只给候选、不称最优；
4. **边界情形**：若撤销**全部**可撤销约束后仍无解（矛盾只由 source_order 边与
   事件区间构成），明确报告"没有仅靠撤销约束的修复方案"并展示剩余矛盾路径；
   若 3 条以内无解但全撤可行，提示需要同时撤销更多约束；
5. **只读预览**：建议不写入数据库、不改写任何事件或假设；确认后可到右栏
   「顺序约束」手动删除对应约束，或回左栏调整时钟假设后点 **⟳ 重新搜索** 重算。

---

## 输入 JSON 格式

顶层对象（也接受直接的事件数组）：

```json
{
  "case": "案件编号（可选）",
  "sources": [
    {
      "id": "gateway",
      "name": "API 网关",
      "clock_offset": 0,      // 秒：本地时钟相对真实时间快多少
      "drift_ppm": 0,         // 线性漂移 ppm
      "uncertainty": 0.3,     // 秒：时钟不确定半径 ±
      "reliability": 0.95,    // 0~1 来源整体可靠度
      "kind": "server"
    }
  ],
  "events": [
    {
      "id": "g1",                         // 可省（缺省按内容哈希）
      "source": "gateway",                // 别名: source_id / src / host / node
      "time": "2026-09-18T08:01:40Z",     // 别名: ts / timestamp / local_time ...
                                          // 支持 ISO-8601、RFC2822、秒/毫秒/微秒/纳秒数字
      "type": "session.start",            // 别名: event_type / kind / action
      "actor": "user-4417",               // 别名: user / subject
      "summary": "可读描述",               // 别名: message / msg / description / title
      "seq": 12,                          // 同来源内序号（可选，优先于时间排序）
      "error_ms": 200                     // 可选：本条观测固有抖动（毫秒），等价于 sigma（秒）
    }
  ],
  "constraints": [
    {"from": "g1", "to": "a1", "kind": "causal", "note": "会话建立后才能登录"}
  ]
}
```

规则：

- 事件中出现但未在 `sources` 声明的来源会**自动登记**（offset=0、uncertainty=1），等待审计员校正；
- 同一来源内事件自动生成 `source_order` 严格时序边（本地时钟单调）；
- 重复导入按事件 `id` **幂等**，且不会覆盖审计员已调整的来源假设；
- 无法解析的时间戳不会静默入库，会在导入结果 `rejected` 中逐条说明；
- 约束端点不存在时导入成功但产生告警；单文件上限 8 MB、单次上限 5000 事件。

完整示例见 [`examples/login-anomaly.json`](examples/login-anomaly.json)，
运行中也可访问 `GET /api/sample` 下载。页面支持点击导入或**直接把 JSON 文件拖进窗口**。

---

## 时钟与可信度模型

设来源 `s`、本地时间戳 `t_local`、参考纪元 `t_ref`（数据集最早本地时间）：

```
偏移量   Δ = clock_offset + drift_ppm × 1e-6 × (t_local - t_ref)
估计时刻 t_est = t_local - Δ
时间区间 [t_est - uncertainty - sigma,  t_est + uncertainty + sigma]
```

对约束边 `a → b`，两区间之差仍是区间：

```
gap ∈ [ lo_b - hi_a ,  hi_b - lo_a ]
```

| 条件 | 判定 | 含义 |
|---|---|---|
| `gap_hi < 0` | 🔴 impossible | b 必定早于 a，该顺序不可能 |
| `gap_lo ≥ 0` | 🟢 ok | 顺序被区间支持 |
| 跨越 0 | 🟠 歧义 | 可能成立但先后无法锁定 |

- **矛盾链**：若某条边不可能，同时图上存在一条"成立边"构成的反向路径，则闭合为可解释的冲突链（BFS 取证路径）。
- **因果环**：在成立边上跑迭代版 Tarjan，任何非平凡强连通分量都是逻辑矛盾。
- **歧义组**：跨来源、时间区间相交的事件用扫描线 + 并查集聚类，提示审计员需要更精确的时钟证据。
- **事件可信度** = `0.6 × (5 / (5 + 区间半径)) + 0.4 × 来源可靠度`。

所有推理每次都从原始观测时间戳出发重算，调整假设**无需迁移任何数据**；
5000 事件规模下全量重算约 0.6 秒，页面输入做了 250 ms 防抖。

---

## 页面功能

- **文件导入**：按钮选择或拖拽上传 JSON；
- **来源时钟假设**（左栏）：逐来源修改 offset / drift / uncertainty / reliability，改动即时重算，
  橙色高亮未保存调整；可一键放弃或"💾 保存假设"持久化；
- **冲突定位**（右栏）：列出全部冲突链（编号、严重度、自然语言解释、事件节点链），
  点击链上节点或"🔍 在时间线中定位"自动清除筛选并滚动高亮；
- **时间线**（中栏）：按真实估计时刻排序，每行展示
  估计时刻 / 原始本地时刻、彩色**时间区间条**与估计点、±半径与综合可信度；
  冲突事件红色左边框并挂冲突标签，歧义事件橙色标记；
- **筛选**：关键字（摘要 / ID / 操作者 / 类型）、来源、事件类型、仅冲突、仅歧义；
  筛选只改变展示，冲突与歧义始终全量计算以免漏报；
- **约束管理**：查看每条边的状态与间隔区间，可删除非系统约束；
- **审计结果导出**：下载完整 JSON 证据包（含时钟模型说明、生效假设、统计、事件区间、边、冲突解释）。
- **假设方案对比**（右上 ⚖）：把当前 offset / drift / uncertainty / reliability 快照命名保存；
  任选两套方案（或"当前生效假设"）对同一批事件分别重算，并排展示冲突链 / 歧义组的新增、消失、
  持续，顺序边 ok / boundary / impossible 的状态翻转，以及时间线位次交换；点击任意差异事件可定位
  主时间线，对比结果可导出 JSON。
- **偏移敏感性扫描**（右上 📈）：选定来源扫描 offset 上下界，解析临界点切出边状态稳定的连续区间，
  逐段展示不可能边 / 冲突链相对当前结果的新增与消失（含签名）；点击区间段把其中点写入该来源
  未保存 offset 并即时重算时间线。
- **全局时序可行性**（右上 🧭）：全部事件区间 × 全部有效约束联立求解；可行时展示每个事件的
  最早可行时刻（见证，可过滤、可点击定位），无解时展示带事件 ID / 约束 ID / 两端冲突界限的
  矛盾路径；使用当前含未保存调整的假设，不受筛选影响，只读不改写数据。
- **约束撤销建议**（可行性抽屉内，无解时出现）：沿矛盾路径搜索需撤销的最少人工/导入约束
  （source_order 边与事件区间不可撤销），原求解器逐候选复核；至多 5 个同样最少的方案，
  各附约束 ID、端点与撤销后全量可行见证；最多撤销 3 条、最多求解 2000 次，触限标未完成；
  预览不写库，支持按当前假设重新搜索。

---

## HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/import` | multipart 上传 JSON 文件 |
| POST | `/api/import/raw` | 直接提交 JSON（便于 curl / 集成） |
| POST | `/api/recompute` | 应用临时假设 + 筛选条件，返回完整推理结果 |
| POST | `/api/sources/assumptions` | 持久化审计员确认的偏差假设 |
| GET | `/api/sources` | 来源列表（含生效值 / 已存值 / dirty 标记） |
| DELETE | `/api/sources/{id}` | 删除来源（级联删除其事件与约束） |
| POST | `/api/constraints` | 新增声明约束（自环 / 悬空端点返回 400/404） |
| DELETE | `/api/constraints/{id}` | 删除约束 |
| GET | `/api/event-types` | 事件类型聚合 |
| GET | `/api/export` | 下载审计结果 JSON（可用 query 带未保存假设，如 `?clock_offset=app-server:60`） |
| GET | `/api/scenarios` | 命名假设方案列表（自包含完整假设快照） |
| POST | `/api/scenarios` | 新建命名方案；`from_current=true` 时把当前库存假设 + 未保存 overrides 合并快照 |
| GET | `/api/scenarios/{id}` | 获取方案 |
| PATCH | `/api/scenarios/{id}` | 重命名 / 改备注 / 局部更新假设（默认以旧快照为基线合并；`from_current=true` 改用当前库存为基线） |
| DELETE | `/api/scenarios/{id}` | 删除方案（不影响事件与来源已保存假设） |
| GET | `/api/scenarios/current/assumptions` | 当前库存完整生效假设（另存基线预览） |
| POST | `/api/compare` | 两套方案在同一批事件上分别重算，返回结构化差异 |
| POST | `/api/compare/export` | 下载方案对比 JSON 证据包（侧引用可携带未保存 overrides，故为 POST） |
| POST | `/api/offset-sensitivity` | 偏移敏感性扫描：解析临界点 → 稳定区间 → 逐段重算并与当前结果对比 |
| POST | `/api/temporal-feasibility` | 全局时序可行性：全量事件区间 × 全部约束联立求解，返回最早可行时刻见证或矛盾路径 |
| POST | `/api/retraction-suggestions` | 约束撤销建议：沿矛盾路径搜索需撤销的最少人工/导入约束，原求解器复核，返回至多 5 个同样最少的方案及撤销后全量可行见证（只读预览） |
| GET | `/api/sample` | 下载内置示例 JSON |
| POST | `/api/reset` | 清空全部数据 |
| GET | `/api/health` | 健康检查（Compose healthcheck 使用） |

`/api/recompute` 请求体示例：

```json
{
  "overrides": {
    "app-server": {"clock_offset": 60},
    "mobile-app": {"clock_offset": -30, "uncertainty": 1}
  },
  "source_id": null,
  "event_type": null,
  "q": "MFA",
  "only_conflicts": false,
  "only_ambiguous": false,
  "lo": 1789123320,
  "hi": 1789123380
}
```

curl 示例：

```bash
curl -F "file=@examples/login-anomaly.json" http://localhost:8000/api/import
curl -X POST http://localhost:8000/api/recompute -H 'Content-Type: application/json' \
  -d '{"overrides":{"app-server":{"clock_offset":60}}}'
curl -o audit_result.json http://localhost:8000/api/export
```

`/api/scenarios` 与 `/api/compare` 请求体示例：

```json
// POST /api/scenarios —— 保存当前页面假设（含未保存调整）
{
  "name": "校正后假设",
  "description": "app +60s, mobile -30s",
  "from_current": true,
  "assumptions": {"app-server": {"clock_offset": 60}, "mobile-app": {"clock_offset": -30}}
}
```

```json
// POST /api/compare —— 侧引用：{"kind":"scenario","scenario_id":N} 或
// {"kind":"current","overrides":{...可选未保存调整...}}
{
  "a": {"kind": "scenario", "scenario_id": 1},
  "b": {"kind": "scenario", "scenario_id": 2}
}
```

响应中的差异按稳定标识配对（冲突/歧义组为与编号无关的 `signature`，顺序边为数据库边 id）：

```json
{
  "comparison_type": "assumption-scenario-diff",
  "sides": {"a": {"label": "纸面假设", "assumptions": {"...": "..."}},
            "b": {"label": "校正后假设", "assumptions": {"...": "..."}}},
  "summary": {"conflicts_added": 1, "conflicts_removed": 1, "conflicts_persisted": 0,
              "ambiguities_added": 1, "edges_changed": 2,
              "timeline_swapped_pairs": 6, "sources_with_assumption_diff": 2},
  "conflicts": {"added": [{"signature": "impossible:g3->a3", "b": {"...": "..."}}],
                "removed": [{"signature": "impossible:a1->m1", "a": {"...": "..."}}],
                "persisted": [{"signature": "...", "a": {"...": "..."}, "b": {"...": "..."}}]},
  "ambiguity_groups": {"added": [], "removed": [], "persisted": []},
  "edge_changes": [{"edge_id": 7, "from": "a1", "to": "m1",
                    "status_a": "impossible", "status_b": "ok",
                    "gap_a": {"lo_text": "...", "hi_text": "..."},
                    "gap_b": {"lo_text": "...", "hi_text": "..."}}],
  "timeline_changes": {"swapped_pairs": [], "swapped_pair_count": 6,
                       "rank_shifts": [], "order_a": ["m1", "..."], "order_b": ["g1", "..."]},
  "assumption_diff": [{"source_id": "app-server",
                       "params": [{"param": "clock_offset", "a": 0.0, "b": 60.0, "delta": 60.0}]}]
}
```

导出对比结果：`curl -X POST http://localhost:8000/api/compare/export -H 'Content-Type: application/json' \
  -d '{"a":{"kind":"scenario","scenario_id":1},"b":{"kind":"scenario","scenario_id":2}}' \
  -o scenario_comparison.json`

`/api/offset-sensitivity` 请求体与响应示例：

```json
// POST /api/offset-sensitivity —— overrides 传页面当前（含未保存）的其它来源假设
{"source_id": "app-server", "lo": -120, "hi": 120,
 "overrides": {"mobile-app": {"clock_offset": -30}}}
```

```json
{
  "scan_type": "offset-sensitivity",
  "source_id": "app-server",
  "range": {"lo": -120, "hi": 120},
  "current_offset": 0.0,
  "involved_edge_count": 4,
  "critical_points": [{"offset": 73.8, "edge_id": 8, "from": "a1", "to": "m1",
                       "bound": "gap_hi", "direction": "rising"}],
  "cancelled_edges": [{"id": 12, "from": "a1", "to": "a2", "kind": "source_order",
                       "status": "ok"}],
  "intervals": [{
    "index": 0, "lo": -120, "hi": 48.7, "midpoint": -35.65,
    "representative": 0.0, "contains_current": true,
    "stats": {"conflict_count": 1, "impossible_edges": 1, "ambiguity_group_count": 0},
    "impossible_edges": {"added": [], "removed": [], "persisted": [
      {"signature": "impossible:a1->m1", "edge": {"from": "a1", "to": "m1", "...": "..."}}]},
    "conflicts": {"added": [], "removed": [], "persisted": [
      {"signature": "impossible:a1->m1", "a": {"...": "..."}, "b": {"...": "..."}}]}
  }],
  "notice": null
}
```

- `critical_points[].bound` 指明是 `gap_lo` 还是 `gap_hi` 穿越 0，`direction` 为 gap 随 offset 增大的变化方向；
- `cancelled_edges` 为两端同属该来源的边：offset 整体平移相互抵消，状态恒定，不制造临界点；
- 每段的 `impossible_edges` / `conflicts` 都是**该段相对当前结果**的差异（签名配对，形态同方案对比）；
- `notice` 在"范围内无临界点 / 来源不参与跨来源约束边"时给出明确提示（此时返回单一稳定区间）。

`/api/temporal-feasibility` 请求体与响应示例（只接收 `overrides`，无筛选参数；只读）：

```json
// POST /api/temporal-feasibility —— overrides 传页面当前（含未保存）的时钟假设
{"overrides": {"app-server": {"clock_offset": 50}, "mobile-app": {"clock_offset": -30}}}
```

```json
// 可行：events 即见证——每个事件的最早可行时刻（落在各自闭区间内、满足全部约束）
{
  "check_type": "global-temporal-feasibility",
  "feasible": true,
  "summary": "当前时钟假设下全局时序可行：8 个事件与 11 条约束联立有解……",
  "stats": {"event_count": 8, "constraint_count": 11, "skipped_constraints": 0,
            "component_count": 8, "cycle_count": 0, "events_in_cycles": 0},
  "events": [{"id": "g1", "source_id": "gateway", "earliest": 1789123299.7,
              "earliest_text": "2026-09-18T08:01:39.700Z",
              "lo": 1789123299.7, "hi": 1789123300.3, "slack": 0.6, "in_cycle": false}],
  "overrides_applied": {"app-server": {"clock_offset": 50.0}, "...": "..."}
}
```

```json
// 无解：witness 为一条矛盾路径（事件 ID + 约束 ID + 两端冲突界限）
{
  "check_type": "global-temporal-feasibility",
  "feasible": false,
  "summary": "当前时钟假设下，全量事件区间与全部约束联立无解。",
  "witness": {
    "head": {"event": "a1", "bound": "lo", "value": 1789123369.0,
             "text": "2026-09-18T08:02:49.000Z"},
    "tail": {"event": "m1", "bound": "hi", "value": 1789123295.2,
             "text": "2026-09-18T08:01:35.200Z"},
    "overshoot": 73.8, "overshoot_text": "1.2 min",
    "events": ["a1", "m1"],
    "steps": [{"from": "a1", "to": "m1", "constraint_id": 8, "kind": "causal",
               "individually_feasible": false, "running_lo": 1789123369.0}],
    "all_edges_individually_feasible": false,
    "explanation": "全局联立无解：从 a1 的区间下界 …… 超出其区间上界 ……"
  }
}
```

- `head` / `tail` 为路径两端的冲突界限：起点事件区间下界 > 终点事件区间上界；
- `steps[].individually_feasible` 表示该边单独是否可行；全为 `true` 时即
  "各边单独可行而整条路径无解"（环内区间无公共交集或长链下界累积），
  `all_edges_individually_feasible` 与 `explanation` 会明确标出；
- 环（因果环）内事件取同一时刻：可行时这些事件的 `earliest` 相同且 `in_cycle=true`。

`/api/retraction-suggestions` 请求体与响应示例（只接收 `overrides`，含未保存假设；只读预览）：

```json
// POST /api/retraction-suggestions
{"overrides": {"app-server": {"clock_offset": 60}, "mobile-app": {"clock_offset": -30}}}
```

```json
{
  "suggestion_type": "constraint-retraction",
  "status": "ok",
  "complete": true,
  "summary": "最少撤销 1 条约束即可恢复全局可行，共找到 1 个同样最少的方案……",
  "limits": {"max_depth": 3, "max_solves": 2000, "max_solutions": 5},
  "stats": {"event_count": 8, "constraint_count": 11,
            "retractable_constraints": 6, "protected_constraints": 5, "solves_used": 3},
  "min_retractions": 1,
  "solutions_truncated": false,
  "solutions": [{
    "constraints": [{"id": 11, "from": "g3", "to": "a3", "kind": "claimed",
                     "note": "应用方合规声明：导出发生在强制登出之后"}],
    "witness": {"summary": "……", "stats": {"...": "..."},
                "events": [{"id": "g1", "earliest": 1789123299.7,
                            "earliest_text": "2026-09-18T08:01:39.700Z", "...": "..."}]}
  }],
  "remaining_witness": null,
  "notice": "方案仅为预览：不写入数据库……"
}
```

- `status`：`ok`（找到方案）/ `already_feasible`（当前已可行）/
  `no_retraction_fix`（撤销全部可撤销约束仍无解，没有仅靠撤销约束的修复方案，
  附 `remaining_witness` 剩余矛盾路径）/ `none_within_limits`（限制内无解）；
- `complete=false` 表示求解次数触限、搜索**未完成**：此时 `solutions` 只是候选，
  不能当作已穷尽的最优结论；`solutions_truncated=true` 表示同规模方案超过 5 个、仅展示前 5 个；
- `solutions[].witness.events` 即撤销后全量可行见证（每个事件的最早可行时刻，形态同可行性检查）。

交互式文档：启动后访问 `http://localhost:8000/docs`。

---

## 项目结构

```
.
├── app/
│   ├── main.py          # FastAPI 路由：导入/假设/重算/筛选/约束/方案 CRUD/对比/敏感性/时序可行性/撤销建议/导出/静态页
│   ├── engine.py        # 区间模型、边分类、约束传播、Tarjan 环、歧义聚类、稳定签名、导出
│   ├── feasibility.py   # 全局时序可行性：差分约束联立求解（SCC + Kahn 最长路）、最早可行时刻见证、矛盾路径
│   ├── retraction.py    # 约束撤销建议：沿矛盾路径的冲突驱动最小撤销搜索，原求解器复核，预算/深度限制
│   ├── scenarios.py     # 命名假设方案快照 CRUD、双方案重算差异（冲突/歧义/边/时间线/参数）
│   ├── sensitivity.py   # 偏移敏感性：临界点解析求解、稳定区间切分、逐段重算与差异配对
│   ├── importer.py      # 多别名宽松 JSON 规范化、幂等入库、来源时序边重建
│   ├── db.py            # SQLite 连接、建表初始化（含 scenarios 表）
│   ├── timeutil.py      # 多格式时间戳解析（秒/毫秒/微秒/纳秒、ISO、RFC2822）
│   ├── sample.py        # 内置示例案件
│   └── static/          # 原生前端 index.html / style.css / app.js / compare.js / sensitivity.js / feasibility.js / retraction.js
├── examples/login-anomaly.json
├── tests/test_engine.py      # 纯标准库测试（11 项）
├── tests/test_scenarios.py   # 方案快照与双方案对比测试（12 项）
├── tests/test_sensitivity.py # 偏移敏感性扫描测试（9 项）
├── tests/test_feasibility.py # 全局时序可行性测试（11 项，含 5000 事件规模与深环无递归）
├── tests/test_retraction.py  # 约束撤销建议测试（12 项：最少撤销/多解/平行边/保护与预算限制）
├── docker/entrypoint.sh # 启动钩子：初始化数据库后拉起 uvicorn
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATA_DIR` | `./data` | 数据目录（Docker 内为 `/data`） |
| `DB_PATH` | `$DATA_DIR/audit.db` | SQLite 文件路径 |
| `LOAD_SAMPLE` | `1` | 库为空时是否自动载入示例案件 |
| `PORT` | `8000` | 容器监听端口（entrypoint 使用） |
