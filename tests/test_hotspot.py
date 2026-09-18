"""热点/聚类测试：已知结构还原、退化体检、STKDE 时间窗、网格聚合。"""

from __future__ import annotations

import numpy as np

from policesight.hotspot.grid import grid_counts, hour_weekday_matrix
from policesight.hotspot.kde import kde_grid, kde_peaks
from policesight.hotspot.stcluster import cluster_summary, st_dbscan
from policesight.hotspot.stkde import stkde_cube, stkde_points, stkde_recall


def test_kde_peaks_find_blobs():
    rng = np.random.default_rng(3)
    a = rng.normal(3000, 120, (500, 2))
    b = rng.normal(9000, 150, (400, 2))
    x = np.concatenate([a[:, 0], b[:, 0]])
    y = np.concatenate([a[:, 1], b[:, 1]])
    density, extent = kde_grid(x, y, cell_m=200, bandwidth_m=250)
    peaks = kde_peaks(density, extent)
    assert peaks, "应检出峰点"
    near_a = min((p["x"] - 3000) ** 2 + (p["y"] - 3000) ** 2 for p in peaks) ** 0.5
    near_b = min((p["x"] - 9000) ** 2 + (p["y"] - 9000) ** 2 for p in peaks) ** 0.5
    assert near_a < 400 and near_b < 400, (near_a, near_b)


def test_st_dbscan_recovers_three_clusters():
    rng = np.random.default_rng(11)
    centers = [(2000, 2000, 5), (6000, 3000, 40), (9000, 7000, 90)]
    xs, ys, ts = [], [], []
    for cx, cy, ct in centers:
        xs.append(rng.normal(cx, 60, 60))
        ys.append(rng.normal(cy, 60, 60))
        ts.append(rng.normal(ct, 1.0, 60))
    xs.append(rng.uniform(0, 12000, 200))
    ys.append(rng.uniform(0, 9000, 200))
    ts.append(rng.uniform(0, 180, 200))
    x, y, t = np.concatenate(xs), np.concatenate(ys), np.concatenate(ts)
    labels = st_dbscan(x, y, t, eps_m=200, eps_t=3, min_samples=5)
    summary = cluster_summary(x, y, t, labels)
    assert summary["n_clusters"] == 3
    # 每个真簇的案件应聚在同一标签（前 180 个案件）
    for start in (0, 60, 120):
        chunk = labels[start : start + 60]
        assert len(set(chunk[chunk >= 0])) == 1


def test_st_dbscan_sparse_noise():
    rng = np.random.default_rng(5)
    x = rng.uniform(0, 12000, 300)
    y = rng.uniform(0, 9000, 300)
    t = rng.uniform(0, 180, 300)
    labels = st_dbscan(x, y, t, eps_m=150, eps_t=2, min_samples=6)
    assert (labels < 0).mean() > 0.7


def test_degenerate_detection():
    rng = np.random.default_rng(9)
    x = rng.normal(5000, 200, 400)
    y = rng.normal(5000, 200, 400)
    t = rng.normal(30, 3, 400)
    labels = st_dbscan(x, y, t, eps_m=800, eps_t=30, min_samples=3)
    summary = cluster_summary(x, y, t, labels, eps_m=800)
    assert summary["n_clusters"] == 1
    assert summary["degenerate"] is True
    assert "eps_m" in summary["advice"]


def test_stkde_window_localization_and_recall():
    rng = np.random.default_rng(21)
    # 同一地点两个时间窗的密集团
    xs = np.concatenate([rng.normal(4000, 100, 400), rng.normal(4000, 100, 400)])
    ys = np.concatenate([rng.normal(4000, 100, 400), rng.normal(4000, 100, 400)])
    ts = np.concatenate([rng.integers(5, 12, 400), rng.integers(80, 90, 400)])
    cube, extent, _nw = stkde_cube(xs, ys, ts, days_total=120)
    points = stkde_points(cube, extent, step_days=2)
    assert points
    windows = [p["window_day0"] for p in points]
    assert any(w <= 20 for w in windows)
    assert any(70 <= w <= 95 for w in windows)
    truth = [
        {"id": "T1", "center_m": [4000, 4000], "radius_m": 500, "window": ["2026-03-06", "2026-03-13"]},
        {"id": "T2", "center_m": [4000, 4000], "radius_m": 500, "window": ["2026-05-20", "2026-05-29"]},
    ]
    result = stkde_recall(truth, points, start_date="2026-03-01")
    assert result["recall"] == 1.0
    # 时间窗错开 → 仅空间召回会误判：倒转窗口不应对上
    wrong = [{"id": "T3", "center_m": [4000, 4000], "radius_m": 500, "window": ["2026-04-01", "2026-04-05"]}]
    assert stkde_recall(wrong, points, start_date="2026-03-01")["recall"] == 0.0


def test_hour_weekday_matrix():
    day = np.array([0, 0, 1, 7])
    hour = np.array([9, 9, 23, 0])
    matrix = hour_weekday_matrix(day, hour, start_weekday=0)
    assert matrix.shape == (7, 24)
    assert matrix.sum() == 4
    assert matrix[0, 9] == 2


def test_grid_counts_top():
    x = np.array([100, 120, 9000, 700, 750])
    y = np.array([100, 130, 8000, 700, 760])
    result = grid_counts(x, y)
    assert result["nx"] == 24 and result["ny"] == 18
    assert result["top"][0]["n"] == 2
