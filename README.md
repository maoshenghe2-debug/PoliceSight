# PoliceSight · 警情时空智能研判平台

> 带真值的合成警情数据引擎 → KDE/STKDE 时空热点 → ST-DBSCAN 聚类 → 串并案图谱 → 突增预警 → 单页研判看板与周研判报告。

[![CI](https://github.com/maoshenghe2-debug/PoliceSight/actions/workflows/ci.yml/badge.svg)](https://github.com/maoshenghe2-debug/PoliceSight/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

## 定位与边界（先读这三点）

- **仅合成数据**：平台不包含任何真实警务数据或个人隐私数据；所有城市、案件、嫌疑线索均为程序生成的虚构数据。
- **区域级资源配置辅助**：分析结论定位于宏观态势与资源投放参考，**不用于个人画像与个人预测**（明确规避预测性警务的伦理风险）。
- **可量化验收**：数据生成器自带"真值"（预设热点 / 系列案分组 / 突增场景），所有算法效果（热点召回、聚类 F1、分组纯度）可对照真值一键复现。

## 快速开始

```bash
uv venv --python 3.11 && uv pip install -e ".[all]"
policesight doctor                                    # 环境自检
policesight data generate --cases 50000 --days 180    # 生成 5 万条带真值合成警情
policesight demo                                      # 全流程演示
```

## 核心能力（v1.0 冻结范围）

| 模块 | 说明 |
|---|---|
| 合成数据引擎 ★ | 参数化城市/热点/系列案/突增生成，同步输出 `ground_truth.json`，5 万条 ≤5 分钟 |
| 时空热点分析 | KDE 核密度 + STKDE 时空核密度（时段×空间联合显著热点），对照真值召回 ≥80%（≥5 seed 均值） |
| ST-DBSCAN 聚类 | 基于 cKDTree 的时空双参数聚类；purity + recall/F 双指标 + degenerate baseline 对照 |
| 串并案分析 | 时空/手法/文本多特征加权相似度 → 疑似系列案分组（附证据链）+ 二部图与社区发现 |
| 趋势与预警 | STL/ETS 趋势分解 + YAML 规则引擎（突增/突降，含无突增集误报计数） |
| 研判看板 | 单页看板（热力 + 列表 + 时间轴回放[预聚合帧]）+ 周研判报告（MD/DOCX，数字可溯源） |

## 合规声明

- 本平台**仅使用合成数据**，不含任何真实警务数据或个人隐私数据；
- 分析结论定位于**宏观态势与资源配置辅助**，不用于个人画像与个人预测；
- 使用者须遵守《数据安全法》《个人信息保护法》及公安数据管理相关规定；
  如需接入真实数据，须在合法授权与合规评估前提下自行承担。

## 许可

[Apache-2.0](LICENSE) ｜ 第三方组件：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
