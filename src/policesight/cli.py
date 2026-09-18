"""PoliceSight CLI 入口（policesight doctor | data | …）。"""

from __future__ import annotations

import json as jsonlib
import sys

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .errors import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(
    name="policesight",
    help="PoliceSight · 警情时空智能研判平台（合成数据 / 热点 / 聚类 / 串并案 / 预警 / 看板）",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def _version_callback(
    version: bool = typer.Option(False, "--version", help="显示版本并退出", is_eager=True),
) -> None:
    if version:
        console.print(f"policesight v{__version__}")
        raise typer.Exit(code=EXIT_OK)


@app.command()
def doctor(
    data_dir: str = typer.Option("_synth", "--data-dir", help="合成数据目录"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """环境自检（9 项）。"""
    from .doctor import run_doctor

    report = run_doctor(data_dir)
    if as_json:
        console.print_json(jsonlib.dumps(report, ensure_ascii=False))
        raise typer.Exit(code=report["exit_code"])

    table = Table(title=f"PoliceSight 环境自检 · v{report['version']}")
    table.add_column("检查项", no_wrap=True)
    table.add_column("状态")
    table.add_column("详情")
    table.add_column("建议", style="dim")
    color = {"就绪": "green", "缺失": "yellow", "不满足": "red"}
    for check in report["checks"]:
        table.add_row(check["name"], f"[{color[check['status']]}]{check['status']}[/]", check["detail"], check["fix"])
    console.print(table)
    summary = report["summary"]
    console.print(f"就绪 {summary['ok']} · 缺失 {summary['warn']} · 不满足 {summary['fail']} → 退出码 {report['exit_code']}")
    raise typer.Exit(code=report["exit_code"])


data_app = typer.Typer(help="合成数据引擎（带真值）与质量检查", no_args_is_help=True)
app.add_typer(data_app, name="data")


@data_app.command("generate")
def data_generate(
    cases: int = typer.Option(50000, "--cases", help="案件总数（1000-500000）"),
    days: int = typer.Option(180, "--days", help="时间跨度（天数，30-730）"),
    seed: int = typer.Option(42, "--seed", help="随机种子（可复现）"),
    start: str = typer.Option("2026-03-01", "--start", help="起始日期 YYYY-MM-DD"),
    out: str = typer.Option("_synth", "--out", help="输出目录"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON 摘要"),
) -> None:
    """生成合成警情数据 + 真值（热点 / 系列案 / 突增）。"""
    from .data.generator import generate_dataset

    try:
        summary = generate_dataset(out, cases=cases, days=days, seed=seed, start_date=start)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=EXIT_USAGE) from exc

    if as_json:
        console.print_json(jsonlib.dumps(summary, ensure_ascii=False))
        return

    table = Table(title=f"合成数据生成完成 · {summary['cases']} 条 · {summary['elapsed_s']}s")
    table.add_column("项", no_wrap=True)
    table.add_column("值")
    table.add_row("规模 / 跨度 / 种子", f"{summary['cases']} 条 · {summary['days']} 天 · seed={summary['seed']}")
    table.add_row("真值", f"热点 {summary['hotspots']} · 系列案 {summary['series_groups']} · 突增 {summary['anomalies']}")
    table.add_row("类型分布", " · ".join(f"{k} {v}" for k, v in summary["per_type"].items()))
    table.add_row("产物", f"{summary['csv']} + {summary['ground_truth']}")
    console.print(table)
    console.print("[dim]定位声明：全部为程序生成的虚构数据；结论仅用于区域级资源配置辅助，不用于个人画像与个人预测。[/dim]")


@data_app.command("quality")
def data_quality(
    data_dir: str = typer.Option("_synth", "--data-dir", help="合成数据目录"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """数据质量检查（缺失 / 重复 / 时间 / 坐标）。"""
    from pathlib import Path

    from .data.quality import check_quality, format_report

    csv_path = Path(data_dir) / "cases.csv"
    if not csv_path.exists():
        console.print(f"[red]PS-E001：未找到 {csv_path}，请先运行 policesight data generate[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    report = check_quality(csv_path, Path(data_dir) / "ground_truth.json")
    if as_json:
        console.print_json(jsonlib.dumps(report, ensure_ascii=False))
    else:
        console.print(format_report(report))
        if not report["passed"]:
            raise typer.Exit(code=EXIT_RUNTIME)


hotspot_app = typer.Typer(help="时空热点分析（KDE / STKDE / ST-DBSCAN / 定标测评）", no_args_is_help=True)
app.add_typer(hotspot_app, name="hotspot")


@hotspot_app.command("kde")
def hotspot_kde(
    data_dir: str = typer.Option("_synth", "--data-dir", help="合成数据目录"),
    cell: float = typer.Option(200.0, "--cell", help="网格边长（米）"),
    bandwidth: float = typer.Option(300.0, "--bandwidth", help="高斯核带宽（米）"),
    top_n: int = typer.Option(15, "--top-n", help="显示峰点数"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """KDE 核密度：热力图网格 + 峰点。"""
    from pathlib import Path

    from .hotspot.bench import load_dataset
    from .hotspot.kde import kde_grid, kde_peaks

    if not (Path(data_dir) / "cases.csv").exists():
        console.print(f"[red]PS-E005：未找到 {data_dir}/cases.csv，请先运行 policesight data generate[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    data = load_dataset(data_dir)
    density, extent = kde_grid(data["x"], data["y"], cell_m=cell, bandwidth_m=bandwidth)
    peaks = kde_peaks(density, extent)
    if as_json:
        console.print_json(jsonlib.dumps({"grid": list(density.shape), "extent": extent, "peaks": peaks[:top_n]}, ensure_ascii=False))
        return
    table = Table(title=f"KDE 峰点 Top{min(top_n, len(peaks))} · 网格 {density.shape[1]}×{density.shape[0]}（{cell:g}m）")
    table.add_column("#", no_wrap=True)
    table.add_column("x_m", justify="right")
    table.add_column("y_m", justify="right")
    table.add_column("分值", justify="right")
    for i, peak in enumerate(peaks[:top_n], 1):
        table.add_row(str(i), f"{peak['x']:.0f}", f"{peak['y']:.0f}", f"{peak['score']:.1f}")
    console.print(table)


@hotspot_app.command("stkde")
def hotspot_stkde(
    data_dir: str = typer.Option("_synth", "--data-dir"),
    step: int = typer.Option(2, "--step", help="时间窗步长（天）"),
    cell: float = typer.Option(250.0, "--cell", help="空间网格边长（米）"),
    top_n: int = typer.Option(10, "--top-n"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """STKDE 时空热点：显著点（含时间窗）。"""
    from pathlib import Path

    from .hotspot.bench import load_dataset
    from .hotspot.stkde import stkde_cube, stkde_points

    if not (Path(data_dir) / "cases.csv").exists():
        console.print(f"[red]PS-E005：未找到 {data_dir}/cases.csv[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    data = load_dataset(data_dir)
    cube, extent, _nw = stkde_cube(data["x"], data["y"], data["day"], cell_m=cell, step_days=step, days_total=int(data["day"].max()) + 1)
    points = stkde_points(cube, extent, step_days=step, start_date=data["truth"]["params"]["start_date"])
    if as_json:
        console.print_json(jsonlib.dumps(points[:top_n], ensure_ascii=False))
        return
    table = Table(title=f"STKDE 显著点 Top{min(top_n, len(points))} · 立方体 {cube.shape[0]}×{cube.shape[1]}×{cube.shape[2]}")
    table.add_column("#", no_wrap=True)
    table.add_column("时间窗")
    table.add_column("x_m", justify="right")
    table.add_column("y_m", justify="right")
    table.add_column("分值", justify="right")
    for i, point in enumerate(points[:top_n], 1):
        table.add_row(str(i), f"{point['window'][0]} 起", f"{point['x']:.0f}", f"{point['y']:.0f}", f"{point['score']:.1f}")
    console.print(table)


@hotspot_app.command("cluster")
def hotspot_cluster(
    data_dir: str = typer.Option("_synth", "--data-dir"),
    eps_m: float = typer.Option(300.0, "--eps-m", help="空间邻域（米）"),
    eps_t: float = typer.Option(7.0, "--eps-t", help="时间邻域（天）"),
    min_samples: int = typer.Option(5, "--min-samples", help="最小簇规模"),
    out: str = typer.Option("", "--out", help="聚类结果导出 JSON 路径（可选）"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """ST-DBSCAN 时空聚类（cKDTree；含参数体检）。"""
    from pathlib import Path

    from .hotspot.bench import load_dataset
    from .hotspot.stcluster import cluster_summary, st_dbscan

    if not (Path(data_dir) / "cases.csv").exists():
        console.print(f"[red]PS-E005：未找到 {data_dir}/cases.csv[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    data = load_dataset(data_dir)
    labels = st_dbscan(data["x"], data["y"], data["day"], eps_m=eps_m, eps_t=eps_t, min_samples=min_samples)
    summary = cluster_summary(data["x"], data["y"], data["day"], labels, types=data["types"], eps_m=eps_m)
    summary["params"] = {"eps_m": eps_m, "eps_t": eps_t, "min_samples": min_samples}
    if out:
        Path(out).write_text(jsonlib.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if as_json:
        console.print_json(jsonlib.dumps(summary, ensure_ascii=False))
        return
    clusters = sorted(summary["clusters"], key=lambda c: c["n"], reverse=True)[:10]
    table = Table(title=f"ST-DBSCAN 簇 Top{len(clusters)}（共 {summary['n_clusters']} 簇 · 噪声比 {summary['noise_ratio']:.1%}）")
    table.add_column("#", no_wrap=True)
    table.add_column("规模", justify="right")
    table.add_column("中心 x_m", justify="right")
    table.add_column("中心 y_m", justify="right")
    table.add_column("半径 m", justify="right")
    table.add_column("时间跨度 d", justify="right")
    table.add_column("主要类型")
    for cluster in clusters:
        table.add_row(
            str(cluster["id"]),
            str(cluster["n"]),
            f"{cluster['center_m'][0]:.0f}",
            f"{cluster['center_m'][1]:.0f}",
            f"{cluster['radius_m']:.0f}",
            f"{cluster['t_span']:.1f}",
            cluster["dominant_type"],
        )
    console.print(table)
    if summary["degenerate"]:
        console.print(f"[yellow]PS-E006 参数体检：{summary['advice']}[/yellow]")


@hotspot_app.command("bench")
def hotspot_bench(
    cases: int = typer.Option(50000, "--cases", help="每个 seed 的案件数"),
    days: int = typer.Option(180, "--days"),
    seeds: str = typer.Option("41,42,43,44,45", "--seeds", help="逗号分隔的 seed 列表"),
    out: str = typer.Option("docs/benchmark.md", "--out", help="报告输出路径"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """定标测评：对照真值的多 seed 指标（热点召回 / 聚类还原）。"""
    from .hotspot.bench import run_benchmark, write_benchmark_md

    seed_list = tuple(int(item) for item in seeds.split(","))
    console.print(f"开始定标测评：{cases} 条 × {days} 天 × {len(seed_list)} seeds（合成数据，无外部依赖）…")
    report = run_benchmark(cases=cases, days=days, seeds=seed_list)
    path = write_benchmark_md(report, out)
    if as_json:
        console.print_json(jsonlib.dumps(report["means"] | {"verdict": report["verdict"]}, ensure_ascii=False))
    else:
        means = report["means"]
        verdict = report["verdict"]
        table = Table(title="定标测评结果（多 seed 均值）")
        table.add_column("指标", no_wrap=True)
        table.add_column("均值", justify="right")
        table.add_column("判定")
        table.add_row("热点召回（KDE）", f"{means['kde_recall']:.1%}", "通过" if verdict["kde_recall_pass"] else "未达标")
        table.add_row("热点召回（STKDE）", f"{means['stkde_recall']:.1%}", "参考")
        table.add_row("聚类 F1（ST-DBSCAN）", f"{means['cluster_f1']:.3f}", "通过" if verdict["cluster_f1_pass"] else "未达标")
        table.add_row("基线 F1（空间-only）", f"{means['baseline_f1']:.3f}", "对照")
        console.print(table)
    console.print(f"报告：[bold]{path}[/bold]")


link_app = typer.Typer(help="串并案分析（多特征相似度 / 疑似系列案组 / 关系图谱）", no_args_is_help=True)
app.add_typer(link_app, name="link")


@link_app.command("run")
def link_run(
    data_dir: str = typer.Option("_synth", "--data-dir"),
    threshold: float = typer.Option(0.78, "--threshold", help="相似度阈值（0-1）"),
    min_group: int = typer.Option(5, "--min-group", min=3, max=50, help="最小分组规模"),
    search_m: float = typer.Option(800.0, "--search-m", help="候选对空间搜索半径（米）"),
    search_days: float = typer.Option(21.0, "--search-days", help="候选对时间搜索窗（天）"),
    top_k: int = typer.Option(10, "--top-k", help="展示 Top-K 候选组"),
    out: str = typer.Option("", "--out", help="完整结果导出 JSON 路径（可选）"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """运行串并案分析：疑似系列案组 + 可疑度排名 + 真值评估。"""
    from pathlib import Path

    from .hotspot.bench import load_dataset
    from .link.evaluate import evaluate_groups
    from .link.group import find_groups, with_suspect_scores

    if not (Path(data_dir) / "cases.csv").exists():
        console.print(f"[red]PS-E005：未找到 {data_dir}/cases.csv[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    data = load_dataset(data_dir)
    cases = {
        "x": data["x"],
        "y": data["y"],
        "day": data["day"],
        "type": data["types"],
        "method": data["method"],
        "text": data["text"],
        "case_ids": data["case_ids"],
    }
    console.print(f"串并案分析中（{len(data['x'])} 案件 · 阈值 {threshold} · 搜索 {search_m:g}m/{search_days:g}d）…")
    result = find_groups(cases, threshold=threshold, min_group=min_group, search_m=search_m, search_days=search_days)
    ranked = with_suspect_scores(result["groups"], cases)
    evaluation = evaluate_groups({"groups": ranked}, data["truth"])
    summary = {
        "groups": len(ranked),
        "pairs": result["pairs"],
        "kept_pairs": result["kept_pairs"],
        "threshold": threshold,
        "evaluation": {key: evaluation[key] for key in ("truth_groups", "purity", "recall", "f1", "spurious_groups")},
    }
    if out:
        Path(out).write_text(
            jsonlib.dumps({"summary": summary, "top": ranked[:200]}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    if as_json:
        console.print_json(jsonlib.dumps(summary, ensure_ascii=False))
        return
    table = Table(title=f"疑似系列案组 Top{min(top_k, len(ranked))}（共 {len(ranked)} 组 · 过阈对 {result['kept_pairs']}）")
    table.add_column("组", no_wrap=True)
    table.add_column("可疑度", justify="right")
    table.add_column("规模", justify="right")
    table.add_column("半径 m", justify="right")
    table.add_column("手法", justify="right")
    table.add_column("主要手法")
    for group in ranked[:top_k]:
        table.add_row(
            group["id"],
            f"{group['suspect_score']:.3f}",
            str(group["n"]),
            f"{group['radius_m']:.0f}",
            str(len(group["methods"])),
            " / ".join(group["methods"][:3]),
        )
    console.print(table)
    console.print(
        f"评估（对照真值 {evaluation['truth_groups']} 个预设系列案）：纯度 {evaluation['purity']:.2f} · "
        f"召回 {evaluation['recall']:.2f} · F1 {evaluation['f1']:.2f} · 杂散组 {evaluation['spurious_groups']}"
    )
    if out:
        console.print(f"完整结果：[bold]{out}[/bold]")


@link_app.command("graph")
def link_graph(
    data_dir: str = typer.Option("_synth", "--data-dir"),
    group: str = typer.Option("", "--group", help="组 id（默认取可疑度排名第一组）"),
    out: str = typer.Option("", "--out", help="图谱 JSON 导出路径（可选）"),
    gexf: str = typer.Option("", "--gexf", help="GEXF 导出路径（Gephi 可打开，可选）"),
) -> None:
    """为指定疑似系列案组构建关系图谱（案件-手法-网格 二部图 + Louvain 社区）。"""
    from pathlib import Path

    from .hotspot.bench import load_dataset
    from .link.graph import build_group_graph, export_gexf, graph_to_json, louvain_communities
    from .link.group import find_groups, with_suspect_scores

    if not (Path(data_dir) / "cases.csv").exists():
        console.print(f"[red]PS-E005：未找到 {data_dir}/cases.csv[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    data = load_dataset(data_dir)
    cases = {
        "x": data["x"],
        "y": data["y"],
        "day": data["day"],
        "type": data["types"],
        "method": data["method"],
        "text": data["text"],
        "case_ids": data["case_ids"],
    }
    result = find_groups(cases)
    ranked = with_suspect_scores(result["groups"], cases)
    if not ranked:
        console.print("[yellow]未发现分组（可尝试降低 --threshold）[/yellow]")
        raise typer.Exit(code=EXIT_OK)
    target = next((item for item in ranked if item["id"] == group), None) if group else ranked[0]
    if target is None:
        console.print(f"[red]未找到组 {group}[/red]")
        raise typer.Exit(code=EXIT_USAGE)
    graph = build_group_graph(cases, target)
    communities = louvain_communities(graph)
    console.print(
        f"组 {target['id']}：{target['n']} 案件 · 节点 {graph.number_of_nodes()} · 边 {graph.number_of_edges()} · "
        f"Louvain 社区 {len(communities)} 个（最大 {len(communities[0]) if communities else 0} 节点）"
    )
    if out:
        Path(out).write_text(jsonlib.dumps(graph_to_json(graph), ensure_ascii=False), encoding="utf-8")
        console.print(f"图谱 JSON：[bold]{out}[/bold]")
    if gexf:
        path = export_gexf(graph, gexf)
        console.print(f"GEXF：[bold]{path}[/bold]")


alert_app = typer.Typer(help="趋势与预警（规则引擎 / 真值验收）", no_args_is_help=True)
app.add_typer(alert_app, name="alert")


@alert_app.command("run")
def alert_run(
    data_dir: str = typer.Option("_synth", "--data-dir"),
    out: str = typer.Option("", "--out", help="预警列表导出 JSON（可选）"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """执行预警规则：预警列表 + 突增场景验收（命中/误报）。"""
    from pathlib import Path

    from .alert.engine import alert_acceptance, run_alerts
    from .hotspot.bench import load_dataset

    if not (Path(data_dir) / "cases.csv").exists():
        console.print(f"[red]PS-E005：未找到 {data_dir}/cases.csv[/red]")
        raise typer.Exit(code=EXIT_RUNTIME)
    data = load_dataset(data_dir)
    cases = {"x": data["x"], "y": data["y"], "day": data["day"], "type": data["types"]}
    result = run_alerts(cases, days_total=int(data["day"].max()) + 1, start_date=data["truth"]["params"]["start_date"])
    acceptance = alert_acceptance(result["alerts"], data["truth"])
    if out:
        Path(out).write_text(jsonlib.dumps({"alerts": result["alerts"], "acceptance": acceptance}, ensure_ascii=False, indent=1), encoding="utf-8")
    if as_json:
        console.print_json(jsonlib.dumps({"acceptance": acceptance, "alerts": result["alerts"][:20]}, ensure_ascii=False))
        return
    level_color = {"red": "red", "orange": "yellow", "yellow": "yellow"}
    table = Table(title=f"预警列表（共 {len(result['alerts'])} 条 · 显示前 12）")
    table.add_column("级别", no_wrap=True)
    table.add_column("区域")
    table.add_column("类型")
    table.add_column("周")
    table.add_column("本周/基线", justify="right")
    table.add_column("倍数", justify="right")
    for alert in result["alerts"][:12]:
        table.add_row(
            f"[{level_color[alert['level']]}]{alert['level']}[/]",
            alert["district"] + (f" {alert.get('grid', '')}" if alert.get("scope") == "grid_neighborhood" else ""),
            alert["type"],
            alert["week"][0],
            f"{alert['current']}/{alert['baseline']:.0f}",
            f"{alert['factor']:.1f}x",
        )
    console.print(table)
    console.print(
        f"验收：突增场景命中 {acceptance['hit']}/{acceptance['anomalies']} · "
        f"热点区对齐 {acceptance['hotspot_aligned']} 条 · 无关预警 {acceptance['false_alerts']} 条（总预警 {acceptance['alerts_total']}）"
    )


@alert_app.command("rules")
def alert_rules() -> None:
    """查看当前预警规则（YAML 配置）。"""
    from .alert.rules import DEFAULT_RULES_PATH, load_rules

    doc = load_rules()
    console.print(f"规则文件：{DEFAULT_RULES_PATH}")
    table = Table(title=f"预警规则 v{doc.get('version')}（基线 {doc['defaults']['baseline_weeks']} 周）")
    table.add_column("id", no_wrap=True)
    table.add_column("名称")
    table.add_column("粒度")
    table.add_column("触发", justify="right")
    table.add_column("最小数量", justify="right")
    scope_label = {"district_type": "区域×类型", "grid_neighborhood": "网格邻域(3×3)"}
    for rule in doc["rules"]:
        table.add_row(
            rule["id"],
            rule["name"],
            scope_label.get(str(rule.get("scope", "")), str(rule.get("scope", ""))),
            f"≥ 基线×{rule['factor']}",
            str(rule["min_count"]),
        )
    console.print(table)
    levels = doc.get("levels") or {}
    console.print(f"级别阈值：red ≥ {levels.get('red')}x · orange ≥ {levels.get('orange')}x · yellow ≥ {levels.get('yellow')}x")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
