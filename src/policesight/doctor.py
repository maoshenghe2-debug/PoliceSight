"""policesight doctor：环境自检（9 项）与建议动作。"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__

STATUS_OK = "就绪"
STATUS_WARN = "缺失"
STATUS_FAIL = "不满足"

MIN_PY = (3, 11)
MIN_DISK_GIB = 2.0
DEFAULT_DATA_DIR = Path("_synth")

DEPS = ["numpy", "scipy", "sklearn", "shapely", "networkx", "statsmodels", "fastapi", "docx", "yaml", "typer", "rich"]


@dataclass
class Check:
    key: str
    name: str
    status: str
    detail: str
    fix: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


def check_python() -> Check:
    ok = sys.version_info[:2] >= MIN_PY
    return Check(
        key="python",
        name="Python 版本",
        status=STATUS_OK if ok else STATUS_FAIL,
        detail=f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}（要求 ≥{MIN_PY[0]}.{MIN_PY[1]}）",
        fix="" if ok else "请使用 Python 3.11+",
    )


def check_platform() -> Check:
    return Check(key="platform", name="平台", status=STATUS_OK, detail=f"{os.name} / {sys.platform}")


def check_deps() -> Check:
    missing = [name for name in DEPS if importlib.util.find_spec(name) is None]
    ok = not missing
    return Check(
        key="deps",
        name="依赖完整性",
        status=STATUS_OK if ok else STATUS_FAIL,
        detail="核心依赖全部就绪" if ok else f"缺少：{', '.join(missing)}",
        fix="" if ok else 'uv pip install -e ".[all]"',
    )


def check_data_dir(data_dir: Path) -> Check:
    csv_path = data_dir / "cases.csv"
    truth_path = data_dir / "ground_truth.json"
    if csv_path.exists() and truth_path.exists():
        return Check(key="data", name="合成数据", status=STATUS_OK, detail=f"{csv_path} + ground_truth.json 存在")
    return Check(
        key="data",
        name="合成数据",
        status=STATUS_WARN,
        detail=f"未找到 {csv_path} / {truth_path}",
        fix="policesight data generate --cases 50000 --days 180",
    )


def check_truth_contract(data_dir: Path) -> Check:
    truth_path = data_dir / "ground_truth.json"
    if not truth_path.exists():
        return Check(key="truth", name="真值契约", status=STATUS_WARN, detail="ground_truth.json 不存在", fix="policesight data generate")
    try:
        import json

        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        missing = [k for k in ("schema_version", "hotspots", "series_groups", "anomalies") if k not in truth]
        if missing:
            return Check(key="truth", name="真值契约", status=STATUS_WARN, detail=f"缺少字段：{', '.join(missing)}")
        detail = f"schema v{truth['schema_version']} · 热点 {len(truth['hotspots'])} · 系列案 {len(truth['series_groups'])} · 突增 {len(truth['anomalies'])}"
        return Check(key="truth", name="真值契约", status=STATUS_OK, detail=detail)
    except Exception as exc:
        return Check(key="truth", name="真值契约", status=STATUS_FAIL, detail=f"解析失败：{exc}", fix="重新生成数据")


def check_disk(base: Path) -> Check:
    anchor = base.anchor or base.drive or "/"
    usage = shutil.disk_usage(anchor)
    free_gib = usage.free / (1024**3)
    ok = free_gib >= MIN_DISK_GIB
    return Check(
        key="disk",
        name="磁盘空间",
        status=STATUS_OK if ok else STATUS_WARN,
        detail=f"{anchor} 可用 {free_gib:.1f} GiB（要求 ≥{MIN_DISK_GIB:g} GiB）",
    )


def check_workdir() -> Check:
    target = Path.cwd() / ".policesight"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check(key="workdir", name="工作目录可写", status=STATUS_OK, detail=str(target))
    except Exception as exc:
        return Check(key="workdir", name="工作目录可写", status=STATUS_FAIL, detail=str(exc), fix="更换工作目录或修复权限")


def check_web_assets() -> Check:
    vendor = Path(__file__).parent / "web" / "static" / "vendor"
    if vendor.is_dir() and any(vendor.iterdir()):
        return Check(key="web", name="前端资产（离线）", status=STATUS_OK, detail=str(vendor))
    return Check(key="web", name="前端资产（离线）", status=STATUS_WARN, detail="vendor 资产未就绪（v1.0 看板交付）", fix="随 v1.0 提供（离线 Leaflet/ECharts）")


def check_core_import() -> Check:
    try:
        from .data.generator import CITY  # noqa: F401

        return Check(key="core", name="核心模块（数据引擎）", status=STATUS_OK, detail="policesight.data 可导入")
    except Exception as exc:
        return Check(key="core", name="核心模块（数据引擎）", status=STATUS_FAIL, detail=f"导入失败：{exc}")


def run_doctor(data_dir: Path | None = None) -> dict:
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    checks = [
        check_python(),
        check_platform(),
        check_deps(),
        check_core_import(),
        check_data_dir(data_dir),
        check_truth_contract(data_dir),
        check_disk(Path.cwd()),
        check_workdir(),
        check_web_assets(),
    ]
    ok = sum(1 for c in checks if c.status == STATUS_OK)
    warn = sum(1 for c in checks if c.status == STATUS_WARN)
    fail = sum(1 for c in checks if c.status == STATUS_FAIL)
    exit_code = 0 if fail == 0 and warn == 0 else (1 if fail == 0 else 3)
    return {
        "tool": "policesight",
        "version": __version__,
        "checks": [c.to_dict() for c in checks],
        "summary": {"ok": ok, "warn": warn, "fail": fail},
        "exit_code": exit_code,
    }
