"""KDE 核密度：网格直方 + 高斯卷积（纯 numpy/scipy，离线可复现）。

带宽语义：``bandwidth_m`` 为高斯核的标准差（米），转换为网格单元数后卷积。
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

from ..data.generator import CITY, xlon_to_lonlat


def kde_grid(
    x: np.ndarray,
    y: np.ndarray,
    *,
    cell_m: float = 200.0,
    bandwidth_m: float = 300.0,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """返回 (density[ny, nx], extent=(x0, y0, x1, y1))。"""
    x0, y0, x1, y1 = bbox or CITY["bbox_m"]
    nx = max(1, round((x1 - x0) / cell_m))
    ny = max(1, round((y1 - y0) / cell_m))
    hist, _, _ = np.histogram2d(y, x, bins=[ny, nx], range=[[y0, y1], [x0, x1]])
    sigma_cells = max(bandwidth_m / cell_m, 1e-6)
    density = gaussian_filter(hist, sigma=sigma_cells, mode="constant")
    return density, (x0, y0, x1, y1)


def kde_peaks(
    density: np.ndarray,
    extent: tuple[float, float, float, float],
    *,
    top_n: int = 200,
    separation_cells: int = 3,
    min_frac_of_max: float = 0.03,
    min_frac_of_mean: float = 1.2,
) -> list[dict]:
    """局部极大值峰点（按密度降序，含经纬度供前端直接使用）。

    阈值 = max(全局均值×min_frac_of_mean, 全局最大×min_frac_of_max)。
    """
    if density.size == 0 or density.max() <= 0:
        return []
    local_max = maximum_filter(density, size=separation_cells * 2 + 1)
    threshold = max(density.mean() * min_frac_of_mean, density.max() * min_frac_of_max)
    mask = (density == local_max) & (density >= threshold)
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return []
    values = density[ys, xs]
    order = np.argsort(values)[::-1][:top_n]
    x0, y0, x1, y1 = extent
    ny, nx = density.shape
    cell_x = (x1 - x0) / nx
    cell_y = (y1 - y0) / ny
    px = x0 + (xs[order] + 0.5) * cell_x
    py = y0 + (ys[order] + 0.5) * cell_y
    lon, lat = xlon_to_lonlat(px, py)
    return [
        {"x": float(px[i]), "y": float(py[i]), "lon": float(lon[i]), "lat": float(lat[i]), "score": float(values[order][i])}
        for i in range(len(order))
    ]


def hotspot_recall(truth_hotspots: list[dict], peaks: list[dict]) -> dict:
    """对照真值计算热点召回率：真值热点半径内出现任一峰点即视为召回。"""
    details = []
    for record in truth_hotspots:
        cx, cy = record["center_m"]
        radius = record["radius_m"]
        hit = any((peak["x"] - cx) ** 2 + (peak["y"] - cy) ** 2 <= radius * radius for peak in peaks)
        details.append({"id": record["id"], "recalled": bool(hit)})
    recalled = sum(1 for item in details if item["recalled"])
    return {
        "total": len(details),
        "recalled": recalled,
        "recall": round(recalled / len(details), 4) if details else 0.0,
        "details": details,
    }
