"""★ 合成警情数据生成器：参数化城市模拟，同步输出「真值」（热点 / 系列案 / 突增场景）。

设计要点：
- 城市为**虚构**「滨江市」：12000m × 9000m 局部平面（500m 网格 24×18），
  按平滑随机场生成人口/商业强度 → 基础发案强度；
- 四层结构叠加：基础发案 + 预设热点区（K 个）+ 系列案（S 个团伙）+ 突增场景（A 个）；
- 真值与数据同源生成：热点/分组/突增的案件归属逐案记录，供算法效果量化评估；
- 规模与可控：``--cases 50000 --days 180 --seed 42``（向量化采样，5 万条秒级）。

伦理边界：全部数据为程序生成的虚构数据，不含任何真实警务数据；
分析定位为区域级资源配置辅助，不用于个人画像与个人预测。
"""

from __future__ import annotations

import csv
import json
import time as _time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

CITY = {
    "name": "滨江市（虚构）",
    "bbox_m": (0.0, 0.0, 12000.0, 9000.0),
    "nx": 24,
    "ny": 18,
    "cell_m": 500.0,
    "lon0": 118.7000,
    "lat0": 32.0000,
    "m_per_lon": 94390.8,
    "m_per_lat": 110574.0,
}

DISTRICTS = ["滨江商务区", "老城区", "西郊片区", "南湖景区", "东湖新城", "北岸片区"]

TYPES = ["盗窃", "抢劫", "诈骗", "伤害", "寻衅滋事"]
TYPE_WEIGHTS = np.array([0.52, 0.07, 0.23, 0.10, 0.08])

METHODS: dict[str, list[str]] = {
    "盗窃": ["技术开锁", "入室盗窃", "扒窃", "砸车窗", "撬盗电动车"],
    "抢劫": ["拦路抢劫", "飞车抢夺"],
    "诈骗": ["网络刷单", "冒充客服", "投资理财", "冒充公检法"],
    "伤害": ["酒后斗殴", "纠纷引发伤害"],
    "寻衅滋事": ["酒后滋事", "群体纠纷"],
}

HOUR_PROBS: dict[str, list[float]] = {
    "盗窃": [0.05, 0.05, 0.04, 0.03, 0.02, 0.02, 0.02, 0.02, 0.03, 0.04, 0.04, 0.04, 0.04, 0.03, 0.03, 0.03, 0.04, 0.05, 0.06, 0.06, 0.06, 0.06, 0.05, 0.05],
    "抢劫": [0.07, 0.06, 0.04, 0.03, 0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.02, 0.03, 0.03, 0.03, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.08, 0.08, 0.07, 0.06],
    "诈骗": [0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.02, 0.03, 0.05, 0.06, 0.07, 0.07, 0.07, 0.07, 0.07, 0.06, 0.05, 0.04, 0.04, 0.04, 0.03, 0.03, 0.02],
    "伤害": [0.08, 0.07, 0.05, 0.03, 0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.02, 0.03, 0.03, 0.03, 0.03, 0.04, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.09, 0.08],
    "寻衅滋事": [0.10, 0.08, 0.05, 0.03, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.02, 0.02, 0.03, 0.03, 0.03, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.09, 0.09],
}

# 周一..周日（相对权重，代码内归一化到 max=1 用于接受-拒绝采样）
WEEKDAY_W: dict[str, list[float]] = {
    "盗窃": [1.0, 1.0, 1.0, 1.0, 1.0, 1.15, 1.10],
    "抢劫": [1.0, 1.0, 1.0, 1.0, 1.10, 1.15, 1.10],
    "诈骗": [1.10, 1.10, 1.10, 1.05, 1.05, 0.90, 0.80],
    "伤害": [0.90, 0.90, 0.95, 1.00, 1.15, 1.20, 1.15],
    "寻衅滋事": [0.90, 0.90, 0.95, 1.00, 1.20, 1.25, 1.15],
}

STATUS = ["已受理", "侦办中", "已结案"]
STATUS_W = np.array([0.45, 0.35, 0.20])

SUMMARY_TEMPLATES: dict[str, str] = {
    "技术开锁": "{district}{place}住户报警称房门被技术开锁，室内财物被盗，损失约{loss}元。",
    "入室盗窃": "{district}{place}低层住户报警称窗户被撬，家中现金与首饰被盗，损失约{loss}元。",
    "扒窃": "{district}{place}附近人流中发现手机/钱包被扒窃，报案人损失约{loss}元。",
    "砸车窗": "{district}{place}路边停车位车辆车窗被砸，车内物品被盗，损失约{loss}元。",
    "撬盗电动车": "{district}{place}地铁口电动车被盗，锁具被撬，损失约{loss}元。",
    "拦路抢劫": "{district}{place}僻静路段发生拦路抢劫，受害人随身财物被抢，损失约{loss}元。",
    "飞车抢夺": "{district}{place}人行道发生飞车抢夺，受害人背包/手机被抢，损失约{loss}元。",
    "网络刷单": "{district}居民报警称参与网络刷单被骗，对方诱导多次转账，损失约{loss}元。",
    "冒充客服": "{district}居民接到自称客服的电话，以退款为由被骗，损失约{loss}元。",
    "投资理财": "{district}居民称在虚假理财平台投资被骗，平台无法提现，损失约{loss}元。",
    "冒充公检法": "{district}居民称接到冒充公检法电话，被要求转账至“安全账户”，损失约{loss}元。",
    "酒后斗殴": "{district}{place}夜宵摊附近发生酒后斗殴，一人受伤送医，现场已控制。",
    "纠纷引发伤害": "{district}{place}因纠纷引发肢体冲突，当事人受轻微伤，已调解处理。",
    "酒后滋事": "{district}{place}有人酒后滋事、损坏公共设施，现场处置中。",
    "群体纠纷": "{district}{place}发生多人争执，未造成人员伤亡，已现场调解。",
}

PLACES = ["小区", "商业街", "地铁口", "夜市摊区", "公园东门", "超市停车场", "公交站台", "老旧院落"]


def _relative_ts() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def grid_id_of(x: float, y: float) -> str:
    """返回网格编码 ``r{row}c{col}``（行=南北，列=东西）。"""
    col = int(x // CITY["cell_m"])
    row = int(y // CITY["cell_m"])
    col = min(max(col, 0), CITY["nx"] - 1)
    row = min(max(row, 0), CITY["ny"] - 1)
    return f"r{row:02d}c{col:02d}"


def district_of(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """按 x=6000 / y=3000、6000 将城市分为 6 个片区（虚构名）。"""
    out = np.empty(x.shape, dtype=object)
    out[(x < 6000) & (y < 3000)] = DISTRICTS[0]
    out[(x < 6000) & (y >= 3000) & (y < 6000)] = DISTRICTS[1]
    out[(x < 6000) & (y >= 6000)] = DISTRICTS[2]
    out[(x >= 6000) & (y < 3000)] = DISTRICTS[3]
    out[(x >= 6000) & (y >= 3000) & (y < 6000)] = DISTRICTS[4]
    out[(x >= 6000) & (y >= 6000)] = DISTRICTS[5]
    return out


def xlon_to_lonlat(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """局部平面（米）→ 经纬度（简化线性映射，仅作演示可视化）。"""
    lon = CITY["lon0"] + x / CITY["m_per_lon"]
    lat = CITY["lat0"] + y / CITY["m_per_lat"]
    return lon, lat


def _smooth_field(rng: np.random.Generator, nx: int, ny: int, sigma: float) -> np.ndarray:
    """平滑随机场（高斯滤波的随机噪声），归一到 [0, 1]。"""
    noise = rng.normal(0.0, 1.0, (ny, nx))
    kernel = np.exp(-0.5 * (np.arange(-4, 5) / sigma) ** 2)
    kernel /= kernel.sum()
    field = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="same"), 1, noise)
    field = np.apply_along_axis(lambda col: np.convolve(col, kernel, mode="same"), 0, field)
    field -= field.min()
    if field.max() > 0:
        field /= field.max()
    return field


@dataclass
class CityModel:
    """城市强度模型（人口/商业/基础发案强度）。"""

    pop: np.ndarray
    commercial: np.ndarray
    lam: np.ndarray
    nx: int = CITY["nx"]
    ny: int = CITY["ny"]
    extras: dict = field(default_factory=dict)

    def cell_centers(self, flat_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # 行主序展平（(ny, nx) 数组）：分母用 nx
        rows = flat_idx // self.nx
        cols = flat_idx % self.nx
        x = (cols + 0.5) * CITY["cell_m"]
        y = (rows + 0.5) * CITY["cell_m"]
        return x.astype(float), y.astype(float)

    def sample_cells(self, rng: np.random.Generator, n: int, mask: np.ndarray | None = None) -> np.ndarray:
        weights = self.lam.copy()
        if mask is not None:
            weights = np.where(mask, weights, 0.0)
        p = weights.ravel() / weights.sum()
        return rng.choice(weights.size, size=n, p=p)


def build_city(rng: np.random.Generator) -> CityModel:
    """构建城市强度场：中心商务区隆起 + 两个副中心 + 平滑噪声。"""
    nx, ny = CITY["nx"], CITY["ny"]
    xs = (np.arange(nx) + 0.5) * CITY["cell_m"]
    ys = (np.arange(ny) + 0.5) * CITY["cell_m"]
    gx, gy = np.meshgrid(xs, ys)

    def bump(cx: float, cy: float, sx: float, sy: float) -> np.ndarray:
        return np.exp(-(((gx - cx) / sx) ** 2 + ((gy - cy) / sy) ** 2))

    # 中心商务区（东南）+ 副中心（西北/中部）
    commercial = 0.15 + 0.85 * np.clip(1.05 * bump(8600, 3200, 2600, 1800) + 0.45 * bump(3800, 6800, 2200, 1800), 0, 1)
    commercial *= 0.75 + 0.5 * _smooth_field(rng, nx, ny, 2.2)
    commercial = np.clip(commercial, 0, 1)

    pop = 0.20 + 0.80 * np.clip(0.75 * bump(5600, 4600, 4200, 3400) + 0.55 * bump(3000, 2500, 2200, 2000) + 0.35 * bump(9500, 7000, 2400, 2000), 0, 1)
    pop *= 0.70 + 0.6 * _smooth_field(rng, nx, ny, 2.8)
    pop = np.clip(pop, 0, 1)

    lam = 0.35 + 0.65 * pop + 0.85 * commercial
    return CityModel(pop=pop, commercial=commercial, lam=lam)


def _sample_hours(rng: np.random.Generator, types_idx: np.ndarray) -> np.ndarray:
    hours = np.empty(len(types_idx), dtype=int)
    for idx, tname in enumerate(TYPES):
        mask = types_idx == idx
        n = int(mask.sum())
        if n:
            probs = np.asarray(HOUR_PROBS[tname], dtype=float)
            hours[mask] = rng.choice(24, size=n, p=probs / probs.sum())
    return hours


def _sample_days(rng: np.random.Generator, types_idx: np.ndarray, days: int, start_weekday: int) -> np.ndarray:
    """按类型×星期的接受-拒绝采样（最大接受率 1.0）。"""
    out = np.full(len(types_idx), -1, dtype=int)
    pending = np.arange(len(types_idx))
    while pending.size:
        m = pending.size
        d = rng.integers(0, days, m)
        wd = (start_weekday + d) % 7
        prob = np.empty(m)
        for idx, tname in enumerate(TYPES):
            base = WEEKDAY_W[tname]
            mx = max(base)
            mask = types_idx[pending] == idx
            if mask.any():
                prob[mask] = np.asarray(base, dtype=float)[wd[mask]] / mx
        accept = rng.random(m) < prob
        accepted = pending[accept]
        out[accepted] = d[accept]
        pending = pending[~accept]
    return out


def _sample_methods(rng: np.random.Generator, types_idx: np.ndarray) -> np.ndarray:
    out = np.empty(len(types_idx), dtype=object)
    for idx, tname in enumerate(TYPES):
        mask = types_idx == idx
        n = int(mask.sum())
        if n:
            out[mask] = rng.choice(METHODS[tname], size=n)
    return out


def _clip_to_city(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, x1, y1 = CITY["bbox_m"]
    return np.clip(x, x0 + 50, x1 - 50), np.clip(y, y0 + 50, y1 - 50)


def generate_dataset(
    out_dir: Path | str,
    cases: int = 50000,
    days: int = 180,
    seed: int = 42,
    start_date: str = "2026-03-01",
    hotspot_count: int = 12,
    series_gangs: int = 6,
    anomalies: int = 4,
    hotspot_share: float = 0.35,
) -> dict:
    """生成合成警情数据与真值文件。返回摘要字典。"""
    t0 = _time.perf_counter()
    if not 1000 <= cases <= 500000:
        raise ValueError("cases 需在 [1000, 500000] 区间")
    if not 30 <= days <= 730:
        raise ValueError("days 需在 [30, 730] 区间")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    city = build_city(rng)
    start = date.fromisoformat(start_date)

    n_hot = int(cases * hotspot_share)
    # 系列案规模
    gang_sizes = rng.integers(15, 61, size=series_gangs)
    n_series = int(gang_sizes.sum())
    # 突增额外量
    anom_extra = rng.integers(60, 161, size=anomalies)
    n_anom = int(anom_extra.sum())
    n_base = max(cases - n_hot - n_series - n_anom, 0)

    def new_types(n: int, dominant: str | None = None, dominant_p: float = 0.8) -> np.ndarray:
        if dominant is None:
            return rng.choice(len(TYPES), size=n, p=TYPE_WEIGHTS / TYPE_WEIGHTS.sum())
        idx = np.full(n, TYPES.index(dominant))
        mix = rng.random(n) >= dominant_p
        if mix.any():
            idx[mix] = rng.choice(len(TYPES), size=int(mix.sum()), p=TYPE_WEIGHTS / TYPE_WEIGHTS.sum())
        return idx

    # ── 基础发案 ─────────────────────────────────────────────
    base_cells = city.sample_cells(rng, n_base)
    bx, by = city.cell_centers(base_cells)
    bx += rng.normal(0, 180, n_base)
    by += rng.normal(0, 180, n_base)
    bx, by = _clip_to_city(bx, by)
    base_types = new_types(n_base)

    # ── 预设热点区 ───────────────────────────────────────────
    hot_records: list[dict] = []
    hot_x = np.empty(0)
    hot_y = np.empty(0)
    hot_t = np.empty(0, dtype=int)
    hot_types = np.empty(0, dtype=int)
    for k in range(hotspot_count):
        cell = int(city.sample_cells(rng, 1)[0])
        cx, cy = city.cell_centers(np.array([cell]))
        cx, cy = float(cx[0]), float(cy[0])
        radius = float(rng.uniform(300, 900))
        w_start = int(rng.integers(0, max(1, days - 45)))
        w_len = int(rng.integers(14, 46))
        dominant = TYPES[int(rng.choice(len(TYPES), p=TYPE_WEIGHTS / TYPE_WEIGHTS.sum()))]
        n_k = int(n_hot // hotspot_count + rng.integers(-80, 81))
        n_k = max(40, n_k)
        px = cx + rng.normal(0, radius / 2.2, n_k)
        py = cy + rng.normal(0, radius / 2.2, n_k)
        px, py = _clip_to_city(px, py)
        ptypes = new_types(n_k, dominant=dominant, dominant_p=0.8)
        pdays = w_start + rng.integers(0, w_len, n_k)
        hot_x = np.concatenate([hot_x, px])
        hot_y = np.concatenate([hot_y, py])
        hot_t = np.concatenate([hot_t, pdays])
        hot_types = np.concatenate([hot_types, ptypes])
        hot_records.append(
            {
                "id": f"H{k + 1:02d}",
                "center_m": [round(cx, 1), round(cy, 1)],
                "radius_m": round(radius, 1),
                "window": [str(start + timedelta(days=w_start)), str(start + timedelta(days=w_start + w_len - 1))],
                "dominant_type": dominant,
                "expected_cases": int(n_k),
                "_stage": "hotspot",
                "_group": f"H{k + 1:02d}",
            }
        )

    # ── 系列案团伙 ───────────────────────────────────────────
    series_records: list[dict] = []
    ser_x = np.empty(0)
    ser_y = np.empty(0)
    ser_t = np.empty(0, dtype=int)
    ser_types = np.empty(0, dtype=int)
    for g in range(series_gangs):
        n_g = int(gang_sizes[g])
        cell = int(city.sample_cells(rng, 1)[0])
        cx, cy = city.cell_centers(np.array([cell]))
        cx, cy = float(cx[0]), float(cy[0])
        gtype = TYPES[int(rng.choice([0, 1, 2], p=[0.6, 0.15, 0.25]))]
        gmethods = list(rng.choice(METHODS[gtype], size=int(rng.integers(2, min(4, len(METHODS[gtype])) + 1)), replace=False))
        w_start = int(rng.integers(0, max(1, days - 60)))
        w_len = int(rng.integers(20, 61))
        sigma = float(rng.uniform(150, 250))
        gx = cx + rng.normal(0, sigma, n_g)
        gy = cy + rng.normal(0, sigma, n_g)
        gx, gy = _clip_to_city(gx, gy)
        gdays = w_start + rng.integers(0, w_len, n_g)
        ser_x = np.concatenate([ser_x, gx])
        ser_y = np.concatenate([ser_y, gy])
        ser_t = np.concatenate([ser_t, gdays])
        ser_types = np.concatenate([ser_types, np.full(n_g, TYPES.index(gtype))])
        series_records.append(
            {
                "id": f"G{g + 1:02d}",
                "anchor_m": [round(cx, 1), round(cy, 1)],
                "window": [str(start + timedelta(days=w_start)), str(start + timedelta(days=w_start + w_len - 1))],
                "types": [gtype],
                "methods": [str(m) for m in gmethods],
                "expected_cases": n_g,
                "_stage": "series",
                "_group": f"G{g + 1:02d}",
            }
        )

    # ── 突增场景 ─────────────────────────────────────────────
    anom_records: list[dict] = []
    an_x = np.empty(0)
    an_y = np.empty(0)
    an_t = np.empty(0, dtype=int)
    an_types = np.empty(0, dtype=int)
    for a in range(anomalies):
        cell = int(city.sample_cells(rng, 1)[0])
        cx, cy = city.cell_centers(np.array([cell]))
        cx, cy = float(cx[0]), float(cy[0])
        factor = float(np.round(rng.uniform(1.8, 2.5), 2))
        w_start = int(rng.integers(10, max(11, days - 12)))
        w_len = int(rng.integers(7, 11))
        n_a = int(anom_extra[a])
        ax = cx + rng.normal(0, 220, n_a)
        ay = cy + rng.normal(0, 220, n_a)
        ax, ay = _clip_to_city(ax, ay)
        adays = w_start + rng.integers(0, w_len, n_a)
        atypes = new_types(n_a)
        an_x = np.concatenate([an_x, ax])
        an_y = np.concatenate([an_y, ay])
        an_t = np.concatenate([an_t, adays])
        an_types = np.concatenate([an_types, atypes])
        anom_records.append(
            {
                "id": f"A{a + 1:02d}",
                "center_m": [round(cx, 1), round(cy, 1)],
                "grid_id": grid_id_of(cx, cy),
                "window": [str(start + timedelta(days=w_start)), str(start + timedelta(days=w_start + w_len - 1))],
                "factor": factor,
                "extra_cases": n_a,
                "_stage": "anomaly",
                "_group": f"A{a + 1:02d}",
            }
        )

    # ── 合并 + 时间采样 + 排序 + 编号 ────────────────────────
    xs = np.concatenate([bx, hot_x, ser_x, an_x])
    ys = np.concatenate([by, hot_y, ser_y, an_y])
    types_idx = np.concatenate([base_types, hot_types, ser_types, an_types])
    stage = np.concatenate(
        [
            np.full(n_base, "base", dtype=object),
            np.full(len(hot_x), "hotspot", dtype=object),
            np.full(len(ser_x), "series", dtype=object),
            np.full(len(an_x), "anomaly", dtype=object),
        ]
    )
    # group 标签：基础段为空；其余按各记录实际段长重建（与生成顺序一致）
    seg_groups: list[np.ndarray] = [np.full(n_base, "", dtype=object)]
    seg_groups += [np.full(int(rec["expected_cases"]), rec["_group"], dtype=object) for rec in hot_records]
    seg_groups += [np.full(int(gang_sizes[g]), series_records[g]["_group"], dtype=object) for g in range(len(series_records))]
    seg_groups += [np.full(int(rec["extra_cases"]), rec["_group"], dtype=object) for rec in anom_records]
    group = np.concatenate(seg_groups)
    assert len(group) == len(xs), f"group 段长不一致：{len(group)} != {len(xs)}"

    # 天（突增段按窗口内均匀；其余段统一按星期权重采样，直接以既有窗口天为准）
    # base 段用星期采样；hotspot/series/anomaly 段已给窗口天数
    base_days_arr = _sample_days(rng, base_types, days, start.weekday())
    day_arr = np.concatenate([base_days_arr, hot_t, ser_t, an_t])

    hour_arr = _sample_hours(rng, types_idx)
    minute_arr = rng.integers(0, 60, len(xs))
    method_arr = np.empty(len(xs), dtype=object)
    for idx, tname in enumerate(TYPES):
        mask = types_idx == idx
        n = int(mask.sum())
        if n:
            method_arr[mask] = rng.choice(METHODS[tname], size=n)
    # 系列案手法收紧到团伙手法集
    ser_off = n_base + len(hot_x)
    for g, rec in enumerate(series_records):
        start_i = ser_off + int(gang_sizes[:g].sum())
        end_i = start_i + int(gang_sizes[g])
        method_arr[start_i:end_i] = rng.choice(rec["methods"], size=int(gang_sizes[g]))

    order = np.argsort(day_arr, kind="stable")
    xs, ys = xs[order], ys[order]
    types_idx = types_idx[order]
    day_arr, hour_arr, minute_arr = day_arr[order], hour_arr[order], minute_arr[order]
    method_arr = method_arr[order]
    stage, group = stage[order], group[order]

    n = len(xs)
    case_ids = [f"PS-{start.year}-{i + 1:06d}" for i in range(n)]
    districts = district_of(xs, ys)
    lons, lats = xlon_to_lonlat(xs, ys)
    status_idx = rng.choice(len(STATUS), size=n, p=STATUS_W / STATUS_W.sum())
    losses = rng.integers(300, 30000, n)
    places = rng.choice(PLACES, size=n)

    # ── 写出 CSV ─────────────────────────────────────────────
    csv_path = out / "cases.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "time", "x_m", "y_m", "lon", "lat", "district", "grid_id", "type", "method", "summary", "status"])
        for i in range(n):
            ts = datetime.combine(start + timedelta(days=int(day_arr[i])), datetime.min.time()).replace(hour=int(hour_arr[i]), minute=int(minute_arr[i]))
            summary = SUMMARY_TEMPLATES[str(method_arr[i])].format(
                district=districts[i], place=str(places[i]), loss=int(losses[i])
            )
            writer.writerow(
                [
                    case_ids[i],
                    ts.isoformat(timespec="minutes"),
                    f"{xs[i]:.1f}",
                    f"{ys[i]:.1f}",
                    f"{lons[i]:.6f}",
                    f"{lats[i]:.6f}",
                    districts[i],
                    grid_id_of(xs[i], ys[i]),
                    TYPES[int(types_idx[i])],
                    str(method_arr[i]),
                    summary,
                    STATUS[int(status_idx[i])],
                ]
            )

    # ── 真值（回填 case_ids） ────────────────────────────────
    def ids_for(grp: str) -> list[str]:
        return [case_ids[i] for i in range(n) if group[i] == grp]

    truth = {
        "schema_version": 1,
        "generated_at": _relative_ts(),
        "params": {
            "cases": int(n),
            "days": days,
            "seed": seed,
            "start_date": start_date,
            "grid": {"nx": CITY["nx"], "ny": CITY["ny"], "cell_m": CITY["cell_m"]},
            "hotspot_share": hotspot_share,
        },
        "city": {"name": CITY["name"], "bbox_m": list(CITY["bbox_m"])},
        "hotspots": [
            {k: v for k, v in rec.items() if not k.startswith("_")} | {"case_ids": ids_for(rec["_group"])}
            for rec in hot_records
        ],
        "series_groups": [
            {k: v for k, v in rec.items() if not k.startswith("_")} | {"case_ids": ids_for(rec["_group"])}
            for rec in series_records
        ],
        "anomalies": [
            {k: v for k, v in rec.items() if not k.startswith("_")} | {"case_ids": ids_for(rec["_group"])}
            for rec in anom_records
        ],
        "benchmark_protocol": {"hotspot_recall_target": 0.8, "seeds": [41, 42, 43, 44, 45]},
    }
    truth_path = out / "ground_truth.json"
    truth_path.write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")

    elapsed = round(_time.perf_counter() - t0, 2)
    per_type = {tname: int((types_idx == idx).sum()) for idx, tname in enumerate(TYPES)}
    return {
        "cases": int(n),
        "days": days,
        "seed": seed,
        "elapsed_s": elapsed,
        "hotspots": len(hot_records),
        "series_groups": len(series_records),
        "anomalies": len(anom_records),
        "per_type": per_type,
        "csv": str(csv_path),
        "ground_truth": str(truth_path),
    }
