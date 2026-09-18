"""policesight demo：端到端演示（数据 → 热点 → 聚类 → 串并案 → 预警 → 看板 → 周报）。

全本地计算、无外部依赖；50k 规模全流程约 2-4 分钟（≤15 分钟要求）。
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .alert.engine import alert_acceptance, run_alerts
from .data.generator import generate_dataset
from .data.quality import check_quality
from .hotspot.bench import cluster_quality, load_dataset
from .hotspot.kde import hotspot_recall, kde_grid, kde_peaks
from .hotspot.stcluster import st_dbscan
from .hotspot.stkde import stkde_cube, stkde_points, stkde_recall


def run_demo(
    data_dir: Path | str = "_synth",
    *,
    cases: int = 50000,
    days: int = 180,
    seed: int = 42,
    with_web: bool = True,
    with_report: bool = True,
) -> dict:
    out = Path(data_dir)
    steps: list[dict] = []
    started = time.perf_counter()

    def _step(name: str, detail: str, t0: float) -> None:
        steps.append({"name": name, "detail": detail, "seconds": round(time.perf_counter() - t0, 2)})

    # ① 数据（缺失时生成）
    t0 = time.perf_counter()
    if not (out / "cases.csv").exists():
        summary = generate_dataset(out, cases=cases, days=days, seed=seed)
        _step("① 合成数据引擎", f"生成 {summary['cases']:,} 条（seed={seed}）", t0)
    else:
        quality = check_quality(out / "cases.csv", out / "ground_truth.json")
        _step("① 合成数据引擎", f"复用现有数据（质量检查 {'通过' if quality['passed'] else '未通过'}）", t0)

    data = load_dataset(out)
    truth = data["truth"]
    start = truth["params"]["start_date"]
    days_total = int(data["day"].max()) + 1

    # ② 热点（KDE + STKDE）
    t0 = time.perf_counter()
    density, extent = kde_grid(data["x"], data["y"])
    peaks = kde_peaks(density, extent)
    kde_rec = hotspot_recall(truth["hotspots"], peaks)
    cube, cube_extent, _nw = stkde_cube(data["x"], data["y"], data["day"])
    st_points = stkde_points(cube, cube_extent, start_date=start)
    stkde_rec = stkde_recall(truth["hotspots"], st_points, start_date=start)
    _step(
        "② 时空热点",
        f"KDE 召回 {kde_rec['recall']:.0%}（{kde_rec['recalled']}/{kde_rec['total']}）· "
        f"STKDE 召回 {stkde_rec['recall']:.0%}（{stkde_rec.get('recalled', '—')}/{stkde_rec.get('total', '—')}）",
        t0,
    )

    # ③ 时空聚类
    t0 = time.perf_counter()
    labels = st_dbscan(data["x"], data["y"], data["day"], eps_m=300.0, eps_t=7.0, min_samples=12)  # bench 参数
    group_of = data["group_of"]
    dense_flags = np.asarray([1 if group_of.get(cid) else 0 for cid in data["case_ids"]], dtype=int)
    quality = cluster_quality(labels, dense_flags)
    _step(
        "③ ST-DBSCAN 聚类",
        f"簇内密集案件 recall {quality['recall']:.2f} · purity {quality['purity']:.2f} · F1 {quality['f1']:.2f}",
        t0,
    )

    # ④ 预警
    t0 = time.perf_counter()
    alert_cases = {"x": data["x"], "y": data["y"], "day": data["day"].astype(int), "type": data["types"]}
    alert_result = run_alerts(alert_cases, days_total=days_total, start_date=start)
    acceptance = alert_acceptance(alert_result["alerts"], truth)
    _step(
        "④ 趋势预警",
        f"{acceptance['alerts_total']} 条 · 突增命中 {acceptance['hit']}/{acceptance['anomalies']} · "
        f"无关预警 {acceptance['false_alerts']}",
        t0,
    )

    result: dict = {"steps": steps, "data_dir": str(out)}

    # ⑤ 看板构建（含串并案分组）
    if with_web:
        from .web.build import build_web

        t0 = time.perf_counter()
        web_summary = build_web(out, include_link=True)
        groups_info = web_summary.get("groups") or {}
        _step(
            "⑤ 研判看板构建",
            f"{web_summary['frames']} 回放帧 · {web_summary['clusters']} 簇 · {web_summary['alerts']} 预警 · "
            f"疑组 {groups_info.get('total', '—')}（纯度 {groups_info.get('purity', '—')}）",
            t0,
        )
        result["web"] = web_summary

    # ⑥ 周报
    if with_report:
        from .report.report import build_weekly

        t0 = time.perf_counter()
        last_index = (days_total + 6) // 7 - 1
        weeks_with_alerts = [a["week_index"] for a in alert_result["alerts"]]
        target_index = max(weeks_with_alerts) if weeks_with_alerts else last_index
        weekly = build_weekly(out, weeks_back=max(0, last_index - target_index))
        _step(
            "⑥ 周研判报告",
            f"第 {weekly['week_index'] + 1} 周（最近有预警的 7 日窗口）· {weekly['cases']} 起 · 预警 {weekly['alerts']} 条",
            t0,
        )
        result["weekly"] = weekly

    result["seconds"] = round(time.perf_counter() - started, 2)
    return result
