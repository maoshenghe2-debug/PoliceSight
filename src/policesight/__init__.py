"""PoliceSight · 警情时空智能研判平台。

模块规划：
- ``policesight.doctor``     环境自检（依赖 / 数据目录 / 契约校验）
- ``policesight.data``       合成数据引擎（带真值）+ 导入 + 质量检查
- ``policesight.hotspot``    KDE / STKDE 热点 + ST-DBSCAN 聚类 + 网格聚合
- ``policesight.link``       串并案相似度 + 分组 + 关系图谱
- ``policesight.alert``      趋势分解 + 规则预警引擎
- ``policesight.report``     周研判报告（MD / DOCX）
- ``policesight.web``        FastAPI 服务 + 单页看板（Leaflet + ECharts）
- ``policesight.demo``       全流程演示
"""

__version__ = "0.1.0"
