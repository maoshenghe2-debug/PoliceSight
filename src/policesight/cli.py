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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
