"""Image metadata must win over a stale deployment environment."""
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from app import settings


class ImageReleaseCommitTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.marker = self.root / ".umanews-release-commit"
        base = patch.object(settings, "BASE_DIR", self.root / "server")
        base.start()
        self.addCleanup(base.stop)

    def test_baked_commit_wins_over_stale_or_missing_environment(self):
        self.marker.write_text("b" * 40 + "\n", encoding="ascii")
        for environment in ({"UMANEWS_RELEASE_COMMIT": "a" * 40}, {}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(settings.image_release_commit(), "b" * 40)

    def test_source_checkout_retains_environment_fallback(self):
        with patch.dict(os.environ, {"UMANEWS_RELEASE_COMMIT": "a" * 40}, clear=True):
            self.assertEqual(settings.image_release_commit(), "a" * 40)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.image_release_commit(), "")

    def test_invalid_image_marker_cannot_claim_the_environment_commit(self):
        for value in ("", "unknown", "invalid"):
            self.marker.write_text(value, encoding="ascii")
            with self.subTest(value=value), patch.dict(os.environ, {"UMANEWS_RELEASE_COMMIT": "a" * 40}):
                self.assertEqual(settings.image_release_commit(), value)

    def test_unreadable_image_marker_fails_instead_of_using_stale_environment(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("unreadable")):
            with self.assertRaises(PermissionError):
                settings.image_release_commit()
