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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
