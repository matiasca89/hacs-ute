"""Checks that Home Assistant update metadata is complete for every release."""
from __future__ import annotations

import re
from pathlib import Path
import unittest


ADDON_DIR = Path(__file__).parents[1]


class TestReleaseMetadata(unittest.TestCase):
    def test_current_version_has_addon_changelog_entry(self) -> None:
        """Prevent releases that show an empty changelog in Home Assistant."""
        config = (ADDON_DIR / "config.yaml").read_text(encoding="utf-8")
        version_match = re.search(r'^version:\s*["\']?([^"\'\s]+)', config, re.MULTILINE)
        self.assertIsNotNone(version_match, "config.yaml must define a version")
        version = version_match.group(1)

        changelog = (ADDON_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        heading = re.compile(rf"^##\s+\[?{re.escape(version)}\]?\s*$", re.MULTILINE)
        self.assertRegex(
            changelog,
            heading,
            f"ute_addon/CHANGELOG.md needs a section for version {version}",
        )
