"""预警引擎：区域×类型周序列 → 规则判定 → 预警列表 + 真值验收（命中/误报）。"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from ..data.generator import DISTRICTS, district_of
from .rules import load_rules
from .trend import daily_counts, weekly_from_daily

LEVEL_ORDER = {"red": 0, "orange": 1, "yellow": 2}


def _scan_series(weekly: np.ndarray, rule: dict, levels: dict, baseline_weeks: int, start: date, *, meta: dict, advice_fields: dict) -> list[dict]:
    """对单一周序列执行一条规则，返回触发的预警列表。"""
    alerts: list[dict] = []
    min_count = float(rule.get("min_count", 5))
    factor_threshold = float(rule.get("factor", 1.8))
    # 暖机放宽：从第 2 周起即可扫描；基线取「近 baseline_weeks 周」中已有的周（≥2 周）
    for w in range(2, len(weekly)):
        base_slice = weekly[max(0, w - baseline_weeks) : w]
        if len(base_slice) < 2:
            continue
        baseline = float(base_slice.mean())
        current = float(weekly[w])
        if current < max(min_count, baseline * factor_threshold):
            continue
        factor = current / baseline if baseline > 0 else 99.0
        level = "yellow"
        if factor >= float(levels.get("red", 2.4)):
            level = "red"
        elif factor >= float(levels.get("orange", 2.0)):
            level = "orange"
        week_start = start + timedelta(days=w * 7)
        alerts.append(
            {
                "rule": rule["id"],
                "week": [str(week_start), str(week_start + timedelta(days=6))],
                "week_index": w,
                "level": level,
                "current": int(current),
                "baseline": round(baseline, 2),
                "factor": round(min(factor, 99.0), 2),
                "advice": str(rule["advice"]).format(
                    current=int(current),
                    baseline=round(baseline, 1),
                    weeks=baseline_weeks,
                    factor=round(min(factor, 99.0), 2),
                    **advice_fields,
                ),
                **meta,
            }
        )
    return alerts


def run_alerts(cases: dict, *, days_total: int, start_date: str, rules_path=None) -> dict:
    """执行全部规则（区域×类型 与 网格邻域 两种粒度）；返回预警列表（级别排序）与统计。"""
    rules_doc = load_rules(rules_path)
    defaults = rules_doc.get("defaults") or {}
    levels = rules_doc.get("levels") or {}
    baseline_weeks = int(defaults.get("baseline_weeks", 8))
    rules = rules_doc.get("rules") or []

    x = np.asarray(cases["x"], dtype=float)
    y = np.asarray(cases["y"], dtype=float)
    districts = district_of(x, y)
    types = np.asarray(cases["type"])
    day_idx = np.asarray(cases["day"], dtype=int)
    start = date.fromisoformat(start_date)
    type_list = sorted(set(types.tolist()))

    # ── 区域×类型 周序列 ────────────────────────────────────
    district_series: dict[tuple[str, str], np.ndarray] = {}
    for district in DISTRICTS:
        d_mask = districts == district
        for case_type in type_list:
            mask = d_mask & (types == case_type)
            district_series[(district, case_type)] = weekly_from_daily(daily_counts(day_idx, days_total, mask))

    # ── 网格邻域（3×3）周序列 ───────────────────────────────
    from ..data.generator import CITY, grid_id_of

    cell = CITY["cell_m"]
    ci = np.clip((x // cell).astype(int), 0, CITY["nx"] - 1)
    cj = np.clip((y // cell).astype(int), 0, CITY["ny"] - 1)
    type_idx = {name: i for i, name in enumerate(type_list)}
    cube = np.zeros((CITY["nx"], CITY["ny"], len(type_list), days_total), dtype=np.float32)
    np.add.at(cube, (ci, cj, np.asarray([type_idx[t] for t in types.tolist()]), np.clip(day_idx, 0, days_total - 1)), 1)

    def neighborhood_weekly(gi: int, gj: int, ti: int) -> np.ndarray:
        acc = np.zeros(days_total, dtype=np.float32)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                x_i, y_j = gi + di, gj + dj
                if 0 <= x_i < CITY["nx"] and 0 <= y_j < CITY["ny"]:
                    acc += cube[x_i, y_j, ti]
        return weekly_from_daily(acc)

    alerts: list[dict] = []
    series_count = 0
    for rule in rules:
        scope = str(rule.get("scope", "district_type"))
        if scope == "district_type":
            for (district, case_type), weekly in district_series.items():
                series_count += 1
                alerts += _scan_series(
                    weekly,
                    rule,
                    levels,
                    baseline_weeks,
                    start,
                    meta={"scope": scope, "district": district, "type": case_type},
                    advice_fields={"district": district, "type": case_type, "grid": ""},
                )
        elif scope == "grid_neighborhood":
            for gi in range(CITY["nx"]):
                for gj in range(CITY["ny"]):
                    for ti, case_type in enumerate(type_list):
                        weekly = neighborhood_weekly(gi, gj, ti)
                        if weekly.sum() < 30:
                            continue
                        series_count += 1
                        cx = (gi + 0.5) * cell
                        cy = (gj + 0.5) * cell
                        alerts += _scan_series(
                            weekly,
                            rule,
                            levels,
                            baseline_weeks,
                            start,
                            meta={
                                "scope": scope,
                                "district": str(district_of(np.asarray([cx]), np.asarray([cy]))[0]),
                                "type": case_type,
                                "grid": grid_id_of(cx, cy),
                                "center_m": [round(cx, 1), round(cy, 1)],
                            },
                            advice_fields={"district": "", "type": case_type, "grid": grid_id_of(cx, cy)},
                        )

    counter = {"AL": 0, "AG": 0}
    for alert in alerts:
        prefix = "AG" if alert["scope"] == "grid_neighborhood" else "AL"
        counter[prefix] += 1
        alert["id"] = f"{prefix}-{counter[prefix]:04d}"
    alerts.sort(key=lambda alert: (LEVEL_ORDER.get(alert["level"], 9), -alert["factor"]))
    return {"alerts": alerts, "series": series_count, "baseline_weeks": baseline_weeks}


def alert_acceptance(alerts: list[dict], truth: dict, *, window_margin_days: int = 3) -> dict:
    """真值验收：突增场景命中 + 结构性信号（热点区抬升）对齐 + 无关预警。

    - anomalies：生成器注入的 4 个突增场景（主目标，同区域+时间窗重叠即命中）；
    - hotspots：热点区激活期同样构成真实「周突增」（非注入目标），对齐的预警计为结构性对齐；
    - false_alerts（无关预警）：既未命中突增场景、也未对齐热点区的预警。
    """
    matched_anomaly: set[int] = set()
    matched_any: set[int] = set()
    details: list[dict] = []

    def overlaps(alert: dict, d0: date, d1: date) -> bool:
        w0 = date.fromisoformat(alert["week"][0])
        w1 = date.fromisoformat(alert["week"][1])
        return not (w1 < d0 - timedelta(days=window_margin_days) or w0 > d1 + timedelta(days=window_margin_days))

    for anomaly in truth.get("anomalies") or []:
        ax, ay = anomaly["center_m"]
        anomaly_district = str(district_of(np.asarray([ax]), np.asarray([ay]))[0])
        a0 = date.fromisoformat(anomaly["window"][0])
        a1 = date.fromisoformat(anomaly["window"][1])
        hit_ids = []
        for j, alert in enumerate(alerts):
            if alert.get("scope") == "grid_neighborhood" and "center_m" in alert:
                gx, gy = alert["center_m"]
                near = ((gx - ax) ** 2 + (gy - ay) ** 2) ** 0.5 <= 800.0
                matched = near and overlaps(alert, a0, a1)
            else:
                matched = alert["district"] == anomaly_district and overlaps(alert, a0, a1)
            if matched:
                hit_ids.append(alert["id"])
                matched_anomaly.add(j)
                matched_any.add(j)
        details.append(
            {
                "anomaly": anomaly["id"],
                "district": anomaly_district,
                "window": anomaly["window"],
                "factor": anomaly["factor"],
                "matched_alerts": hit_ids,
                "hit": bool(hit_ids),
            }
        )

    hotspot_matched: set[int] = set()
    for hotspot in truth.get("hotspots") or []:
        hx, hy = hotspot["center_m"]
        hotspot_district = str(district_of(np.asarray([hx]), np.asarray([hy]))[0])
        h0 = date.fromisoformat(hotspot["window"][0])
        h1 = date.fromisoformat(hotspot["window"][1])
        for j, alert in enumerate(alerts):
            if alert["district"] == hotspot_district and overlaps(alert, h0, h1):
                hotspot_matched.add(j)
                matched_any.add(j)
    hotspot_aligned = len(hotspot_matched)

    unrelated = [alerts[j]["id"] for j in range(len(alerts)) if j not in matched_any]
    hit = sum(1 for item in details if item["hit"])
    return {
        "anomalies": len(details),
        "hit": hit,
        "miss": len(details) - hit,
        "hotspot_aligned": hotspot_aligned,
        "false_alerts": len(unrelated),
        "alerts_total": len(alerts),
        "details": details,
        "fp_ids": unrelated[:30],
    }
