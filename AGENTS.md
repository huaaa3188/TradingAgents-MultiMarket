# 项目级工作规范

## 快速路由

- 状态 / schema 问题：先看 `tradingagents/agents/utils/agent_states.py`、`tradingagents/graph/propagation.py`、`tradingagents/default_config.py`
- 动作执行 / 流程推进问题：先看 `tradingagents/graph/trading_graph.py`、`tradingagents/graph/setup.py`、`tradingagents/graph/conditional_logic.py`
- CLI 动态渲染 / 交互问题：先看 `cli/main.py`、`cli/utils.py`、`cli/stats_handler.py`
- 协议 / transport / 工具层问题：先看 `tradingagents/dataflows/interface.py`、`tradingagents/dataflows/instruments.py`、`tradingagents/dataflows/akshare.py`、`tradingagents/dataflows/y_finance.py`、`tradingagents/dataflows/yfinance_news.py`
- 模型 / provider / 参数兼容问题：先看 `tradingagents/llm_clients/factory.py`、`tradingagents/llm_clients/base_client.py`、`tradingagents/llm_clients/model_catalog.py`
- 文档与实现不一致：先看 `README.md`，再以 `cli/main.py` 与 `tradingagents/graph/trading_graph.py` 的真实行为为准

---

## 仓库定位

### 仓库目标

- 本仓库是一个基于 LangGraph 的多代理投研框架，负责把 analyst、researcher、trader、portfolio manager 串成可执行工作流，并输出分析报告与最终 `BUY/SELL/HOLD` 信号。
- 主要业务域只有一个：LLM 驱动的证券投研与交易决策生成。
- 主要入口有两个：
  - CLI 入口：`tradingagents` -> `cli.main:app`
  - Python 入口：`TradingAgentsGraph(...).propagate(...)`

### 不在本仓库解决的问题

- 不把真实券商接入、真实下单执行、真实账户状态同步作为主链路能力；阅读代码时以 `Portfolio Manager` 最终裁决和 `SignalProcessor` 抽取信号为实际结束点。
- 不要把 README 中“simulated exchange”表述直接当成当前代码事实；涉及执行链路时先回到 `tradingagents/graph/` 验证。

### 任务理解要求

- 先判断需求落在四层中的哪一层：CLI 展示层、Graph 编排层、Agent/Tool 层、Dataflow/LLM Provider 层。
- 先确认是“研究决策输出问题”还是“终端动态渲染问题”；这两个路径共享同一份状态流，但代码入口不同。

---

## 架构地图

### 目录分层

- `cli/`：交互式命令行、Rich 动态界面、用户选择、统计展示。
- `tradingagents/graph/`：LangGraph 状态机编排、条件路由、状态传播、信号提取、反思。
- `tradingagents/agents/`：各类 analyst、researcher、debator、portfolio manager 节点与工具包装。
- `tradingagents/dataflows/`：yfinance / Alpha Vantage / AkShare vendor 路由、A 股股票与 ETF/LOF/REIT 识别、行情与新闻抓取、缓存与回测日期约束。
- `tradingagents/llm_clients/`：多 provider client、模型目录、参数归一化、模型校验。
- `tests/`：当前主要自动化回归入口。

### 热代码区

- `cli/main.py`
- `tradingagents/graph/trading_graph.py`
- `tradingagents/graph/setup.py`
- `tradingagents/graph/conditional_logic.py`
- `tradingagents/dataflows/interface.py`
- `tradingagents/llm_clients/model_catalog.py`

### 噪声区 / 低优先级区

- `assets/`：README 与 CLI 截图资源，不是运行时主链。
- `tradingagents.egg-info/`：打包产物，不要作为事实来源。
- `.venv/`：本地环境目录，不要把依赖实现和仓库代码混读。
- `test.py`：更像手工脚本；优先看 `tests/` 下的自动化测试。

### 强耦合关系

- `cli/main.py` <-> `tradingagents/graph/trading_graph.py`：CLI 自己拿 `graph.graph.stream(...)` 驱动界面，不是简单调用 `propagate()` 黑盒。
- `tradingagents/graph/setup.py` <-> `tradingagents/graph/conditional_logic.py`：节点名、条件路由返回值、边的目标字符串必须严格一致。
- `tradingagents/agents/utils/agent_states.py` <-> `cli/main.py`：CLI 的动态报告和状态面板依赖固定 state 字段名。
- `tradingagents/dataflows/interface.py` <-> `tradingagents/default_config.py`：vendor 选择先读 category 级配置，再读 tool 级覆盖。
- `tradingagents/dataflows/instruments.py` <-> `tradingagents/graph/propagation.py` <-> `tradingagents/agents/utils/agent_utils.py`：ticker 规范化、market/instrument 类型、`company_display_name`、黄金事实 prompt 是同一条 contract。
- `tradingagents/llm_clients/model_catalog.py` <-> `cli/utils.py` <-> `tradingagents/llm_clients/validators.py`：CLI 可选模型、已知模型集合、校验逻辑必须同步。

---

## 术语表

### 业务名词与代码映射

- “Analyst Team” -> `market/social/news/fundamentals` 四类 analyst 节点与对应 tool node。
- “Research debate” -> `investment_debate_state`，由 `Bull Researcher` 与 `Bear Researcher` 轮转。
- “Risk debate” -> `risk_debate_state`，由 `Aggressive/Conservative/Neutral Analyst` 轮转。
- “Portfolio Manager” -> 当前代码里的最终裁决节点，产出 `final_trade_decision`。
- “Signal” -> `SignalProcessor` 从长文本裁决中再抽取的 `BUY/SELL/HOLD` 单词。
- `InstrumentType` -> `equity/fund/crypto/unknown`，其中 ETF/LOF/REIT 等场内基金统一走 `fund` 语义。
- `MarketType` -> `us/cn_a/hk/jp/crypto/other`，A 股市场识别依赖 `tradingagents/dataflows/instruments.py`。
- “Listed fund / 场内基金” -> ETF/LOF/REIT，按基金画像、费率、持仓、流动性、折溢价和跟踪标的分析，不按上市公司分析。
- “Verified target / 黄金事实” -> `company_display_name` 加 `build_verified_target_context(...)`，用于减少 ticker 与中文简称幻觉。

### 容易混淆的概念

- `final_trade_decision` 和最终展示信号不同：
  - `final_trade_decision` 是长文本裁决。
  - 最终 CLI 输出的 `BUY/SELL/HOLD` 还会再经过一次 `SignalProcessor`。
- CLI 中的“当前报告”不是完整状态本体：
  - `MessageBuffer.current_report` 是从 state 快照归一化后的视图。
  - 真正执行依据仍是 LangGraph state。
- `company_of_interest` 是工具调用和状态传播中的 ticker；`company_display_name` 是 AkShare 解析出的中文简称/展示名，不能互相替代。
- ETF/场内基金不是上市公司；报告中不应套用公司营收、利润表、资产负债表或现金流表口径。
- 默认 vendor 仍保持上游兼容口径；只有显式配置 `data_vendors.* = "akshare"` 或类似 `akshare,yfinance` fallback 时，A 股/场内基金才走 AkShare。

---

## 需求路由规则

### 按需求类型路由

- 如果需求涉及工作流节点增删、顺序调整、辩论轮次或终止条件，优先查看 `tradingagents/graph/setup.py`、`tradingagents/graph/conditional_logic.py`。
- 如果需求涉及 state 字段缺失、界面不刷新、报告区域展示不对，优先查看 `tradingagents/agents/utils/agent_states.py`、`tradingagents/graph/propagation.py`、`cli/main.py`。
- 如果需求涉及 ticker 归一化、A 股/ETF 识别、模型选择、输出语言、Provider 选择，优先查看 `tradingagents/dataflows/instruments.py`、`cli/utils.py`、`tradingagents/default_config.py`。
- 如果需求涉及新闻/行情/财报数据口径、fallback、look-ahead bias，优先查看 `tradingagents/dataflows/interface.py`、`tradingagents/dataflows/akshare.py`、`tradingagents/dataflows/stockstats_utils.py`、`tradingagents/dataflows/y_finance.py`、`tradingagents/dataflows/yfinance_news.py`。
- 如果需求涉及 OpenAI / Google / Anthropic / OpenRouter / Ollama 模型兼容与参数传递，优先查看 `tradingagents/llm_clients/factory.py`、`tradingagents/llm_clients/base_client.py`、`tradingagents/llm_clients/google_client.py`、`tradingagents/llm_clients/validators.py`。

### 按改动性质路由

- 图编排改动：同时检查节点名字符串、条件返回值、CLI 中对 agent 名称的映射，避免只改 graph 不改 UI。
- 新增或修改工具：同时检查 `agents/utils/*tools.py`、`dataflows/interface.py`、默认 vendor 配置。
- 改动 README 或对外说明：先核对代码主链是否真的支持该能力，再修改文档。

---

## 验证入口

### 首选验证命令

- 全量单测：`.venv/bin/python -m pytest tests`
- 模型目录 / 校验一致性：`.venv/bin/python -m pytest tests/test_model_validation.py`
- Provider 参数归一化：`.venv/bin/python -m pytest tests/test_google_api_key.py`
- Ticker 处理与上下文构建：`.venv/bin/python -m pytest tests/test_ticker_symbol_handling.py`
- A 股/ETF 数据流与黄金事实上下文：`.venv/bin/python -m pytest tests/test_akshare_dataflow.py tests/test_verified_target_context.py tests/test_trading_graph_cn_ticker.py`
- 真实 AkShare 网络 smoke：`.venv/bin/python scripts/smoke_akshare_live.py --end-date 2026-05-22`，这会访问外网，不应放入默认 CI。
- 轻量导入验证：`.venv/bin/python -c "from tradingagents.graph.trading_graph import TradingAgentsGraph; from cli.main import app; from tradingagents.default_config import DEFAULT_CONFIG; print('imports_ok', TradingAgentsGraph.__name__, bool(DEFAULT_CONFIG), app.info.name)"`

### 按改动类型选择最小验证集

- 小范围 CLI / 文案 / 配置改动：至少执行对应单测或上面的轻量导入验证。
- Graph / state / provider 共享逻辑改动：至少执行 `tests/` 相关用例；涉及入口或导入链时再补轻量导入验证。
- Dataflow / 回测日期口径改动：优先补或执行相关单测；如果没有现成测试，至少说明未验证，不能跳过。

---

## 仓库特有风险边界

### 谨慎修改区域

- `tradingagents/graph/`：这里控制主状态机；字符串节点名改错会直接让工作流失联。
- `tradingagents/agents/utils/agent_states.py`：字段名是 graph、agent、CLI 三方共享 contract。
- `tradingagents/dataflows/instruments.py`：ticker/market/instrument contract，改动会同时影响 CLI、graph、AkShare 路由和 prompt。
- `tradingagents/dataflows/akshare.py`：依赖外部站点字段和网络状态；改字段映射、fallback 或缓存策略时要补 mock 测试，必要时跑 live smoke。
- `tradingagents/dataflows/stockstats_utils.py`、`tradingagents/dataflows/y_finance.py`、`tradingagents/dataflows/yfinance_news.py`：这里承载回测日期过滤与 look-ahead bias 防护。
- `tradingagents/llm_clients/model_catalog.py`：改动会同时影响 CLI 选项和 validator 行为。

### 不要手改的内容

- `tradingagents.egg-info/`
- 各类缓存目录与运行结果目录，例如 `~/.tradingagents/` 下的 cache / logs

### 高风险改动类型

- 修改 `AgentState`、`InvestDebateState`、`RiskDebateState` 的字段结构。
- 修改 graph 节点名称、条件路由返回值、tool node 名称而不同步 CLI 映射。
- 修改 provider 参数名或模型目录而不补 validator / CLI 对应调整。
- 改动日期过滤逻辑导致未来数据泄漏进回测。
- 改动 `uv.lock` 时要说明是新增依赖还是锁文件同步；本 fork 已引入 `akshare` 与 `diskcache`。
