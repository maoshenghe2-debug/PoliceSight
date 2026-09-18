"""ST-DBSCAN：时空双参数聚类（基于 cKDTree 缩放度量，禁止 O(n²)）。

实现：将三维坐标 (x/eps_m, y/eps_m, t/eps_t) 缩放后，时空邻域等价于
单位球邻域，使用 ``cKDTree.query_ball_point(r=1.0)`` 做邻域查询，
整体复杂度 O(n log n)。聚类语义与经典 DBSCAN（Ester 等 1996）一致。
"""

from __future__ import annotations

from collections import deque

import numpy as np
from scipy.spatial import cKDTree


def st_dbscan(
    x: np.ndarray,
    y: np.ndarray,
    t_days: np.ndarray,
    *,
    eps_m: float = 300.0,
    eps_t: float = 7.0,
    min_samples: int = 5,
) -> np.ndarray:
    """返回标签数组：-1=噪声，其余为簇编号（0 起）。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    t = np.asarray(t_days, dtype=float)
    n = len(x)
    if n == 0:
        return np.empty(0, dtype=int)

    coords = np.column_stack([x / float(eps_m), y / float(eps_m), t / float(eps_t)])
    tree = cKDTree(coords)
    cache: dict[int, list[int]] = {}

    def neighbors(i: int) -> list[int]:
        found = cache.get(i)
        if found is None:
            found = tree.query_ball_point(coords[i], 1.0)
            cache[i] = found
        return found

    labels = np.full(n, -1, dtype=int)
    visited = np.zeros(n, dtype=bool)
    cluster_id = 0

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        seed_neighbors = neighbors(i)
        if len(seed_neighbors) < min_samples:
            labels[i] = -1
            continue
        labels[i] = cluster_id
        queue = deque(seed_neighbors)
        while queue:
            j = queue.popleft()
            if not visited[j]:
                visited[j] = True
                j_neighbors = neighbors(j)
                if len(j_neighbors) >= min_samples:
                    queue.extend(k for k in j_neighbors if not visited[k] or labels[k] == -1)
            if labels[j] < 0:
                labels[j] = cluster_id
        cluster_id += 1
    return labels


def cluster_summary(
    x: np.ndarray,
    y: np.ndarray,
    t_days: np.ndarray,
    labels: np.ndarray,
    types: np.ndarray | None = None,
    *,
    eps_m: float = 300.0,
) -> dict:
    """聚类统计：每簇规模/中心/半径/时间跨度/主要类型；含退化体检。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    t = np.asarray(t_days, dtype=float)
    clusters: list[dict] = []
    for cid in sorted(set(int(v) for v in labels if v >= 0)):
        mask = labels == cid
        cx, cy = float(x[mask].mean()), float(y[mask].mean())
        radius = float(np.sqrt(np.max((x[mask] - cx) ** 2 + (y[mask] - cy) ** 2)))
        dominant = ""
        if types is not None and mask.any():
            values, counts = np.unique(types[mask], return_counts=True)
            dominant = str(values[int(np.argmax(counts))])
        clusters.append(
            {
                "id": int(cid),
                "n": int(mask.sum()),
                "center_m": [round(cx, 1), round(cy, 1)],
                "radius_m": round(radius, 1),
                "t_span_days": [round(float(t[mask].min()), 2), round(float(t[mask].max()), 2)],
                "t_span": round(float(t[mask].max() - t[mask].min()), 2),
                "dominant_type": dominant,
            }
        )
    noise = int((labels < 0).sum())
    n = len(labels)
    degenerate = False
    advice = ""
    if len(clusters) <= 1 and n and noise / n < 0.05:
        degenerate = True
        advice = f"单簇且噪声占比 {(noise / n):.1%}（<5%）：建议调小 eps_m（当前 {eps_m:g}m）或增大 min_samples"
    return {
        "clusters": clusters,
        "n_clusters": len(clusters),
        "noise": noise,
        "noise_ratio": round(noise / n, 4) if n else 0.0,
        "degenerate": degenerate,
        "advice": advice,
    }
