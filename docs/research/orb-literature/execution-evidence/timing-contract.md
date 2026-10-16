# 离线执行时序契约 v1

范围：实现方案v2的W2工程部分。[实现](../../../../research/orb-diagnostics/execution_timing.py)是无网络、无订单接口的纯函数，不接入旧引擎，不认证原始观测，也不校准真实延迟。生产156个src文件及旧登记保持不变。

## 输入和时序

`evaluate_timing(trace, quotes, max_quote_age_us=...)`接收JSON兼容的trace和按本地接收顺序排列的quote列表。

trace必须声明：

- `contract=ORB_OFFLINE_TIMING:1`；`observation_kind`为SYNTHETIC、RECORDED_OBSERVATION或HISTORICAL_RECONSTRUCTION。
- `symbol`、显式`required_feed`（sip或iex）、BUY/SELL方向、正整数股数。SELL只是报价匹配方向，不决定开空/平多，也不证明可借。
- `signal_window_end <= last_input_available_at <= last_input_received_at <= decision_at <= intent_ready_at`。这些值都是输入声明；没有认证最后输入的完整性、首五分钟计算或原始可见性。

quote必须有：唯一quote_id、严格递增本地receipt_sequence、非递减received_at、event_at、symbol、feed、正数bid/ask及其size，size单位明确为SHARES。不接受未知手数换算、布尔数字、非有限价格、交叉报价、无时区时间或隐式丢失纳秒精度。当前只精确处理至微秒；纳秒源需要另定无损适配，不得直接截断。

event_at晚于received_at时阻断，因为跨时钟误差尚未解决；不会默认为0延迟。真实观测需额外记录时钟来源、精度/同步证据、估计误差和数据来源/文件封印；本函数不认证这些信息，输入自称RECORDED也不会变成已验证实测。

## 固定选择规则

逐个检查收到的报价前缀，选择**第一个**符合下列条件的报价，不比较未来更好价格：

1. symbol/feed匹配，不从SIP隐式退到IEX。
2. quote事件和接收时间均不早于intent_ready_at；不会回填09:35 bar open。
3. 接收时该quote的事件年龄不超过外部明确给定的max_quote_age_us。
4. 请求股数不大于对应方向显示股数；BUY用ask及ask_size，SELL用bid及bid_size。只做单层完整数量的理想匹配，没有部分成交、排队或冲击模拟。

不满足的有效报价按原因计数：来源不匹配、意图前报价、过期、显示量不足。结构错误、重复/乱序接收或未解决时钟顺序则抛错；未找到匹配时输出NO_ELIGIBLE_QUOTE。找到匹配即停止读取后续列表，未来价格和未来错误都不能改变已经做出的前缀匹配。完整录制质量统计应另做，不应使用后来观测修改过去决策。

模型匹配时刻取选中报价的接收时刻，只表达这一离线即时匹配假设，不表示交易所真实成交。显示量可变化，满足显示量检查也不保证真实可成交。报价本身也不证明NBBO或覆盖完整，feed标签只是声明。不得把已经采用bid/ask的报价参考再机械加一次原“完整点差2bps”，以免双算；真实滑点、冲击、佣金/监管费仍应单独有证据。

## 输出和阻断

SYNTHETIC_MODEL_MATCH只证明构造时序可匹配；其他来源即使结构通过，也仅为UNAUTHENTICATED_MODEL_MATCH。所有输出均有`execution_enabled=false`、`actual_fill_verified=false`、`authenticity_verified=false`、`live_latency_verified=false`、`costs_calibrated=false`和`runtime_guard=false`。

输出各阶段的**声明时间差**，不能称真实平均延迟。缺少max_quote_age_us时明确BLOCKED_MISSING_QUOTE_FRESHNESS_POLICY，不默认0或套示例。真实活跃策略的报价新鲜度、时钟误差、数据源权利和完整性仍未固定；[progress.json](progress.json)保持null，因此本工程交付不解除W3阻断。

[示例](synthetic-timing-example.json)的50/60毫秒时间点和500,000微秒新鲜度仅用于构造测试，不是测得延迟或推荐参数。没有实际账户/报价/撮合观测参与；也不暗示能在09:35后几十毫秒获得完整真实信号。
