"""预警规则加载与校验（YAML 配置驱动）。"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_RULES_PATH = Path(__file__).parent / "rules.yaml"
REQUIRED_FIELDS = ("id", "name", "factor", "min_count", "advice")


def load_rules(path: Path | str | None = None) -> dict:
    """加载并校验预警规则 YAML。"""
    with open(path or DEFAULT_RULES_PATH, encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}
    rules = doc.get("rules") or []
    if not rules:
        raise ValueError("PS-E002：预警规则为空（rules.yaml 需至少一条规则）")
    for rule in rules:
        missing = [field for field in REQUIRED_FIELDS if field not in rule]
        if missing:
            raise ValueError(f"PS-E002：规则 {rule.get('id', '?')} 缺少字段 {', '.join(missing)}")
    return doc
