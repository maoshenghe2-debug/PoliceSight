"""policesight.alert：趋势分解与规则预警。

- ``trend``：日/周序列、STL 分解（趋势/季节/残差）、ETS 预测（区域级）
- ``rules``：YAML 预警规则加载与校验
- ``engine``：规则执行（区域×类型 × 周）→ 预警列表（级别/依据/建议）+ 真值验收（命中/误报）
"""

from .engine import alert_acceptance, run_alerts
from .rules import DEFAULT_RULES_PATH, load_rules
from .trend import daily_counts, ets_forecast, stl_decompose, weekly_from_daily

__all__ = [
    "DEFAULT_RULES_PATH",
    "alert_acceptance",
    "daily_counts",
    "ets_forecast",
    "load_rules",
    "run_alerts",
    "stl_decompose",
    "weekly_from_daily",
]
