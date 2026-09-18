# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-09-18

### Added
- **合成数据引擎**：5 万条 / 180 天 / 0.52s；12 预设热点 + 6 系列案团伙 + 4 突增场景真值
  （`ground_truth.json`，含逐案归属）+ 质量检查（缺失/重复/时间/越界）
- **热点分析**：KDE / STKDE 核密度（热点召回 91.7% / 100%，5 万 × 5 seed 均值）
- **时空聚类**：ST-DBSCAN（cKDTree 缩放度量，O(n log n)）；聚类 F1 0.867（基线 0.531）、
  退化参数体检（PS-E006）
- **串并案**：多特征加权相似度（时空/手法/文本二元组）+ 候选对向量化预剪枝 + 阈值连通分量 +
  团伙可疑度排名 + 关系图谱（Louvain，GEXF/JSON 导出）
- **趋势预警**：STL/ETS + YAML 规则引擎（区域×类型 + 网格邻域 3×3 双粒度，暖机 ≥2 周）
  → 注入突增场景 4/4 命中、无关预警 7.0%（993 条）
- **研判看板**：离线合成矢量底图（CRS.Simple）+ KDE 热力 + 时间轴回放（26 预聚合帧）
  + 时空簇/疑组/预警图层 + ECharts 趋势与时段分布（Leaflet/ECharts 本地化，无外部请求）
- **周研判报告**：HTML（内联 SVG）+ DOCX（python-docx），`policesight report weekly`
- **定标测评**：`docs/benchmark.md`（热点/聚类）与 `docs/benchmark-link-alert.md`
  （串并案/预警），均由 CLI/脚本真实运行产出，可复现
- CLI 六组命令：`data` / `hotspot` / `link` / `alert` / `web` / `report` + `demo`
  + doctor 9 项自检；测试 21 项（含端到端链路与真值一致性）

### Notes
- 5 万规模下串并案分组纯度 0.52（2 万规模同参数 0.835）；规模效应与调参扫描过程在
  `docs/benchmark-link-alert.md` 与 `docs/benchmark.md`「调参说明」如实披露
