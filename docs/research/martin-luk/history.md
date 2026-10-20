# MLP1 历史验证：协议、数据与回放

2026-10-20。执行用户批准的“先历史回测，再影子运行，最后小仓位 Paper”第一步。
不新增订单，不修改 MLP1，不使用新取得的 2026 年 SOXL 价格。

## 先冻结，再计算

[协议](history-protocol.json) 于提交 `e95bfae` 推送发布，随后才进行股票筛选和收益计算。
策略固定在主干 `1d784e3d519a0d82f62191cc5b05f7cc8860efb9`，
`strategy.py` SHA256 为 `8f73d3c2437c34c034f8c5c513e6488f07ad010d7b751ae952459e1286d63fdf`。
原代码没有修改。回测区间 2025-04-28 至 2025-12-31；每日使用此前 160 个交易日，
初始资金 $100,000、现金利息零、无追加资金、每次买卖假设 5bp 不利成交成本。
这是成本情景，不是已核验的券商佣金、监管费与滑点拆分费表。

## 可获得数据与缺口

1. Alpaca 当前 `status=all` 目录读到 33,567 条记录，其中 19,163 条为 inactive。
   目录字段没有历史行业分类和完整历史上市/退市有效区间；不能把当前 active
   目录倒推成历史股票池。[资产接口文档](https://docs.alpaca.markets/us/reference/getassets)。
2. 使用 [2025 年已公开的历史 screener 归档](https://gist.github.com/nickmccarty/a481c4d2587e5600d2cc53e07a58e650)，
   固定 revision `adb5f855f29b023188f11abed0664648948da11f` 的 `nasdaq_screener_04252025.csv`。
   最后发布时间 2025-04-25 20:19:02 UTC，早于研究起点。
   CSV SHA256 `8230a9b5f23eb91eb7b426ed40f08c81fbe9755f16ea41054471ee2369b8232a`。
   归档证明当时已公开，不能认证 Nasdaq 原始响应的完整性。
3. 固定筛选美国、行业非空、名称含 common stock/common shares、纯英文字母代码，
   得 4,002 个名称匹配证券，分布 12 个源行业。**并非逐只认证过的普通股清单**：
   其中 191 个名称带 fund/warrant，均未进入后续 331 只初筛集合。
   不按今天存活状态剔除历史证券。不增加此后 IPO，不声称行业分类此后保持正确。
4. 下载该集合 2024-08-01 至 2025-12-31 的 1,404,386 根 SIP 原始日线。
   [Alpaca 文档](https://docs.alpaca.markets/us/reference/stockbars)中的 `asof`
   用于证券名称映射，**不是复权截止日**，所以请求 raw，按已生效拆股逐日处理。
5. [官方聚合规则](https://docs.alpaca.markets/us/docs/market-data-faq)显示，部分盘前盘后
   交易会增加日线成交量而不更新日线价格。因此日线成交量仅作初筛的成交金额上界；
   最终指标使用正常交易时段五分钟柱重建。日线与五分钟聚合的 OHLC 也可能因成交
   条件、收盘修正或边界而不同，必须记录差异，不能默认为相同。
6. 初筛只应用必要条件，不计算收益，不调整阈值，留下 331 个证券、3,877 个股票日。
   初筛的完整性以日线与正常时段聚合价格一致为前提。未为其余证券重建全部五分钟
   价格时，不能认证“所有真实候选都已进入样本”，这是一项明确的数据覆盖缺口。
7. 公司行动响应合并去重后 14,200 条；[接口文档](https://docs.alpaca.markets/us/reference/corporateactions-1)
   不保证最初可用时点。其用途为机械记账与风险事件审查，不据未来公司行动过滤买入。

因此，这一轮是**历史固定集合的条件性诊断**，不是完整动态全市场、无幸存者偏差
回测。尚无可认证的历史证券主表、每日行业/主题归属和退市结算全覆盖，
不得以该结果宣布策略已通过 Paper 晋级。

## 组合与成交回放

- 所有股票使用同一个现金/权益账户。按原观察名单顺序竞争资金，未成交买单预留
  现金、名义敞口和风险；不能把每个股票单独 $100,000 的收益相加。
- 五分钟柱在结束后一秒才可用，这是模型假设。仅在信号可用之后、有效期内的
  第一根可观察柱开盘尝试成交，且计入成本后的买价不能超过限价。信号当根、
  之前的边界开盘或“盘中碰到限价”均不算入场。开盘代理不能保证真实成交。
- 开盘低于保护价的已模拟买入立即按双边成本退出，不能看见坏开盘后撤销一笔
  本已假设成交的买单。既有止损跳空按更差开盘；同柱目标/止损按原代码止损优先。
- 3R 部分卖出按市场触发代理处理，不能声称在低于卖出限价的价格完成限价成交。
  收盘触发趋势退出，下一交易时段的可观察开盘执行，保留隔夜跳空。
- 拆股同步调整股数、成本与止损。无法核清碎股/并购/权利等持仓事件时停止完整
  收益结论；没有默默删掉退市持仓或按不存在的最后收盘成交。
- 股息在除息日形成应收，支付日才进入可用现金；应收计入权益但不能提前再投资。
- 持仓五分钟柱缺失时停止可认证净值，终值与总回报为 null。候选数据缺口按当时
  已观察信息处理，不因后来某根缺失而事后删掉当天已有入场。
- 期末未平仓按最后可观察收盘估值，单列持仓与已平仓损益，不伪造期末强制卖出。
  回撤是五分钟收盘估值的回撤，不代表已知盘中最大回撤。

## 重现与审计

以下命令需要原有历史行情读取权限；不访问交易申报接口。供应商响应、归档原文、
标准化行情、逐笔回放与数据库留在私有 `work/`，不提交公共仓库。

```bash
python research/martin-luk/capture_universe.py --root work/mlp1-history
python research/martin-luk/capture_daily.py --root work/mlp1-history
python research/martin-luk/capture_actions.py --root work/mlp1-history
python research/martin-luk/prefilter_history.py --root work/mlp1-history
python research/martin-luk/capture_intraday.py --root work/mlp1-history
python research/martin-luk/prepare_intraday.py --root work/mlp1-history
python research/martin-luk/prepare_manifest.py --root work/mlp1-history
python research/martin-luk/run_history.py --manifest work/mlp1-history/normalized/manifest.json --output work/mlp1-history/attempt-1
python research/martin-luk/audit_history.py --report work/mlp1-history/attempt-1
```

行情页逐页落盘并记 SHA256，重启读取前核对缓存。输入会话逐份封存；回放先核对
策略与会话哈希。数据需 `exchange-calendars==4.13.2`；测试不依赖外网。

独立 `audit_history.py` 不导入策略/回放代码，用 Decimal 从买卖、已支付股息、
应收及拆股重算现金、权益、库存、已平仓损益、回撤与买入时序。
其 PASS 只证明这些记账恒等式与所声明时序一致，不能认证股票池或报价成交。
38 项本地测试覆盖以上关键边界；保留原 157 项诊断回归。

结果另存于 `docs/reports/martin-luk-history/`；原始策略、旧 SOXL 协议与旧结果保留。
