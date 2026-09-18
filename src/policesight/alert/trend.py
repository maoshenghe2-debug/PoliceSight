"""趋势统计：日/周序列、STL 分解、ETS 预测（区域级，稳健降级）。"""

from __future__ import annotations

import numpy as np


def daily_counts(day: np.ndarray, days_total: int, mask: np.ndarray | None = None) -> np.ndarray:
    """案件天数索引 → 日计数序列（长度 days_total）。"""
    day = np.asarray(day, dtype=int)
    if mask is not None:
        day = day[np.asarray(mask, dtype=bool)]
    counts = np.zeros(int(days_total), dtype=float)
    valid = day[(day >= 0) & (day < days_total)]
    np.add.at(counts, valid, 1)
    return counts


def weekly_from_daily(daily: np.ndarray) -> np.ndarray:
    """日序列 → 周聚合（不足一周的部分并入最后一档）。"""
    daily = np.asarray(daily, dtype=float)
    n_weeks = int(np.ceil(len(daily) / 7))
    padded = np.pad(daily, (0, n_weeks * 7 - len(daily)))
    return padded.reshape(n_weeks, 7).sum(axis=1)


def stl_decompose(daily: np.ndarray, period: int = 7) -> dict:
    """STL 分解（趋势/季节/残差）；序列过短时降级为移动平均 + 零季节。"""
    daily = np.asarray(daily, dtype=float)
    if len(daily) < 2 * period:
        kernel = np.ones(min(period, len(daily))) / max(1, min(period, len(daily)))
        trend = np.convolve(daily, kernel, mode="same")
        return {"trend": trend.tolist(), "seasonal": np.zeros_like(daily).tolist(), "resid": (daily - trend).tolist(), "method": "moving_average"}
    from statsmodels.tsa.seasonal import STL

    result = STL(daily, period=period, robust=True).fit()
    return {
        "trend": result.trend.tolist(),
        "seasonal": result.seasonal.tolist(),
        "resid": result.resid.tolist(),
        "method": "stl",
    }


def ets_forecast(series: np.ndarray, steps: int = 2) -> list[float] | None:
    """ETS（指数平滑）区域级预测；序列过短/拟合失败时返回 None（调用方降级为均值）。"""
    series = np.asarray(series, dtype=float)
    if len(series) < 8:
        return None
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        model = ExponentialSmoothing(series, trend="add", seasonal=None, initialization_method="estimated").fit()
        return [round(float(value), 2) for value in model.forecast(steps)]
    except Exception:
        return None
