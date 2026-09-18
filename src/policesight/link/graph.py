"""关系图谱：案件-手法-网格 二部图 + Louvain 社区发现 + JSON/GEXF 导出。"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from ..data.generator import grid_id_of


def build_group_graph(cases: dict, group: dict) -> nx.Graph:
    """为单个疑似系列案组构建 案件-手法-网格 二部图（无向）。"""
    index = {cid: i for i, cid in enumerate(cases["case_ids"])}
    graph = nx.Graph()
    for cid in group["case_ids"]:
        i = index.get(cid)
        if i is None:
            continue
        method_node = f"method:{cases['method'][i]}"
        grid_node = f"grid:{grid_id_of(float(cases['x'][i]), float(cases['y'][i]))}"
        graph.add_node(cid, kind="case", label=cid)
        graph.add_node(method_node, kind="method", label=str(cases["method"][i]))
        graph.add_node(grid_node, kind="grid", label=grid_node.split(":", 1)[1])
        graph.add_edge(cid, method_node)
        graph.add_edge(cid, grid_node)
    return graph


def louvain_communities(graph: nx.Graph, *, seed: int = 42) -> list[list[str]]:
    """Louvain 社区发现（networkx 内置实现）。"""
    if graph.number_of_nodes() == 0:
        return []
    communities = nx.community.louvain_communities(graph, seed=seed)
    return sorted((sorted(str(node) for node in community) for community in communities), key=len, reverse=True)


def graph_to_json(graph: nx.Graph) -> dict:
    """导出为前端可用的 JSON（nodes/edges）。"""
    return {
        "nodes": [
            {"id": str(node), "kind": data.get("kind", ""), "label": data.get("label", str(node))}
            for node, data in graph.nodes(data=True)
        ],
        "edges": [{"source": str(u), "target": str(v)} for u, v in graph.edges()],
    }


def export_gexf(graph: nx.Graph, path: Path | str) -> Path:
    """导出 GEXF（Gephi 可打开）。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(graph, out)
    return out
