# RC1：带证据的元数据代码映射与形成期采集

本阶段落实 VSCO→VSXY 的**元数据查询映射**、可在形成期运行的完整采集入口及八本空的本地影子账。没有改变归档池、原排名、10% 目标预算或此前满仓版本的 FAIL。原研究与 156 个核心文件保持原样。

[方案](protocol.json)先登记，再提交[代码封存](code-seal.json)，随后构建私有映射表、准备本地账本、用真实当前时钟运行预检。此次没有新的行情或券商网络请求。

## 映射如何接入

私有 registry.json 由 RI1 留存的 SEC、发行人公告、供应商改名事件和当前资产响应构建。生成器核对原始文件哈希与已公开个案收据的一致性；加载器再核对[映射表摘要](registry-receipt.json)。当前只登记 VSCO→VSXY，自 2026-06-02 生效且 CUSIP 不变。原始依据及其局限见[身份个案](../residual-integration/README.md)。

研究、行业和价格键继续用原 VSCO，价格请求仍为原归档代码加 `asof=2025-04-25`。查询当前资产时才使用 VSXY；保留接口实际返回的 VSXY 原始响应，并另存 canonical→metadata_lookup 绑定。不改写响应，不编造“VSCO 请求成功”的收据，也不把 VSXY 加入股票池。当前资产 ID 若不同于已登记证据会阻塞，而不是自动接受新 UUID。

代码还会拒绝目标代码与归档池发生碰撞、重复映射、未登记别名或生效日以前的别名使用。材料只证明已阅读的个案及字节一致性，并非所有时期股权或行情映射的真实性证明；本阶段 formation-ready 身份数仍为零。

## 正式入口的顺序与边界

命令必须明确选择六个已登记形成期之一。当前时钟早于形成期收盘时返回 BLOCKED_FORMATION_NOT_CLOSED；达到执行日开盘时返回 SKIP_CYCLE_INCOMPLETE。这两种情况不会读取凭据、查询源接口、抓行情或计算新排名。CLI 不提供模拟日期参数。

有效窗口内按以下顺序运行：

1. 抓取 FF3；缺少此前完整 36 个月即停止，只留下因子收据，不请求股票。初始资金与已有持仓来自八本实际本地日志及其头摘要，不读取 Paper 账户。
2. 对原 4,002 股加 SPY 分批、取完分页，分别获取完整 `all`／`raw` 日线；统一使用形成月减 37 月之首日至形成日的窗口。实际 API 参数明确为 UTC 00:00:00 至 UTC 23:59:59，日期声明和实际 RFC3339 参数分别留存，避免日末解释歧义；这不是对旧研究结果作漏价结论或修订。
3. 检查源字节、请求 URL／参数、页令牌、返回代码与日期、SPY 交易日历，随后重算原资格及独立 QR／Decimal 排名。没有新旧复权拼接或自动隔离。进入步骤前与每次请求后都检查截止时间；生产请求间至少保留 0.35 秒间隔。
4. 对整个原基础同行池、四组目标及既有持仓，抓取所有类型、包含不完整记录的公司行动，以及当前资产元数据；已登记的代码映射只在资产查询使用。逐项保存原响应与独立绑定记录。
5. 全部成功才保存 RC1 清单和候选排名封存，状态固定为 **CAPTURED_PENDING_IDENTITY_REVIEW**。失败则 BLOCKED_CAPTURE_INCOMPLETE，不生成最终候选封存；重新尝试需新目录，不覆盖或静默退回其他数据源。

RC1 保存了显式 API 时间界限与元数据别名来源，**不能伪装成旧 RA1 输入**。旧 RA1 检查器未改动，本阶段也没有把候选排名变为已准入交易计划。后续仍需新的身份／公司行动审查、明确保留来源证明的别名准入适配，以及每日账本服务。没有订单、自动推广或后台调度。

`network_requests` 计数为源请求尝试；请求若在本地校验或连接前失败，也可能没有实际联网。形成期外的实际预检在创建传输器之前返回，因此此次的零请求结论不依赖这个计数近似。已计算但尚未封存的排名在后续资产失败时也会如实计入 new_rankings，不能冒充“尚未看分数”。

## 已实际准备和验证的内容

- 私有映射表已从真实留存证据生成、加载并核对资产绑定：[摘要](registry-receipt.json)。没有新增证券或价格别名，没有重新查询或更新供应商证据。
- 八本独立的空本地影子账已经准备；每本初始代理金额 100,000 美元，无持仓、无每日标记，均通过日志头及独立会计核验：[准备收据](accounts.json)。这不是 Paper 资金、账户余额或资金预留，未修改既有日志。模型仍自带 OFFLINE_REHEARSAL_ONLY 标记，不冒充已启动前向账户。
- 真正用当前时钟运行 2026-10-30 的采集命令，得到[预检收据](preflight.json)：BLOCKED_FORMATION_NOT_CLOSED，零请求、零新排名、零订单。
- 8 项新增测试及 62 项父研究回归通过。完整采集测试使用明确的 55 股合成行情和假传输器，真实运行分页、资格、评分、原日志审计与元数据检查；仅替换合成归档池哈希，不替换模型和账户验证。该合成采集成功案例不含实际别名；真实别名的证据校验在上述私有材料上另行完成，不能称生产别名完整准入已验证。

未重新请求因子，因此不能更新前次“只到 2026-08”的观测结论。当前尚未进入首个形成期；不存在新的策略收益、交易胜率或前向绩效。

## 使用

```sh
python -m pip install exchange_calendars==4.13.2
python -m unittest discover -s research/residual-capture -p 'test_*.py' -v
python research/residual-capture/registry.py --output work/residual-capture/NEW-REGISTRY
python research/residual-capture/prepare_accounts.py --root work/residual-capture/NEW-EMPTY-ACCOUNTS
python research/residual-capture/collector.py --formation 2026-10-30 --registry work/residual-capture/registry-1/registry.json --ledgers work/residual-capture/empty-proxy-accounts-1/ledger-heads.json --output work/residual-capture/NEW-CAPTURE
```

形成期外运行最后一行不需要私有输入或凭据，也可省略 registry／ledgers 参数。有效窗口内必须提供已有、摘要匹配的私有映射表，以及含绝对 root 和八个相对路径／头摘要的 ledger-heads.json。账本是外部独立目录，采集器仅核验、不会更新；日志改变后必须提供对应的新头证据，不能继续使用旧头。

映射加载器以当前公开 registry-receipt.json 的摘要为锚，随意重建另一份表不能绕过；更换证据或 UUID 必须登记新版本。构建映射需保留 RI1 私有原文与资产快照。全部输出目录必须不存在，原始行情、因子、身份与逐股候选仅留在忽略的 work/。CI 在 Ubuntu、Windows 跑 70 项测试及字节封存核验，不使用凭据或真实行情。
