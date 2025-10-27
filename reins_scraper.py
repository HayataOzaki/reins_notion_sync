"""Selenium automation layer for interacting with REINS."""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import httpx
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

LOGGER = logging.getLogger("scraper")

# ---------------------------------------
# ログインページと要素ID（2025-10時点）
# ---------------------------------------
LOGIN_URL = "https://system.reins.jp/login/main/KG/GKG001200"

# ログイン画面の要素（あなたの実環境で確認済みのID）
LOGIN_ID_INPUT_ID = "__BVID__13"
LOGIN_PW_INPUT_ID = "__BVID__16"
TERMS_CHECKBOX_ID = "__BVID__20"

# ボタン（data-v は動的なので使わない）
LOGIN_BUTTON_SELECTOR = "button.btn.p-button.p-3.large.btn-primary.btn-block.px-0"
RENTAL_SEARCH_BUTTON_SELECTOR = "button.btn.p-button.btn-primary.btn-block.px-0"

# 検索ページの主たるコントロール
SEARCH_BUTTON_TEXT = "検索"
DETAIL_BUTTON_SELECTOR = "button.btn.p-button.m-0.py-0.btn-outline.btn-block.px-0"


FieldDefinition = Dict[str, object]

# Known field definitions for locating and interacting with the 検索 form controls.
FIELD_DEFINITIONS: Dict[str, FieldDefinition] = {
    "駅名": {
        "locators": [
            (By.CSS_SELECTOR, "input[placeholder='駅名']"),
            (By.CSS_SELECTOR, "input[placeholder*='駅']"),
            (By.CSS_SELECTOR, "input[name*='station']"),
            (By.CSS_SELECTOR, "input[data-testid*='station']"),
        ],
        "labels": [["駅名"], ["駅", "沿線"]],
        "input_kind": "text",
    },
    "賃料下限": {
        "locators": [
            (By.CSS_SELECTOR, "input[name='rentMin']"),
            (By.CSS_SELECTOR, "input[name*='RentMin']"),
            (By.CSS_SELECTOR, "input[name*='rent'][name*='Min']"),
            (By.CSS_SELECTOR, "input[aria-label*='賃料'][aria-label*='下限']"),
        ],
        "labels": [["賃料", "下限"], ["賃料（下限）"]],
        "input_kind": "text",
    },
    "賃料上限": {
        "locators": [
            (By.CSS_SELECTOR, "input[name='rentMax']"),
            (By.CSS_SELECTOR, "input[name*='RentMax']"),
            (By.CSS_SELECTOR, "input[name*='rent'][name*='Max']"),
            (By.CSS_SELECTOR, "input[aria-label*='賃料'][aria-label*='上限']"),
        ],
        "labels": [["賃料", "上限"], ["賃料（上限）"]],
        "input_kind": "text",
    },
    "間取部屋数": {
        "locators": [
            (By.CSS_SELECTOR, "select[name='layoutMin']"),
            (By.CSS_SELECTOR, "select[name*='layout']"),
            (By.CSS_SELECTOR, "select[data-testid*='layout']"),
        ],
        "labels": [["間取"], ["間取部屋数"], ["間取り"]],
        "input_kind": "select",
    },
    "駅徒歩": {
        "locators": [
            (By.CSS_SELECTOR, "input[name='walkMinutes']"),
            (By.CSS_SELECTOR, "input[name*='walk']"),
            (By.CSS_SELECTOR, "input[aria-label*='駅徒歩']"),
        ],
        "labels": [["駅徒歩"], ["徒歩"]],
        "input_kind": "text",
    },
    "駐車場在否": {
        "locators": [
            (By.CSS_SELECTOR, "select[name='parking']"),
            (By.CSS_SELECTOR, "select[name*='parking']"),
            (By.CSS_SELECTOR, "select[data-testid*='parking']"),
        ],
        "labels": [["駐車場"], ["駐車場在否"]],
        "input_kind": "select",
    },
    "種別": {
        "locators": [
            (By.CSS_SELECTOR, "select[name='propertyType']"),
            (By.CSS_SELECTOR, "select[name*='shubetsu']"),
            (By.CSS_SELECTOR, "select[data-testid*='type']"),
        ],
        "labels": [["種別"], ["物件種別"]],
        "input_kind": "select",
    },
    "登録年月日": {
        "locators": [
            (By.CSS_SELECTOR, "select[name*='register']"),
            (By.CSS_SELECTOR, "select[name*='regist']"),
            (By.CSS_SELECTOR, "select[data-testid*='登録']"),
        ],
        "labels": [["登録年月日"], ["登録", "年月日"]],
        "input_kind": "select",
    },
    "新築": {
        "locators": [
            (By.CSS_SELECTOR, "input[name='newBuilding']"),
            (By.CSS_SELECTOR, "input[name*='new']"),
            (By.CSS_SELECTOR, "input[type='checkbox'][data-testid*='新築']"),
        ],
        "labels": [["新築"]],
        "input_kind": "checkbox",
    },
    "ペット可": {
        "locators": [
            (By.CSS_SELECTOR, "input[name='pet']"),
            (By.CSS_SELECTOR, "input[name*='pet']"),
            (By.CSS_SELECTOR, "input[type='checkbox'][data-testid*='ペット']"),
        ],
        "labels": [["ペット可"], ["ペット"]],
        "input_kind": "checkbox",
    },
}


@dataclass
class ReinsCredentials:
    username: str
    password: str


@dataclass
class ReinsSearchResult:
    details: Dict[str, str]
    pdf_path: Optional[Path]


class ReinsScraper:
    """High level automation driver for REINS."""

    def __init__(
        self,
        credentials: ReinsCredentials,
        driver: Optional[WebDriver] = None,
        *,
        headless: bool = False,
        wait_timeout: int = 30,
    ) -> None:
        self.credentials = credentials
        self.driver = driver or self._create_driver(headless=headless)
        self.wait_timeout = wait_timeout
        self.wait = WebDriverWait(self.driver, wait_timeout)

    # ------------------------------------------------------------------
    # Context manager helpers
    # ------------------------------------------------------------------
    def __enter__(self) -> "ReinsScraper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # LOGIN
    # ------------------------------------------------------------------
    def login(self) -> None:
        """ログインページを開き、ID/PW入力 → 規約チェック → ログイン押下。"""
        LOGGER.info("Opening REINS login page: %s", LOGIN_URL)
        self.driver.get(LOGIN_URL)

        # 入力欄を待つ（IDで待機しつつ、無ければフォールバック）
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, LOGIN_ID_INPUT_ID)))
            input_id = self.driver.find_element(By.ID, LOGIN_ID_INPUT_ID)
            input_pw = self.driver.find_element(By.ID, LOGIN_PW_INPUT_ID)
        except Exception:
            # 予防：name/type でフォールバック（環境差異向け）
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input[type='password']")))
            inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
            pwds = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if not inputs or not pwds:
                raise RuntimeError("ログイン入力欄が見つかりませんでした。")
            input_id = inputs[0]
            input_pw = pwds[0]

        input_id.clear()
        input_id.send_keys(self.credentials.username)
        input_pw.clear()
        input_pw.send_keys(self.credentials.password)

        # 規約チェック（Vue対策: JSで checked + イベントを発火）
        LOGGER.info("Clicking terms checkbox...")
        checkbox = self.wait.until(EC.presence_of_element_located((By.ID, TERMS_CHECKBOX_ID)))
        self.driver.execute_script(
            """
            const cb = arguments[0];
            if (!cb.checked) {
                cb.checked = true;
                cb.dispatchEvent(new Event('input', { bubbles: true }));
                cb.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """,
            checkbox,
        )

        # ログインボタンが有効になるまで待機（disabled解除 & クリック可能）
        LOGGER.info("Waiting for login button to become enabled...")
        self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, LOGIN_BUTTON_SELECTOR)))
        login_btn = self.driver.find_element(By.CSS_SELECTOR, LOGIN_BUTTON_SELECTOR)

        # 念のため disabled 属性を除去するフォールバックも用意
        if login_btn.get_attribute("disabled"):
            self.driver.execute_script("arguments[0].removeAttribute('disabled');", login_btn)

        # クリック
        self.driver.execute_script("arguments[0].click();", login_btn)
        LOGGER.info("Clicked login button")

        # ページロード完了を待機
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div#app")))
        except Exception:
            self.wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button.btn.p-button")))

        LOGGER.info("✅ Logged into REINS successfully")

    # ------------------------------------------------------------------
    # GO TO RENTAL SEARCH
    # ------------------------------------------------------------------
    def go_to_rental_search(self) -> None:
        """トップから『賃貸 物件検索』ボタンを押下して検索画面へ遷移。"""
        LOGGER.info("Navigating to 賃貸 物件検索")
        self.wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, RENTAL_SEARCH_BUTTON_SELECTOR)))
        buttons = self.driver.find_elements(By.CSS_SELECTOR, RENTAL_SEARCH_BUTTON_SELECTOR)

        target = None
        for b in buttons:
            txt = (b.text or "").strip()
            if "賃貸" in txt and "物件検索" in txt:
                target = b
                break

        if not target:
            # 端UI向けフォールバック
            all_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.btn")
            for b in all_buttons:
                txt = (b.text or "").strip()
                if "賃貸" in txt and "物件検索" in txt:
                    target = b
                    break

        if not target:
            raise RuntimeError("賃貸 物件検索ボタンが見つかりませんでした。")

        before_handles = list(self.driver.window_handles)
        self.driver.execute_script("arguments[0].click();", target)

        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: len(d.window_handles) > len(before_handles)
            )
            LOGGER.debug("Detected new window after navigating to search page")
        except TimeoutException:
            LOGGER.debug("No new window detected after navigation; continuing on current handle")

        self._switch_to_latest_window()
        self._focus_search_form_context()

        # 検索フォーム待機
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='駅名']")))
            LOGGER.info("✅ Search form loaded successfully")
        except Exception:
            self.wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button.btn.p-button")))
            LOGGER.warning("⚠️ Search form not found by '駅名' placeholder, fallback wait used")

        LOGGER.info("✅ Arrived at 賃貸 物件検索 page")

    # ------------------------------------------------------------------
    # SEARCH EXECUTION
    # ------------------------------------------------------------------
    def set_conditions(self, conditions: Dict[str, object]) -> None:
        """検索条件を設定。Notion→REINSマッピングで対応。"""
        LOGGER.info("Applying %d search conditions", len(conditions))
        self._focus_search_form_context()
        self._reset_form()

        for field, value in conditions.items():
            LOGGER.info("Setting condition '%s' to %r", field, value)
            self._apply_condition(field, value)

    def run_search(self, max_results: int = 50) -> List[ReinsSearchResult]:
        """検索実行 → 詳細抽出 → PDF保存。"""
        LOGGER.info("Executing search...")
        self._focus_search_form_context()
        buttons = self.wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button.btn.p-button")))
        search_button = None
        for b in buttons:
            if (b.text or "").strip() == SEARCH_BUTTON_TEXT:
                search_button = b
                break
        if not search_button:
            raise RuntimeError("検索ボタンが見つかりませんでした。")

        self.driver.execute_script("arguments[0].click();", search_button)
        LOGGER.info("Collecting search results...")

        detail_buttons = self.wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, DETAIL_BUTTON_SELECTOR))
        )

        results: List[ReinsSearchResult] = []
        for idx, button in enumerate(detail_buttons[:max_results], start=1):
            try:
                self.driver.execute_script("arguments[0].click();", button)
                self._wait_for_detail_view()

                details = self._extract_details()
                pdf_path = self._download_pdf_if_available()

                results.append(ReinsSearchResult(details=details, pdf_path=pdf_path))
                LOGGER.info(
                    "✅ Result %d collected (fields=%d, pdf=%s)",
                    idx,
                    len(details),
                    "yes" if pdf_path else "no",
                )
            finally:
                self._close_detail_view()

        LOGGER.info("✅ Collected %d result(s)", len(results))
        return results

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _switch_to_latest_window(self) -> None:
        try:
            handles = self.driver.window_handles
        except Exception:
            return
        if not handles:
            return
        current = self.driver.current_window_handle
        latest = handles[-1]
        if current != latest:
            LOGGER.debug("Switching from window %s to %s", current, latest)
            self.driver.switch_to.window(latest)

    def _focus_search_form_context(self, timeout: int = 15) -> None:
        """検索フォームが含まれるウィンドウ/フレームへフォーカス。"""
        target_definition = FIELD_DEFINITIONS.get("駅名", {})
        target_locators: List[Tuple[str, str]] = list(target_definition.get("locators", []))
        if not target_locators:
            target_locators = [(By.CSS_SELECTOR, "input[placeholder*='駅']")]

        def has_target() -> bool:
            for by, value in target_locators:
                try:
                    if self.driver.find_elements(by, value):
                        return True
                except Exception:
                    continue
            return False

        def search_in_frames(depth: int = 0) -> bool:
            if depth > 5:
                return False
            frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            for frame in frames:
                try:
                    self.driver.switch_to.frame(frame)
                except Exception:
                    continue
                if has_target():
                    return True
                if search_in_frames(depth + 1):
                    return True
                try:
                    self.driver.switch_to.parent_frame()
                except Exception:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

            if has_target():
                return

            if search_in_frames():
                LOGGER.debug("Switched into frame containing search form")
                return

            time.sleep(0.5)

        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        raise TimeoutException("検索フォームが見つからず、フレームの切替に失敗しました。")

    def _apply_condition(self, field: str, value: object) -> None:
        """フィールド名→CSSマッピング。必要に応じて拡張。"""
        if value in (None, ""):
            LOGGER.debug("No value provided for %s; skipping", field)
            return

        definition = FIELD_DEFINITIONS.get(field)
        if not definition:
            LOGGER.warning("No field definition for '%s'; skipping", field)
            return

        try:
            element = self._find_field_element(field)
        except TimeoutException as exc:
            LOGGER.error("検索フォームのフィールド '%s' が見つかりません: %s", field, exc)
            raise

        tag_name = (element.tag_name or "").lower()
        input_kind = definition.get("input_kind")

        if input_kind == "select" or tag_name == "select":
            value_text = str(value).strip()
            try:
                Select(element).select_by_visible_text(value_text)
            except NoSuchElementException:
                if not self._select_option_by_text_or_value(element, value_text):
                    raise
            self._dispatch_input_events(element)
        elif input_kind == "checkbox" or (
            tag_name == "input"
            and (element.get_attribute("type") or "").lower() == "checkbox"
        ):
            should_check = self._as_bool(value)
            self._set_checkbox_state(element, should_check)
        else:
            text_value = self._format_input_value(value)
            try:
                element.clear()
            except Exception:
                pass
            element.send_keys(text_value)
            self._dispatch_input_events(element)

    def _reset_form(self) -> None:
        """主要項目を初期化。"""
        for field, definition in FIELD_DEFINITIONS.items():
            input_kind = definition.get("input_kind")
            if input_kind not in {"text", "select", "checkbox"}:
                continue
            try:
                element = self._find_field_element(field, timeout=5)
            except TimeoutException:
                LOGGER.debug("Skipping reset for %s; field not found", field)
                continue

            try:
                if input_kind == "text":
                    try:
                        element.clear()
                    except Exception:
                        pass
                    self.driver.execute_script(
                        "arguments[0].value = '';",
                        element,
                    )
                    self._dispatch_input_events(element)
                elif input_kind == "select":
                    try:
                        Select(element).select_by_index(0)
                    except Exception:
                        options = element.find_elements(By.TAG_NAME, "option")
                        if options:
                            self.driver.execute_script(
                                "arguments[0].selected = true;",
                                options[0],
                            )
                    self._dispatch_input_events(element)
                elif input_kind == "checkbox":
                    self._set_checkbox_state(element, False)
            except Exception as exc:
                LOGGER.debug("Failed to reset field %s: %s", field, exc)

    def _find_field_element(
        self,
        field: str,
        *,
        timeout: Optional[int] = None,
    ) -> WebElement:
        definition = FIELD_DEFINITIONS.get(field)
        if not definition:
            raise TimeoutException(f"フィールド '{field}' の定義が存在しません。")

        locators: List[Tuple[str, str]] = list(definition.get("locators", []))
        label_groups: List[Sequence[str]] = list(definition.get("labels", []))

        deadline = time.monotonic() + float(timeout or self.wait_timeout)
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            try:
                self._focus_search_form_context(timeout=remaining)
            except TimeoutException as exc:
                last_error = exc
                break

            for by, value in locators:
                try:
                    element = self.driver.find_element(by, value)
                    LOGGER.debug("Located field '%s' via selector %s=%s", field, by, value)
                    return element
                except Exception as exc:
                    last_error = exc

            for keywords in label_groups:
                element = self._find_element_by_label_keywords(keywords)
                if element:
                    LOGGER.debug("Located field '%s' via label keywords %s", field, keywords)
                    return element

            for keywords in label_groups:
                element = self._find_element_by_attribute_keywords(keywords)
                if element:
                    LOGGER.debug(
                        "Located field '%s' via attribute keywords %s (JS search)",
                        field,
                        keywords,
                    )
                    return element

            time.sleep(0.3)

        raise TimeoutException(f"フィールド '{field}' の入力欄が見つかりませんでした。") from last_error

    def _find_element_by_label_keywords(self, keywords: Sequence[str]) -> Optional[WebElement]:
        if not keywords:
            return None

        contains_expr = " and ".join(
            f"contains(normalize-space(), \"{kw}\")" for kw in keywords if kw
        )
        if not contains_expr:
            return None

        xpath_candidates = [
            f"//label[{contains_expr}]",
            f"//*[self::span or self::div][{contains_expr}]",
        ]

        for xpath in xpath_candidates:
            try:
                labels = self.driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue
            for label in labels:
                element = self._locate_control_from_label(label)
                if element:
                    return element
        return None

    def _find_element_by_attribute_keywords(
        self, keywords: Sequence[str]
    ) -> Optional[WebElement]:
        usable_keywords = [kw for kw in keywords if kw]
        if not usable_keywords:
            return None

        script = r"""
            const keywords = arguments[0];
            const attrNames = [
                'placeholder',
                'aria-label',
                'name',
                'id',
                'title',
                'data-testid',
                'data-label',
                'data-column',
                'data-field'
            ];

            function normalize(text) {
                if (!text) return '';
                return text.replace(/\s+/g, ' ').trim();
            }

            function matchesText(text) {
                if (!text) return false;
                return keywords.every((kw) => normalize(text).includes(kw));
            }

            function isVisible(el) {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }

            function checkElement(el) {
                if (!el) return false;
                for (const attr of attrNames) {
                    if (matchesText(el.getAttribute(attr))) {
                        return true;
                    }
                }

                const label = el.closest('label');
                if (label && matchesText(label.innerText)) {
                    return true;
                }

                let sibling = el.previousElementSibling;
                for (let i = 0; i < 3 && sibling; i += 1) {
                    if (matchesText(sibling.innerText)) {
                        return true;
                    }
                    sibling = sibling.previousElementSibling;
                }

                const parent = el.parentElement;
                if (parent && matchesText(parent.innerText)) {
                    return true;
                }

                return false;
            }

            const elements = Array.from(document.querySelectorAll('input, select, textarea'));
            for (const el of elements) {
                if (!isVisible(el)) continue;
                if (checkElement(el)) {
                    return el;
                }
            }
            return null;
        """

        try:
            element = self.driver.execute_script(script, usable_keywords)
        except Exception:
            return None

        if isinstance(element, WebElement):
            return element
        return None

    def _locate_control_from_label(self, label: WebElement) -> Optional[WebElement]:
        try:
            for_attr = label.get_attribute("for")
            if for_attr:
                element = self.driver.find_element(By.ID, for_attr)
                if element.is_displayed():
                    return element
        except Exception:
            pass

        try:
            container = label.find_element(
                By.XPATH,
                "./ancestor-or-self::div[contains(@class, 'form-group')][1]",
            )
            controls = container.find_elements(By.CSS_SELECTOR, "input, select, textarea")
            for control in controls:
                if control.is_displayed():
                    return control
        except NoSuchElementException:
            pass
        except Exception:
            pass

        try:
            following_controls = label.find_elements(
                By.XPATH,
                "following::input[1] | following::select[1] | following::textarea[1]",
            )
            for control in following_controls:
                if control.is_displayed():
                    return control
        except Exception:
            pass

        return None

    def _dispatch_input_events(self, element: WebElement) -> None:
        try:
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
                "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                element,
            )
        except Exception:
            LOGGER.debug("Failed to dispatch events for element %s", element)

    def _select_option_by_text_or_value(self, element: WebElement, target: str) -> bool:
        options = element.find_elements(By.TAG_NAME, "option")
        normalized_target = target.strip()
        for option in options:
            option_text = option.text.strip()
            option_value = (option.get_attribute("value") or "").strip()
            if option_text == normalized_target or option_value == normalized_target:
                self.driver.execute_script("arguments[0].selected = true;", option)
                return True
        return False

    def _set_checkbox_state(self, element: WebElement, should_check: bool) -> None:
        try:
            current = element.is_selected()
        except Exception:
            current = None
        if current is not None and current == should_check:
            return
        try:
            self.driver.execute_script(
                "arguments[0].checked = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
                "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                element,
                bool(should_check),
            )
        except Exception:
            try:
                element.click()
                self._dispatch_input_events(element)
            except Exception:
                LOGGER.debug("Failed to toggle checkbox state via click for %s", element)

    @staticmethod
    def _as_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in {"1", "true", "yes", "y", "on", "有", "あり", "可", "○", "◯"}
        return bool(value)

    @staticmethod
    def _format_input_value(value: object) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _extract_details(self) -> Dict[str, str]:
        """詳細画面のラベル/値を抽出。"""
        details: Dict[str, str] = {}
        rows = self.driver.find_elements(By.CSS_SELECTOR, "div.detail-row")
        if not rows:
            rows = self.driver.find_elements(By.CSS_SELECTOR, "div.row")

        for row in rows:
            try:
                label = ""
                value = ""
                for sel in (".label", ".col-3", ".col-sm-3"):
                    els = row.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        label = els[0].text.strip()
                        break
                for sel in (".col", ".col-9", ".col-sm-9"):
                    els = row.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        value = els[0].text.strip()
                        break
                if label:
                    details[label] = value
            except Exception:
                continue
        return details

    def _download_pdf_if_available(self) -> Optional[Path]:
        """『図面参照』PDFがあれば保存。"""
        button = None
        for sel in ("button.btn.p-button.btn-outline", "button.btn.p-button"):
            for b in self.driver.find_elements(By.CSS_SELECTOR, sel):
                if "図面参照" in (b.text or "").strip():
                    button = b
                    break
            if button:
                break

        if not button:
            return None

        pdf_url = button.get_attribute("data-url") or button.get_attribute("href")
        if not pdf_url:
            self.driver.execute_script("arguments[0].click();", button)
            pdf_url = button.get_attribute("data-url") or button.get_attribute("href")
        if not pdf_url:
            return None

        try:
            cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
            resp = httpx.get(pdf_url, timeout=30.0, cookies=cookies)
            resp.raise_for_status()
        except Exception as exc:
            LOGGER.warning("Failed to download PDF: %s", exc)
            return None

        tmp_dir = Path(tempfile.mkdtemp(prefix="reins_pdf_"))
        pdf_path = tmp_dir / "floorplan.pdf"
        pdf_path.write_bytes(resp.content)
        return pdf_path

    def _close_detail_view(self) -> None:
        """詳細を閉じて一覧に戻る。"""
        try:
            close_button = self.driver.find_element(By.CSS_SELECTOR, "button.p-frame-backer")
            self.driver.execute_script("arguments[0].click();", close_button)
            self.wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, DETAIL_BUTTON_SELECTOR))
            )
        except Exception:
            LOGGER.debug("Failed to close detail view or wait for list")

    def _wait_for_detail_view(self) -> None:
        """詳細画面の出現待機。"""
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.p-frame-backer")))
        except Exception:
            LOGGER.debug("Detail view did not appear in time")

    @staticmethod
    def _create_driver(*, headless: bool) -> WebDriver:
        options = ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=ja-JP")
        driver = Chrome(options=options)
        return driver


__all__ = ["ReinsScraper", "ReinsCredentials", "ReinsSearchResult"]
