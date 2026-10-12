"""Small, evidence-bound summaries of public research; no trading signals."""

from __future__ import annotations

from datetime import date, datetime
import math


SECTORS = {
    "information_technology": "科技", "energy": "能源", "financials": "金融",
    "health_care": "医疗", "industrials": "工业", "materials": "材料",
    "consumer_staples": "必需消费", "consumer_discretionary": "可选消费",
    "communication_services": "通信服务", "utilities": "公用事业",
    "real_estate": "房地产",
}


def _valid_metrics(source: dict, now: datetime) -> list[dict]:
    if source.get("status") not in {"AVAILABLE", "PARTIAL"}:
        return []
    result = []
    for metric in source.get("metrics", []):
        value = metric.get("value")
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            continue
        if not all(metric.get(k) for k in ("metric_id", "subject_id", "unit", "target_period", "reference_id", "locator")):
            continue
        observed = metric.get("observation_date")
        if observed:
            try:
                if date.fromisoformat(observed) > now.date():
                    continue
            except (TypeError, ValueError):
                continue
        result.append(metric)
    return result


def _key(source_id: str, metric: dict) -> tuple:
    return (
        source_id, metric["metric_id"], metric["subject_id"],
        metric["unit"], metric["target_period"], metric.get("baseline_date"),
        metric.get("estimate_status"),
    )


def _number(value: float, signed: bool = False) -> str:
    rounded = round(value, 2)
    return f"{rounded:+.2f}" if signed and rounded != 0 else f"{rounded:.2f}"


def _value(metric: dict) -> str:
    unit = metric["unit"].lower()
    value = metric["value"]
    if unit in {"percent", "percentage", "pct", "%", "percentage_points"}:
        return _number(value, metric["metric_id"] in {"earnings_revision_pct", "price_change_pct", "sector_neri"}) + "%"
    if unit in {"count", "companies"}:
        return str(int(value)) if value == int(value) else _number(value)
    if unit in {"multiple", "ratio", "x", "pe"}:
        return _number(value) + " 倍"
    if unit in {"usd", "dollars", "usd_per_share"}:
        return "$" + _number(value)
    if unit in {"usd_billions", "billion_usd"}:
        return _number(value) + " 十亿美元"
    return _number(value) + " " + unit


def _date_label(metric: dict) -> str:
    return str(metric.get("observation_date") or metric.get("observation_period") or "来源未明确日期")


def _citation(metric: dict) -> str:
    return metric["reference_id"] + " · " + _locator(metric)


def _locator(metric: dict) -> str:
    locator = metric["locator"]
    if isinstance(locator, dict):
        page = locator.get("page")
        section = locator.get("section") or locator.get("figure") or ""
        return (f"第 {page} 页 · " if page is not None else "") + str(section)
    return str(locator)


def _label(metric: dict) -> str:
    subject = SECTORS.get(metric["subject_id"], {"sp500": "标普 500", "sp493": "S&P493", "mega7": "Mega7"}.get(metric["subject_id"], ""))
    names = {
        "earnings_revision_pct": "当季预期盈利金额修订", "price_change_pct": "行业价格变化",
        "eps_up_count": "EPS 上修公司数", "eps_down_count": "EPS 下修公司数",
        "eps_company_count": "公司总数", "earnings_growth_yoy": "预期盈利同比增速",
        "revenue_growth_yoy": "预期营收同比增速", "forward_pe": "前瞻市盈率",
        "sector_neri": "盈利净修订指数 NERI", "forward_eps": "滚动前瞻 EPS",
        "forward_total_earnings": "前瞻总盈利",
        "mega7_market_cap_share": "Mega7 市值占比", "mega7_forward_earnings_share": "Mega7 前瞻盈利占比",
        "mega7_forward_revenues_share": "Mega7 前瞻营收占比",
    }
    metric_id = metric["metric_id"]
    if metric_id.startswith("annual_eps:"):
        name = metric_id.split(":", 1)[1] + " 年 EPS" + ("（最终值）" if metric.get("estimate_status") == "final" else "共识")
    else:
        name = names.get(metric_id, metric.get("label") or metric_id)
    return name if metric_id.startswith("mega7_") else (subject + " · " if subject else "") + name


def _sector_pairs(metrics: list[dict]) -> list[dict]:
    """Only pair a price change with revisions sharing the period and baseline."""
    rows = []
    for subject, label in SECTORS.items():
        revisions = [m for m in metrics if m["subject_id"] == subject and m["metric_id"] == "earnings_revision_pct"]
        if not revisions:
            continue
        revision = revisions[0]
        related = {
            m["metric_id"]: m for m in metrics
            if m["subject_id"] == subject
            and m["target_period"] == revision["target_period"]
            and m.get("baseline_date") == revision.get("baseline_date")
            and m.get("observation_date") == revision.get("observation_date")
        }
        price = related.get("price_change_pct")
        up, down, total = (related.get(k) for k in ("eps_up_count", "eps_down_count", "eps_company_count"))
        breadth = []
        for direction, item in (("上修", up), ("下修", down)):
            if item is not None:
                count = int(item["value"])
                suffix = f" / {int(total['value'])} 家" if total is not None else " 家"
                breadth.append(direction + str(count) + suffix)
        change = revision["value"]
        interpretation = "当季预期盈利上修" if change > 0 else "当季预期盈利下修" if change < 0 else "当季预期盈利持平"
        if price is not None:
            if price["value"] > 0 and change > 0:
                interpretation = "价格上涨伴随当季盈利预期上修"
            elif price["value"] > 0 and change < 0:
                interpretation = "价格上涨与当季盈利预期下修背离；核查后续季度与估值"
            elif price["value"] < 0 and change > 0:
                interpretation = "价格下跌与当季盈利预期上修背离；原因尚未确定"
            elif price["value"] < 0 and change < 0:
                interpretation = "价格与当季盈利预期同时走弱"
        baseline = revision.get("baseline_date") or "来源比较基准"
        period = f"{revision['target_period']} · {baseline} → {_date_label(revision)}"
        rows.append({
            "sector": label, "subject_id": subject,
            "earnings_revision": _value(revision),
            "price_change": _value(price) if price is not None else "未取得",
            "breadth": "；".join(breadth) or "未取得",
            "interpretation": interpretation, "period": period,
            "evidence": _citation(revision),
        })
    return rows


def build_research_trends(sources: list[dict], previous: dict | None, now: datetime) -> dict:
    """Compare actual saved research snapshots, never recomputed prior-day prices."""
    current = {s["source_id"]: _valid_metrics(s, now) for s in sources}
    old_sources = (previous or {}).get("research_sources", [])
    prior = {
        _key(s["source_id"], m): m
        for s in old_sources for m in _valid_metrics(s, now)
    }
    current_index = {_key(sid, m): m for sid, values in current.items() for m in values}
    comparable = {key for key in current_index if key in prior}
    changes = []
    direction_changes = []
    comparable_directions = 0
    for key in sorted(comparable):
        metric, old = current_index[key], prior[key]
        if metric["metric_id"] in {"earnings_revision_pct", "sector_neri"}:
            comparable_directions += 1
            if (metric["value"] > 0) != (old["value"] > 0) or (metric["value"] < 0) != (old["value"] < 0):
                direction_changes.append(_label(metric))
        if metric["value"] == old["value"]:
            continue
        label = _label(metric)
        changes.append(f"{label}（{metric['target_period']}）：{_value(old)} → {_value(metric)}。")
    new_keys = set(current_index) - set(prior)
    unavailable = [s for s in sources if not current.get(s["source_id"])]
    partial = [s for s in sources if s.get("status") != "AVAILABLE"]
    status = "UNAVAILABLE" if not current_index else "PARTIAL" if partial else "AVAILABLE"
    if not current_index:
        change_status, headline = "UNAVAILABLE", "本次研究资料未取得，趋势变化暂无法判断"
    elif not prior:
        change_status, headline = "INITIAL", "首份研究快照：先建立趋势依据，尚无前次比较"
    elif changes:
        change_status = "CHANGED"
        if direction_changes:
            headline = "相对上次报告，盈利修订方向出现变化"
        elif comparable_directions:
            headline = "指标有更新；可比盈利修订方向延续"
        else:
            headline = "相对上次报告，研究指标有变化"
    elif new_keys:
        change_status, headline = "INCOMPARABLE", "本次新增或切换了预测期间，可比指标未发现变化"
    elif unavailable:
        change_status, headline = "UNAVAILABLE", "可比资料未发现数值变化；部分来源失败，完整趋势无法判断"
    else:
        change_status, headline = "UNCHANGED", "所列可比指标未发现新变化"
    if previous and not comparable and prior and current_index:
        change_status, headline = "INCOMPARABLE", "本次资料与上次没有相同口径，暂不能直接比较变化"

    factset = current.get("factset", [])
    yardeni = current.get("yardeni", [])
    sectors = _sector_pairs(factset)
    brief = []
    aligned = [r for r in sectors if r["interpretation"].startswith("价格上涨伴随")]
    diverged = [r for r in sectors if "背离" in r["interpretation"]]
    if aligned:
        brief.append("、".join(r["sector"] for r in aligned) + "的价格上涨伴随当季盈利预期上修；这是同一比较期间的观察。")
    if diverged:
        upward_price = [r for r in diverged if r["interpretation"].startswith("价格上涨")]
        if upward_price:
            brief.append("、".join(r["sector"] for r in upward_price) + "的价格上涨与当季盈利预期下修背离；需要核查后续季度预期与估值。")
        else:
            brief.append("；".join(r["sector"] + "：" + r["interpretation"] for r in diverged[:2]) + "。")
    shares = {m["metric_id"]: m for m in yardeni if m["subject_id"] == "mega7"}
    cap, earnings = shares.get("mega7_market_cap_share"), shares.get("mega7_forward_earnings_share")
    if cap is not None and earnings is not None and cap.get("observation_date") and cap.get("observation_date") == earnings.get("observation_date"):
        relation = "高于" if cap["value"] > earnings["value"] else "低于" if cap["value"] < earnings["value"] else "等于"
        brief.append(f"Mega7 占标普市值 {_value(cap)}、前瞻盈利 {_value(earnings)}（{_date_label(cap)}）；市值份额{relation}盈利份额，估值需结合增长预期理解。")
    if not brief and current_index:
        brief.append("本次取得部分盈利与结构资料；行业价格与盈利尚缺同口径对照，暂不作方向判断。")

    structure = []
    display_metrics = [m for m in factset if m["subject_id"] == "sp500" and m["metric_id"] in {"earnings_growth_yoy", "revenue_growth_yoy", "forward_pe"}]
    display_metrics.extend(yardeni)
    for metric in display_metrics:
        if metric["metric_id"] == "sector_neri":
            continue
        source_id = "factset" if metric in factset else "yardeni"
        old = prior.get(_key(source_id, metric))
        if old is None:
            change = "暂无同口径比较"
        elif old["value"] == metric["value"]:
            change = "未发现数值变化"
        else:
            change = _value(old) + " → " + _value(metric)
        structure.append({"metric": _label(metric) + " · " + metric["target_period"], "value": _value(metric), "change": change, "observed_on": _date_label(metric), "evidence": _citation(metric)})
    for metric in yardeni:
        if metric["metric_id"] != "sector_neri":
            continue
        subject = metric["subject_id"]
        row = next((r for r in sectors if r["subject_id"] == subject), None)
        neri = _value(metric) + "（3 月均值；" + _date_label(metric) + "）"
        if row:
            row["breadth"] += "；NERI " + neri
            row["evidence"] += "；" + _citation(metric)
        elif subject in SECTORS:
            sectors.append({"sector": SECTORS[subject], "subject_id": subject, "earnings_revision": "当季金额修订未取得", "price_change": "同期间价格未取得", "breadth": "NERI " + neri, "interpretation": "净上修多于下修" if metric["value"] > 0 else "净下修多于上修" if metric["value"] < 0 else "净修订为零", "period": "NERI 3 月移动均值 · " + _date_label(metric), "evidence": _citation(metric)})

    source_rows = []
    for source in sources:
        source_id = source["source_id"]
        valid = current[source_id]
        source_rows.append({
            "name": "FactSet Earnings Insight" if source_id == "factset" else "Yardeni Research",
            "status": source.get("status", "SOURCE_ERROR"),
            "publication_date": source.get("publication_date"),
            "retrieved_at": source.get("retrieved_at"),
            "url": source.get("source_url", ""),
            "reference_id": "；".join(sorted({m["reference_id"] for m in valid})),
            "locator": "；".join(sorted({_locator(m) for m in valid})),
            "document_id": source.get("document_id", ""),
            "errors": source.get("errors", []),
        })
    notices = []
    if not changes and prior and comparable:
        notices.append("未发现变化仅指上次保存与本次数值相同；资料未更新不代表市场没有变化。")
    if new_keys and prior:
        notices.append("新增、恢复或不同季度/年度的指标未与旧口径直接相减。")
    if partial:
        notices.append("部分指标尚未取得；本次可用内容不代表完整的行业或成分股覆盖。")
    notices.extend([
        "行业价格变化来自 FactSet 的同期间行业比较，区别于下方 ETF 的 20 日回报。",
        "NERI 是上修数减下修数占预测总数的比例之三月均值，区别于当季预期盈利金额修订。",
        "滚动前瞻 EPS 可受年度权重滚动影响；同一年度 EPS 的变化才用于检查固定年度预期修订。",
        "财报季的同比增长汇总可混合已披露财报与未披露公司的预测，区别于纯预测或全部实现值。",
        "本模块提供盈利预期与价格的观察和解释，不发布买卖信号或已验证的未来概率。",
    ])
    return {
        "status": status, "change_status": change_status, "headline": headline,
        "brief_lines": brief[:3], "changes": changes[:6], "direction_changes": direction_changes,
        "compared_to": (previous or {}).get("generated_at"),
        "sector_rows": sectors, "structure_rows": structure,
        "sources": source_rows, "notices": notices,
        "comparable_metric_count": len(comparable), "changed_metric_count": len(changes),
        "unavailable_source_count": len(unavailable),
    }
