"""Utilities for mapping between Notion properties and REINS fields without external CSV."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SearchMapping:
    notion_column: str
    reins_field: str
    input_type: str
    transform: str = ""


@dataclass(frozen=True)
class PropertyMapping:
    reins_element: str
    notion_field: str
    transform: str


SEARCH_MAPPINGS: List[SearchMapping] = [
    SearchMapping("登録日", "登録年月日", "select"),
    SearchMapping("物件種別", "物件種別", "select"),
    SearchMapping("物件種目", "物件種目", "select"),
    SearchMapping("沿線名", "沿線名", "text"),
    SearchMapping("駅名(始点)", "駅名(始点)", "text"),
    SearchMapping("駅名(終点)", "駅名(終点)", "text"),
    SearchMapping("駅より徒歩(分)", "駅より徒歩(分)", "input"),
    SearchMapping("都道府県", "都道府県", "text"),
    SearchMapping("市区町村", "市区町村", "text"),
    SearchMapping("使用部分面積(㎡)下限", "使用部分面積(㎡)下限", "input"),
    SearchMapping("所在階(下限)", "所在階(下限)", "input"),
    SearchMapping("所在階(上限)", "所在階(上限)", "input"),
    SearchMapping("賃料上限(万円)", "賃料上限(万円)", "input"),
    SearchMapping("新築フラグ", "新築フラグ", "checkbox"),
    SearchMapping("築年数(上限)", "築年数上限", "select", "max_age"),
    SearchMapping("部屋数(下限)", "部屋数(下限)", "input"),
    SearchMapping("角部屋フラグ", "角部屋フラグ", "checkbox"),
    SearchMapping("バルコニー方向", "バルコニー方向", "select"),
    SearchMapping("駐車場の有無", "駐車場の有無", "select"),
    SearchMapping("ペット可", "ペット可", "checkbox"),
]

PROPERTY_MAPPINGS: List[PropertyMapping] = [
    PropertyMapping("物件番号", "物件番号", ""),
    PropertyMapping("登録年月日", "登録年月日", "和暦日付"),
    # 追加項目があればここに定義
]


class DataMapper:
    """Provides in-code mapping definitions between Notion and REINS."""

    def __init__(self, base_path: Optional[object] = None) -> None:
        # base_path は後方互換のために受け取るが使用しない
        self.base_path = base_path

    def get_reins_field(self, notion_column: str) -> Optional[SearchMapping]:
        notion_column = notion_column.strip()
        for mapping in SEARCH_MAPPINGS:
            if mapping.notion_column == notion_column:
                return mapping
        return None

    def get_notion_field(self, reins_element: str) -> Optional[PropertyMapping]:
        reins_element = reins_element.strip()
        for mapping in PROPERTY_MAPPINGS:
            if mapping.reins_element == reins_element:
                return mapping
        return None

    def normalize_search_conditions(self, row: Dict[str, object]) -> Dict[str, object]:
        normalized: Dict[str, object] = {}
        for mapping in SEARCH_MAPPINGS:
            value = row.get(mapping.notion_column)
            if value in (None, ""):
                continue
            normalized[mapping.reins_field] = self._normalize_value(mapping, value)
        return normalized

    def map_property_details(self, details: Dict[str, str]) -> Dict[str, object]:
        normalized: Dict[str, object] = {}
        for mapping in PROPERTY_MAPPINGS:
            value = details.get(mapping.reins_element)
            if value in (None, ""):
                continue
            normalized[mapping.notion_field] = self._normalize_property_value(mapping, value)
        name = details.get("物件名") or details.get("建物名")
        if name and "物件名" not in normalized:
            normalized["物件名"] = str(name).strip()
        return normalized

    def _normalize_value(self, mapping: SearchMapping, value: object) -> object:
        if mapping.transform == "max_age":
            return self._convert_max_age_to_year(value)
        if mapping.input_type == "input" and isinstance(value, str):
            return _normalize_numeric(value)
        if mapping.input_type in {"text", "select"}:
            return str(value).strip()
        if mapping.input_type == "checkbox":
            return bool(value)
        return value

    def _normalize_property_value(self, mapping: PropertyMapping, value: str) -> object:
        if mapping.transform == "通貨":
            return convert_currency_to_yen(value)
        if mapping.transform in {"和暦日付", "年月"}:
            return convert_japanese_date(value)
        if mapping.transform == "面積":
            return _normalize_numeric(value)
        if mapping.transform == "pdf":
            return value
        return value.strip()

    def _convert_max_age_to_year(self, value: object) -> Optional[str]:
        try:
            years = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None
        current_year = dt.date.today().year
        target_year = current_year - max(years, 0)
        # REINS側の選択肢は西暦値なので文字列として返す
        return str(target_year)


def _normalize_numeric(raw: object) -> Optional[float]:
    text = str(raw).strip()
    if not text:
        return None
    allowed = {"-", "."}
    normalized = [ch for ch in text if ch.isdigit() or ch in allowed]
    if not normalized:
        return None
    result = "".join(normalized)
    try:
        if "." in result:
            return float(result)
        return int(result)
    except ValueError:
        return None


def convert_currency_to_yen(text: str) -> Optional[int]:
    text = text.strip()
    multiplier = 1
    if "万円" in text:
        multiplier = 10000
    elif "千円" in text:
        multiplier = 1000
    elif "百円" in text:
        multiplier = 100
    numeric = _normalize_numeric(text)
    if numeric is None:
        return None
    return int(float(numeric) * multiplier)


def convert_japanese_date(text: str) -> Optional[str]:
    """Convert simple Japanese era dates (令和/平成/昭和) into ISO date strings."""

    text = text.strip().replace(" ", "").replace("築", "")
    if not text:
        return None

    era_year_map = {
        "令和": 2018,
        "平成": 1988,
        "昭和": 1925,
    }

    for era, offset in era_year_map.items():
        if text.startswith(era):
            remainder = text[len(era):].strip()
            parts = remainder.replace("年", "/").replace("月", "/").replace("日", "").split("/")
            try:
                year = int(parts[0]) + offset
                month = int(parts[1]) if len(parts) > 1 else 1
                day = int(parts[2]) if len(parts) > 2 else 1
            except (ValueError, IndexError):
                return None
            return f"{year:04d}-{month:02d}-{day:02d}"

    # Already in Western format
    try:
        normalized = text.replace("年", "-").replace("月", "-").replace("日", "")
        parts = [int(p) for p in normalized.split("-") if p]
        if len(parts) >= 3:
            return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    except ValueError:
        return None

    return None


__all__ = [
    "DataMapper",
    "SearchMapping",
    "PropertyMapping",
    "convert_japanese_date",
    "convert_currency_to_yen",
]
