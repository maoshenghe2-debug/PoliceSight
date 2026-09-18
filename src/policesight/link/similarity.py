"""多特征加权相似度：空间 / 时间 / 手法 / 文本（中文字符二元组余弦）。

特征定义（论文/工程实践常见口径）：
- space  ：exp(-d_m / 800) 空间距离衰减；
- time   ：exp(-Δt_days / 10) 时间差衰减；
- method ：同手法 1.0；同类型不同手法 0.5；跨类型 0.0；
- text   ：案情简述的字符二元组余弦相似度（轻量、无分词依赖、对中文稳健）。
"""

from __future__ import annotations

import math
from collections import Counter

DEFAULT_WEIGHTS = {"space": 0.40, "time": 0.20, "method": 0.25, "text": 0.15}

SPACE_SIGMA_M = 800.0
TIME_SIGMA_DAYS = 10.0


def char_bigrams(text: str) -> Counter:
    """中文字符二元组计数（去空白）。"""
    clean = "".join(ch for ch in str(text) if not ch.isspace())
    return Counter(clean[i : i + 2] for i in range(max(0, len(clean) - 1)))


def bigram_cosine(a: Counter, b: Counter) -> float:
    """二元组余弦相似度（对空文本返回 0）。"""
    if not a or not b:
        return 0.0
    inter = sum((a & b).values())
    if inter == 0:
        return 0.0
    denom = math.sqrt(sum(a.values()) * sum(b.values()))
    return float(inter / denom) if denom else 0.0


def feature_scores(case_a: dict, case_b: dict) -> dict:
    """逐特征分数（0-1）。case 字典字段：x, y, day, type, method, bigrams。"""
    dx = float(case_a["x"]) - float(case_b["x"])
    dy = float(case_a["y"]) - float(case_b["y"])
    dist = math.hypot(dx, dy)
    dt = abs(float(case_a["day"]) - float(case_b["day"]))
    space = math.exp(-dist / SPACE_SIGMA_M)
    time = math.exp(-dt / TIME_SIGMA_DAYS)
    if case_a["method"] == case_b["method"]:
        method = 1.0
    elif case_a["type"] == case_b["type"]:
        method = 0.5
    else:
        method = 0.0
    text = bigram_cosine(case_a["bigrams"], case_b["bigrams"])
    return {"space": round(space, 4), "time": round(time, 4), "method": method, "text": round(text, 4)}


def pair_similarity(scores: dict, weights: dict | None = None) -> float:
    """加权总分（0-1）。"""
    weights = weights or DEFAULT_WEIGHTS
    total = sum(scores[key] * weights.get(key, 0.0) for key in ("space", "time", "method", "text"))
    weight_sum = sum(weights.get(key, 0.0) for key in ("space", "time", "method", "text")) or 1.0
    return round(float(total / weight_sum), 4)
