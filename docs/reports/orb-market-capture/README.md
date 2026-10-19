# 有界只读行情采样：真实接口验收

2026-10-19，按Paper工程研究范围接入`research/orb-diagnostics/market_capture.py`。仅使用已有凭据访问固定`https://data.alpaca.markets`，没有broker账户/订单接口、订阅购买、策略调参或交易。

## 实际结果

两个feed在运行前明确指定，分别保存日志，不存在SIP失败后自动选IEX的分支。本轮共3次GET，无重试：

|明确指定的feed|latest quote|latest minute bar|结果|
|---|---|---|---|
|SIP|403|未请求|失败后停止；不能宣称当前SIP可用|
|IEX|200|200|独立的免费接口验收；不能替代R1的SIP输入|

采样在柏林时间11:41左右完成（响应技术字段保留UTC）。IEX最新报价在HTTP响应完成时约已过去60.8小时；最新分钟线约61.2小时。这些都是“latest接口返回的旧样本”，不是当时的新鲜市场报价，不能把HTTP成功当实时策略信号。SIP的403仅作为本次访问被拒的证据，不从状态码独自推断账户完整权限或费表。

[SIP匿名摘要](sip-summary.json)、[IEX匿名摘要](iex-summary.json)仅含状态、时间、年龄、模式和哈希。完整响应字节（包括拒绝响应）以base64保存在本地`work/orb-market-capture/{sip,iex}-1/private-capture.sqlite`；文件在本地为0600，公开文件不含原始报价、账号或凭据。重新打开两份日志后摘要不变，SIP失败状态和IEX请求额度均阻止额外请求。

## 传输与恢复边界

- 路径只允许QQQ latest quote或latest bar；GET方法、主机、feed参数固定，拒绝重定向，不使用API默认feed。没有可传入任意URL或交易路径的入口。
- 单日志最多4次请求，本轮各设2次；每次超时10秒、响应最多64KiB。无自动重试、分页、轮询等待或付费feed升级。失败后停止该日志的后续请求。
- 请求前先原子保存PENDING，再进行HTTP；完整响应读取结束立即记录本机微秒UTC时间，随后解析。另记单调时钟测得的HTTP耗时；它不是交易所到客户端的端到端延迟。
- 原始响应与请求结果一起落盘，凭据和认证headers不写入日志。重启遇到未决请求不自动重发，避免把未知结果当未发生。请求额度、feed、标的和模式由日志manifest固定。
- 校验JSON重复键/非有限值、返回标的、价格/OHLC、规模和时间关系；异常响应仍保留已有的有界原始字节。超限/截断正文被拒，错误正文最多保留64KiB并标注截断。

## 时间与单位：不做有损接入

provider时间保留原字符串，并用原封存核心的UTC纳秒整数解析器计算年龄，未经过Python微秒datetime截断。HTTP接收时间指本次完整响应读取完成，不是原始市场事件第一次到达客户端的时刻。

现有观察日志精确至微秒。因此只有SIP报价、已确认SHARES单位、正的显示规模、且provider纳秒值能被1000整除时，才可无损生成规范化QUOTE。其他情况保留原始响应并明确返回原因；不四舍五入、不截断、不把IEX重标SIP。此次真实IEX样本同时受feed、规模单位和非整微秒时间限制，未进入R1观察日志。

报价规模使用日期和feed适用范围：Alpaca的[2025-10-30变更公告](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change)说明CTA/UTP自2025-11-03起改以股显示；[实时schema](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)仍写round lots。代码仅将该日期以后的SIP规模标为SHARES，保持数值原样；此前数据及当前IEX单位标为UNRESOLVED，不乘以100。没有把旧论坛惯例当当前全部feed的定义。

latest bar可以是尚未结束的分钟，本模块显式检查结束时间，不能因HTTP成功就认为闭合。即使结束也不证明最终不再修订；官方另有updated bars。一次latest bar也不提供完整开盘六分钟，缺失前缀不补造。当前尚无流式接收、持续运行、provider事件完整性、修订/补洞或正常化BAR到策略链路。

## 验收与后续

诊断套件共97项，本轮新增16项，覆盖固定GET、请求预算、失败/未知结果恢复、重定向、超限/截断、原始字节、时间精度、单位边界及构造报价到观察日志的连接。跨平台CI运行同一套件。构造的可精确表示SIP报价能接入上一轮日志并得到参考价，但不创建Paper意图。原156个`src/dx27`文件未变；历史A/B与冻结R1结果未改动。

复查单独feed时使用新的本地输出目录；命令最多请求quote与bar各一次，失败即停止：

```bash
PYTHONPATH=src python research/orb-diagnostics/market_capture.py \
  --feed iex --output work/orb-market-capture/new-iex-sample
PYTHONPATH=src python -m unittest discover -s research/orb-diagnostics -p 'test_*.py' -v
```

这是捕获和检查接口，不是完整策略接入或订单运行守卫。实际Paper意图为0，实际策略Paper收益为null，订单提交始终关闭。按用户旧数据优先的要求，下一步先补无损纳秒观察与记录回放；不以购买SIP作为继续工程研究的前提。[当前进度](../../research/orb-literature/market-capture-progress.json)、[验证封存](validation.json)、[官方依据及核验范围](sources.json)。
