"""对照真值系列案的分组评估：纯度 / 召回 / F1 + 杂散组统计。"""

from __future__ import annotations


def evaluate_groups(result: dict, truth: dict, *, min_overlap: int = 2) -> dict:
    """按真值系列案分组评估疑似系列案分组结果。

    - purity（纯度）：真值组最佳匹配估计组的「纯」程度（重叠/估计组规模）；
    - recall（召回）：真值组被覆盖比例（重叠/真值组规模）；
    - 未匹配任何真值组的估计组计为杂散组（诊断项）。
    """
    truth_groups = truth.get("series_groups") or []
    estimates = result.get("groups") or []
    est_sets = [set(g["case_ids"]) for g in estimates]
    matched_estimate_idx: set[int] = set()
    purities: list[float] = []
    recalls: list[float] = []
    details: list[dict] = []

    for truth_group in truth_groups:
        truth_set = set(truth_group["case_ids"])
        best_idx, best_overlap = -1, 0
        for i, estimate in enumerate(est_sets):
            overlap = len(truth_set & estimate)
            if overlap > best_overlap:
                best_idx, best_overlap = i, overlap
        if best_idx < 0 or best_overlap < min_overlap:
            purities.append(0.0)
            recalls.append(0.0)
            details.append({"truth": truth_group["id"], "matched": None, "overlap": 0, "purity": 0.0, "recall": 0.0})
            continue
        matched_estimate_idx.add(best_idx)
        estimate_size = len(est_sets[best_idx])
        purity = best_overlap / estimate_size if estimate_size else 0.0
        recall = best_overlap / len(truth_set) if truth_set else 0.0
        purities.append(purity)
        recalls.append(recall)
        details.append(
            {
                "truth": truth_group["id"],
                "matched": estimates[best_idx]["id"],
                "overlap": best_overlap,
                "purity": round(purity, 4),
                "recall": round(recall, 4),
            }
        )

    mean_purity = sum(purities) / len(purities) if purities else 0.0
    mean_recall = sum(recalls) / len(recalls) if recalls else 0.0
    f1 = 2 * mean_purity * mean_recall / (mean_purity + mean_recall) if (mean_purity + mean_recall) > 0 else 0.0
    spurious = [estimates[i]["id"] for i in range(len(estimates)) if i not in matched_estimate_idx]
    return {
        "truth_groups": len(truth_groups),
        "estimated_groups": len(estimates),
        "purity": round(mean_purity, 4),
        "recall": round(mean_recall, 4),
        "f1": round(f1, 4),
        "spurious_groups": len(spurious),
        "spurious_ids": spurious[:20],
        "details": details,
    }
