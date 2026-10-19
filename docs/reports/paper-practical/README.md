# Paper账户：首笔实际买卖闭环

2026-10-19。用户明确授权开始Paper交易实操后，工作从只读验收转入真实Paper订单。本轮已完成一股QQQ买入和卖出，两边均由Paper券商回报确认filled，并找到分别匹配两个订单ID的FILL活动记录。未调用真实资金交易域名。

|结果|值|
|---|---:|
|买入数量|1股QQQ|
|买入平均成交价|718.43美元|
|卖出数量|1股QQQ|
|卖出平均成交价|718.35美元|
|成交价差|−0.08美元|
|最终账户持仓数|0|
|最终挂单数|0|

费用尚未核验，净收益为null。此笔为独立的`PAPER_EXECUTION_SMOKE_NOT_R1`执行试单，不计R1策略收益。执行前Paper账户ACTIVE且未封锁、账户空仓、无挂单，市场已开盘。今日R1的开盘入场时点已经过去，本轮没有用历史开盘信号追溯下单。

## 实际执行

实现：`research/orb-diagnostics/paper_roundtrip.py`。唯一交易主机硬编码为`https://paper-api.alpaca.markets`，未提供实盘主机覆盖参数。当前IEX报价仅作为独立工程试单参考，不被冒充为原SIP策略输入；事件时间按纳秒整数检查新鲜度，不进行有损时间转换，也不依赖未确认的报价规模换算。

买入为1股QQQ限价FOK订单，限价按当时ask上浮0.1%并向上取整至美分，且不超过1000美元。该0.1%、5秒新鲜度和0.5%价差上限是一次工程试单的项目约束，不是新策略参数或文献最优值。FOK未成交部分不留为日内长期挂单；本次实际完整成交。确认本次买入filled、成交量1股且账户QQQ持仓恰为1股后，立即发出1股市价卖出。卖出也确认filled，之后再次查账户持仓与挂单，均为0。

每边client order ID、完整订单payload和发送状态均在POST前落盘；请求开始后标记DISPATCHED，禁止原payload再次POST。未知结果只允许按已登记client ID查单；查不到时停止供核查，不把超时当未成交。恢复运行实测只有5次GET、0次POST，最终摘要不变。此为单次、有人监督的执行闭环，不是守护进程；过程中若停机、非整数成交或长时间未决，需要继续按原ID核查及处理，不能宣称已有完整自动灾备或保护性挂单。

账户前置检查、真实订单、成交活动、报价原响应及client/broker ID保存在本地`work/paper-practical/`私有文件，原始响应不上传。公开[成交摘要](roundtrip.json)、[FILL归属核验](fill-evidence.json)和[前置检查](preflight.json)不含账户或订单身份。成交活动只取有界页面，不宣称完整费用历史。

## 边界与后续重点

- 用户最新Paper交易授权覆盖本轮实际POST；此前报告的GET-only和execution=false是当时快照，不是本轮权限现状。真实资金交易依旧关闭，持续策略自动交易尚未启动。
- 原156个`src/dx27`源码、冻结R1和历史A/B结果不改；试单使用独立日志和标识，不污染R1收益样本。
- 本地共103项检查通过，其中本轮6项覆盖一股/限价上限、固定Paper路径、未知发送结果不重发、卖出需己方成交、时效与空仓检查，以及订单归属。跨平台CI运行同一套件。
- 下一步优先开展下一交易时段的小仓位Paper策略试运行，明确免费IEX观察版的身份、当时可用输入和退出规则；不继续把付费SIP或更多离线报告当作启动Paper实操的前提。当前没有部署无人值守任务或预挂下一日订单。

操作API依据：[Alpaca创建订单](https://docs.alpaca.markets/us/reference/postorder)、[按client order ID查单](https://docs.alpaca.markets/us/reference/getorderbyclientorderid)。[最新进度](../../research/orb-literature/paper-practical-progress.json)、[验证封存](validation.json)。
