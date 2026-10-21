# 高贝塔财报后漂移：文献与数据可行性审查

审查日期：2026-10-21。**决定：暂缓收益回测，PEAD 保留为低优先候选；没有可部署的新策略。**

此前把 PEAD 排在研究首位，主要依据经典文献，低估了现代反证和数据难度。本轮把两方面补齐。结论是研究条件尚未满足，不是已经通过回测证明 PEAD 在所有股票上无效。没有计算策略收益、购买数据、下单或改动现有 Paper 策略。

## 文献究竟支持什么

完整书目信息、版本与实际阅读范围见 [literature.json](literature.json)。没有取得全文的文献明确标记，不声称已逐页复现。

| 文献 | 本轮核对结果 | 对我们研究的约束 |
|---|---|---|
| [Bernard & Thomas，1989](https://www.jstor.org/stable/2491062)、[1990](https://deepblue.lib.umich.edu/handle/2027.42/28288?show=full) | 经典历史依据；本轮只有书目／摘要，未取得可读的完整原文 | 不从记忆中捏造原论文的精确买卖规则 |
| [Livnat & Mendenhall，2006](https://doi.org/10.1111/j.1475-679X.2006.00196.x) | 基于分析师预期与基于历史盈利的意外，并非等价定义 | 缺少预期值时，不能悄悄改用同比 EPS 冒充复现 |
| [Chordia 等，2009](https://rpc.cfainstitute.org/research/financial-analysts-journal/2009/liquidity-and-the-post-earnings-announcement-drift) | 漂移集中于低流动性股票；其研究中成本可消耗多空组合纸面利润的 70%–100% | 高贝塔之外还要检查流动性、价差与冲击成本，不能直接移植论文多空收益 |
| [Martineau，2022](https://cfr.ivo-welch.org/published/papers/martineau2021rest.pdf) | 截至 2019 年的样本，对现代分析师盈利意外漂移提出强反证 | 分时期、微盘／非微盘检查；这不是对 2025 年所有高贝塔子集的定论 |
| [Hirshleifer、Peng & Wang，2025](https://doi.org/10.1093/rfs/hhae025) | 社交连接程度与漂移差异有关；所读工作稿使用同比历史盈利 SUE | 这是应保留的条件性支持证据，不能直接当作“当前分析师超预期＋高贝塔”策略的验证 |
| [Dickerson、Julliard & Mueller，2026](https://wrap.warwick.ac.uk/id/eprint/199281/7/1-s2.0-S0304405X26000668-main.pdf) | 股票／债券联合定价中，PEAD 相关因子仍有作用 | 因子定价、公告收益动量与盈利意外延迟入场是不同问题；综合模型的夏普不属于 PEAD 单独策略 |
| [Subrahmanyam，2026](https://www.sciencepg.com/article/10.11648/j.jim.20261501.11) | 重建公告收益因子时，剔除微盘使所报 t 值从 2.18 降到 1.43 | 检查信号定义和样本构成；不显著并不等于证明效应为零。其批评针对早期版本，本轮没有独立复跑争议双方 |

因此，不能仅凭经典论文认定它现在能赚钱，也不能仅凭一篇反证宣布所有变体失效。**现有文献没有验证我们想要的“高贝塔、高胜率、成本后盈利”的具体组合。** 高贝塔筛选是用户目标带来的新扩展，需要单独检验。

## 数据实际测到了什么

通过现有凭据与公开演示接口做了小规模字段检查，原始响应保留在私有 `work/`。它是接口可用性检查，**不是代表性股票样本，更没有构成合格事件池**。可重算的字段、数量和响应哈希见 [data-audit.json](data-audit.json)。

| 来源 | 实测结果 | 尚不能证明的事项 |
|---|---|---|
| Alpaca 历史新闻 | NVDA 固定历史窗口，2 页全部取完，共 82 条；58 条更新时间晚于创建时间 | 缺少结构化实际 EPS／一致预期字段；没有验证正文历史版本及财报前预期快照。更新时间变化也不证明每条正文都被实质修订 |
| SEC submissions | 能读取申报表单、申报日与受理时间 | 受理时间不是原始财报发布时间；没有分析师一致预期 |
| SEC diluted-EPS concept | 能读取实际 EPS；期末不晚于 2025 年的 120 个期间／单位键中，18 个在不同申报中有不同数值；当前下载包含其后申报 | 差异可能来自拆股、不同披露或修订；不能一律当作错误，也不能直接取今天看到的最后一个值 |
| Alpha Vantage 官方 IBM 演示 | 122 条季度记录，4 条报告日期在 2025 年；存在实际、预期、意外值与盘前／盘后类别 | 未验证预期历史版本、EPS 会计与股份口径、精确时间及整个股票池的访问权限 |
| 已有财报禁交易日文件 | 205 条事件，204 条未确认精确发布时间；实际 EPS 与一致预期字段均为 0 条 | 日期事件不等于盈利意外样本；不能把 205 当作可交易样本数量 |

[Alpaca 新闻文档](https://docs.alpaca.markets/us/reference/news-3)说明排序依据更新时间。[SEC API 文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)提供申报与 XBRL 数据；[Form 8-K](https://www.sec.gov/divisions/corpfin/forms/8-k.htm)的报送时间规则也不能用来反推首次公告时刻。[Alpha Vantage 文档](https://www.alphavantage.co/documentation/#earnings)确认历史盈利接口含预期及意外值，但这些字段存在不自动建立历史可知性。

另外，Alpaca 文档索引中本轮没有找到 earnings 条目；这只是检索结果，不是“所有 Alpaca 产品都没有此功能”的证明。其他供应商已有结构化产品，例如 [Massive/Benzinga](https://massive.com/docs/rest/partners/benzinga/earnings)，但当前没有配置该访问权限，也没有验证其预期历史版本。购买权限本身不能解决版本问题。

## 重启条件与后续决策

[data-contract.json](data-contract.json)记录后续研究必须具备的证据。关键是：

1. 用财报前可知的一致预期，与当时首次可知的实际 EPS 比较；统一 GAAP／调整后口径、币种、财政期和拆股股份基准。
2. 区分首次公告、SEC 受理、供应商更新与研究者下载时间。日级研究可以采用经核验的公告日期与保守可得时间上界，并延后入场，无须强求秒级时刻；不能用未知信息提前交易。
3. 用事件前收益估计市场贝塔，不能用今天的贝塔或把 ADR 当作贝塔。还需历史股票资格、退市、行业、规模、流动性与公司行动数据。
4. 在看收益前固定样本、信号、持有期、成本和主统计量。分别检验分析师盈利意外、历史 SUE、公告收益动量；报告近期与微盘敏感性，不挑赢家。
5. 先分清事件研究与有现金约束的账户回放。处理重叠事件及发行人／日期相关性，报告胜率、盈亏结构、回撤、敞口和少数交易集中度。

本轮没有冻结交易阈值或持有期，没有构建历史时点合格事件池。其数量为“未建立”，不能填写成已验证的 0 或把接口记录总数当作样本规模。

**执行安排：降低 PEAD 的研究优先级；下一方向先审查行业相对动量的现代证据与历史行业数据。** PEAD 的重启需要补齐事件版本证据，并完成现代文献争议的针对性复核。没有充分理由现在为它购买数据或大量跑参数。行业动量同样尚未验证，不承诺高胜率。

## 复算与验证

```sh
python research/earnings-drift/capture_feasibility.py --output work/pead-evidence
python research/earnings-drift/audit_feasibility.py --root work/pead-evidence --old-events docs/research/soxl-earnings/events.json --output docs/research/earnings-drift/data-audit.json
python -m unittest discover -s research/earnings-drift -p 'test_*.py' -v
```

抓取程序仅对固定的历史新闻接口携带 Alpaca 凭据；其余为 SEC 或公开演示请求，重定向被拒绝。分页、请求绑定与响应哈希均检查，API 原始正文不公开。7 项离线测试验证篡改响应、错绑来源、缺页、重复新闻、时区、拒绝访问及“有字段不等于有合格样本”。[validation.json](validation.json)记录核验结果。没有读取预留的 2026 SOXL 价格，原有策略与 156 个核心源码文件保持不变。
