from __future__ import annotations

import random
import statistics
import unittest
from datetime import datetime, timedelta, timezone

from backend import demographics
from backend import synthetic_population as model

MONDAY = datetime(2026, 10, 5, tzinfo=timezone.utc)


def _simulate(count: int, days: int, seed: int = 7):
    rng = random.Random(seed)
    people = []
    for _ in range(count):
        persona = model.generate_persona(rng)
        items = model.generate_days(rng, persona, first_day=MONDAY, total_days=days)
        people.append((persona, items))
    return people


class SyntheticPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.people = _simulate(1200, 7)

    def test_every_profile_has_a_valid_age_range_and_sex(self):
        for persona, _ in self.people:
            self.assertIn(persona.age_range, demographics.AGE_RANGES)
            low, high = demographics.age_bounds(persona.age_range)
            self.assertTrue(low <= persona.age <= high)
            self.assertIn(persona.sex, ("female", "male"))
            self.assertEqual(persona.model_group, demographics.model_group(persona.age_range))
        self.assertEqual(
            {persona.age_range for persona, _ in self.people}, set(demographics.AGE_RANGES)
        )

    def test_same_seed_gives_the_same_population(self):
        first, second = _simulate(20, 7, seed=3), _simulate(20, 7, seed=3)
        self.assertEqual(
            [(p.age_range, len(items)) for p, items in first],
            [(p.age_range, len(items)) for p, items in second],
        )

    def test_items_never_overlap_so_watch_time_survives_clipping(self):
        # Watch time is clipped at the next event; overlapping items would
        # silently shorten it.
        for _, items in self.people[:300]:
            ordered = sorted(items, key=lambda item: item.occurred_at)
            for current, following in zip(ordered, ordered[1:]):
                self.assertLessEqual(
                    current.occurred_at + timedelta(seconds=current.watched_seconds),
                    following.occurred_at,
                )

    def test_adolescent_girls_use_social_media_more_than_boys(self):
        # Kelly et al. 2018: markedly higher use among girls.
        def median_total(sex):
            return statistics.median(
                sum(item.watched_seconds for item in items) / 60 / 7
                for persona, items in self.people
                if persona.model_group == "adolescent" and persona.sex == sex
            )

        self.assertGreater(median_total("female"), 1.15 * median_total("male"))

    def test_young_adults_are_near_an_hour_a_day(self):
        # Lin et al. 2016: median about 61 minutes a day.
        totals = [
            sum(item.watched_seconds for item in items) / 60 / 7
            for persona, items in self.people
            if persona.model_group == "young_adult"
        ]
        self.assertTrue(40 <= statistics.median(totals) <= 90, statistics.median(totals))

    def test_a_minority_are_heavy_users(self):
        totals = sorted(sum(i.watched_seconds for i in items) / 3600 / 7 for _, items in self.people)
        top_tenth = totals[int(0.9 * len(totals))]
        self.assertGreater(top_tenth, 3 * statistics.median(totals))

    def test_weekends_carry_more_youtube_time_than_weekdays(self):
        by_weekday = [0.0] * 7
        for _, items in self.people:
            for item in items:
                if item.platform == "youtube":
                    by_weekday[item.occurred_at.weekday()] += item.watched_seconds
        self.assertGreater(min(by_weekday[5:]), max(by_weekday[:4]))

    def test_youtube_is_used_in_several_sessions_a_day(self):
        sessions_per_day = []
        for _, items in self.people[:400]:
            youtube = sorted((i for i in items if i.platform == "youtube"), key=lambda i: i.occurred_at)
            if not youtube:
                continue
            sessions, previous_end = 0, None
            for item in youtube:
                if previous_end is None or (item.occurred_at - previous_end).total_seconds() > 300:
                    sessions += 1
                previous_end = item.occurred_at + timedelta(seconds=item.watched_seconds)
            sessions_per_day.append(sessions / 7)
        self.assertTrue(1.5 <= statistics.median(sessions_per_day) <= 5, statistics.median(sessions_per_day))


if __name__ == "__main__":
    unittest.main()
