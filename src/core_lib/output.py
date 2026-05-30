"""Minimal output utility — restored from v3.4.1 scripts/utils/output.py"""
from __future__ import annotations

import json as _json
import sys as _sys
import math
from typing import Any

_JSON_MODE = False


def set_json(on: bool = True) -> None:
    global _JSON_MODE
    _JSON_MODE = on


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def result(data: dict, text: str = "") -> None:
    if _JSON_MODE:
        _sys.stdout.write(
            _json.dumps(_sanitize(data), ensure_ascii=False, default=str) + "\n"
        )
    elif text:
        print(text)
    else:
        print(data)
