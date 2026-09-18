"""policesight.hotspot：时空热点分析。

- ``kde``：网格化高斯核密度（全城热力图 + 峰点）
- ``stkde``：时空核密度（时段×空间联合，3D 高斯核）
- ``stcluster``：ST-DBSCAN 时空聚类（cKDTree 缩放度量，避免 O(n²)）
- ``grid``：时段×网格聚合（时空立方体数据）
- ``bench``：对照真值的定标测评（热点召回 / 聚类指标 / 多 seed）
"""

from .grid import grid_counts, hour_weekday_matrix
from .kde import hotspot_recall, kde_grid, kde_peaks
from .stcluster import cluster_summary, st_dbscan
from .stkde import stkde_cube, stkde_points, stkde_recall

__all__ = [
    "cluster_summary",
    "grid_counts",
    "hotspot_recall",
    "hour_weekday_matrix",
    "kde_grid",
    "kde_peaks",
    "st_dbscan",
    "stkde_cube",
    "stkde_points",
    "stkde_recall",
]
