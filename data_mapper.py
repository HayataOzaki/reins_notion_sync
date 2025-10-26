"""Utilities for loading and transforming mapping definitions between Notion and REINS."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


@dataclass(frozen=True)
class SearchMapping:
    """Represents a mapping from a Notion search column to a REINS form field."""

    notion_column: str
    reins_field: str
    input_type: str
    notes: str

    @classmethod
    def from_series(cls, series: pd.Series) -> "SearchMapping":
        return cls(
            notion_column=str(series["Notion列名"]).strip(),
            reins_field=str(series["REINS項目"]).strip(),
            input_type=str(series["入力方式"]).strip(),
            notes=str(series.get("備考", "") or "")
        )


@dataclass(frozen=True)
class PropertyMapping:
    """Represents a mapping from a REINS property detail element to a Notion property field."""

    reins_element: str
    notion_field: str
    transform: str
    notes: str

    @classmethod
    def from_series(cls, series: pd.Series) -> "PropertyMapping":
        return cls(
            reins_element=str(series["REINS要素"]).strip(),
            notion_field=str(series["Notionカラム"]).strip(),
            transform=str(series["変換"]).strip(),
            notes=str(series.get("変換内容", "") or ""),
        )


class DataMapper:
    """Loads mapping CSV files and exposes handy lookup helpers."""

    def __init__(self, base_path: Optional[Path] = None) -> None:
        self.base_path = Path(base_path or Path(__file__).resolve().parent)

    @property
    @lru_cache(maxsize=1)
    def search_mappings(self) -> List[SearchMapping]:
        csv_path = self.base_path / "data" / "notion_search_to_reins.csv"
        df = pd.read_csv(csv_path)
        return [SearchMapping.from_series(row) for _, row in df.iterrows()]

    @property
    @lru_cache(maxsize=1)
    def property_mappings(self) -> List[PropertyMapping]:
        csv_path = self.base_path / "data" / "reins_property_to_notion.csv"
        df = pd.read_csv(csv_path)
        return [PropertyMapping.from_series(row) for _, row in df.iterrows()]

    def get_reins_field(self, notion_column: str) -> Optional[SearchMapping]:
        notion_column = notion_column.strip()
        for mapping in self.search_mappings:
            if mapping.notion_column == notion_column:
                return mapping
        return None

    def get_notion_field(self, reins_element: str) -> Optional[PropertyMapping]:
        reins_element = reins_element.strip()
        for mapping in self.property_mappings:
            if mapping.reins_element == reins_element:
                return mapping
        return None

    def normalize_search_conditions(self, row: Dict[str, object]) -> Dict[str, object]:
        """Normalize a Notion search row into REINS form field values."""

        normalized: Dict[str, object] = {}
        for mapping in self.search_mappings:
            value = row.get(mapping.notion_column)
            if value in (None, ""):
                continue
            normalized[mapping.reins_field] = self._normalize_value(mapping, value)
        return normalized

    def map_property_details(self, details: Dict[str, str]) -> Dict[str, object]:
        """Normalize REINS property details into Notion payload."""

        normalized: Dict[str, object] = {}
        for mapping in self.property_mappings:
            value = details.get(mapping.reins_element)
            if value in (None, ""):
                continue
            normalized[mapping.notion_field] = self._normalize_property_value(mapping, value)
        name = details.get("物件名") or details.get("建物名")
        if name and "物件名" not in normalized:
            normalized["物件名"] = str(name).strip()
        return normalized

    def _normalize_value(self, mapping: SearchMapping, value: object) -> object:
        if mapping.input_type == "input" and isinstance(value, str):
            return _normalize_numeric(value)
        if mapping.input_type == "text":
            return str(value).strip()
        if mapping.input_type == "select":
            return str(value).strip()
        if mapping.input_type == "checkbox":
            return bool(value)
        return value

    def _normalize_property_value(self, mapping: PropertyMapping, value: str) -> object:
        transform = mapping.transform
        if transform == "通貨":
            return convert_currency_to_yen(value)
        if transform in {"和暦日付", "年月"}:
            return convert_japanese_date(value)
        if transform == "面積":
            return _normalize_numeric(value)
        if transform == "pdf":
            return value
        return value.strip()


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
