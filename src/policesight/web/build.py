"""构建看板静态数据（一次构建、离线服务；对应命令 ``policesight web build``）。

产物（data_dir/web/data/）：
- meta.json        城市/时间/规模元信息
- cases.json       案件点（紧凑字段）
- kde.json         全期 KDE 热度网格（250m）
- clusters.json    时空聚类（默认参数）
- frames.json      时间轴回放帧（周序滚动 7 日 · 250m 网格稀疏计数）
- trend.json       周序列 + 类型分解 + 小时×星期矩阵
- alerts.json      预警列表 + 真值验收摘要
- groups.json      疑似系列案组 Top30（含成员点）+ 评估摘要
- basemap.json     合成城市矢量底图
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from ..alert.engine import alert_acceptance, run_alerts
from ..data.generator import CITY, TYPES, district_of
from ..hotspot.bench import load_dataset
from ..hotspot.grid import hour_weekday_matrix
from ..hotspot.kde import kde_grid
from ..hotspot.stcluster import st_dbscan
from ..link.evaluate import evaluate_groups
from ..link.group import find_groups, with_suspect_scores
from .basemap import write_basemap

FRAME_CELL_M = 250.0


def _week_start(start_date: str, week_index: int) -> str:
    return str(date.fromisoformat(start_date) + timedelta(days=week_index * 7))


def build_web(data_dir: Path | str, out_dir: Path | str | None = None, *, include_link: bool = True) -> dict:
    data_dir = Path(data_dir)
    out = Path(out_dir) if out_dir else data_dir / "web"
    payload_dir = out / "data"
    payload_dir.mkdir(parents=True, exist_ok=True)

    data = load_dataset(data_dir)
    truth = data["truth"]
    params = truth["params"]
    days = int(params["days"])
    start_date = str(params["start_date"])
    x = np.asarray(data["x"], dtype=float)
    y = np.asarray(data["y"], dtype=float)
    day = np.asarray(data["day"], dtype=float)
    hour = np.asarray(data["hour"], dtype=int)
    types = np.asarray(data["types"])
    districts = district_of(x, y)
    n = len(x)
    files: dict[str, int] = {}

    def _write(name: str, obj) -> None:
        path = payload_dir / name
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        files[name] = path.stat().st_size

    # ── meta ────────────────────────────────────────────────
    _write(
        "meta.json",
        {
            "city": CITY["name"],
            "bbox_m": list(CITY["bbox_m"]),
            "grid": {"nx": CITY["nx"], "ny": CITY["ny"], "cell_m": CITY["cell_m"]},
            "days": days,
            "start_date": start_date,
            "cases": n,
            "districts": list({str(d) for d in districts}),
            "types": TYPES,
            "truth": {
                "hotspots": len(truth.get("hotspots") or []),
                "series_groups": len(truth.get("series_groups") or []),
                "anomalies": len(truth.get("anomalies") or []),
            },
            "note": "合成数据（虚构城市「滨江市」）· 仅用于技术演示",
        },
    )

    # ── cases（紧凑字段）────────────────────────────────────
    cases_list = [
        {
            "i": str(cid),
            "t": round(float(d), 2),
            "x": round(float(px), 1),
            "y": round(float(py), 1),
            "ty": str(ty),
            "d": str(di),
            "m": str(mth),
        }
        for cid, d, px, py, ty, di, mth in zip(
            data["case_ids"], day, x, y, types, districts, data["method"], strict=True
        )
    ]
    _write("cases.json", cases_list)

    # ── kde ─────────────────────────────────────────────────
    density, extent = kde_grid(x, y, cell_m=250.0, bandwidth_m=430.0)
    _write(
        "kde.json",
        {
            "extent": [float(v) for v in extent],
            "nx": int(density.shape[1]),
            "ny": int(density.shape[0]),
            "values": [round(float(v), 2) for v in density.ravel()],
        },
    )

    # ── clusters ────────────────────────────────────────────
    labels = st_dbscan(x, y, day)
    cluster_items = []
    for cid in sorted({int(v) for v in labels if v >= 0}):
        idxs = np.nonzero(labels == cid)[0]
        cx = float(x[idxs].mean())
        cy = float(y[idxs].mean())
        radius = float(np.sqrt(np.max((x[idxs] - cx) ** 2 + (y[idxs] - cy) ** 2)))
        # 地图展示过滤：过小（<8）或过大（半径 >2km 的「聚集区」由 KDE 层表达）不入图
        if len(idxs) < 8 or radius > 2000:
            continue
        values, counts = np.unique(types[idxs], return_counts=True)
        cluster_items.append(
            {
                "id": cid,
                "n": len(idxs),
                "cx": round(cx, 1),
                "cy": round(cy, 1),
                "r": round(radius, 1),
                "ty": str(values[int(np.argmax(counts))]),
                "d0": round(float(day[idxs].min()), 1),
                "d1": round(float(day[idxs].max()), 1),
            }
        )
    _write("clusters.json", cluster_items)

    # ── frames（周序滚动 7 日 · 250m 网格稀疏计数）───────────
    cell = FRAME_CELL_M
    x0, y0, x1, y1 = CITY["bbox_m"]
    nxc = round((x1 - x0) / cell)
    nyc = round((y1 - y0) / cell)
    ci = np.clip(((x - x0) // cell).astype(int), 0, nxc - 1)
    cj = np.clip(((y - y0) // cell).astype(int), 0, nyc - 1)
    flat = cj * nxc + ci
    n_weeks = int(np.ceil(days / 7))
    frames = []
    for week in range(n_weeks):
        d_end = min(days - 1, week * 7)
        d_start = max(0, d_end - 6)
        mask = (day >= d_start) & (day <= d_end)
        fp = flat[mask]
        cells = []
        if fp.size:
            uniq, counts = np.unique(fp, return_counts=True)
            cells = [[int(a), int(b)] for a, b in zip(uniq, counts, strict=True)]
        frames.append({"w": week, "from": d_start, "to": d_end, "cells": cells})
    _write("frames.json", {"cell_m": cell, "nx": nxc, "ny": nyc, "frames": frames})

    # ── trend ───────────────────────────────────────────────
    weekly_total = [
        int(np.sum((day >= week * 7) & (day < (week + 1) * 7))) for week in range(n_weeks)
    ]
    by_type = {
        str(t): [int(np.sum((day >= week * 7) & (day < (week + 1) * 7) & (types == t))) for week in range(n_weeks)]
        for t in TYPES
    }
    hour_matrix = hour_weekday_matrix(
        day.astype(int), hour, date.fromisoformat(start_date).weekday()
    ).tolist()
    _write(
        "trend.json",
        {
            "weeks": [_week_start(start_date, week) for week in range(n_weeks)],
            "total": weekly_total,
            "by_type": by_type,
            "hour_weekday": hour_matrix,
        },
    )

    # ── alerts ──────────────────────────────────────────────
    alert_cases = {"x": x, "y": y, "day": day.astype(int), "type": types}
    alert_result = run_alerts(alert_cases, days_total=days, start_date=start_date)
    acceptance = alert_acceptance(alert_result["alerts"], truth)
    _write(
        "alerts.json",
        {
            "alerts": alert_result["alerts"],
            "total": len(alert_result["alerts"]),
            "acceptance": {key: acceptance[key] for key in ("anomalies", "hit", "hotspot_aligned", "false_alerts", "alerts_total")},
        },
    )

    # ── groups（疑似系列案组 Top30 + 评估）───────────────────
    if include_link:
        link_cases = {
            "x": x, "y": y, "day": day, "type": types,
            "method": data["method"], "text": data["text"], "case_ids": data["case_ids"],
        }
        result = find_groups(link_cases)
        ranked = with_suspect_scores(result["groups"], link_cases)
        evaluation = evaluate_groups({"groups": ranked}, truth)
        index = {cid: i for i, cid in enumerate(data["case_ids"])}
        top = []
        for group in ranked[:30]:
            idxs = np.asarray([index[c] for c in group["case_ids"] if c in index])
            if idxs.size == 0:
                continue
            cx = float(x[idxs].mean())
            cy = float(y[idxs].mean())
            top.append(
                {
                    "id": group["id"],
                    "n": group["n"],
                    "methods": group["methods"],
                    "suspect_score": group["suspect_score"],
                    "radius_m": group["radius_m"],
                    "cx": round(cx, 1),
                    "cy": round(cy, 1),
                    "t_span_days": group["t_span_days"],
                    "pts": [[round(float(x[i]), 1), round(float(y[i]), 1)] for i in idxs[:200].tolist()],
                }
            )
        _write(
            "groups.json",
            {
                "total_groups": len(ranked),
                "top": top,
                "evaluation": {
                    "purity": evaluation["purity"],
                    "recall": evaluation["recall"],
                    "f1": evaluation["f1"],
                    "spurious_groups": evaluation["spurious_groups"],
                },
            },
        )

    # ── basemap ─────────────────────────────────────────────
    feature_count = write_basemap(payload_dir / "basemap.json")
    files["basemap.json"] = (payload_dir / "basemap.json").stat().st_size

    summary = {
        "out_dir": str(out),
        "cases": n,
        "frames": len(frames),
        "clusters": len(cluster_items),
        "alerts": len(alert_result["alerts"]),
        "basemap_features": feature_count,
        "files": files,
    }
    if include_link:
        summary["groups"] = {
            "total": len(ranked),
            "purity": evaluation["purity"],
            "recall": evaluation["recall"],
        }
    _write("build.json", {"built_at": datetime.now(UTC).isoformat(timespec="seconds"), **summary})
    return summary
