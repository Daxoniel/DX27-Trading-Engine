# AA1：原生 RC1 别名准入与形成期身份审查

完成 RC1 采集结果到影子输入准入的适配。VSCO 保留为研究与价格键，VSXY 保留为资产接口实际查询／响应代码，两者用登记映射和原始来源摘要核对。**没有制造旧代码接口响应，没有修改原归档池、模型、预算、六周期评价或此前满仓 FAIL。**

[方案](protocol.json)先登记，[执行哈希](code-seal.json)在演练前提交。所有此前跟踪文件及 156 个核心文件不变。旧 RA1 准入器和 RC1 采集器仍保持封存版本，本阶段是独立的原生 RC1 检查器，不通过改写数据来绕过旧检查。

## 输入及别名如何核对

生产命令先以 RC1 公开摘要核对实际私有映射表，不能自由传入另一只证券或新的资产 ID。随后读取真实 RC1 格式的完整请求与响应字节，重新检查显式 RFC3339 日线 API 时间边界、时间戳、原归档池加 SPY 的请求覆盖、分页、交易日和因子月份。行情与公司行动查询仍只允许原代码，登记的元数据别名不能扩张到价格查询。

重新计算原 SM1 资格、RM1a QR 与独立 Decimal 评分，并与候选排名封存比较；RC1 采集清单摘要、候选封存、实际来源和报告都须一致。八本外部日志重新重放及独立审计，核对原资金、成本档、日历和头摘要，从日志读取已有持仓。

元数据绑定须逐项复算，保留当前代码的原始响应、当前资产 UUID 和对应原始响应摘要／文件路径。只在独立绑定记录里解释 canonical→metadata_lookup，不修改收到的 symbol，不伪造请求 URL，也不移动价格键。绑定范围必须恰好覆盖原基础同行池、四组目标并集与全部持仓；非赢家也不能漏审。

## 形成期身份审查的要求

每个必要证券需要新的审查文件，绑定本轮采集清单、归档池、当前查询代码／资产 ID 和精确的公司行动响应摘要，并留存 HTTPS 来源原文哈希。审查必须明确标为 COMMON_STOCK，说明经济连续性及行动会计处理，记录审查者、完成时间，以及不存在尚未建模权益的结论。来源 URL 和哈希只检查一致性，仍须实际阅读发行人、交易所或监管材料，不能自动证明内容真实。

审查时间不得早于本轮源快照；所有请求、响应、排名及审查都必须在形成期收盘后、第二个后续交易日开盘前，且没有晚于决定时刻的观察。公司行动快照还须覆盖决定的同一 UTC 日。已提前阅读的 RI1 改名公告可以作为资料，但不能代替形成期新快照和新审查。空事件列表也不等于自动确认没有行动。

新增 checklist 工具只生成 **PENDING_NOT_APPROVED** 模板，不填入通过状态、完成时间或审查结论；模板本身不能准入。当前尚未到 2026-10-30 形成期，真实形成期身份批准数仍为零。

## 已完成的验证

[合成演练收据](rehearsal.json)使用 55 个明确虚构的股票，其中一个研究键为 VSCO、元数据查询为 VSXY；价格和文档均非真实市场／发行人资料。沿用原模型与 RC1 采集器，使用假传输器和显式合成映射种子；仅在测试中替换合成归档池的哈希边界，不替换模型、来源字节、身份检查或账户验证。

- 独立核对 55 组评分、55 份合成身份审查与 1 个元数据别名，得到 SHADOW_INPUTS_ADMISSIBLE，但 execution_enabled 仍为 false。
- 68 个原始响应文件、八本外部日志及其头摘要保持不变，没有把准入检查变成交易。
- 清单生成器产生 55 份待审模板，批准数为零。
- 9 项新测试覆盖完整别名链、审查时间／普通股类型、待审／漏审、UUID 改变、请求时间边界、行情代码替换、行动文档、排名与外部日志头变化，以及真实时钟边界。
- 70 项父研究测试通过。CI 在 Ubuntu、Windows 运行共 79 项测试及源码字节封存核验，不用凭据或真实行情。

合成种子不声称通过真实 RI1 发行人证据校验；生产映射锚另在留存的真实 RC1 私有表上核验。演练日期 2026-11-03 仅为合成测试时钟，不是已发生的前向观察。输入审查仍依赖受信任本机时钟，没有外部时间公证、来源真实性证明或自动语义审查。

[真实当前时钟预检](preflight.json)在 2026-10-22 执行，结果为 BLOCKED_FORMATION_NOT_CLOSED，零源请求、零订单。没有新的真实行情、实时排名或身份批准，没有更新八本本地账，也没有查询 Paper 账户。未再次请求因子，因此不对它此后是否已更新作结论。

## 使用和下一边界

```sh
python -m pip install exchange_calendars==4.13.2
python -m unittest discover -s research/residual-alias-admission -p 'test_*.py' -v
python research/residual-alias-admission/rehearse.py --output work/residual-alias-admission/NEW-SYNTHETIC-RUN
python research/residual-alias-admission/checklist.py --capture work/PRIVATE-CAPTURE --output work/NEW-PENDING-CHECKLIST
python research/residual-alias-admission/decide.py --formation 2026-10-30 --capture work/PRIVATE-CAPTURE --registry work/residual-capture/registry-1/registry.json --reviews work/PRIVATE-CAPTURE/reviews.json --output work/NEW-DECISION.json
```

形成期外可省略 capture／registry／reviews 参数，入口在读取它们以前阻塞；没有倒填时钟的命令参数。有效窗口内 reviews.json 需含 capture_manifest_sha256 和 identity_reviews 文件／哈希列表；每份审查及其来源文件直接存于 capture 目录，源响应仍留在 sources 子目录。决定收据的 review_manifest_sha256 基于审查清单的规范 JSON，其他文件摘要按实际字节核对。

准入成功仍只表示本轮影子输入证据齐全，不会下单、修改日志或自动转 Paper。下一边界是把每日行情／公司行动准入与影子账更新串接；RC1 第一轮输入和真实审查仍要等形成期。原始数据、身份资料和完整合成夹具仅存忽略的 work/，公开聚合不含真实逐股持仓。
