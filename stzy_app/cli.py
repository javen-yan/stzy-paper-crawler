from __future__ import annotations

import argparse
from dataclasses import asdict

from stzy_app.config import AppSettings
from stzy_app.crawler import CrawlRunner
from stzy_app.models import CrawlFilters


def sample() -> None:
    """Run the small acceptance sample from the implementation plan."""

    local_settings = AppSettings(subject_code="1", subject_name="语文")
    filters = CrawlFilters(
        scenes=["4"],
        years=["2026"],
        ranks=["-1"],
        provinces=["410000"],
        grades=["11"],
        terms=["21"],
        max_pages_per_combo=1,
    )

    runner = CrawlRunner(
        local_settings,
        filters,
        on_log=print,
        on_record=lambda record: print(
            f"{record.status.value}: {record.resource_id} {record.resource_name}"
        ),
        on_progress=lambda stats: print(f"progress: {asdict(stats)}"),
    )
    runner.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="STZY paper crawler helpers")
    parser.add_argument("command", choices=["sample"])
    args = parser.parse_args()
    if args.command == "sample":
        sample()


if __name__ == "__main__":
    main()
