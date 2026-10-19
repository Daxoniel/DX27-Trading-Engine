# 历史行情信号到隔离意图：工程验收

2026-10-19。按用户“用Paper账户作为研究基础、旧数据可以继续测试”的指示，完成冻结R1的历史信号桥接。实际Paper意图和策略专属订单仍为0，实际策略Paper收益为null，没有调用订单提交接口。

## 结果

|阶段|完整核对的交易日|历史入场意图|无入场日|检查的分钟前缀|
|---|---:|---:|---:|---:|
|A|251|115|136|1,757|
|B|64|30|34|448|

每个交易日仅向原`OpeningDirectionFixture(profile='R1')`提供09:30至09:36的7根分钟线。入场的存在性、方向、股数、参考价、时间，以及截至09:36的所有决策，逐项与封存的原始R1记录一致。两个阶段分别关闭并重新打开日志，重复处理全部交易日；输出、意图数量与日志序号均不变。每日资金直接读取原始日账本，不重新模拟资金递推、退出或收益。

输入CSV、原始报告、日账本、成交与决策记录均先核验公开封存哈希。原156个`src/dx27`文件保持不变；日历使用原`exchange-calendars==4.13.2`并核验原日历身份。A/B都是已暴露数据，这不是新的样本外效果确认。

## 时间限制及依据

这里复用的是项目冻结R1，不是声称复现论文原始策略。论文与项目规则差别见[文献审查](../../research/orb-literature/review-2026-10-16.md)和[冻结设计](../../research/orb-literature/evaluation-design.json)。没有增加指标、训练、参数搜索或成本校准。

原实现及[已有实现约定](../../research/orb-literature/fixture-implementation.md)明确：完整分钟在结束时交给模型，再回记分钟内事件。首五分钟方向在09:35形成；09:36起始分钟的开盘参考价及其模拟入场，在09:37收到闭合分钟线后才可由这条输入链路恢复。新结果分别记录`signal_at`、`modeled_entry_at`与`intent_ready_at`，不把回记的09:36当成真实收到数据或可下单的时间。09:37同样只是历史分钟结束可用假设，不是测得的网络接收时间。这是对原代码契约的核验，不是新的文献结论。

因此本桥接没有完成实时Paper信号适配。实时路径还需要明确可观察的事件接收时间、当时可用的参考价、定仓及重连策略；不能把当前完整分钟或事后历史开盘价用于伪造当时订单。

## 隔离和恢复

- 日志新增显式`HISTORICAL_REPLAY`模式，意图origin同名、ID前缀为`orb-hst1-`，与Paper的`orb-ppr1-`区分。历史桥接拒绝Paper和构造测试日志；历史origin也不能直接登记到Paper模式。
- 每个交易日有确定性signal/intent ID；payload封存7根分钟线、资金、日历时段、规则版本、SIP标记及原始文件哈希。模型不读取后续分钟；更换档案来源哈希也会改变payload身份。
- 相同输入重复登记和重启恢复返回相同ID；已登记入场的payload变化或变为无入场会停止新增登记。历史模式拒绝broker成交回报，不能拿这些回放意图认领真实订单。
- 缺失或零量分钟阻止意图生成，重复/乱序、错误标的/周期、无效OHLC、IEX替代SIP均拒绝。无入场决策保存于本轮逐日检查文件，不写入意图日志；尚未实现无入场决策的持久接收工作流。
- 两个阶段的历史SQLite和逐日明细保留在本地`work/orb-signal-bridge/`。公开仅发布匿名汇总和哈希，不发布原始行情、账号或凭据。

没有完整账户资金对账、来源真实性验证或当前行情接入。历史意图并非原市场时点已落盘的意图，也不作为实际Paper成交证据。既有实时费用未知项不阻挡上述工程工作。

## 复查

构造测试及既有诊断共66项，包含11项新测试；覆盖缺失的每个前缀分钟、前一分钟量定仓、时间/DST、模式隔离、来源变更和恢复。Windows和Ubuntu运行相同套件；新增固定`tzdata==2025.2`以提供跨平台纽约时区数据。

有本地原始数据和既有研究依赖时，可复查历史匹配（输出目录必须尚不存在；B同理替换阶段和路径）：

```bash
PYTHONPATH=src python research/orb-diagnostics/check_historical_signals.py \
  --stage A --csv work/orb-stage-a/stage-a-with-june-warmup.csv \
  --artifacts work/orb-stage-a/attempt-1 --output work/orb-signal-bridge/recheck-a
PYTHONPATH=src python -m unittest discover -s research/orb-diagnostics -p 'test_*.py' -v
```

[A汇总](stage-a.json)、[B汇总](stage-b.json)、[验证封存](validation.json)、[当前进度](../../research/orb-literature/historical-signals-progress.json)。下一步是只读当前信号的时钟和价格可用性适配；历史、构造测试与实际Paper观察继续分开。
