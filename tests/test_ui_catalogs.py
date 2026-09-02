from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.crawler import TagCatalog
from stzy_app.models import TagOption
from stzy_app.storage import Preferences
from stzy_app.ui.catalogs import catalog_settings
from stzy_app.ui.catalogs import load_catalog_cache
from stzy_app.ui.catalogs import save_catalog_cache


class UiCatalogsTest(unittest.TestCase):
    def test_catalog_settings_do_not_use_proxy_defaults(self) -> None:
        settings = catalog_settings()

        self.assertEqual(settings.proxy_mode, "off")
        self.assertEqual(settings.proxy_pool, "")
        self.assertEqual(settings.proxy_api_url, "")

    def test_catalog_cache_round_trips_through_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preferences = Preferences(Path(tmpdir) / "stzy.db")
            save_catalog_cache(
                preferences,
                {"200": {"1": "语文"}, "300": {"2": "数学"}},
                {
                    "200": TagCatalog(
                        {
                            "provinceCode": [
                                TagOption("provinceCode", "370000", "山东"),
                            ]
                        }
                    ),
                    "300": TagCatalog({}),
                },
            )

            subject_options, catalogs, updated_at = load_catalog_cache(preferences)

        self.assertEqual(subject_options["200"]["1"], "语文")
        self.assertEqual(catalogs["200"].as_select_options("provinceCode"), {"370000": "山东"})
        self.assertTrue(updated_at)


if __name__ == "__main__":
    unittest.main()
