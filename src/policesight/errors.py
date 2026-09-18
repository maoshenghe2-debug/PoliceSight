"""PoliceSight 错误码与退出码（统一契约，同 docs/06 §15）。

退出码：0 成功 · 1 可用但有缺失（doctor）· 2 用法错误 · 3 环境不满足 · 4 运行期失败。
错误码：``PS-E<NNN>``（现象 → 原因 → 建议动作）。
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_CHECK_WARN = 1
EXIT_USAGE = 2
EXIT_ENV = 3
EXIT_RUNTIME = 4

ERRORS: dict[str, str] = {
    "PS-E001": "数据目录不存在或为空：请先运行 policesight data generate",
    "PS-E002": "参数越界：cases/seed/days 等取值不满足范围约束",
    "PS-E003": "真值文件损坏或 schema 校验失败：请重新生成数据",
    "PS-E004": "数据质量检查未通过：参考报告中的修复建议",
    "PS-E005": "分析前置数据缺失：请先完成数据生成或导入",
    "PS-E006": "聚类参数退化（单簇无噪声）：建议调小 eps 或增大 min_samples",
    "PS-E007": "报告导出失败：检查输出目录可写与依赖完整性",
    "PS-E008": "Web 服务启动失败：端口占用或依赖缺失",
}


def describe(code: str) -> str:
    """返回「错误码：现象 → 建议动作」的可读描述。"""
    return f"{code}：{ERRORS.get(code, '未知错误')}"
