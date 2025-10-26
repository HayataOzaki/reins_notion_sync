"""Notion API client wrappers for syncing REINS search results."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import requests

LOGGER = logging.getLogger("notion")


@dataclass
class NotionSearchJob:
    """Represents a Notion search row that must be processed."""

    page_id: str
    properties: Dict[str, object]


class NotionIntegration:
    """High level helper around the Notion SDK (Notion API direct version)."""

    def __init__(self, token: str, search_db_id: str, property_db_id: str) -> None:
        self.token = token
        self.search_db_id = search_db_id
        self.property_db_id = property_db_id

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

    # ------------------------------------------------------------------
    # Search jobs
    # ------------------------------------------------------------------
    def fetch_pending_search_jobs(self) -> List[NotionSearchJob]:
        """Fetch Notion rows where 検索対象 = True"""
        url = f"https://api.notion.com/v1/databases/{self.search_db_id}/query"
        payload = {
            "filter": {
                "property": "検索対象",
                "checkbox": {"equals": True}
            }
        }

        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()

        results = response.json().get("results", [])
        jobs: List[NotionSearchJob] = []
        for row in results:
            jobs.append(
                NotionSearchJob(
                    page_id=row["id"],
                    properties=self._simplify_properties(row.get("properties", {})),
                )
            )

        LOGGER.info("Found %d pending search job(s)", len(jobs))
        return jobs

    def mark_search_job_complete(self, job: NotionSearchJob, property_ids: Sequence[str]) -> None:
        """Mark job complete and link properties."""
        url = f"https://api.notion.com/v1/pages/{job.page_id}"

        properties: Dict[str, object] = {
            "検索対象": {"checkbox": False},
        }
        if property_ids:
            properties["物件"] = {
                "relation": [{"id": pid} for pid in property_ids]
            }

        response = requests.patch(url, headers=self.headers, json={"properties": properties})
        response.raise_for_status()
        LOGGER.info("Marked search job %s as complete (linked %d properties)", job.page_id, len(property_ids))

    # ------------------------------------------------------------------
    # Property syncing
    # ------------------------------------------------------------------
    def upsert_property(self, property_data: Dict[str, object], pdf_path: Optional[Path] = None) -> Optional[str]:
        """Create or update a property page in Notion."""

        property_number = property_data.get("物件番号")
        page_id: Optional[str] = None
        if property_number:
            page_id = self._find_property_by_number(str(property_number))

        notion_properties = self._build_property_properties(property_data)

        if page_id:
            LOGGER.info("Updating existing property %s", property_number)
            url = f"https://api.notion.com/v1/pages/{page_id}"
            response = requests.patch(url, headers=self.headers, json={"properties": notion_properties})
        else:
            LOGGER.info("Creating property %s", property_number)
            url = "https://api.notion.com/v1/pages"
            payload = {
                "parent": {"database_id": self.property_db_id},
                "properties": notion_properties,
            }
            response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        result = response.json()
        page_id = result["id"]

        if pdf_path and page_id:
            self._upload_pdf(page_id, pdf_path)
        return page_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _simplify_properties(self, properties: Dict[str, dict]) -> Dict[str, object]:
        simplified: Dict[str, object] = {}
        for name, value in properties.items():
            simplified[name] = self._simplify_property_value(value)
        return simplified

    def _simplify_property_value(self, prop: Dict[str, object]) -> object:
        prop_type = prop.get("type")
        if prop_type == "title":
            return "".join(block["plain_text"] for block in prop["title"])
        if prop_type == "rich_text":
            return "".join(block["plain_text"] for block in prop["rich_text"])
        if prop_type == "number":
            return prop.get("number")
        if prop_type == "select":
            option = prop.get("select")
            return option["name"] if option else None
        if prop_type == "multi_select":
            options = prop.get("multi_select", [])
            return [opt.get("name") for opt in options]
        if prop_type == "checkbox":
            return prop.get("checkbox")
        if prop_type == "date":
            date_value = prop.get("date") or {}
            return date_value.get("start")
        if prop_type == "relation":
            return [rel.get("id") for rel in prop.get("relation", [])]
        return None

    def _build_property_properties(self, data: Dict[str, object]) -> Dict[str, object]:
        properties: Dict[str, object] = {}

        title = str(data.get("物件名") or data.get("所在地") or "不明な物件")
        properties["物件名"] = {
            "title": [{"type": "text", "text": {"content": title[:2000]}}],
        }

        text_fields = ["物件番号", "所在地", "間取り", "交通"]
        for field in text_fields:
            value = data.get(field)
            if value:
                properties[field] = {
                    "rich_text": [{"type": "text", "text": {"content": str(value)[:2000]}}]
                }

        number_fields = ["賃料", "管理費", "面積"]
        for field in number_fields:
            value = data.get(field)
            if value is not None:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                properties[field] = {"number": number}

        date_fields = ["登録年月日", "築年月"]
        for field in date_fields:
            value = data.get(field)
            if not value:
                continue
            iso_value = self._ensure_iso_date(str(value))
            if iso_value:
                properties[field] = {"date": {"start": iso_value}}

        return properties

    def _ensure_iso_date(self, value: str) -> Optional[str]:
        try:
            if len(value) == 7 and value.count("-") == 1:
                return f"{value}-01"
            dt.datetime.fromisoformat(value)
            return value
        except ValueError:
            return None

    def _find_property_by_number(self, property_number: str) -> Optional[str]:
        url = f"https://api.notion.com/v1/databases/{self.property_db_id}/query"
        payload = {
            "filter": {
                "property": "物件番号",
                "rich_text": {"equals": property_number}
            },
            "page_size": 1
        }

        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()

        results = response.json().get("results", [])
        return results[0]["id"] if results else None

    def _upload_pdf(self, page_id: str, pdf_path: Path) -> None:
        try:
            with pdf_path.open("rb") as fp:
                files = {"file": (pdf_path.name, fp, "application/pdf")}
                response = requests.post(
                    "https://api.notion.com/v1/files",
                    headers={"Authorization": f"Bearer {self.token}", "Notion-Version": "2022-06-28"},
                    files=files
                )
                response.raise_for_status()
                file_response = response.json()
        except Exception as exc:
            LOGGER.warning("Failed to upload PDF for %s: %s", page_id, exc)
            return

        url = file_response.get("file", {}).get("url")
        if not url:
            LOGGER.warning("Upload response missing URL for %s", page_id)
            return

        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {
            "properties": {
                "図面ファイル": {
                    "files": [{
                        "type": "external",
                        "name": pdf_path.name,
                        "external": {"url": url}
                    }]
                }
            }
        }
        requests.patch(update_url, headers=self.headers, json=payload)
        try:
            pdf_path.unlink()
            if not any(pdf_path.parent.iterdir()):
                pdf_path.parent.rmdir()
        except Exception:
            pass


__all__ = ["NotionIntegration", "NotionSearchJob"]
