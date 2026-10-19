# 方向与参考价可用性的持久观察

2026-10-19，Paper工程研究。本轮完成规范化输入的持久观察适配；没有新行情连接、实际Paper意图、订单或收益结果。实现为`research/orb-diagnostics/observed_signals.py`，仅新增研究模块，原156个`src/dx27`文件保持封存。

## 完成的链路

按接收顺序输入开盘09:30至09:35的六根闭合QQQ/SIP分钟线，在原`OpeningDirectionFixture(profile='R1')`内恢复首五分钟方向。第六根提供09:36之前已闭合的完整前缀，模块不调用09:36的原模型入场路径，不读取09:36分钟的未来高低收量。方向、缺失/零量等判断复用原实现；未新增指标或训练。

方向为多、输入完整且显式新鲜度规则通过后，记录本次程序处理时间。随后复用`execution_timing.evaluate_timing`选择处理完成以后按接收顺序出现的第一份合格ask参考，不选择未来更好价格，不回填09:36开盘价。报价须为QQQ/SIP、未交叉、正有限价格、明确SHARES单位，且能覆盖声明的探测股数；报价事件时间不能晚于接收时间。

这是时序与参考价观察，不是完整R1定仓或新的交易策略。股数为显式工程探测参数；没有使用真实账户资金或将ask当作冻结R1开盘参考价的等价替代。已有时序契约中的`intent_ready_at`字段在此仅表示假设意图的处理就绪时间，并无实际登记的订单意图。所有输出均为`execution_enabled=false`、`actual_paper_intents_created=0`和`actual_strategy_paper_pnl=null`。

## 三类时间及证据范围

- 分钟结束时间是数据可用性的假设下界；没有测得provider发布时刻。
- `received_at`来自规范化输入，当前没有接入原始provider接收器，因此只是调用方声明。
- 日志在每次新输入处理时读取本机时间并保存`processed_at`；RECORDED_OBSERVATION模式不允许注入程序时钟。程序时钟也不证明跨系统同步或来源真实性。

新鲜度规则必须显式给定，缺失时阻止参考价确认。分别检查每根分钟线结束到接收的延迟、最后输入接收到程序处理的延迟、报价事件到接收的年龄、报价接收到处理的延迟，以及等候报价期间信号是否已过期。接收早于分钟完成、接收晚于程序时间、时钟回退等拒绝；过期信号不能因后来收到新报价而复活，原R1收盘前10分钟的入场截止也保留。

构造例子中的`max_quote_age_us=500000`、`max_input_age_us=1000000`和10股只用于工程测试，是项目声明情景，未经文献优化或实测校准；真实模式没有默认值。不把这些规则当实盘延迟标准，也不拿Paper实际费率未知阻挡工程研究。

## 恢复与边界

SQLite事务将接收事件、已收分钟前缀、处理时间、就绪状态及参考价一起保存。相同event ID与相同payload重放返回DUPLICATE，不推进序号；同ID冲突、接收序列缺口/乱序、时钟回退会落盘停止标记。参考价首次确认后冻结，不能被后来更好的价格替换。模式、session、探测股数或新鲜度配置不能在原日志上静默更换。

序号只验证本地输入序列连续，不证明provider无丢包。日志限单session、最多2048个已接受事件，适用于有界验收，尚非持续行情服务。缺失分钟不补造，缺失或损坏输入不产生参考价。没有自动重连、数据修订/补洞、网络认证、provider规模单位转换、原子账户快照或定仓到Paper意图的连接。

RECORDED_OBSERVATION与SYNTHETIC分库并由manifest隔离；RECORDED标签不代表已经真实抓取或认证来源。新增[空的记录模式日志摘要](empty-recorded-journal.json)只验证模式初始化，不含真实行情。历史CSV的封存哈希再次核验通过，但缺少原始接收时间和逐笔bid/ask，因此本轮没有将旧OHLCV伪装成记录模式输入；已有315日历史一致性结果仍见[上轮报告](../orb-historical-signals/README.md)。

## 验收与依据

同一套81项检查在本地通过，其中15项新增观察日志检查，覆盖恢复、重复、缺口、冲突、时钟、过期、缺失规则、IEX拒绝、无效价格、部分方向及配置隔离；Ubuntu/Windows CI运行相同套件。构造数据[示例](synthetic-example.json)包含六根闭合分钟及后续ask参考，重开日志后重放7个事件，摘要和序号保持不变。它没有实际成交。

规则依据仍为[冻结设计](../../research/orb-literature/evaluation-design.json)、[实现约定](../../research/orb-literature/fixture-implementation.md)、[文献核对](../../research/orb-literature/review-2026-10-16.md)及既有离线报价时序模块。本文不新增收益或论文复现结论；ask探测契约属于工程观察，不声称论文指定了这种成交规则。

验证命令：

```bash
PYTHONPATH=src python -m unittest discover -s research/orb-diagnostics -p 'test_*.py' -v
```

[文件封存](validation.json)与[进度](../../research/orb-literature/observed-signals-progress.json)。下一步接有界只读provider接收和schema规范化，明确feed与规模单位；真实接收、可用价格和定仓契约完整前不生成Paper订单意图。
