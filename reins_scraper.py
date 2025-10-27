"""Selenium automation layer for interacting with REINS."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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

        self.driver.execute_script("arguments[0].click();", target)

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
        self._reset_form()

        for field, value in conditions.items():
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
    def _apply_condition(self, field: str, value: object) -> None:
        """フィールド名→CSSマッピング。必要に応じて拡張。"""
        selector_map = {
            "駅名": "input[placeholder='駅名']",
            "賃料下限": "input[name='rentMin']",
            "賃料上限": "input[name='rentMax']",
            "間取部屋数": "select[name='layoutMin']",
            "駅徒歩": "input[name='walkMinutes']",
            "駐車場在否": "select[name='parking']",
        }
        selector = selector_map.get(field)
        if not selector or value in (None, ""):
            LOGGER.debug("No selector mapping or empty value for %s", field)
            return

        element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        tag_name = (element.tag_name or "").lower()

        if tag_name == "select":
            from selenium.webdriver.support.ui import Select

            Select(element).select_by_visible_text(str(value))
        else:
            element.clear()
            element.send_keys(self._format_input_value(value))

    def _reset_form(self) -> None:
        """主要項目を初期化。"""
        selectors = {
            "input[placeholder='駅名']": "text",
            "input[name='rentMin']": "text",
            "input[name='rentMax']": "text",
            "input[name='walkMinutes']": "text",
            "select[name='layoutMin']": "select",
            "select[name='parking']": "select",
        }
        for selector, kind in selectors.items():
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
            except Exception:
                continue
            if kind == "text":
                element.clear()
            else:
                from selenium.webdriver.support.ui import Select

                Select(element).select_by_index(0)

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
