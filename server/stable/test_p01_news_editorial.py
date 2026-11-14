"""T08–T10/T29：事件届次、公告身份、候选溢出和重大增量。"""
from django.test import SimpleTestCase
from stable.services.news_content import ContentBlocked
from stable.services.news_editorial import identity_key, validate_editorial


class EditorialIdentityTests(SimpleTestCase):
    def test_response_region_example_is_scalar_and_matches_allowed_regions(self):
        from stable.services.news_editorial import RESPONSE_SCHEMA
        from stable.services.news_pipeline import REGIONS
        region = RESPONSE_SCHEMA["primary_region"]
        self.assertIsInstance(region, str)
        self.assertEqual(set(region.split("|")), set(REGIONS))
        for value in region.split("|"):
            response = {"priority": "uncertain", "primary_region": value,
                "reason": "缺少身份依据", "identity": {}, "facts": [],
                "comparison": {"event_id": None, "version": 0}}
            self.assertEqual(validate_editorial({}, response, source_scope="jra")["primary_region"], value)
            with self.assertRaises(ContentBlocked):
                validate_editorial({}, {**response, "primary_region": [value]}, source_scope="jra")

    def test_verified_cross_source_aliases_share_one_event(self):
        aliases = {"race:jra:2026102701": "race:123", "race:netkeiba:2026102701": "race:123"}
        first = identity_key("race", {"source_race_id": "2026102701"}, source_scope="jra", aliases=aliases)
        other = identity_key("race", {"canonical_race_id": "123"})
        self.assertEqual(first, other)

    def test_same_race_name_without_edition_cannot_be_identity(self):
        with self.assertRaises(ContentBlocked):
            identity_key("race", {"name": "Autumn Cup"})

    def test_different_editions_and_injury_episodes_remain_separate(self):
        common = {"organizer": "Organizer", "venue": "Venue", "race_number": "5"}
        self.assertNotEqual(identity_key("race", {**common, "local_date": "2026-10-27"}), identity_key("race", {**common, "local_date": "2025-10-27"}))
        self.assertNotEqual(identity_key("injury", {"subject_ref": "horse:jra:1", "episode_ref": "date:2026-10-01:injury"}), identity_key("injury", {"subject_ref": "horse:jra:1", "episode_ref": "date:2026-10-20:injury"}))

    def test_publication_date_is_not_an_injury_episode(self):
        with self.assertRaises(ContentBlocked):
            identity_key("injury", {"subject_ref": "horse:jra:1", "published_at": "2026-10-27"})

    def test_21st_candidate_blocks_instead_of_silently_truncating(self):
        with self.assertRaisesRegex(ContentBlocked, "recall_overflow"):
            validate_editorial({"title": "Title", "blocks": []}, {}, source_scope="jra", candidates=[{} for _ in range(21)])

    def test_model_cannot_supply_unverified_identity_or_tools(self):
        with self.assertRaises(ContentBlocked):
            validate_editorial({"title": "Title", "blocks": []}, {"priority": "major", "identity": {"canonical_race_id": "123"}, "tools": ["publish"]}, source_scope="jra")
