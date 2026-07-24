"""
Tests for race_term_display module.

This file is intentionally written against a module that does not yet exist.
``from stable.services import race_term_display`` will raise
``ModuleNotFoundError`` — this is the expected RED state before implementation.

Test case identifiers below refer to ``test_cases.md`` section 7 (formal term
display) and section 10 (query performance).
"""

# ---------------------------------------------------------------------------
# Module-level import that will fail on first run (target module does not
# exist yet).  This prevents any test class in this file from being loaded.
# ---------------------------------------------------------------------------
from stable.services import race_term_display  # noqa: F401  # ModuleNotFoundError expected


from django.test import TestCase


class RaceTermDisplayModuleExistsTest(TestCase):
    """test_cases.md id: 58-64, 89a — batch term resolution module."""

    def test_race_term_display_module_exists(self):
        """Module should be importable (currently ModuleNotFoundError — RED)."""
        self.assertIsNotNone(race_term_display)

    def test_resolve_batch_race_terms_function_exists(self):
        """Batch term resolution should exist as a callable API."""
        from stable.services.race_term_display import resolve_batch_race_terms  # noqa: F811
        self.assertTrue(callable(resolve_batch_race_terms))

    def test_race_name_display_function_exists(self):
        """Single race name display helper should exist."""
        from stable.services.race_term_display import display_race_name  # noqa: F811
        self.assertTrue(callable(display_race_name))

    def test_racecourse_display_function_exists(self):
        """Single racecourse display helper should exist."""
        from stable.services.race_term_display import display_racecourse_name  # noqa: F811
        self.assertTrue(callable(display_racecourse_name))

    def test_race_term_resolver_class_exists(self):
        """RaceTermResolver class should exist for request-scoped batch lookup."""
        from stable.services.race_term_display import RaceTermResolver  # noqa: F811
        self.assertTrue(callable(RaceTermResolver))
