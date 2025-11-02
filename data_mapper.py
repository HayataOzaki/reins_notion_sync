"""Utilities for mapping between Notion properties and REINS fields without external CSV."""

from __future__ import annotations

import datetime as dt
import unicodedata
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
    PropertyMapping("物件番号", "物件番号", "半角"),
    PropertyMapping("物件番号@1", "物件番号", "半角"),
    PropertyMapping("登録年月日", "登録日", "和暦日付"),
    PropertyMapping("更新年月日", "更新日", "和暦日付"),
    PropertyMapping("物件種目", "物件種目", "半角"),
    PropertyMapping("賃料", "賃料", "通貨"),
    PropertyMapping("共益費", "共益費", ""),
    PropertyMapping("管理費", "管理費", ""),
    PropertyMapping("都道府県名", "都道府県", "半角"),
    PropertyMapping("所在地名１", "所在地名1", "住所"),
    PropertyMapping("所在地名２", "所在地名2", "住所"),
    PropertyMapping("所在地名３", "所在地名3", "住所"),
    PropertyMapping("建物名", "建物名", ""),
    PropertyMapping("部屋番号@1", "部屋番号", "半角"),
    PropertyMapping("広告転載区分", "広告転載区分", ""),
    PropertyMapping("敷金", "敷金", ""),
    PropertyMapping("礼金", "礼金", ""),
    PropertyMapping("保証金", "保証金", ""),
    PropertyMapping("権利金", "権利金", ""),
    PropertyMapping("建物賃貸借区分", "建物賃貸借区分", ""),
    PropertyMapping("建物賃貸借期間", "建物賃貸借期間", ""),
    PropertyMapping("建物賃貸借更新", "建物賃貸借更新", ""),
    PropertyMapping("間取タイプ", "間取タイプ", "半角"),
    PropertyMapping("間取部屋数", "間取部屋数", "数値"),
    PropertyMapping("室１:室タイプ", "室1:室タイプ", "半角"),
    PropertyMapping("室１:室広さ", "室1:室広さ", "数値"),
    PropertyMapping("室２:室タイプ", "室2:室タイプ", "半角"),
    PropertyMapping("室２:室広さ", "室2:室広さ", "数値"),
    PropertyMapping("室３:室タイプ", "室3:室タイプ", "半角"),
    PropertyMapping("室３:室広さ", "室3:室広さ", "数値"),
    PropertyMapping("室４:室タイプ", "室4:室タイプ", "半角"),
    PropertyMapping("室４:室広さ", "室4:室広さ", "数値"),
    PropertyMapping("室５:室タイプ", "室5:室タイプ", "半角"),
    PropertyMapping("室５:室広さ", "室5:室広さ", "数値"),
    PropertyMapping("築年月", "築年月", ""),
    PropertyMapping("建物構造", "建物構造", "半角"),
    PropertyMapping("地上階層", "地上階層", "数値"),
    PropertyMapping("地下階層", "地下階層", "数値"),
    PropertyMapping("所在階", "所在階", "数値"),
    PropertyMapping("バルコニー方向", "バルコニー方向", "半角"),
    PropertyMapping("更新区分", "更新区分", ""),
    PropertyMapping("更新料", "更新料", ""),
    PropertyMapping("その他一時金なし", "その他一時金なし", ""),
    PropertyMapping("その他一時金名称１", "その他一時金名称1", ""),
    PropertyMapping("金額１", "その他一時金金額1", "通貨"),
    PropertyMapping("その他一時金名称２", "その他一時金名称2", ""),
    PropertyMapping("金額２", "その他一時金金額2", "通貨"),
    PropertyMapping("その他月額費名称", "その他月額費名称", ""),
    PropertyMapping("その他月額費金額", "その他月額費金額", "通貨"),
    PropertyMapping("沿線名", "交通1 沿線名", "半角"),
    PropertyMapping("駅名", "交通1 駅名", "半角"),
    PropertyMapping("駅より徒歩", "交通1 駅より徒歩(分)", "数値"),
    PropertyMapping("沿線名#2", "交通2 沿線名", "半角"),
    PropertyMapping("駅名#2", "交通2 駅名", "半角"),
    PropertyMapping("駅より徒歩#2", "交通2 駅より徒歩(分)", "数値"),
    PropertyMapping("沿線名#3", "交通3 沿線名", "半角"),
    PropertyMapping("駅名#3", "交通3 駅名", "半角"),
    PropertyMapping("駅より徒歩#3", "交通3 駅より徒歩(分)", "数値"),
    PropertyMapping("使用部分面積", "使用部分面積(㎡)", "数値"),
    PropertyMapping("保険加入義務", "保険加入義務", "半角"),
    PropertyMapping("保険名称", "保険名称", ""),
    PropertyMapping("保険料", "保険料", "通貨"),
    PropertyMapping("保険期間", "保険期間", ""),
    PropertyMapping("周辺環境１(フリー)", "周辺環境1(フリー)", ""),
    PropertyMapping("距離１", "距離1", "数値"),
    PropertyMapping("周辺環境２(フリー)", "周辺環境2(フリー)", ""),
    PropertyMapping("距離２", "距離2", "数値"),
    PropertyMapping("周辺環境３(フリー)", "周辺環境3(フリー)", ""),
    PropertyMapping("距離３", "距離3", "数値"),
    PropertyMapping("周辺環境４(フリー)", "周辺環境4(フリー)", ""),
    PropertyMapping("距離４", "距離4", "数値"),
    PropertyMapping("周辺環境５(フリー)", "周辺環境5(フリー)", ""),
    PropertyMapping("距離５", "距離5", "数値"),
    PropertyMapping("備考１", "備考1", ""),
    PropertyMapping("備考２", "備考2", ""),
    PropertyMapping("備考３", "備考3", ""),
    PropertyMapping("備考４", "備考4", ""),
    PropertyMapping("入居年月@2", "入居時期詳細", ""),
    PropertyMapping("入居時期", "入居時期", ""),
    PropertyMapping("取引態様", "取引態様", ""),
    PropertyMapping("新築フラグ", "新築フラグ", "bool"),
    PropertyMapping("条件(フリースペース)", "条件(フリースペース)", ""),
    PropertyMapping("現況", "現況", ""),
    PropertyMapping("部屋番号", "角部屋フラグ", "contains:角部屋"),
    PropertyMapping("設備(フリースペース)", "設備(フリースペース)", ""),
    PropertyMapping("設備・条件・住宅性能等", "設備・条件・住宅性能等", ""),
    PropertyMapping("鍵交換代金", "鍵交換代金", "通貨"),
    PropertyMapping("鍵交換区分", "鍵交換区分", ""),
    PropertyMapping("駐車場在否", "駐車場有無", ""),
    PropertyMapping("駐車場月額", "駐車場月額", "通貨"),
    PropertyMapping("契約期間", "契約期間", ""),
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
            if isinstance(value, str):
                stripped = value.strip()
                if stripped in {mapping.reins_element, mapping.notion_field}:
                    continue
            if mapping.notion_field == "物件番号":
                import logging
                logging.getLogger("reins").debug("Detail raw for 物件番号: key=%s value=%r", mapping.reins_element, value)
            normalized[mapping.notion_field] = self._normalize_property_value(mapping, value)
        self._ensure_core_fields(normalized, details)
        if normalized:
            import logging
            logger = logging.getLogger("reins")
            sample_items = list(normalized.items())[:8]
            logger.debug("Normalized property sample: %s", sample_items)
        name = details.get("物件名") or details.get("建物名")
        if name and "物件名" not in normalized:
            normalized["物件名"] = str(name).strip()
        return normalized

    def _ensure_core_fields(self, normalized: Dict[str, object], details: Dict[str, str]) -> None:
        """Ensure必須キー（物件番号・部屋番号など）が欠落していれば補完する。"""
        core_fields = {
            "物件番号": ("物件番号", 3),
            "部屋番号": ("部屋番号", 3),
        }
        for notion_key, (base_label, max_suffix) in core_fields.items():
            if normalized.get(notion_key):
                continue
            candidate = self._pick_detail_value(details, base_label, max_suffix)
            if candidate:
                if notion_key == "物件番号":
                    candidate = _to_half_width(candidate)
                elif notion_key == "部屋番号":
                    candidate = self._clean_room_number(candidate)
                normalized[notion_key] = candidate
                import logging
                logging.getLogger("reins").debug("補完フィールド %s <- %s", notion_key, candidate)

    @staticmethod
    def _pick_detail_value(details: Dict[str, str], base_label: str, max_suffix: int) -> Optional[str]:
        """詳細情報から base_label に一致する最初の値を取得。"""
        candidates = [base_label] + [f"{base_label}@{idx}" for idx in range(1, max_suffix + 1)]
        for key in candidates:
            value = details.get(key)
            if value in (None, ""):
                continue
            stripped = value.strip()
            if not stripped:
                continue
            if stripped in {key, base_label}:
                continue
            return stripped
        return None

    @staticmethod
    def _clean_room_number(value: str) -> str:
        """部屋番号から不要な文言（角部屋など）を除去し半角変換。"""
        text = _to_half_width(value)
        for tag in ("角部屋",):
            text = text.replace(tag, "")
        return text.strip()

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
        if not isinstance(value, str):
            return value
        if mapping.transform == "通貨":
            return convert_currency_to_yen(value)
        if mapping.transform in {"和暦日付", "年月"}:
            return convert_japanese_date(value)
        if mapping.transform == "面積":
            return _normalize_numeric(value)
        if mapping.transform == "数値":
            return _normalize_numeric(value)
        if mapping.transform == "半角":
            return _to_half_width(value)
        if mapping.transform == "住所":
            return _normalize_address(value)
        if mapping.transform == "first_token":
            return _first_token(value)
        if mapping.transform.startswith("contains:"):
            keyword = mapping.transform.split(":", 1)[1]
            return keyword in value
        if mapping.transform == "bool":
            text = value.strip()
            if not text:
                return False
            positives = {"有", "あり", "可", "新築", "○", "◯", "yes", "true", "True"}
            negatives = {"無", "なし", "不可", "中古", "×", "バツ", "no", "false", "False"}
            if text in positives:
                return True
            if text in negatives:
                return False
            return True
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


def _to_half_width(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _first_token(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized
    return normalized.split()[0]

def _normalize_address(text: str) -> str:
    normalized = _to_half_width(text)
    replacements = str.maketrans({
        "ー": "-",
        "−": "-",
        "－": "-",
        "―": "-",
        "—": "-",
    })
    normalized = normalized.translate(replacements)
    return normalized.strip()


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
