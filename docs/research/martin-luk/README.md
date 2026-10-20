# Martin Luk 跨股票回调策略 MLP1

2026-10-20。用户要求按 Martin 的框架落地，不绑定 SOXL。
旧 SOXL 早盘反转及财报过滤研究停止推进；原协议与结果保留。

已实现可运行的盘前选股、盘中信号、组合仓位分配和持仓退出计算。
代码：`research/martin-luk/`。本版本实现**顺势回调做多分支**，
不是其突破、EP、极端反转和空头方法的全部集合，也不声称精确复制主观交易。
不要求高胜率，不把冠军账户收益当成代码回测收益。

## 来源与量化边界

| 来源 | 可以支持的内容 | 不能据此声称 |
|---|---|---|
| [USIC 2025 最终排名](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025) | $20,000+ 股票组冠军，+969.8% | 本策略代码也有相同收益 |
| [Martin 本人客座文章，2025-02-01](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons) | 高 ADR、主题与 EMA 观察名单；控制账户风险、硬止损 | 所有偏好都是固定门槛 |
| [TraderLion 访谈，2026-01-31](https://www.youtube.com/watch?v=VKNEJA5r8zw) | 回调分支、多周期与 AVWAP、紧止损、灵活退出 | 完整机械化公式或逐笔独立审计 |
| [本人客座文章及问答，2026-01-10](https://tradingresourcehub.substack.com/p/martin-luk-study-process) | 高周期关键位配合小周期确认；明确存在主观判断 | 将文中的做空细节全部视为做多硬规则 |
| [Making Millions 本人访谈，2026-02-10](https://www.youtube.com/watch?v=-Qr4LJcup84) | 周线结构、热门板块、日内转强确认 | 极端反转就是普通顺势回调 |

访谈的可获取转录已检查相关部分，自动转录有 EMA/VWAP/R 等识别错误。
未宣称完整观看四小时视频或持有其券商逐笔记录。原始转录留在私有 work/。

## 本版本固定规则

下表的**所有精确周期、阈值和代理定义都是我们的工程选择**。
与文献中的大方向分别列出，不能把这些数字称为 Martin 的完整原规则。

| 环节 | MLP1 实现 |
|---|---|
| 股票池 | 输入提供当时可交易的美国普通股及当时已知分类；不设特定 ticker 白名单，不包含 ETF |
| 数据 | 至少 160 个完整日线；显式交易日程、可用时点、截至当时的拆股口径；拒绝缺日、未来数据与过期末日 |
| 流动性 | 股价 ≥ $5；20 日均成交金额 ≥ $20M |
| 波动与动量 | 20 日平均 `(high-low)/close` ≥ 5%；63 或 126 日涨幅至少 30% |
| 趋势 | EMA9 > EMA21 > EMA50，EMA21 比五个交易日前高，收盘在 EMA21 上方 |
| 结构代理 | 最近五个交易日最低价高于此前五日；这是滚动结构代理，不是真正周线形态识别 |
| 热点代理 | 同一个 sector 至少两只股票同时满足候选条件；固定行业分类只代理主题，不能识别跨行业新主题 |
| AVWAP | 已知最近 60 日最高价所在日为锚点；典型价乘成交量求均值，近似真实逐笔 AVWAP |
| 支撑 | EMA9、EMA21、AVWAP 中最近一对距离 ≤ 0.5%；其均值作支撑，收盘在其上且距离不超过 ADR |
| 首次回调代理 | 最近一次收盘上穿 EMA21 后，无已完成的 EMA21 回踩 episode；无交叉则检查最近 20 日。连续触碰合成一个 episode |
| 观察排序 | 动量降序、成交金额降序、symbol 升序，保证容量竞争可复现 |
| 入场窗口 | 开盘后前两小时，使用连续完整五分钟 K 线；至少三根 |
| 触发 | 前两根至少一根接近支撑且未深穿；最新阳线收盘站回支撑并超过前一根高点 |
| 入场方式 | 信号在 K 线可用后才成立；最多晚 60 秒评估；限价为信号收盘加 5bp 并向上取整至分，从信号可用时起五分钟有效 |
| 初始止损 | 最近三根最低价；按限价计算距离在 0.3%–2.5% 且不超过 ADR 一半 |
| 单笔与组合 | 单笔计划风险 0.5%，单股名义上限 25%，行业 50%，总名义 100%，组合开放风险 2%；现金约束，无融资 |
| 去重 | 同股同交易日同形态稳定 ID；已有持仓或预留订单禁止重复配置 |
| 部分退出 | 达初始 3R 卖出初始整数股数的 15%（向下取整，仅一次）；小于一股不拆分 |
| 趋势退出 | 正式收盘跌破已完成日线 EMA9，下一根可观察 K 线开盘退出；不虚构收盘已知后的同价成交 |
| 止损优先 | 回放同根同时触及止损/目标，先处理止损；跳空穿止损按更差开盘处理 |

5bp 是情景假设，不是 Alpaca 实测费用或滑点。股息、借贷、成交队列、
涨跌停/停牌、部分成交不由本引擎假定解决。没有把 Paper 申报或行情接收
等同于真实成交。做空、消息 EP、突破分支及融资不在本版执行范围。

## 运行

不需要券商凭据或网络：

```bash
python research/martin-luk/example.py --output work/martin-luk-v1/input.json
python research/martin-luk/run.py --input work/martin-luk-v1/input.json --output work/martin-luk-v1/result.json
python -m unittest discover -s research/martin-luk -p "test_*.py" -v
```

示例是四只虚构股票、两个行业的 SYNTHETIC 测试，非真实市场回测。
运行后输出观察名单、各股票拒绝原因、可审查的 Paper 限价意图、
仓位与组合风险预留，以及输入/计划/信号证据 SHA256。
退出回放入口是 `manage(position, bar, completed_daily_ema9, session_close)`；
CLI 的可选 `management` 数组可批量调用，结果标为 `management_replay`。
每项提供 symbol/position/bar；CLI 从已验证盘前日线计算 EMA9 参考值。
收盘价低于更新后 EMA9 与低于前一日 EMA9 等价，不接收外部未来均线。
position 需有 filled_at；更新后保存 last_bar_end，拒绝重复或成交前的管理 K 线。

## 输入契约

顶层：`mode`、`snapshot`、当前 `asof`、按 symbol 分组的 `intraday`、`account`。
`mode` 是 SYNTHETIC / HISTORICAL_REPLAY / PAPER_REVIEW。

`snapshot`：盘前 `asof`、真实交易日的 `session_open/session_close`、
`previous_session_close`、`history_schedule`（完整日线的 start/end 对）、
`universe_kind`、`price_basis=ASOF_SPLIT_ADJUSTED`、`adjustment_asof`、`assets`。
时间一律显式 UTC。半日市必须使用对应提前收盘日程。

`assets` 中每项：`symbol`、`sector`、`kind`、`tradable`、当时已知的 `known_at`、`daily`。
每根 K 线有 start/end/available_at/open/high/low/close/volume。
日线要来自正式交易时段，成交量必须为正；无法确定数据完整性的股票应单列
排除，而不是把缺失日期从全市场日程抹掉。新上市不足 160 日股票会被排除。

股票池标记必须是 POINT_IN_TIME、DIAGNOSTIC_SURVIVOR_BIASED 或 SYNTHETIC。
这些是**输入声明而非认证**：引擎能检查时间和结构，不能认证供应商。
幸存者样本可用于接口诊断，不能当作无偏全市场证据。历史股票池需包含退市股、
改名/并购及当时行业分类；不能用今天股票池宣称过去能选到全部赢家。

`account`：`equity`、券商现金 `cash`、`positions`、`pending_orders_unaccounted`。
持仓/预留项包括 symbol/sector/quantity/mark/stop_price；未成交买单用
`pending=true`，按限价预留资金。账户现金须未重复扣除这些 pending 预留。
必须一并提供已有持仓和未成交买单；有未计入订单时拒绝生成新增意图。
未分配到本策略、没有可核验止损的账户持仓不应默认为零风险。

## Paper 对接状态与验证边界

本版提供**策略内核和 Paper 审查意图**；不复用旧 ORB 命名空间，不改旧源文件，
不调用旧的一股 QQQ 烟测来伪装策略成交，也未把历史信号送到实时账户。
输出中的 Paper endpoint 是目标标签，`execution_enabled=false`，无 HTTP 申报传输。
`actual_fills=[]`、`profit_estimate=null` 明确保留。

自动申报前仍需真实股票池与数据接入、券商持仓/订单核对、报价有效性、
持久化去重、部分成交后的保护单和断线恢复。这些不能由一个离线输入文件替代。
因此当前不是正在运行的 Paper 自动交易服务，也没有声称已有历史盈利验证。

19 项测试覆盖跨行业筛选、未来与缺失数据、首次回调、信号重复、组合限制、
pending 现金预留、跳空、同根路径歧义及下一根开盘退出。Ubuntu/Windows CI
运行同一套测试。原来封存的 src/dx27 文件保持不变。
