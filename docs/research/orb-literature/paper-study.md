# 当前研究基础：Alpaca Paper

用户已指定以Paper账户为研究基础。本工作流按此推进，**不再以真实账户费表/滑点校准作为Paper工程研究的前置阻断**。[机器工作单](paper-study.json)与[本轮报告](../../reports/orb-paper-basis/README.md)记录实际完成事项。

此前方案v2关于真实成交与未来效果确认的限制保留，但不能把这些要求误用为“Paper研究也不能开始”。本轮已完成固定Paper主机GET观测、匿名摘要和历史账目分解；不要求购买实时SIP。后续免费IEX若用于观察，必须标明IEX，不能冒充原SIP规则的等价输入；旧数据可继续用于离线工程验收。

## 两类账本分开

1. **Paper试验账本**：以本策略专属意图、client_order_id和Paper订单/成交/账户观测为依据。记录部分成交、拒绝、取消、断线/恢复与资金对账；没有完整且可归属的记录时不报告完整策略收益。当前没有本工作流创建的订单，已知client ID登记表为空，因此实际策略Paper PnL为null。
2. **现实成本压力账本**：保留费用/价差/滑点的声明情景与适用边界，单独展示。当前不把它当真实账户费率或Paper平台实际收费，也不把Paper未计的成本自动设为真实0。

[官方Paper说明](https://docs.alpaca.markets/us/v1.4.2/docs/paper-trading)把它定义为模拟环境，并列明其执行和费用简化。因此Paper能支持工程链路研究，Paper收益不能自动升级为实盘净收益。之前实际账户费用适用值仍为null，但不阻挡本Paper工作流。

## 本轮已做与下一步

- P0完成：复用原GET-only probe和recorder，不另造券商接口。Paper账户、clock、positions、open orders和有界activities采样完成；只发布状态/数量，原响应留本地私有文件。采样不是完整历史或原子快照。
- P1完成：对已封存A/B原R1交易计算完整固定成交成本视图，明确不重新定仓/重放、不称Alpaca撮合复现。
- P2可继续：使用`orb-paper-r1-v1`策略命名空间建立专属意图和client ID登记，复用已有时序和生命周期验收。命名空间前缀本身不能证明归属，需精确登记和意图先于订单观测。市场/数据/时钟缺口作为Paper实验完整性问题记录，而不是用实盘费率阻断；输入缺失时不得伪造成交。
- P3尚无结果：收集策略专属Paper链路后再报告其完整性和模拟绩效。不能把他人/其他算法账户活动归给R1，不能把本轮空样本记成零费用或零收益。

本轮不修改R1规则、资金/风险默认值，不选参数、不训练，也不把历史信号当成当前市场意图提交。历史A/B继续标为已暴露。当前代码只有只读观测与离线核算，Paper和真实订单提交均未开启；这不妨碍继续做Paper专属意图记录和模拟生命周期工程研究。该工作单只是研究范围记录，不是已接入broker的运行守卫。

2026-10-19进展：[意图/累计回报进度](paper-intents-progress.json)和[工程报告](../../reports/orb-paper-intents/README.md)记录P2登记与离线对账验收；当前市场信号适配和策略专属Paper成交尚未接入，不改变原工作单快照或历史结果。

2026-10-19后续：[历史信号桥接进度](historical-signals-progress.json)和[验收报告](../../reports/orb-historical-signals/README.md)记录315个已暴露交易日前缀与145次原R1入场匹配、隔离的历史意图及恢复去重。闭合分钟线到达后回记09:36入场的模型不能直接作为09:36实时下单依据；当前信号接收时间和价格可用性适配仍待完成。

2026-10-19继续：[观察就绪进度](observed-signals-progress.json)与[工程报告](../../reports/orb-observed-signals/README.md)记录规范化分钟接收、程序处理时间及后续ask参考的持久观察验收。接收时间目前仍由调用方声明，尚无provider接收器、完整R1定仓或新Paper意图；旧OHLCV不补造接收时刻或报价。

2026-10-19接口验收：[采样进度](market-capture-progress.json)和[报告](../../reports/orb-market-capture/README.md)记录3次真实有界GET：SIP latest quote返回403，独立声明的IEX quote/bar返回200。旧样本、纳秒时间及规模单位保留，不作为R1新鲜SIP信号；未购买数据或生成Paper意图。下一步继续旧数据/构造数据上的无损纳秒观察与回放。

2026-10-19用户明确授权开始Paper交易实操，后续重点改为实际账户执行。[实操进度](paper-practical-progress.json)与[成交报告](../../reports/paper-practical/README.md)记录首笔1股QQQ买入及卖出均filled、最终空仓无挂单；−0.08美元为成交价差，费用未核验，不是R1收益。该独立执行试单已实际POST至Paper，早期只读标志仅作历史快照保留，真实资金交易仍关闭。

2026-10-19用户要求着重优化策略：[本轮固定规则](rvol-exploration.json)、[首项优化结果](../../reports/r1-rvol/README.md)和[优化进度](strategy-optimization-progress.json)记录单一RVOL14≥1过滤的完整A/B探索。各组独立递推资金、原R1完整重放精确一致；结果混合，未把过滤器晋级Paper，不改原结果或假称新样本外确认。

2026-10-19按用户提出的SPY逢跌买入、长期不卖建议，完成独立[长期积累比较](../../reports/spy-long-hold/README.md)：2000—2025年相同入金，到账即买、首笔分12个月、5%回撤买入的期末资产接近；17个十年窗口没有显示5%规则稳定胜出，约55%长期回撤仍存在。此为历史研究，未据此向Paper下单，规则和完整现金/摩擦情景见[单独方案](../spy-long-hold/protocol.json)。

2026-10-20按用户同意的固定月度10个月均线，完成[趋势过滤对照](../../reports/spy-trend/README.md)。采用含分红月末信号、次日开盘执行；原文核对及规则差异公开。零利息主情景回撤约55.19%→25.63%，但期末资产约179.50万→110.41万美元，收益代价明显。四个主基准和34个窗口基准精确还原，没有改均线长度或自动部署Paper；[进度](../spy-trend/progress.json)保留全部不利结果。
