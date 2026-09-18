"""合成城市矢量底图（仓库自带、离线可用；CRS.Simple 局部平面坐标）。

要素：片区面 / 河流带 / 主干道路网 / 街区块（随建筑密度类目着色）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..data.generator import CITY, DISTRICTS

# 片区矩形（与 generator.district_of 的划分一致）
DISTRICT_RECTS = {
    "滨江商务区": (0, 0, 6000, 3000),
    "南湖景区": (6000, 0, 12000, 3000),
    "老城区": (0, 3000, 6000, 6000),
    "东湖新城": (6000, 3000, 12000, 6000),
    "西郊片区": (0, 6000, 6000, 9000),
    "北岸片区": (6000, 6000, 12000, 9000),
}

DISTRICT_COLOR = {
    "滨江商务区": "#dbeafe",
    "老城区": "#fef3c7",
    "西郊片区": "#dcfce7",
    "南湖景区": "#cffafe",
    "东湖新城": "#ede9fe",
    "北岸片区": "#ffe4e6",
}


def district_name(x: float, y: float) -> str:
    """与 generator.district_of 同规则的单点片区判定。"""
    if x < 6000:
        if y < 3000:
            return DISTRICTS[0]
        if y < 6000:
            return DISTRICTS[1]
        return DISTRICTS[2]
    if y < 3000:
        return DISTRICTS[3]
    if y < 6000:
        return DISTRICTS[4]
    return DISTRICTS[5]


def build_basemap() -> dict:
    """返回 GeoJSON FeatureCollection（局部平面坐标，单位：米）。"""
    x0, y0, x1, y1 = CITY["bbox_m"]
    cell = CITY["cell_m"]
    features: list[dict] = []

    # ── 片区面（色块 + 名称）──────────────────────────────
    for name, (bx0, by0, bx1, by1) in DISTRICT_RECTS.items():
        rect = [[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1], [bx0, by0]]
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "district", "name": name, "color": DISTRICT_COLOR[name]},
                "geometry": {"type": "Polygon", "coordinates": [rect]},
            }
        )

    # ── 河流带（滨江）─────────────────────────────────────
    river_points = [(0, 5050), (2400, 4820), (5200, 4950), (7900, 4480), (10100, 4620), (12000, 4180)]
    upper = [(px, py + 130 + 40 * (i % 3)) for i, (px, py) in enumerate(river_points)]
    lower = [(px, py - 150 - 50 * ((i + 1) % 3)) for i, (px, py) in reversed(list(enumerate(river_points)))]
    river_poly = [list(point) for point in upper] + [list(point) for point in lower] + [[upper[0][0], upper[0][1]]]
    features.append(
        {
            "type": "Feature",
            "properties": {"kind": "water", "name": "滨江"},
            "geometry": {"type": "Polygon", "coordinates": [river_poly]},
        }
    )

    # ── 主干道路网 ─────────────────────────────────────────
    for road_y in (1600, 4600, 7500):
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "road", "name": f"主干道 Y{road_y}"},
                "geometry": {"type": "LineString", "coordinates": [[x0, road_y], [x1, road_y]]},
            }
        )
    for road_x in (1600, 3200, 4600, 6100, 7600, 9000, 10400):
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "road", "name": f"主干道 X{road_x}"},
                "geometry": {"type": "LineString", "coordinates": [[road_x, y0], [road_x, y1]]},
            }
        )

    # ── 街区块（500m 网格缩进 65m；按片区着色）──────────────
    for col in range(CITY["nx"]):
        for row in range(CITY["ny"]):
            bx0 = col * cell + 65
            by0 = row * cell + 65
            bx1 = (col + 1) * cell - 65
            by1 = (row + 1) * cell - 65
            name = district_name((bx0 + bx1) / 2, (by0 + by1) / 2)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "block", "district": name},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1], [bx0, by0]]],
                    },
                }
            )

    return {
        "type": "FeatureCollection",
        "features": features,
        "note": "合成城市底图（虚构「滨江市」）· 局部平面坐标（米）· CRS.Simple 渲染",
    }


def write_basemap(path: Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_basemap()
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return len(doc["features"])
