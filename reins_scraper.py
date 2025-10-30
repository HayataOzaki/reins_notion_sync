"""Selenium automation layer for interacting with REINS."""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import httpx
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

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
RENTAL_SEARCH_URL_FRAGMENT = "GBK001310"

# フィールドマッピング（ラベルベース）
FIELD_CONFIG: Dict[str, Dict[str, object]] = {
    "物件種別": {"label": "物件種別１", "type": "select"},
    "物件種目": {"label": "物件種目１", "type": "select"},
    "バルコニー方向": {"label": "バルコニー方向/採光面方向", "type": "select"},
    "使用部分面積(㎡)下限": {"label": "建物使用部分面積", "type": "text", "index": 0},
    "都道府県": {"label": "都道府県名", "type": "text", "occurrence": 0},
    "市区町村": {"label": "所在地名１", "type": "text"},
    "所在階(下限)": {"label": "所在階", "type": "text", "index": 0},
    "所在階(上限)": {"label": "所在階", "type": "text", "index": 1},
    "賃料上限(万円)": {"label": "賃料", "type": "text", "index": 1},
    "部屋数(下限)": {"label": "間取部屋数", "type": "text", "index": 0},
    "沿線名": {"label": "沿線名", "type": "text", "occurrence": 0, "index": 0},
    "駅名(始点)": {"label": "駅名", "type": "text", "occurrence": 0, "index": 0},
    "駅名(終点)": {"label": "駅名", "type": "text", "occurrence": 0, "index": 1},
    "駅より徒歩(分)": {
        "label": "駅から徒歩",
        "type": "text",
        "occurrence": 0,
        "index": 0,
        "unit_index": 0,
    },
    "築年数上限": {"label": "築年月", "type": "select", "index": 0},
    "駐車場の有無": {"label": "駐車場の有無", "type": "select"},
}

RADIO_OPTIONS: Dict[str, Dict[str, str]] = {
    "登録年月日": {
        "指定なし": "指定なし(全期間)",
        "全期間": "指定なし(全期間)",
        "当日": "当日",
        "前日": "前日",
        "3日以内": "３日以内",
        "３日以内": "３日以内",
        "1週間以内": "１週間以内",
        "１週間以内": "１週間以内",
        "一週間以内": "１週間以内",
        "1ヶ月以内": "１ヶ月以内",
        "１ヶ月以内": "１ヶ月以内",
        "一ヶ月以内": "１ヶ月以内",
        "日付を指定": "日付を指定",
    }
}

CHECKBOX_CONFIG: Dict[str, Dict[str, object]] = {
    "新築フラグ": {"label": "新築"},
    "角部屋フラグ": {"label": "角部屋"},
    "ペット可": {"label": "ペット"},
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
        headless: bool = True,
        wait_timeout: int = 30,
    ) -> None:
        self.credentials = credentials
        self.driver = driver or self._create_driver(headless=headless)
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
            self.wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[type='text'], input[type='password']")
                )
            )
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
        time.sleep(0.8)

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

        # 少し待ってからクリック
        time.sleep(1.2)
        self.driver.execute_script("arguments[0].click();", login_btn)
        time.sleep(0.6)
        LOGGER.info("Clicked login button")

        # ログイン後メニューの出現を待機（賃貸 物件検索ボタン）
        post_login_locator = (
            By.XPATH,
            "//button[contains(@class,'btn') and contains(@class,'p-button') "
            "and contains(normalize-space(.),'賃貸') and contains(normalize-space(.),'物件検索')]",
        )
        try:
            WebDriverWait(self.driver, 12).until(EC.element_to_be_clickable(post_login_locator))
        except TimeoutException:
            self._dump_dom("login_post_timeout")
            raise RuntimeError("ログイン後のメニューが表示されませんでした。")

        LOGGER.info("✅ Logged into REINS successfully")

    # ------------------------------------------------------------------
    # GO TO RENTAL SEARCH
    # ------------------------------------------------------------------
    def go_to_rental_search(self) -> None:
        """トップから『賃貸 物件検索』ボタンを押下して検索画面へ遷移。"""
        LOGGER.info("Navigating to 賃貸 物件検索")
        button_locators = [
            (
                By.XPATH,
                "//button[contains(@class,'btn') and contains(@class,'p-button') "
                "and contains(normalize-space(.),'賃貸') and contains(normalize-space(.),'物件検索')]",
            ),
            (By.CSS_SELECTOR, "button.btn.p-button.btn-primary.btn-block.px-0"),
        ]

        target = None
        for locator in button_locators:
            try:
                target = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable(locator))
                if target:
                    break
            except TimeoutException:
                continue

        if not target:
            candidates = []
            for b in self.driver.find_elements(By.CSS_SELECTOR, "button"):
                text = (b.text or "").strip()
                if text:
                    candidates.append(text)
            raise RuntimeError("賃貸 物件検索ボタンが見つかりませんでした。候補: %s" % candidates)

        def attempt_click(button) -> bool:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
            except Exception:
                pass
            time.sleep(0.2)
            try:
                button.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", button)
                except Exception:
                    return False
            time.sleep(0.25)
            return True

        header_locator = (
            By.XPATH,
            "//h1[contains(normalize-space(),'賃貸検索条件入力')]",
        )
        label_locator = (
            By.XPATH,
            "//span[contains(@class,'p-label-title') and contains(normalize-space(),'物件種別')]",
        )

        success = False
        for attempt in range(4):
            if attempt > 0:
                try:
                    target = WebDriverWait(self.driver, 4).until(EC.element_to_be_clickable(button_locators[0]))
                except TimeoutException:
                    try:
                        target = WebDriverWait(self.driver, 4).until(EC.element_to_be_clickable(button_locators[1]))
                    except TimeoutException:
                        target = None
                if target is None:
                    break

            if not attempt_click(target):
                continue

            try:
                WebDriverWait(self.driver, 3).until(EC.presence_of_element_located(header_locator))
                WebDriverWait(self.driver, 3).until(EC.presence_of_element_located(label_locator))
                success = True
                break
            except TimeoutException:
                LOGGER.debug("Search form not detected after click attempt %d; retrying", attempt + 1)
                continue

        if not success:
            LOGGER.debug("Search form still not detected after retries; collecting diagnostic DOM")
            self._dump_dom("search_form_error")
            try:
                WebDriverWait(self.driver, 10).until(EC.presence_of_element_located(label_locator))
            except TimeoutException:
                raise RuntimeError("賃貸検索フォームが表示されませんでした。")

        LOGGER.info("✅ Search form loaded successfully")
        LOGGER.info("✅ Arrived at 賃貸 物件検索 page")

    # ------------------------------------------------------------------
    # SEARCH EXECUTION
    # ------------------------------------------------------------------
    def set_conditions(self, conditions: Dict[str, object]) -> None:
        """検索条件を設定。Notion→REINSマッピングで対応。"""
        LOGGER.info("Applying %d search conditions", len(conditions))
        for field, value in conditions.items():
            self._human_pause(0.15, 0.35)
            self._apply_condition(field, value)

    def run_search(self, max_results: int = 50) -> List[ReinsSearchResult]:
        """検索実行 → 詳細抽出 → PDF保存。"""
        LOGGER.info("Executing search...")
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
        for idx in range(min(max_results, len(detail_buttons))):
            detail_buttons = self.driver.find_elements(By.CSS_SELECTOR, DETAIL_BUTTON_SELECTOR)
            if idx >= len(detail_buttons):
                break
            button = detail_buttons[idx]
            try:
                self.wait.until(EC.element_to_be_clickable(button))
                self.driver.execute_script("arguments[0].click();", button)
            except StaleElementReferenceException:
                detail_buttons = self.driver.find_elements(By.CSS_SELECTOR, DETAIL_BUTTON_SELECTOR)
                if idx >= len(detail_buttons):
                    LOGGER.warning("Detail button %d disappeared; skipping", idx)
                    continue
                button = detail_buttons[idx]
                self.driver.execute_script("arguments[0].click();", button)
            except Exception:
                LOGGER.warning("Failed to click detail button %d; skipping", idx, exc_info=True)
                continue

            try:
                self._wait_for_detail_view()

                details = self._extract_details()
                pdf_path = self._download_pdf_if_available()

                results.append(ReinsSearchResult(details=details, pdf_path=pdf_path))
                LOGGER.info(
                    "✅ Result %d collected (fields=%d, pdf=%s)",
                    idx + 1,
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
    def _apply_condition(self, field: str, value: object) -> None:
        """フィールド名に応じて検索条件を入力する。"""
        if value in (None, ""):
            LOGGER.debug("Empty value for %s, skipping", field)
            return

        # ラジオボタン（登録年月日など）
        if field in RADIO_OPTIONS:
            self._apply_radio_option(field, value)
            return

        # チェックボックス
        checkbox_cfg = CHECKBOX_CONFIG.get(field)
        if checkbox_cfg:
            self._apply_checkbox_option(checkbox_cfg, value, field)
            return

        config = FIELD_CONFIG.get(field)
        if not config:
            LOGGER.debug("No mapping defined for '%s'", field)
            return

        element = self._locate_field_element(field, config)
        if element is None:
            LOGGER.warning("Field '%s' could not be located; skipping value %s", field, value)
            self._dump_dom(f"missing_field_{field}")
            return

        field_type = config.get("type", "text")
        if field_type == "select":
            self._select_option(element, value, field)
            self._human_pause(0.15, 0.3)
        else:
            element.clear()
            element.send_keys(self._format_input_value(value))
            self._human_pause(0.15, 0.3)
            try:
                element.send_keys(Keys.TAB)
            except Exception:
                LOGGER.debug("Failed to advance focus after setting %s", field, exc_info=True)

        if config.get("unit_index") is not None:
            label = config.get("label", field)
            occurrence = config.get("occurrence", 0)
            self._set_walk_unit(label, occurrence, config.get("unit_index", 0))

    @staticmethod
    def _format_input_value(value: object) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _locate_field_element(self, key: str, config: Dict[str, object], *, wait: bool = True):
        selectors = config.get("selectors")
        if selectors:
            element = self._find_element_by_selectors(selectors, wait=wait)
            if element is not None:
                return element

        label = config.get("label", key)
        tag = config.get("tag")
        if not tag:
            tag = "select" if config.get("type") == "select" else "input"
        occurrence = config.get("occurrence", 0)
        index = config.get("index", 0)
        try:
            return self._find_input_by_label(label, tag=tag, occurrence=occurrence, index=index, wait=wait)
        except Exception:
            return None

    def _find_element_by_selectors(self, selectors: Optional[Sequence[str]], wait: bool = True):
        if not selectors:
            return None
        for css in selectors:
            try:
                if wait:
                    return self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))
                return self.driver.find_element(By.CSS_SELECTOR, css)
            except Exception:
                continue
        return None

    def _select_option(self, element, value: object, field: str) -> None:
        select = Select(element)
        text_value = str(value).strip()
        try:
            select.select_by_visible_text(text_value)
            return
        except Exception:
            pass
        try:
            select.select_by_value(text_value)
            return
        except Exception:
            pass
        for option in select.options:
            if text_value in (option.text or ""):
                select.select_by_visible_text(option.text)
                return
        LOGGER.warning("Option '%s' not found for field '%s'", text_value, field)

    def _set_walk_unit(self, label: str, occurrence: int = 0, index: int = 0) -> None:
        try:
            select_el = self._find_input_by_label(
                label,
                tag="select",
                occurrence=occurrence,
                index=index,
                wait=False,
            )
        except Exception:
            return
        try:
            Select(select_el).select_by_value("1")
        except Exception:
            try:
                Select(select_el).select_by_visible_text("分")
            except Exception:
                LOGGER.debug("Failed to fix walk unit select to '分'")

    def _apply_radio_option(self, field: str, value: object) -> None:
        mapping = RADIO_OPTIONS[field]
        key = str(value).strip()
        candidates = {
            key,
            key.replace(" ", ""),
            key.translate(str.maketrans("０１２３４５６７８９", "0123456789")),
        }
        target = None
        for cand in candidates:
            if cand in mapping:
                target = mapping[cand]
                break
        if not target:
            LOGGER.warning("Radio option '%s' is not defined for field '%s'", value, field)
            return

        xpath = (
            "//label[contains(@class,'custom-control-label') and normalize-space()='%s']" % target
        )
        try:
            label_el = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        except TimeoutException:
            LOGGER.warning("Radio label '%s' not found for field '%s'", target, field)
            self._dump_dom(f"missing_radio_{field}")
            return
        try:
            self.driver.execute_script("arguments[0].click();", label_el)
        except Exception:
            label_el.click()

    def _apply_checkbox_option(self, config: Dict[str, Sequence[str]], value: object, field: str) -> None:
        desired = bool(value)
        checkbox = None
        label_el = None

        if "selectors" in config:
            checkbox = self._find_element_by_selectors(config["selectors"], wait=False)

        if checkbox is None and "label" in config:
            try:
                checkbox, label_el = self._find_checkbox_by_label(
                    config["label"], config.get("occurrence", 0)
                )
            except TimeoutException:
                checkbox = None
                label_el = None

        if checkbox is None:
            LOGGER.warning("Checkbox input not found for field '%s'", field)
            self._dump_dom(f"missing_checkbox_{field}")
            return

        self._set_checkbox_state(checkbox, desired, label_el)

    def _set_checkbox_state(self, checkbox, desired: bool, label_el=None) -> None:
        if bool(checkbox.is_selected()) == desired:
            return
        target = label_el or checkbox
        try:
            self.driver.execute_script("arguments[0].click();", target)
        except Exception:
            target.click()
        self._human_pause(0.12, 0.25)

    def _find_input_by_label(
        self,
        label: str,
        *,
        tag: str = "input",
        occurrence: int = 0,
        index: int = 0,
        wait: bool = True,
    ):
        base = (label or "").strip()
        if not base:
            raise TimeoutException("Empty label")

        variants = [
            base,
            base.replace(" ", ""),
            base.replace("　", ""),
            base.translate(str.maketrans("０１２３４５６７８９", "0123456789")),
        ]

        label_el = None
        def resolve_label(driver):
            nonlocal label_el
            for text in variants:
                xpath_exact = f"//span[contains(@class,'p-label-title') and normalize-space()='{text}']"
                nodes = driver.find_elements(By.XPATH, xpath_exact)
                if len(nodes) > occurrence:
                    return nodes[occurrence]
            for text in variants:
                xpath_contains = f"//span[contains(@class,'p-label-title') and contains(normalize-space(), '{text}')]"
                nodes = driver.find_elements(By.XPATH, xpath_contains)
                if len(nodes) > occurrence:
                    return nodes[occurrence]
            return None

        if wait:
            label_el = self.wait.until(lambda d: resolve_label(d))
        else:
            label_el = resolve_label(self.driver)

        if label_el is None:
            raise TimeoutException(f"Label '{label}' not found")

        search_xpaths = [
            f"./following-sibling::*//{tag}",
            f"./parent::*/following-sibling::*//{tag}",
            f"./ancestor::div[contains(@class,'row')][1]//{tag}",
            f"./ancestor::div[contains(@class,'col')][1]//{tag}",
            f"./ancestor::div[contains(@class,'form-group')][1]//{tag}",
            f".//{tag}",
            f"./following::*//{tag}",
        ]

        candidates: List = []
        for xp in search_xpaths:
            try:
                elements = label_el.find_elements(By.XPATH, xp)
            except Exception:
                continue
            for el in elements:
                if el.tag_name.lower() != tag.lower():
                    continue
                if el not in candidates:
                    candidates.append(el)
        if not candidates or len(candidates) <= index:
            raise TimeoutException(f"No {tag} found near label '{label}' (index {index})")

        visible = [el for el in candidates if el.is_displayed()]
        if visible and len(visible) > index:
            return visible[index]
        return candidates[index]

    def _find_checkbox_by_label(self, label: str, occurrence: int = 0):
        base = (label or "").strip()
        variants = [
            base,
            base.replace(" ", ""),
            base.replace("　", ""),
            base.translate(str.maketrans("０１２３４５６７８９", "0123456789")),
        ]

        def resolve(driver):
            for text in variants:
                xpath = f"//label[contains(@class,'custom-control-label') and normalize-space()='{text}']"
                nodes = driver.find_elements(By.XPATH, xpath)
                if len(nodes) > occurrence:
                    return nodes[occurrence]
            for text in variants:
                xpath = f"//label[contains(@class,'custom-control-label') and contains(normalize-space(),'{text}')]"
                nodes = driver.find_elements(By.XPATH, xpath)
                if len(nodes) > occurrence:
                    return nodes[occurrence]
            return None

        label_el = self.wait.until(lambda d: resolve(d))
        if label_el is None:
            return None, None

        input_id = label_el.get_attribute("for")
        checkbox = None
        if input_id:
            try:
                checkbox = self.driver.find_element(By.ID, input_id)
            except Exception:
                checkbox = None
        if checkbox is None:
            try:
                checkbox = label_el.find_element(By.XPATH, "./preceding-sibling::input[@type='checkbox'][1]")
            except Exception:
                checkbox = None

        return checkbox, label_el

    def _dump_dom(self, suffix: str) -> None:
        try:
            path = Path(tempfile.gettempdir()) / f"reins_dom_{suffix}_{int(time.time())}.html"
            path.write_text(self.driver.page_source, encoding="utf-8")
            LOGGER.debug("Saved DOM snapshot: %s", path)
        except Exception:
            LOGGER.debug("Failed to dump DOM snapshot for %s", suffix, exc_info=True)

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

    @staticmethod
    def _human_pause(min_s: float, max_s: float) -> None:
        try:
            duration = (float(min_s) + float(max_s)) / 2.0
        except Exception:
            duration = max_s
        time.sleep(max(0.0, duration))


__all__ = ["ReinsScraper", "ReinsCredentials", "ReinsSearchResult"]
