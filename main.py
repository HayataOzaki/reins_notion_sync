"""Entry point for the REINS → Notion synchronization workflow."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from data_mapper import DataMapper
from notion_integration import NotionIntegration, NotionSearchJob
from reins_scraper import ReinsCredentials, ReinsScraper


def configure_logging(base_path: Path) -> None:
    logs_dir = base_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    scraper_handler = logging.FileHandler(logs_dir / "scraper.log")
    scraper_handler.setFormatter(formatter)
    logging.getLogger("scraper").addHandler(scraper_handler)

    reins_handler = logging.FileHandler(logs_dir / "reins_to_notion.log")
    reins_handler.setFormatter(formatter)
    logging.getLogger("reins").addHandler(reins_handler)

    notion_handler = logging.FileHandler(logs_dir / "notion_upload.log")
    notion_handler.setFormatter(formatter)
    logging.getLogger("notion").addHandler(notion_handler)


def main() -> None:
    base_path = Path(__file__).resolve().parent
    configure_logging(base_path)
    load_dotenv(dotenv_path=base_path / ".env")

    notion_token = os.environ["NOTION_TOKEN"]
    search_db_id = os.environ["NOTION_DB_SEARCH"]
    property_db_id = os.environ["NOTION_DB_PROPERTY"]
    reins_id = os.environ["REINS_ID"]
    reins_password = os.environ["REINS_PASSWORD"]

    headless_env = os.getenv("REINS_HEADLESS", "true").strip().lower()
    headless = headless_env not in {"0", "false", "no"}

    mapper = DataMapper(base_path)
    notion = NotionIntegration(notion_token, search_db_id, property_db_id)
    credentials = ReinsCredentials(username=reins_id, password=reins_password)

    jobs = notion.fetch_pending_search_jobs()
    if not jobs:
        logging.getLogger("reins").info("No pending search jobs found")
        return

    with ReinsScraper(credentials, headless=headless) as scraper:
        scraper.login()
        scraper.go_to_rental_search()
        for job in jobs:
            try:
                process_search_job(job, scraper, mapper, notion)
            except Exception:
                logging.getLogger("reins").exception("Failed to process job %s", job.page_id)


def process_search_job(job: NotionSearchJob, scraper: ReinsScraper, mapper: DataMapper, notion: NotionIntegration) -> None:
    logger = logging.getLogger("reins")
    logger.info("Processing search job %s", job.page_id)

    conditions = mapper.normalize_search_conditions(job.properties)
    if not conditions:
        logger.warning("No search conditions for job %s", job.page_id)
        notion.mark_search_job_complete(job, [])
        return

    scraper.set_conditions(conditions)
    results = scraper.run_search(max_results=50)
    property_ids: List[str] = []

    for result in results:
        property_payload = mapper.map_property_details(result.details)
        if not property_payload:
            continue
        page_id = notion.upsert_property(property_payload, result.pdf_path)
        if page_id:
            property_ids.append(page_id)

    notion.mark_search_job_complete(job, property_ids)


if __name__ == "__main__":
    main()
