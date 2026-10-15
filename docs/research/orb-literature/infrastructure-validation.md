# 多日研究基础设施：本地验收记录

日期：2026-10-15。全部价格为构造数据，没有采集或计算新的真实行情评价。

- 本地完整离线回归：1,333通过、1项网络测试按默认配置排除、2,574条既有NumPy空切片警告。
  此运行早于最后的登记／日历与可采纳标记收紧；之后对所有相关新旧边界重新运行专项检查。
- 最终专项覆盖：38项既有单日规则、14项旧配对边界，以及64项新多日／统计／登记／文件验收。
  对应测试命令是：

  ```sh
  python -m pytest -q tests/unit/test_intraday_opening_direction_research.py tests/unit/test_intraday_research_multisession.py tests/unit/test_intraday_research_registration.py tests/integration/test_intraday_paired_comparison.py
  ```

- 旧Q2的49个引擎源码集合及hash不变；固定设计JSON的SHA-256仍为
  `6569c2bf1be38b157132ef4508ade1c88cfe104e96dc7939d38348e16fb27d7d`。
- Python编译检查、本地文档链接、staged whitespace及固定设计字节检查通过。
- 两个新测试文件已加入Ubuntu／Windows的独立快速边界步骤；具体CI提交和结果记录在PR。

真实运行登记、公开回执、更新后的阶段暴露审计尚未生成。本地测试中的回执和SIP标签
都是临时构造证据，只验证拒绝条件及API组合，不证明实际数据授权、公开发布或无人查看。
统计方法的收益有效性不因工程验收而成立；未执行A/B研究、调参、paper或实盘下单。
