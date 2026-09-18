"""policesight.link：串并案分析（多特征相似度 → 疑似系列案分组 → 关系图谱）。

- ``similarity``：时空 / 手法 / 文本 多特征加权相似度（权重可配）
- ``group``：候选对生成（cKDTree 时空搜索）+ 阈值连通分量 → 疑似同伙/系列案组（附证据链）
- ``graph``：案件-手法-网格 二部图 + Louvain 社区发现 + JSON/GEXF 导出
- ``evaluate``：对照真值系列案分组的分组纯度 / 召回评估
"""

from .evaluate import evaluate_groups
from .graph import build_group_graph, graph_to_json, louvain_communities
from .group import find_groups
from .similarity import DEFAULT_WEIGHTS, feature_scores, pair_similarity

__all__ = [
    "DEFAULT_WEIGHTS",
    "build_group_graph",
    "evaluate_groups",
    "feature_scores",
    "find_groups",
    "graph_to_json",
    "louvain_communities",
    "pair_similarity",
]
