"""Notion API client wrappers for syncing REINS search results."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
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

        notion_version = os.getenv("NOTION_VERSION", "2022-06-28")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": notion_version,
        }
        self.property_schema = self._fetch_property_schema()

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
        LOGGER.debug(
            "Notion properties prepared for %s: %s",
            property_number or "新規物件",
            list(notion_properties.keys()),
        )

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
        if response.status_code >= 400:
            LOGGER.error("Notion API error %s: %s", response.status_code, response.text)
            response.raise_for_status()
        else:
            LOGGER.debug("Notion response: %s", response.text)
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
        schema = self.property_schema

        for name, value in data.items():
            if value in (None, "", [], {}, ()):
                continue
            prop_meta = schema.get(name)
            if not prop_meta:
                LOGGER.debug("Skipping property '%s' (not present in Notion schema)", name)
                continue

            prop_type = prop_meta.get("type")
            try:
                notion_value = self._convert_value_for_notion(prop_type, value)
            except Exception:
                LOGGER.debug("Failed to convert value for property '%s'; skipping", name, exc_info=True)
                continue

            if notion_value is not None:
                properties[name] = notion_value

        # Ensure at least one title value exists; Notion requires it.
        if not any(meta.get("type") == "title" for meta in schema.values()):
            LOGGER.warning("Notion database %s has no title property; cannot create pages", self.property_db_id)
        else:
            title_name = next(
                (key for key, meta in schema.items() if meta.get("type") == "title"),
                None,
            )
            if title_name and title_name not in properties:
                fallback = str(data.get(title_name) or data.get("物件番号") or "物件")
                properties[title_name] = {
                    "title": [{"type": "text", "text": {"content": fallback[:2000]}}]
                }

        return properties

    def _convert_value_for_notion(self, prop_type: str, value: object) -> Optional[Dict[str, object]]:
        if prop_type == "title":
            content = str(value)
            if not content:
                return None
            return {"title": [{"type": "text", "text": {"content": content[:2000]}}]}

        if prop_type == "rich_text":
            if isinstance(value, dict):
                text = str(value.get("text") or value.get("content") or "").strip()
                url = value.get("url")
                if not text:
                    return None
                rich_text: Dict[str, object] = {
                    "type": "text",
                    "text": {"content": text[:2000], "link": {"url": url} if url else None},
                }
                if rich_text["text"]["link"] is None:
                    del rich_text["text"]["link"]
                return {"rich_text": [rich_text]}
            content = str(value)
            if not content:
                return None
            return {"rich_text": [{"type": "text", "text": {"content": content[:2000]}}]}

        if prop_type == "number":
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return {"number": number}

        if prop_type == "url":
            if isinstance(value, dict):
                link = str(value.get("url") or value.get("text") or "").strip()
            else:
                link = str(value).strip()
            if not link:
                return None
            return {"url": link[:2000]}

        if prop_type == "checkbox":
            if isinstance(value, str):
                normalized = value.strip().lower()
                truthy = {"true", "yes", "1", "有", "あり", "可"}
                falsy = {"false", "no", "0", "無", "なし", "不可"}
                if normalized in truthy:
                    return {"checkbox": True}
                if normalized in falsy:
                    return {"checkbox": False}
            return {"checkbox": bool(value)}

        if prop_type == "date":
            iso_value = self._ensure_iso_date(str(value))
            if not iso_value:
                return None
            return {"date": {"start": iso_value}}

        if prop_type == "select":
            option_name = str(value).strip()
            if not option_name:
                return None
            return {"select": {"name": option_name[:100]}}

        if prop_type == "multi_select":
            items: List[str] = []
            if isinstance(value, (list, tuple, set)):
                items = [str(item).strip() for item in value if str(item).strip()]
            else:
                raw = str(value)
                separators = [",", "、", "\n", "／", "/"]
                for sep in separators[1:]:
                    raw = raw.replace(sep, separators[0])
                items = [item.strip() for item in raw.split(separators[0]) if item.strip()]
            if not items:
                return None
            return {"multi_select": [{"name": item[:100]} for item in items]}

        if prop_type in {"relation", "rollup", "formula", "files"}:
            # Skip complex property types for automatic mapping.
            return None

        # Default fallback: treat as rich text.
        content = str(value)
        if not content:
            return None
        return {"rich_text": [{"type": "text", "text": {"content": content[:2000]}}]}

    def _ensure_iso_date(self, value: str) -> Optional[str]:
        try:
            if len(value) == 7 and value.count("-") == 1:
                return f"{value}-01"
            dt.datetime.fromisoformat(value)
            return value
        except ValueError:
            return None

    def _fetch_property_schema(self) -> Dict[str, dict]:
        url = f"https://api.notion.com/v1/databases/{self.property_db_id}"
        response = requests.get(url, headers=self.headers)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            LOGGER.error("Failed to fetch Notion database schema: %s", response.text)
            raise
        data = response.json()
        properties = data.get("properties", {})
        LOGGER.debug("Fetched Notion property schema with %d properties", len(properties))
        return properties

    def _find_property_by_number(self, property_number: str) -> Optional[str]:
        url = f"https://api.notion.com/v1/databases/{self.property_db_id}/query"
        filter_payload = self._build_property_number_filter(property_number)
        payload = {
            "filter": filter_payload,
            "page_size": 1
        }

        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()

        results = response.json().get("results", [])
        return results[0]["id"] if results else None

    def _build_property_number_filter(self, property_number: str) -> Dict[str, object]:
        """物件番号のプロパティ型に合わせたフィルタを生成。"""
        property_name = "物件番号"
        prop_meta = self.property_schema.get(property_name, {})
        prop_type = prop_meta.get("type")

        if prop_type == "title":
            return {"property": property_name, "title": {"equals": property_number}}
        if prop_type == "rich_text":
            return {"property": property_name, "rich_text": {"equals": property_number}}
        if prop_type == "number":
            number_value: Optional[float] = None
            stripped = property_number.strip()
            try:
                if stripped.isdigit():
                    number_value = int(stripped)
                else:
                    number_value = float(stripped)
            except ValueError:
                number_value = None
            if number_value is not None:
                return {"property": property_name, "number": {"equals": number_value}}
        if prop_type == "select":
            return {"property": property_name, "select": {"equals": property_number}}
        if prop_type == "multi_select":
            return {"property": property_name, "multi_select": {"contains": property_number}}

        # fallback: rich_text として扱う
        return {"property": property_name, "rich_text": {"equals": property_number}}

    def _upload_pdf(self, page_id: str, pdf_path: Path) -> None:
        init_payload = {
            "filename": pdf_path.name,
            "content_type": "application/pdf",
        }
        LOGGER.debug("Initial file upload payload for %s: %s", page_id, init_payload)
        try:
            response = requests.post(
                "https://api.notion.com/v1/file_uploads",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": os.getenv("NOTION_FILE_VERSION", "2025-09-03"),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=init_payload,
            )
        except Exception as exc:
            LOGGER.warning("Failed to initialise Notion file upload for %s: %s", page_id, exc)
            return
        if response.status_code >= 400:
            LOGGER.warning(
                "File upload initialisation failed for %s (status %s): %s",
                page_id,
                response.status_code,
                response.text,
            )
            return

        try:
            file_response = response.json()
        except ValueError:
            LOGGER.warning("File upload initialisation response not JSON for %s", page_id)
            return

        LOGGER.debug("File upload initialise response: %s", file_response)
        upload_id = file_response.get("id")
        upload_url = file_response.get("upload_url")

        if not upload_id or not upload_url:
            LOGGER.warning("Missing upload id/url for %s in response %s", page_id, file_response)
            return

        try:
            with pdf_path.open("rb") as fp:
                send_headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": os.getenv("NOTION_FILE_VERSION", "2025-09-03"),
                }
                files = {"file": (pdf_path.name, fp, "application/pdf")}
                upload_resp = requests.post(upload_url, headers=send_headers, files=files)
                upload_resp.raise_for_status()
        except Exception as exc:
            LOGGER.warning("Failed to send PDF content for %s: %s", page_id, exc)
            return

        file_entry: Dict[str, object] = {
            "type": "file_upload",
            "name": pdf_path.name,
            "file_upload": {"id": upload_id},
        }
        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {
            "properties": {
                "図面": {
                    "files": [file_entry]
                }
            }
        }
        response = requests.patch(update_url, headers=self.headers, json=payload)
        try:
            response.raise_for_status()
            LOGGER.debug("Attached PDF %s to page %s", pdf_path.name, page_id)
        except requests.HTTPError:
            LOGGER.warning("Failed to attach PDF to %s: %s", page_id, response.text)


__all__ = ["NotionIntegration", "NotionSearchJob"]
