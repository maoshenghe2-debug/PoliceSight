"""STKDE 时空核密度：时段×空间联合热点（3D 网格 + 3D 高斯核）。

- 案件按 ``step_days`` 分箱到「时间窗 × 空间网格」；3D 高斯核在时间与空间维
  分别平滑（对应时空核 K(d, t) = K_s(d) × K_t(t) 的可分离近似）；
- 输出显著点（3D 局部极大值，含时间窗与分值），并与真值热点（中心+半径+时间窗）
  计算时空联合召回。
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

from ..data.generator import CITY, xlon_to_lonlat


def stkde_cube(
    x: np.ndarray,
    y: np.ndarray,
    day: np.ndarray,
    *,
    cell_m: float = 250.0,
    step_days: int = 2,
    sigma_space_m: float = 350.0,
    sigma_time_steps: float = 2.0,
    bbox: tuple[float, float, float, float] | None = None,
    days_total: int | None = None,
):
    """返回 (density3d[nw, ny, nx], extent, n_windows)。"""
    x0, y0, x1, y1 = bbox or CITY["bbox_m"]
    nx = max(1, round((x1 - x0) / cell_m))
    ny = max(1, round((y1 - y0) / cell_m))
    nw = max(1, int(np.ceil((days_total or (int(day.max()) + 1)) / step_days)))
    w_idx = np.clip((day // step_days).astype(int), 0, nw - 1)
    counts, _ = np.histogramdd(
        (w_idx, y, x),
        bins=(nw, ny, nx),
        range=((0, nw), (y0, y1), (x0, x1)),
    )
    density = gaussian_filter(
        counts,
        sigma=(sigma_time_steps, max(sigma_space_m / cell_m, 1e-6), max(sigma_space_m / cell_m, 1e-6)),
        mode="constant",
    )
    return density, (x0, y0, x1, y1), nw


def stkde_points(
    density: np.ndarray,
    extent: tuple[float, float, float, float],
    *,
    step_days: int = 2,
    start_date: str = "2026-03-01",
    top_n: int = 60,
    sep_windows: int = 1,
    sep_cells: int = 3,
    min_frac_of_max: float = 0.04,
    min_frac_of_mean: float = 2.0,
) -> list[dict]:
    """3D 局部极大值显著点（含中心坐标 / 时间窗 / 分值）。"""
    if density.size == 0 or density.max() <= 0:
        return []
    local_max = maximum_filter(density, size=(sep_windows * 2 + 1, sep_cells * 2 + 1, sep_cells * 2 + 1))
    threshold = max(density.mean() * min_frac_of_mean, density.max() * min_frac_of_max)
    mask = (density == local_max) & (density >= threshold)
    ws, ys, xs = np.nonzero(mask)
    if len(ws) == 0:
        return []
    values = density[ws, ys, xs]
    order = np.argsort(values)[::-1][:top_n]
    x0, y0, x1, y1 = extent
    _nw, ny, nx = density.shape
    cell_x = (x1 - x0) / nx
    cell_y = (y1 - y0) / ny
    start = date.fromisoformat(start_date)
    out = []
    for i in order:
        px = x0 + (xs[i] + 0.5) * cell_x
        py = y0 + (ys[i] + 0.5) * cell_y
        w = int(ws[i])
        d0 = start + timedelta(days=w * step_days)
        d1 = start + timedelta(days=(w + 1) * step_days - 1)
        lon, lat = xlon_to_lonlat(np.array([px]), np.array([py]))
        out.append(
            {
                "x": float(px),
                "y": float(py),
                "lon": float(lon[0]),
                "lat": float(lat[0]),
                "window": [str(d0), str(d1)],
                "window_day0": w * step_days,
                "score": float(values[i]),
            }
        )
    return out


def stkde_recall(
    truth_hotspots: list[dict],
    points: list[dict],
    *,
    start_date: str = "2026-03-01",
    time_margin_days: float = 4.0,
) -> dict:
    """时空联合召回：半径内出现显著点，且其时间窗与真值窗口（含核宽余量）重叠。"""
    start = date.fromisoformat(start_date)
    details = []
    for record in truth_hotspots:
        cx, cy = record["center_m"]
        radius = record["radius_m"]
        w0 = (date.fromisoformat(record["window"][0]) - start).days
        w1 = (date.fromisoformat(record["window"][1]) - start).days
        hit = False
        for point in points:
            spatial = (point["x"] - cx) ** 2 + (point["y"] - cy) ** 2 <= radius * radius
            temporal = (w0 - time_margin_days) <= point["window_day0"] <= (w1 + time_margin_days)
            if spatial and temporal:
                hit = True
                break
        details.append({"id": record["id"], "recalled": bool(hit)})
    recalled = sum(1 for item in details if item["recalled"])
    return {
        "total": len(details),
        "recalled": recalled,
        "recall": round(recalled / len(details), 4) if details else 0.0,
        "details": details,
    }
