"""policesight.web：研判看板（FastAPI 服务 + 离线静态前端 + 数据构建）。

- ``basemap``：仓库自带合成城市矢量底图（CRS.Simple 局部平面坐标）
- ``build``：将热点/聚类/疑组/预警/回放帧构建为静态 JSON（一次构建、离线服务）
- ``serve``：FastAPI 应用（默认 127.0.0.1:8770；只读接口 + 前端托管）
"""

from .build import build_web
from .serve import create_app

__all__ = ["build_web", "create_app"]
