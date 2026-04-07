import json
from pathlib import Path
from typing import Any

_data: dict[str, Any] = {}


def load_locale() -> None:
    global _data
    path = Path(__file__).resolve().parent / "locales" / "uk.json"
    with open(path, encoding="utf-8") as f:
        _data = json.load(f)


def t(key: str, **kwargs: Any) -> str:
    if not _data:
        load_locale()
    parts = key.split(".")
    node: Any = _data
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return key
        node = node[p]
    if not isinstance(node, str):
        return key
    if kwargs:
        try:
            return node.format(**kwargs)
        except (KeyError, ValueError):
            return node
    return node


load_locale()
