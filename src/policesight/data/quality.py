"""数据质量检查：缺失值 / 坐标越界 / 时间异常 / 重复案件号。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .generator import CITY

REQUIRED_COLUMNS = ["case_id", "time", "x_m", "y_m", "type", "method", "summary", "status"]


def check_quality(csv_path: Path | str, truth_path: Path | str | None = None) -> dict:
    """扫描 CSV（+真值）并返回质量报告字典。"""
    csv_path = Path(csv_path)
    issues: list[dict] = []
    total = 0
    ids: set[str] = set()
    dup = 0
    bad_time = 0
    out_of_bbox = 0
    missing = 0
    x0, y0, x1, y1 = CITY["bbox_m"]

    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames or []
        for col in REQUIRED_COLUMNS:
            if col not in columns:
                issues.append({"kind": "missing_column", "detail": col})
        for row in reader:
            total += 1
            cid = row.get("case_id", "")
            if cid in ids:
                dup += 1
            ids.add(cid)
            try:
                from datetime import datetime

                datetime.fromisoformat(row["time"])
            except Exception:
                bad_time += 1
            try:
                x, y = float(row["x_m"]), float(row["y_m"])
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    out_of_bbox += 1
            except Exception:
                out_of_bbox += 1
            for col in REQUIRED_COLUMNS:
                if not str(row.get(col, "")).strip():
                    missing += 1
                    break

    truth_summary: dict = {}
    if truth_path and Path(truth_path).exists():
        truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
        truth_summary = {
            "hotspots": len(truth.get("hotspots") or []),
            "series_groups": len(truth.get("series_groups") or []),
            "anomalies": len(truth.get("anomalies") or []),
            "schema_version": truth.get("schema_version"),
        }

    checks = {
        "missing_values": missing,
        "duplicate_ids": dup,
        "invalid_time": bad_time,
        "out_of_bbox": out_of_bbox,
    }
    passed = all(v == 0 for v in checks.values()) and not [i for i in issues if i["kind"] == "missing_column"]
    return {"rows": total, "checks": checks, "column_issues": issues, "truth": truth_summary, "passed": passed}


def format_report(report: dict) -> str:
    lines = [
        f"行数：{report['rows']}",
        f"缺失值案件：{report['checks']['missing_values']}",
        f"重复编号：{report['checks']['duplicate_ids']}",
        f"时间异常：{report['checks']['invalid_time']}",
        f"坐标越界：{report['checks']['out_of_bbox']}",
        f"结论：{'通过' if report['passed'] else '存在待处理项'}",
    ]
    if report.get("truth"):
        truth = report["truth"]
        lines.append(
            f"真值：schema v{truth.get('schema_version')} · 热点 {truth.get('hotspots')} · 系列案 {truth.get('series_groups')} · 突增 {truth.get('anomalies')}"
        )
    return " ｜ ".join(lines)
