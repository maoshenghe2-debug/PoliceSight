"""policesight.data：合成数据引擎（带真值）+ 质量检查。

- ``generator``：参数化城市模拟，生成案件 CSV + ``ground_truth.json``（预设热点 / 系列案分组 / 突增场景）
- ``quality``：缺失值 / 坐标越界 / 时间异常 / 重复检查
"""

from .generator import CITY, build_city, generate_dataset, grid_id_of, xlon_to_lonlat
from .quality import check_quality, format_report

__all__ = [
    "CITY",
    "build_city",
    "check_quality",
    "format_report",
    "generate_dataset",
    "grid_id_of",
    "xlon_to_lonlat",
]
