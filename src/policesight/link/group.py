"""疑似系列案分组：cKDTree 候选对 → 向量化相似度 → 阈值连通分量 → 分组（附证据链）。

性能设计（5 万级数据可运行）：
1. 候选对：``cKDTree.query_pairs`` 在 (x/search_m, y/search_m, t/search_days) 单位球内生成；
2. 预剪枝：时空部分分 + 其余特征上限 < 阈值 的候选对直接丢弃（numpy 向量化）；
3. 特征：类型/手法、文本（sklearn 字符二元组稀疏矩阵行余弦）全向量化，分块计算控内存；
4. 连通分量：仅对过阈值边做并查集。
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.spatial import cKDTree
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.preprocessing import normalize

from .similarity import DEFAULT_WEIGHTS, SPACE_SIGMA_M, TIME_SIGMA_DAYS

CHUNK = 120_000


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        root_i, root_j = self.find(i), self.find(j)
        if root_i != root_j:
            self.parent[root_j] = root_i


def _text_matrix(texts: list[str]):
    vectorizer = CountVectorizer(analyzer="char", ngram_range=(2, 2), dtype=np.float32)
    matrix = vectorizer.fit_transform(texts)
    return normalize(matrix)


def _pair_text_cosine(matrix, ia: np.ndarray, ja: np.ndarray) -> np.ndarray:
    """稀疏矩阵成对行余弦（分块控内存）。"""
    out = np.empty(len(ia), dtype=np.float64)
    for start in range(0, len(ia), CHUNK):
        sl = slice(start, min(start + CHUNK, len(ia)))
        prod = matrix[ia[sl]].multiply(matrix[ja[sl]]).sum(axis=1)
        out[sl] = np.asarray(prod).ravel()
    return out


def with_suspect_scores(groups: list[dict], cases: dict) -> list[dict]:
    """为分组追加「团伙可疑度」评分并按分排序（看板 Top-K 与评估共用）。

    可疑度 = 0.35×紧致度 + 0.30×手法多样性 + 0.20×类型纯度 + 0.15×规模适配：
    - 紧致度：exp(-radius/600m)（团伙空间集中；人群团半径大）；
    - 手法多样性：≥2 种手法 1.0，单一手法 0.3（系列案团伙手段多样）；
    - 类型纯度：主类型占比；
    - 规模适配：n≤80 为 1.0，更大按 80/n 折减（超大团多为聚集区而非伙案）。
    """
    x = np.asarray(cases["x"], dtype=float)
    y = np.asarray(cases["y"], dtype=float)
    types = np.asarray(cases["type"])
    index = {cid: i for i, cid in enumerate(cases["case_ids"])}
    out: list[dict] = []
    for item in groups:
        idxs = np.asarray([index[cid] for cid in item["case_ids"] if cid in index])
        if len(idxs) == 0:
            continue
        cx, cy = float(x[idxs].mean()), float(y[idxs].mean())
        radius = float(np.sqrt(np.max((x[idxs] - cx) ** 2 + (y[idxs] - cy) ** 2)))
        tightness = float(np.exp(-radius / 600.0))
        method_diversity = 1.0 if len(item["methods"]) >= 2 else 0.3
        _values, counts = np.unique(types[idxs], return_counts=True)
        type_purity = float(counts.max() / counts.sum())
        n = int(item["n"])
        if 12 <= n <= 80:
            size_fit = 1.0
        elif n < 12:
            size_fit = n / 12.0
        else:
            size_fit = 80.0 / n
        enriched = dict(item)
        enriched.update(
            {
                "radius_m": round(radius, 1),
                "type_purity": round(type_purity, 4),
                "suspect_score": round(
                    0.35 * tightness + 0.30 * method_diversity + 0.20 * type_purity + 0.15 * size_fit, 4
                ),
            }
        )
        out.append(enriched)
    out.sort(key=lambda g: g["suspect_score"], reverse=True)
    return out


def find_groups(
    cases: dict,
    *,
    threshold: float = 0.78,
    search_m: float = 800.0,
    search_days: float = 21.0,
    weights: dict | None = None,
    min_group: int = 5,
    max_pairs_report: int = 5,
) -> dict:
    """疑似系列案分组：返回 {"groups": [...], "pairs": ...}。

    cases 需含：x, y, day, type, method, text, case_ids。
    """
    weights = weights or DEFAULT_WEIGHTS
    x = np.asarray(cases["x"], dtype=float)
    y = np.asarray(cases["y"], dtype=float)
    day = np.asarray(cases["day"], dtype=float)
    types = np.asarray(cases["type"])
    methods = np.asarray(cases["method"])
    case_ids = list(cases["case_ids"])
    n = len(x)
    if n == 0:
        return {"groups": [], "pairs": 0, "kept_pairs": 0, "threshold": threshold}

    coords = np.column_stack([x / search_m, y / search_m, day / search_days])
    tree = cKDTree(coords)
    pair_list = tree.query_pairs(r=1.0, output_type="ndarray")
    if len(pair_list):
        pair_list = pair_list[np.argsort(pair_list[:, 0], kind="stable")]

    weight_sum = sum(weights.values()) or 1.0
    rest_max = max(0.0, weight_sum - weights.get("space", 0.0) - weights.get("time", 0.0))

    if len(pair_list):
        ia_all, ja_all = pair_list[:, 0].astype(int), pair_list[:, 1].astype(int)
        dist_all = np.hypot(x[ia_all] - x[ja_all], y[ia_all] - y[ja_all])
        dt_all = np.abs(day[ia_all] - day[ja_all])
        partial = (
            np.exp(-dist_all / SPACE_SIGMA_M) * weights.get("space", 0.0)
            + np.exp(-dt_all / TIME_SIGMA_DAYS) * weights.get("time", 0.0)
        )
        candidates = pair_list[(partial + rest_max) / weight_sum >= threshold]
    else:
        candidates = np.zeros((0, 2), dtype=int)

    groups: list[dict] = []
    kept_pairs_arr = np.zeros((0, 2), dtype=int)
    kept_sims = np.zeros(0, dtype=float)
    if len(candidates):
        ia, ja = candidates[:, 0].astype(int), candidates[:, 1].astype(int)
        dist = np.hypot(x[ia] - x[ja], y[ia] - y[ja])
        dt = np.abs(day[ia] - day[ja])
        space = np.exp(-dist / SPACE_SIGMA_M)
        time_score = np.exp(-dt / TIME_SIGMA_DAYS)
        method_score = np.where(methods[ia] == methods[ja], 1.0, np.where(types[ia] == types[ja], 0.5, 0.0))
        text_matrix = _text_matrix(list(cases["text"]))
        text_score = _pair_text_cosine(text_matrix, ia, ja)
        sim = (
            space * weights.get("space", 0.0)
            + time_score * weights.get("time", 0.0)
            + method_score * weights.get("method", 0.0)
            + text_score * weights.get("text", 0.0)
        ) / weight_sum
        keep = sim >= threshold
        kept_pairs_arr = candidates[keep]
        kept_sims = sim[keep]

        uf = _UnionFind(n)
        for i, j in kept_pairs_arr:
            uf.union(int(i), int(j))

        members: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            members[uf.find(i)].append(i)

        for _root, idxs in members.items():
            if len(idxs) < min_group:
                continue
            idx_arr = np.asarray(idxs)
            unique_types, type_counts = np.unique(types[idx_arr], return_counts=True)
            unique_methods, method_counts = np.unique(methods[idx_arr], return_counts=True)

            # 证据链：组内相似度最高的若干条边（含特征分解）
            in_group = np.isin(kept_pairs_arr[:, 0], idx_arr) & np.isin(kept_pairs_arr[:, 1], idx_arr)
            top_edges = []
            if in_group.any():
                edge_idx = np.nonzero(in_group)[0]
                edge_idx = edge_idx[np.argsort(-kept_sims[edge_idx])][:max_pairs_report]
                for e in edge_idx:
                    i, j = int(kept_pairs_arr[e, 0]), int(kept_pairs_arr[e, 1])
                    top_edges.append(
                        {
                            "case_a": case_ids[i],
                            "case_b": case_ids[j],
                            "similarity": round(float(kept_sims[e]), 4),
                            "features": {
                                "space": round(float(np.exp(-np.hypot(x[i] - x[j], y[i] - y[j]) / SPACE_SIGMA_M)), 4),
                                "time": round(float(np.exp(-abs(day[i] - day[j]) / TIME_SIGMA_DAYS)), 4),
                                "method": 1.0 if methods[i] == methods[j] else (0.5 if types[i] == types[j] else 0.0),
                                "text": round(float(_pair_text_cosine(text_matrix, np.array([i]), np.array([j]))[0]), 4),
                            },
                        }
                    )

            groups.append(
                {
                    "id": f"LG-{len(groups) + 1:03d}",
                    "n": len(idx_arr),
                    "case_ids": [case_ids[i] for i in idx_arr],
                    "center_m": [round(float(x[idx_arr].mean()), 1), round(float(y[idx_arr].mean()), 1)],
                    "t_span_days": [round(float(day[idx_arr].min()), 1), round(float(day[idx_arr].max()), 1)],
                    "types": [str(t) for t in unique_types[np.argsort(-type_counts)]],
                    "methods": [str(m) for m in unique_methods[np.argsort(-method_counts)]],
                    "evidence": top_edges,
                }
            )
        groups.sort(key=lambda g: g["n"], reverse=True)

    return {
        "groups": groups,
        "pairs": len(pair_list),
        "candidates": len(candidates),
        "kept_pairs": len(kept_pairs_arr),
        "threshold": threshold,
        "weights": weights,
        "search": {"search_m": search_m, "search_days": search_days, "min_group": min_group},
    }
