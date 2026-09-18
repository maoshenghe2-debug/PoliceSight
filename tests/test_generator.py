"""生成器测试：真值一致性 / 契约校验 / 可复现 / 无标签泄漏 / 质量检查。"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from policesight.data.generator import CITY, generate_dataset, grid_id_of
from policesight.data.quality import check_quality

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "policesight" / "schemas" / "ground_truth.schema.json"


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("synth")
    summary = generate_dataset(out, cases=3000, days=60, seed=7)
    return out, summary


def _read_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def test_generate_small_dataset(dataset):
    out, summary = dataset
    assert summary["cases"] >= 3000
    assert summary["hotspots"] == 12
    assert summary["series_groups"] == 6
    assert summary["anomalies"] == 4
    assert (out / "cases.csv").exists()
    assert (out / "ground_truth.json").exists()


def test_csv_schema_and_no_label_leak(dataset):
    out, _ = dataset
    rows = _read_rows(out / "cases.csv")
    with open(out / "cases.csv", encoding="utf-8-sig", newline="") as fh:
        columns = csv.DictReader(fh).fieldnames
    assert columns == ["case_id", "time", "x_m", "y_m", "lon", "lat", "district", "grid_id", "type", "method", "summary", "status"]
    for forbidden in ("hotspot", "group", "series", "anomaly", "label", "truth"):
        assert not any(forbidden in column.lower() for column in columns)
    assert rows


def test_truth_contract_schema(dataset):
    out, _ = dataset
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator(schema).validate(truth)


def test_truth_consistency_with_cases(dataset):
    out, _ = dataset
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    rows = _read_rows(out / "cases.csv")
    index = {row["case_id"]: row for row in rows}

    all_ids: list[str] = []
    for record in truth["hotspots"] + truth["series_groups"] + truth["anomalies"]:
        all_ids.extend(record["case_ids"])
        assert record["case_ids"], f"{record['id']} 无案件归属"
    assert len(set(all_ids)) == len(all_ids), "真值案件不得重复归属"
    assert set(all_ids) <= set(index)

    # 系列案：案件时间落在窗口内、类型与手法符合团伙设定
    for record in truth["series_groups"]:
        w0 = date.fromisoformat(record["window"][0])
        w1 = date.fromisoformat(record["window"][1])
        for cid in record["case_ids"]:
            row = index[cid]
            day = datetime.fromisoformat(row["time"]).date()
            assert w0 <= day <= w1
            assert row["type"] in record["types"]
            assert row["method"] in record["methods"]

    # 热点：案件落在半径外扩 30% 内（高斯尾部裁剪后允许少量越界 → 允许 8%）
    for record in truth["hotspots"]:
        cx, cy = record["center_m"]
        radius = record["radius_m"] * 1.3
        inside = 0
        for cid in record["case_ids"]:
            row = index[cid]
            dx = float(row["x_m"]) - cx
            dy = float(row["y_m"]) - cy
            if (dx * dx + dy * dy) ** 0.5 <= radius:
                inside += 1
        assert inside / len(record["case_ids"]) >= 0.92


def test_determinism(tmp_path):
    generate_dataset(tmp_path / "a", cases=2000, days=45, seed=11)
    generate_dataset(tmp_path / "b", cases=2000, days=45, seed=11)
    text_a = (tmp_path / "a" / "cases.csv").read_text(encoding="utf-8-sig")
    text_b = (tmp_path / "b" / "cases.csv").read_text(encoding="utf-8-sig")
    assert text_a == text_b


def test_quality_check_passes(dataset):
    out, _ = dataset
    report = check_quality(out / "cases.csv", out / "ground_truth.json")
    assert report["passed"], report
    assert report["truth"]["hotspots"] == 12
    assert report["rows"] >= 3000


def test_grid_id_of():
    assert grid_id_of(10, 10) == "r00c00"
    assert grid_id_of(700, 600) == "r01c01"
    _x0, _y0, x1, y1 = CITY["bbox_m"]
    assert grid_id_of(x1 + 999, y1 + 999) == f"r{CITY['ny'] - 1:02d}c{CITY['nx'] - 1:02d}"
