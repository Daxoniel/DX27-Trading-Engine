# 探员：真实数据验收与 INTRA-1B 实现

验收日期：2026-10-14。基线源码：`08c1d82`（PR #40）。验收使用固定工程参数，
没有根据本次结果调整 ADX、风险、费用或成交量阈值。

## 真实历史数据

Alpaca `feed=sip`、`timeframe=1Min`、`adjustment=raw`，标的 SPY、QQQ、IWM。
请求区间为 2025-01-01T00:00:00Z 至 2025-04-01T00:00:00Z（右端不含），
决策期自 2025-02-01 起，之前仅预热指标。

取得 15 页响应、145,553 条源分钟线；XNYS 日历内 60 个交易日、70,200 条
常规时段线，每个标的 23,400 条。独立逐分钟检查缺失数 0、零成交量数 0；
重复键、价格/成交量和 CSV/响应档案 hash 通过已有 loader 校验。
75,353 条盘前/盘后数据不参与决策。原始 CSV、canonical JSONL 档案、完成元数据
和账本均保留在本次交付包，未提交原始行情至公共仓库。

CSV SHA-256：`67cef18fb985a749bc333713cc99e737032e89c714257dc87b45f83aea559f91`

JSONL SHA-256：`81fd4f1658e47ec0d6e812bc20d866f28c3f54abca19b2f9e92882af9ba43a38`

响应档案为 canonical JSON 对象，不是 HTTP 原始字节；原响应字节 hash 独立保留。
可用时点仍为假设分钟结束，尚未验证原始发布时点、实时订阅或普通个股历史股票池。

## 回放和独立账本检查

两种回放均 COMPLETE_REPLAY、60 日完整、零未平持仓。独立复核买入成交严格晚于
决策、现金流对期末现金、交易净损益对权益变化、分钟 cash+holdings 对 equity，
以及逐笔毛损益减佣金/点差/滑点对净损益；所有残差小于 $0.000001。

| 固定工程配置 | 交易数 | 扣费后净损益 | 最大回撤 |
| --- | ---: | ---: | ---: |
| INTRA-1A，筛选关闭 | 46 | -$1,706.63 | 1.7758% |
| INTRA-1B，前 20 日均量、RVOL >= 1.0 | 15 | -$805.66 | 0.8254% |

INTRA-1B 产生 180 条 symbol/session 筛选记录：60 条历史不足、53 条入选、
67 条低于阈值。分子与分母均为同一 30 分钟开盘区间，完整历史仅使用之前的
计划交易日，不跳过缺失样本，不用当日全日成交量，也不做 top-N 排名。

表格仅记录软件验收结果，没有独立统计比较或策略优胜结论。两个版本都亏损；
本时期已被查看，不能在 INTRA-1C 中称为未触碰的独立验证期。
`effectiveness=NOT_EVALUATED`、`production_enabled=false`。

## P0 账户访问

环境域名绑定更新后，2026-10-14 重新执行仓库只读 P0 probe，
`/v2/account`、`/v2/clock`、`/v2/positions` 全部成功，状态
CONNECTED_READ_ONLY。账户 ACTIVE，account_blocked=false、trading_blocked=false，
持仓数 0。原先 HTTP 401 已不再复现。脱敏原始诊断见
[p0-account-connectivity.json](p0-account-connectivity.json)。

本次没有提交订单，未验证订单权限、实时 SIP、持仓恢复或真实成交。
只读诊断程序和错误脱敏/拒绝重定向测试已实现，自动下单开关保持关闭。

## 软件验证与后续

旧检出环境恢复后的全量基线：838 passed、1 deselected。同步 PR #40 后的
INTRA-1A 针对性测试：39 passed。全量回归：900 passed、1 deselected。
最后增加的 5 项安全边界测试与修订纳入最终日内测试：90 passed。
详见随包 `final-pytest.log`、`intraday-targeted-pytest.log` 和 `acceptance.json`。

日内 CI 已增加 RVOL 与账户诊断离线测试，覆盖 Ubuntu/Windows；Ubuntu 与 Windows CI 均通过（run 38536872619）；全量本地回归仅在 Linux 执行。

后续按 [P0–P3 路线](../../architecture/intraday-delivery-roadmap.md)：先完成账户
连通验收，然后 P1 分钟行情 Shadow Mode，再做默认关闭的 P2 自动模拟交易和
P3 固定历史/影子/模拟成交效果评估。
