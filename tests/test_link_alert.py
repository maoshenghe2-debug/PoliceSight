"""串并案与预警测试：相似度 / 分组还原 / 图谱 / 规则触发 / 趋势。"""

from __future__ import annotations

import numpy as np

from policesight.alert.engine import alert_acceptance, run_alerts
from policesight.alert.trend import daily_counts, ets_forecast, stl_decompose, weekly_from_daily
from policesight.link.evaluate import evaluate_groups
from policesight.link.graph import build_group_graph, graph_to_json, louvain_communities
from policesight.link.group import find_groups, with_suspect_scores
from policesight.link.similarity import char_bigrams, feature_scores, pair_similarity


def test_similarity_ordering():
    a = {"x": 1000, "y": 1000, "day": 10, "type": "盗窃", "method": "扒窃", "bigrams": char_bigrams("手机被扒窃，损失约1000元")}
    near = dict(a, x=1050, y=1000, day=10)
    far = dict(a, x=9000, y=8000, day=170)
    assert pair_similarity(feature_scores(a, near)) > pair_similarity(feature_scores(a, far))
    cross = dict(a, method="技术开锁", bigrams=char_bigrams("房门被技术开锁，现金被盗"))
    same = dict(a)
    assert pair_similarity(feature_scores(a, same)) > pair_similarity(feature_scores(a, cross))


def _planted_cases():
    rng = np.random.default_rng(7)
    xs, ys, ds, ts, ms, texts, ids = [], [], [], [], [], [], []
    # 背景噪声
    for i in range(300):
        xs.append(rng.uniform(0, 12000))
        ys.append(rng.uniform(0, 9000))
        ds.append(rng.uniform(0, 180))
        ts.append("盗窃")
        ms.append("扒窃")
        texts.append(f"某处发生扒窃案件 编号{i}")
        ids.append(f"PS-B{i:04d}")
    # 3 个植入团伙（多手法、紧致、同窗口）
    gangs = [
        (2500, 2500, 30, ["入室盗窃", "技术开锁"]),
        (8500, 6000, 90, ["网络刷单", "冒充客服", "投资理财"]),
        (4000, 7500, 140, ["拦路抢劫", "飞车抢夺"]),
    ]
    truth_groups = []
    for gi, (cx, cy, c0, methods) in enumerate(gangs):
        gids = []
        for j in range(18):
            xs.append(cx + rng.normal(0, 80))
            ys.append(cy + rng.normal(0, 80))
            ds.append(c0 + rng.uniform(0, 10))
            method = methods[j % len(methods)]
            ms.append(method)
            ts.append("盗窃" if "盗窃" in method or method in ("扒窃",) else ("诈骗" if method in methods and gi == 1 else "抢劫"))
            texts.append(f"同日同区域{method}案件 特征一致 第{j}起")
            ids.append(f"PS-G{gi}{j:03d}")
            gids.append(f"PS-G{gi}{j:03d}")
        truth_groups.append({"id": f"G{gi + 1:02d}", "case_ids": gids})
    cases = {
        "x": np.array(xs),
        "y": np.array(ys),
        "day": np.array(ds),
        "type": np.array(ts),
        "method": np.array(ms),
        "text": texts,
        "case_ids": ids,
    }
    return cases, {"series_groups": truth_groups}


def test_find_groups_recovers_planted():
    cases, truth = _planted_cases()
    result = find_groups(cases, threshold=0.78, min_group=5, search_m=800, search_days=30)
    assert result["groups"], "应发现分组"
    evaluation = evaluate_groups(result, truth)
    assert evaluation["purity"] >= 0.8, evaluation
    assert evaluation["recall"] >= 0.6, evaluation


def test_suspect_scores_and_ranking():
    cases, _ = _planted_cases()
    result = find_groups(cases, threshold=0.78, min_group=5)
    ranked = with_suspect_scores(result["groups"], cases)
    assert ranked == sorted(ranked, key=lambda g: g["suspect_score"], reverse=True)
    assert all(0 <= g["suspect_score"] <= 1 for g in ranked)


def test_evaluate_groups_math():
    result = {"groups": [{"id": "LG-001", "case_ids": ["a", "b", "c", "x"]}, {"id": "LG-002", "case_ids": ["d", "e"]}]}
    truth = {"series_groups": [{"id": "G01", "case_ids": ["a", "b", "c"]}, {"id": "G02", "case_ids": ["z"]}]}
    evaluation = evaluate_groups(result, truth)
    assert evaluation["details"][0]["purity"] == 0.75
    assert evaluation["details"][0]["recall"] == 1.0
    assert evaluation["details"][1]["matched"] is None


def test_graph_and_louvain():
    cases, _ = _planted_cases()
    group = {"case_ids": cases["case_ids"][300:318]}
    graph = build_group_graph(cases, group)
    assert graph.number_of_nodes() > 18
    data = graph_to_json(graph)
    assert data["nodes"] and data["edges"]
    communities = louvain_communities(graph)
    assert len(communities) >= 2


def test_trend_utils():
    daily = np.zeros(180)
    daily[10:14] = 3
    assert daily_counts(np.array([10, 11, 12]), 180).sum() == 3
    weekly = weekly_from_daily(daily)
    assert weekly.sum() == daily.sum() and len(weekly) == 26
    stl = stl_decompose(daily)
    assert len(stl["trend"]) == 180
    assert ets_forecast(np.array([1.0, 2.0, 3.0])) is None


def test_alert_engine_fires_and_accepts():
    rng = np.random.default_rng(3)
    n = 900
    districts_x = rng.choice([2000, 4000, 8000, 10000], n)
    districts_y = rng.choice([1500, 4500, 7500], n)
    day = rng.integers(0, 175, n)
    types = np.array(["盗窃"] * n)
    # 注入突增：老城区（x<6000, 3000<=y<6000）第 12 周（day 84-90）翻三倍
    surge_x = rng.uniform(3600, 5900, 400)
    surge_y = rng.uniform(3100, 5900, 400)
    surge_day = rng.integers(84, 91, 400)
    cases = {
        "x": np.concatenate([districts_x, surge_x]),
        "y": np.concatenate([districts_y, surge_y]),
        "day": np.concatenate([day, surge_day]),
        "type": np.concatenate([types, np.array(["盗窃"] * 400)]),
    }
    result = run_alerts(cases, days_total=175, start_date="2026-03-01")
    feb = [a for a in result["alerts"] if a["district"] == "老城区" and a["week"][0] == "2026-05-24"]
    assert feb, "应触发老城区突增预警"
    truth = {
        "anomalies": [
            {"id": "A01", "center_m": [4500, 4500], "window": ["2026-05-25", "2026-05-31"], "factor": 3.0}
        ]
    }
    acceptance = alert_acceptance(result["alerts"], truth)
    assert acceptance["hit"] == 1
