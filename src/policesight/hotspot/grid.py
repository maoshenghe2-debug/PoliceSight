"""网格聚合：时段（小时×星期）矩阵与空间网格计数（时空立方体数据）。"""

from __future__ import annotations

import numpy as np

from ..data.generator import CITY, grid_id_of


def hour_weekday_matrix(day_idx: np.ndarray, hour: np.ndarray, start_weekday: int = 0) -> np.ndarray:
    """返回 (7, 24) 计数矩阵：行=星期（0=周一），列=小时。"""
    matrix = np.zeros((7, 24), dtype=int)
    weekday = (np.asarray(day_idx, dtype=int) + start_weekday) % 7
    for wd, hr in zip(weekday.tolist(), np.asarray(hour, dtype=int).tolist(), strict=False):
        matrix[wd, hr] += 1
    return matrix


def grid_counts(x: np.ndarray, y: np.ndarray, *, cell_m: float | None = None, top_n: int = 20) -> dict:
    """空间网格计数 + Top 网格。"""
    cell = cell_m or CITY["cell_m"]
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    cols = np.clip((x // cell).astype(int), 0, CITY["nx"] - 1)
    rows = np.clip((y // cell).astype(int), 0, CITY["ny"] - 1)
    counts = np.zeros((CITY["ny"], CITY["nx"]), dtype=int)
    np.add.at(counts, (rows, cols), 1)
    flat = counts.ravel()
    top_idx = np.argsort(flat)[::-1][:top_n]
    top = []
    for idx in top_idx:
        if flat[idx] <= 0:
            continue
        r, c = int(idx // CITY["nx"]), int(idx % CITY["nx"])
        cx = (c + 0.5) * cell
        cy = (r + 0.5) * cell
        top.append({"grid_id": grid_id_of(cx, cy), "x": cx, "y": cy, "n": int(flat[idx])})
    return {"nx": CITY["nx"], "ny": CITY["ny"], "cell_m": cell, "counts": counts.tolist(), "top": top}
