"""字段定义、默认值、类型转换与校验。"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Tuple

from .bondmath import BondError, parse_date

FIELD_TYPES = {"number", "date", "text", "textarea", "select", "table"}


def default_payload(fields: List[dict]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for field in fields:
        if field.get("type") == "table":
            data[field["key"]] = [dict(row) for row in field.get("default_rows", [])]
        else:
            data[field["key"]] = field.get("default")
    return data


def _coerce_scalar(field: dict, raw: Any) -> Any:
    kind = field["type"]
    if kind == "number":
        if raw is None or str(raw).strip() == "":
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise BondError(f"{field['label']} 必须是数字") from exc
        if field.get("integer"):
            return int(round(value))
        return value
    if kind == "date":
        if raw is None or str(raw).strip() == "":
            return None
        return parse_date(raw)
    if kind == "select":
        options = field.get("options", [])
        values = [option["value"] for option in options]
        if raw in values:
            return raw
        # 允许前端传字符串形式
        for value in values:
            if str(value) == str(raw):
                return value
        raise BondError(f"{field['label']} 的取值不在可选范围内")
    return "" if raw is None else str(raw)


def normalize(fields: List[dict], payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    data: Dict[str, Any] = {}
    errors: List[str] = []
    for field in fields:
        key = field["key"]
        kind = field["type"]
        if kind == "table":
            rows = payload.get(key)
            if not isinstance(rows, list):
                rows = field.get("default_rows", [])
            cleaned: List[Dict[str, Any]] = []
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                item: Dict[str, Any] = {}
                empty = True
                for column in field.get("columns", []):
                    raw = row.get(column["key"])
                    if raw is not None and str(raw).strip() != "":
                        empty = False
                    try:
                        item[column["key"]] = _coerce_scalar(column, raw)
                    except BondError as exc:
                        errors.append(f"{field['label']} 第 {index} 行：{exc}")
                        item[column["key"]] = None
                if not empty:
                    cleaned.append(item)
            minimum = int(field.get("min_rows", 0))
            if len(cleaned) < minimum:
                errors.append(f"{field['label']} 至少需要 {minimum} 行")
            data[key] = cleaned
            continue

        raw = payload.get(key, field.get("default"))
        try:
            value = _coerce_scalar(field, raw)
        except BondError as exc:
            errors.append(str(exc))
            value = None
        if value is None and field.get("required"):
            errors.append(f"{field['label']} 不能为空")
        data[key] = value
    return data, errors


def validate_fields(fields: List[dict]) -> List[str]:
    problems: List[str] = []
    seen = set()
    for field in fields:
        key = field.get("key")
        if not key:
            problems.append("存在没有 key 的字段")
            continue
        if key in seen:
            problems.append(f"字段 key 重复：{key}")
        seen.add(key)
        kind = field.get("type")
        if kind not in FIELD_TYPES:
            problems.append(f"字段 {key} 的类型不支持：{kind}")
        if kind == "select":
            values = [option.get("value") for option in field.get("options", [])]
            if field.get("default") not in values:
                problems.append(f"字段 {key} 的默认值不在选项里")
        if kind == "table":
            for column in field.get("columns", []):
                if column.get("type") not in {"number", "date", "text", "select"}:
                    problems.append(f"表格字段 {key} 的列 {column.get('key')} 类型不支持")
    return problems


def json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
