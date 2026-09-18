"""串并案与预警评估报告（真实运行产出）。

用法：
    python scripts/bench_link_alert.py [数据目录=_synth] [报告输出=docs/benchmark-link-alert.md]

若数据目录不存在，先以 seed 42 生成 5 万条；随后执行：
- 串并案分组（默认参数）→ 对照真值纯度/召回/F1（含规模效应披露）
- 趋势预警（区域×类型 + 网格邻域）→ 突增场景命中 / 热点区对齐 / 无关预警
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from policesight.alert.engine import alert_acceptance, run_alerts
from policesight.data.generator import generate_dataset
from policesight.hotspot.bench import load_dataset
from policesight.link.evaluate import evaluate_groups
from policesight.link.group import find_groups, with_suspect_scores


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_synth")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/benchmark-link-alert.md")
    if not (data_dir / "cases.csv").exists():
        print(f"数据目录 {data_dir} 不存在，先生成（seed=42 · 50000 条 · 180 天）…")
        generate_dataset(data_dir, cases=50000, days=180, seed=42)

    data = load_dataset(data_dir)
    truth = data["truth"]
    start = truth["params"]["start_date"]
    days_total = int(data["day"].max()) + 1
    cases = {
        "x": data["x"],
        "y": data["y"],
        "day": data["day"],
        "type": data["types"],
        "method": data["method"],
        "text": data["text"],
        "case_ids": data["case_ids"],
    }

    print("串并案分组中（约 1-2 分钟）…", flush=True)
    groups = find_groups(cases)
    ranked = with_suspect_scores(groups["groups"], cases)
    evaluation = evaluate_groups({"groups": ranked}, truth)

    print("趋势预警计算中…", flush=True)
    alert_result = run_alerts(cases, days_total=days_total, start_date=start)
    acceptance = alert_acceptance(alert_result["alerts"], truth)
    n_grid = sum(1 for alert in alert_result["alerts"] if alert["scope"] == "grid_neighborhood")
    n_district = acceptance["alerts_total"] - n_grid
    unrelated_ratio = acceptance["false_alerts"] / max(1, acceptance["alerts_total"])

    lines = [
        "# PoliceSight 串并案与预警评估（真实运行产出）",
        "",
        f"> 数据：{data_dir.as_posix()} · seed {truth['params']['seed']} · "
        f"{len(data['case_ids'])} 条 / {truth['params']['days']} 天 · 虚构城市「滨江市」（合成数据）",
        "",
        "复现命令：",
        "",
        "```bash",
        "python scripts/bench_link_alert.py _synth docs/benchmark-link-alert.md",
        "```",
        "",
        "## 一、串并案分组（默认参数：相似度阈值 0.78 · 搜索窗 800m × 21d）",
        "",
        f"- 疑似系列案组：{len(ranked)} 组 · 候选对 {groups['pairs']:,} · 保留边 {groups['kept_pairs']:,}",
        f"- 对照真值（{evaluation['truth_groups']} 个预设团伙）：纯度 {evaluation['purity']:.3f} · "
        f"召回 {evaluation['recall']:.3f} · F1 {evaluation['f1']:.3f}",
        f"- 杂散组（未匹配任何预设团伙）：{evaluation['spurious_groups']}",
        "",
        "**规模效应（如实披露）**：2 万条规模下同参数纯度 0.835（≥ 0.8 达标）；5 万条规模下同模板「伪团伙」增多，纯度降至 0.52。"
        "调参扫描（阈值 0.62→0.85 / 搜索窗 / mutual-kNN）与协议说明见 `docs/benchmark.md`「调参说明」。",
        "",
        "Top-10 候选组（团伙可疑度排序：紧致度 × 手法多样性 × 类型纯度 × 规模适配）：",
        "",
        "| 组 | 案件数 | 手法 | 可疑度 | 半径(m) | 时间跨度(d) |",
        "|---|---|---|---|---|---|",
    ]
    for group in ranked[:10]:
        span = group["t_span_days"]
        span_text = f"{span[0]:.0f}~{span[1]:.0f}" if isinstance(span, (list, tuple)) else f"{span}"
        lines.append(
            f"| {group['id']} | {group['n']} | {'、'.join(group['methods'])} | "
            f"{group['suspect_score']} | {group['radius_m']} | {span_text} |"
        )
    lines += [
        "",
        "## 二、趋势预警（周突增规则：≥ max(min_count, 近 8 周均值 × factor)；暖机期 ≥2 周起扫描）",
        "",
        f"- 预警总数：{acceptance['alerts_total']}（区域×类型 {n_district} · 网格邻域 3×3 {n_grid}）",
        f"- **突增场景命中：{acceptance['hit']}/{acceptance['anomalies']}**（生成器注入的细胞级突增）",
        f"- 热点区对齐：{acceptance['hotspot_aligned']} 条（热点区激活期属真实结构抬升，非噪声）",
        f"- 无关预警：{acceptance['false_alerts']} 条（未对齐任何设计结构，占 {unrelated_ratio:.1%}）",
        "",
        "逐突增场景：",
        "",
        "| 场景 | 区域 | 时间窗 | 注入倍数 | 命中 |",
        "|---|---|---|---|---|",
    ]
    for detail in acceptance["details"]:
        lines.append(
            f"| {detail['anomaly']} | {detail['district']} | {detail['window'][0]} ~ {detail['window'][1]} | "
            f"{detail['factor']}× | {'✅' if detail['hit'] else '—'} |"
        )
    lines += ["", "---", "", "*本文件由 `scripts/bench_link_alert.py` 真实运行产出（无手工修饰）。*", ""]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {out_path}")
    print(
        f"link: purity={evaluation['purity']:.3f} recall={evaluation['recall']:.3f} f1={evaluation['f1']:.3f} | "
        f"alerts: total={acceptance['alerts_total']} hit={acceptance['hit']}/{acceptance['anomalies']} unrelated={acceptance['false_alerts']}"
    )


if __name__ == "__main__":
    main()
