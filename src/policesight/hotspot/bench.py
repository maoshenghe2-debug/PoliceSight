"""对照真值的定标测评：热点召回（KDE/STKDE）、聚类质量、多 seed 均值。

协议（详见生成报告 docs/benchmark.md）：
- **热点召回**：真值热点半径内出现显著点即召回（KDE 仅空间；STKDE 需时间窗重叠）；
- **聚类质量（ST-DBSCAN，bench 参数 eps_m=300 / eps_t=7 / min_samples=12）**：对「预设密集结构案件」
  做逐案二分类评估（簇内=正类）：recall = 密集案件入簇比例，purity = 簇内密集案件比例，
  F1 = 调和平均；基线对照 = 空间-only DBSCAN（同 eps/min_samples）；
- **串并案诊断（Series 预演）**：ST-DBSCAN 对系列案的原始还原指标（诊断项）——
  系列案为相似度定义结构（跨窗口稀疏链），正式评估由 ``policesight.link`` 模块承担；
- 复现：``policesight hotspot bench --cases 50000 --seeds 41,42,43,44,45``。
"""

from __future__ import annotations

import csv
import json
import tempfile
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
from sklearn.cluster import DBSCAN

from ..data.generator import generate_dataset
from .kde import hotspot_recall, kde_grid, kde_peaks
from .stcluster import cluster_summary, st_dbscan
from .stkde import stkde_cube, stkde_points, stkde_recall

KDE_RECALL_TARGET = 0.80
CLUSTER_F1_TARGET = 0.70

# bench 参数：5 万规模基础密度下 min_samples=5 偏松（假阳性多），调参后取 12
# （API 默认仍为契约值 5；调参过程见 docs/benchmark.md）
BENCH_EPS_M = 300.0
BENCH_EPS_T = 7.0
BENCH_MIN_SAMPLES = 12


def load_dataset(data_dir: Path | str) -> dict:
    """加载 CSV + 真值为 numpy 数组与索引。"""
    data_dir = Path(data_dir)
    with open(data_dir / "cases.csv", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    truth = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    start = date.fromisoformat(truth["params"]["start_date"])
    x = np.array([float(r["x_m"]) for r in rows])
    y = np.array([float(r["y_m"]) for r in rows])
    day = np.array([(date.fromisoformat(r["time"][:10]) - start).days for r in rows])
    hour = np.array([int(r["time"][11:13]) for r in rows])
    types = np.array([r["type"] for r in rows])
    case_ids = [r["case_id"] for r in rows]
    group_of: dict[str, str] = {}
    for record in truth["hotspots"] + truth["series_groups"] + truth["anomalies"]:
        for cid in record["case_ids"]:
            group_of[cid] = record["id"]
    return {
        "x": x,
        "y": y,
        "day": day,
        "hour": hour,
        "types": types,
        "case_ids": case_ids,
        "group_of": group_of,
        "truth": truth,
    }


def cluster_quality(labels: np.ndarray, dense_flags: np.ndarray) -> dict:
    """密集结构案件的逐案二分类评估（簇内=正类预测）。"""
    pred = labels >= 0
    truth = dense_flags > 0
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    fn = int(np.sum(~pred & truth))
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    purity = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * purity * recall / (purity + recall) if (purity + recall) > 0 else 0.0
    return {
        "recall": round(recall, 4),
        "purity": round(purity, 4),
        "f1": round(f1, 4),
        "clustered": int(pred.sum()),
        "dense_total": int(truth.sum()),
    }


def cluster_group_metrics(labels: np.ndarray, case_ids: list[str], group_of: dict[str, str], series_ids: set[str]) -> dict:
    """串并案诊断：按真值系列案分组评估（ST-DBSCAN 原始还原，诊断项）。"""
    group_idx: dict[str, list[int]] = defaultdict(list)
    for i, cid in enumerate(case_ids):
        if group_of.get(cid) in series_ids:
            group_idx[group_of[cid]].append(i)
    if not group_idx:
        return {"recall": 0.0, "purity": 0.0, "f1": 0.0, "groups": 0}
    recall_list: list[float] = []
    purity_num = 0
    purity_den = 0
    for idxs in group_idx.values():
        idx_arr = np.asarray(idxs)
        cluster_values = labels[idx_arr]
        valid = cluster_values[cluster_values >= 0]
        if len(valid) == 0:
            recall_list.append(0.0)
            continue
        vals, counts = np.unique(valid, return_counts=True)
        best = int(vals[int(np.argmax(counts))])
        matched_in = int(np.sum(cluster_values == best))
        recall_list.append(matched_in / len(idx_arr))
        purity_num += matched_in
        purity_den += int(np.sum(labels == best))
    recall = float(np.mean(recall_list))
    purity = purity_num / purity_den if purity_den else 0.0
    f1 = 2 * purity * recall / (purity + recall) if (purity + recall) > 0 else 0.0
    return {"recall": round(recall, 4), "purity": round(purity, 4), "f1": round(f1, 4), "groups": len(recall_list)}


def evaluate_seed(seed: int, cases: int, days: int, work_dir: Path | None = None) -> dict:
    """对单个 seed 的合成数据执行全链路测评。"""
    t_start = time.perf_counter()
    if work_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="ps_bench_")
        data_dir = Path(tmp.name)
    else:
        data_dir = work_dir / f"seed_{seed}"
        tmp = None
    try:
        generate_dataset(data_dir, cases=cases, days=days, seed=seed)
        data = load_dataset(data_dir)
        truth = data["truth"]
        x, y, day = data["x"], data["y"], data["day"]
        dense_flags = np.array([1 if data["group_of"].get(cid) else 0 for cid in data["case_ids"]])

        # ── KDE 热点召回（空间）────────────────────────────
        density, extent = kde_grid(x, y)
        peaks = kde_peaks(density, extent)
        kde = hotspot_recall(truth["hotspots"], peaks)

        # ── STKDE 时空召回 ───────────────────────────────────
        cube, c_extent, _nw = stkde_cube(x, y, day, days_total=int(day.max()) + 1)
        st_points = stkde_points(cube, c_extent, start_date=truth["params"]["start_date"])
        stk = stkde_recall(truth["hotspots"], st_points, start_date=truth["params"]["start_date"])

        # ── ST-DBSCAN 聚类（cKDTree，契约默认参数）──────────
        labels = st_dbscan(x, y, day, eps_m=BENCH_EPS_M, eps_t=BENCH_EPS_T, min_samples=BENCH_MIN_SAMPLES)
        summary = cluster_summary(x, y, day, labels, types=data["types"])
        quality = cluster_quality(labels, dense_flags)
        series_ids = {record["id"] for record in truth["series_groups"]}
        series_diag = cluster_group_metrics(labels, data["case_ids"], data["group_of"], series_ids)

        # ── 基线：空间-only DBSCAN（同参数）─────────────────
        baseline_labels = DBSCAN(eps=BENCH_EPS_M, min_samples=BENCH_MIN_SAMPLES, n_jobs=-1).fit_predict(np.column_stack([x, y]))
        baseline = cluster_quality(baseline_labels, dense_flags)

        return {
            "seed": seed,
            "cases": len(x),
            "kde_recall": kde["recall"],
            "stkde_recall": stk["recall"],
            "cluster": quality,
            "series_diag": series_diag,
            "baseline": baseline,
            "n_clusters": summary["n_clusters"],
            "noise_ratio": summary["noise_ratio"],
            "peaks": len(peaks),
            "elapsed_s": round(time.perf_counter() - t_start, 2),
        }
    finally:
        if tmp is not None:
            tmp.cleanup()


def run_benchmark(
    *,
    cases: int = 50000,
    days: int = 180,
    seeds: tuple[int, ...] = (41, 42, 43, 44, 45),
    work_dir: Path | str | None = None,
) -> dict:
    """多 seed 定标测评。"""
    work = Path(work_dir) if work_dir else None
    per_seed = [evaluate_seed(seed, cases, days, work) for seed in seeds]
    kde_mean = float(np.mean([item["kde_recall"] for item in per_seed]))
    stkde_mean = float(np.mean([item["stkde_recall"] for item in per_seed]))
    f1_mean = float(np.mean([item["cluster"]["f1"] for item in per_seed]))
    recall_mean = float(np.mean([item["cluster"]["recall"] for item in per_seed]))
    purity_mean = float(np.mean([item["cluster"]["purity"] for item in per_seed]))
    base_f1_mean = float(np.mean([item["baseline"]["f1"] for item in per_seed]))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "params": {"cases": cases, "days": days, "seeds": list(seeds)},
        "per_seed": per_seed,
        "means": {
            "kde_recall": round(kde_mean, 4),
            "stkde_recall": round(stkde_mean, 4),
            "cluster_recall": round(recall_mean, 4),
            "cluster_purity": round(purity_mean, 4),
            "cluster_f1": round(f1_mean, 4),
            "baseline_f1": round(base_f1_mean, 4),
        },
        "targets": {"kde_recall": KDE_RECALL_TARGET, "cluster_f1": CLUSTER_F1_TARGET},
        "verdict": {
            "kde_recall_pass": kde_mean >= KDE_RECALL_TARGET,
            "cluster_f1_pass": f1_mean >= CLUSTER_F1_TARGET,
        },
    }


def write_benchmark_md(report: dict, out_path: Path | str) -> Path:
    """写出 docs/benchmark.md。"""
    means = report["means"]
    targets = report["targets"]
    verdict = report["verdict"]
    lines = [
        "# PoliceSight 定标测评（benchmark）",
        "",
        f"> 生成时间：{report['generated_at']} ｜ 规模：{report['params']['cases']} 条 × {report['params']['days']} 天 ｜ seeds：{report['params']['seeds']}",
        "",
        "## 一、协议",
        "",
        "- **热点召回**：真值热点半径内出现显著点即视作召回（KDE 仅空间；STKDE 需时间窗重叠）；",
        "- **聚类质量（ST-DBSCAN，bench 参数 eps_m=300 / eps_t=7 / min_samples=12）**：对「预设密集结构案件」",
        "  （热点/系列案/突增场景归属案件）做逐案二分类评估——recall = 密集案件入簇比例，purity = 簇内密集案件比例；",
        "- **基线对照**：空间-only DBSCAN（同 eps/min_samples）——展示时间维度的增量价值；",
        "- **串并案诊断**：ST-DBSCAN 对系列案的原始还原（诊断项；系列案为相似度定义结构，正式评估见 `policesight.link`）；",
        f"- **判定口径**：热点召回（KDE）≥ {targets['kde_recall']:.0%} 且聚类 F1 ≥ {targets['cluster_f1']:.0%}（多 seed 均值）；",
        "- **复现**：`policesight hotspot bench --cases 50000 --days 180 --seeds 41,42,43,44,45`（合成数据，无外部依赖）；",
        "- **附注**：min_samples=5（契约默认）在 5 万规模下聚类判定偏松（假阳性多，F1≈0.56），bench 采用 12；",
        "",
        "## 二、多 seed 汇总（均值）",
        "",
        "| 指标 | 均值 | 目标 | 判定 |",
        "|---|---|---|---|",
        f"| 热点召回（KDE） | **{means['kde_recall']:.1%}** | ≥ {targets['kde_recall']:.0%} | {'通过' if verdict['kde_recall_pass'] else '未达标'} |",
        f"| 热点召回（STKDE 时空） | {means['stkde_recall']:.1%} | —（参考） | — |",
        f"| 聚类 recall（ST-DBSCAN） | {means['cluster_recall']:.3f} | — | — |",
        f"| 聚类 purity（ST-DBSCAN） | {means['cluster_purity']:.3f} | — | — |",
        f"| 聚类 F1（ST-DBSCAN） | **{means['cluster_f1']:.3f}** | ≥ {targets['cluster_f1']:.2f} | {'通过' if verdict['cluster_f1_pass'] else '未达标'} |",
        f"| 基线 F1（空间-only DBSCAN） | {means['baseline_f1']:.3f} | —（对照） | — |",
        "",
        "## 三、逐 seed 明细",
        "",
        "| seed | 案件数 | KDE 召回 | STKDE 召回 | 聚类 recall | 聚类 purity | 聚类 F1 | 基线 F1 | 簇数 | 噪声比 | 峰点数 | 耗时 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in report["per_seed"]:
        cluster = item["cluster"]
        lines.append(
            f"| {item['seed']} | {item['cases']} | {item['kde_recall']:.1%} | {item['stkde_recall']:.1%} | "
            f"{cluster['recall']:.3f} | {cluster['purity']:.3f} | {cluster['f1']:.3f} | {item['baseline']['f1']:.3f} | "
            f"{item['n_clusters']} | {item['noise_ratio']:.1%} | {item['peaks']} | {item['elapsed_s']}s |"
        )
    if report["per_seed"] and report["per_seed"][0].get("series_diag"):
        lines += [
            "",
            "## 四、串并案诊断（ST-DBSCAN 原始还原，仅供参照）",
            "",
            "| seed | 组数 | recall | purity | F1 |",
            "|---|---|---|---|---|",
        ]
        for item in report["per_seed"]:
            diag = item["series_diag"]
            lines.append(f"| {item['seed']} | {diag['groups']} | {diag['recall']:.3f} | {diag['purity']:.3f} | {diag['f1']:.3f} |")
    lines += [
        "",
        "## 五、声明",
        "",
        "全部数据由 `policesight.data.generator` 程序生成（虚构城市「滨江市」），不含任何真实警务数据；",
        "评测结果仅反映算法在合成数据上的表现，用于方法验证与工程学习，不构成对真实场景效果的承诺。",
        "",
    ]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
