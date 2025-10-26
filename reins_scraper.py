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

LOGIN_URL = "https://system.reins.jp/login/main/KG/GKG001200"


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

    def __init__(self, credentials: ReinsCredentials, driver: Optional[WebDriver] = None, *, headless: bool = True, wait_timeout: int = 20) -> None:
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
    # High level flow
    # ------------------------------------------------------------------
    def login(self) -> None:
        LOGGER.info("Navigating to login page")
        self.driver.get(LOGIN_URL)
        self.wait.until(EC.presence_of_element_located((By.NAME, "userId")))
        self.driver.find_element(By.NAME, "userId").send_keys(self.credentials.username)
        self.driver.find_element(By.NAME, "password").send_keys(self.credentials.password)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self._accept_terms()
        LOGGER.info("Logged into REINS")

    def _accept_terms(self) -> None:
        try:
            label = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "label.custom-control-label, label[for='__BVID__20']"))
            )
            label.click()
        except Exception:
            LOGGER.debug("No terms checkbox found")
            return

        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.btn.p-button.btn-primary.btn-block.px-0")
        for button in buttons:
            if "賃貸" in button.text:
                button.click()
                return

    def set_conditions(self, conditions: Dict[str, object]) -> None:
        LOGGER.info("Applying %d search conditions", len(conditions))
        self._reset_form()
        for field, value in conditions.items():
            self._apply_condition(field, value)

    def run_search(self, max_results: int = 50) -> List[ReinsSearchResult]:
        search_button = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn.p-button.btn-primary.btn-block.px-0"))
        )
        search_button.click()
        LOGGER.info("Search executed, collecting results")

        detail_buttons = self.wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button.btn.p-button.m-0.py-0.btn-outline.btn-block.px-0"))
        )
        results: List[ReinsSearchResult] = []
        for button in detail_buttons[:max_results]:
            self.driver.execute_script("arguments[0].click();", button)
            self._wait_for_detail_view()
            details = self._extract_details()
            pdf_path = self._download_pdf_if_available()
            results.append(ReinsSearchResult(details=details, pdf_path=pdf_path))
            self._close_detail_view()
        LOGGER.info("Collected %d result(s)", len(results))
        return results

    # ------------------------------------------------------------------
    # Low level helpers
    # ------------------------------------------------------------------
    def _apply_condition(self, field: str, value: object) -> None:
        selector_map = {
            "駅名": "input[placeholder='駅名']",
            "賃料下限": "input[name='rentMin']",
            "賃料上限": "input[name='rentMax']",
            "間取部屋数": "select[name='layoutMin']",
            "駅徒歩": "input[name='walkMinutes']",
            "駐車場在否": "select[name='parking']",
        }
        selector = selector_map.get(field)
        if not selector:
            LOGGER.debug("No selector mapping for %s", field)
            return

        element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        tag_name = element.tag_name.lower()
        if tag_name == "select":
            from selenium.webdriver.support.ui import Select

            select = Select(element)
            select.select_by_visible_text(str(value))
        else:
            element.clear()
            text_value = self._format_input_value(value)
            element.send_keys(text_value)

    def _reset_form(self) -> None:
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
        LOGGER.debug("Extracting detail view information")
        details: Dict[str, str] = {}
        rows = self.driver.find_elements(By.CSS_SELECTOR, "div.detail-row")
        if not rows:
            rows = self.driver.find_elements(By.CSS_SELECTOR, "div.row")
        for row in rows:
            try:
                label = row.find_element(By.CSS_SELECTOR, ".label, .col-3, .col-sm-3").text.strip()
                value = row.find_element(By.CSS_SELECTOR, ".col, .col-9, .col-sm-9").text.strip()
                if label:
                    details[label] = value
            except Exception:
                continue
        return details

    def _download_pdf_if_available(self) -> Optional[Path]:
        try:
            pdf_button = self.driver.find_element(By.CSS_SELECTOR, "button.btn.p-button.btn-outline")
        except Exception:
            return None

        pdf_url = pdf_button.get_attribute("data-url") or pdf_button.get_attribute("href")
        if not pdf_url:
            try:
                self.driver.execute_script("arguments[0].click();", pdf_button)
            except Exception:
                return None
            pdf_url = pdf_button.get_attribute("data-url")
        if not pdf_url:
            return None

        try:
            cookies = {cookie["name"]: cookie["value"] for cookie in self.driver.get_cookies()}
            response = httpx.get(pdf_url, timeout=30.0, cookies=cookies)
            response.raise_for_status()
        except Exception as exc:
            LOGGER.warning("Failed to download PDF: %s", exc)
            return None

        tmp_dir = Path(tempfile.mkdtemp())
        pdf_path = tmp_dir / "floorplan.pdf"
        pdf_path.write_bytes(response.content)
        return pdf_path

    def _close_detail_view(self) -> None:
        try:
            close_button = self.driver.find_element(By.CSS_SELECTOR, "button.p-frame-backer")
            self.driver.execute_script("arguments[0].click();", close_button)
        except Exception:
            LOGGER.debug("Failed to close detail view")

    def _wait_for_detail_view(self) -> None:
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
        driver = Chrome(options=options)
        return driver


__all__ = ["ReinsScraper", "ReinsCredentials", "ReinsSearchResult"]
