from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from backend import demographics
from backend import procedural_population as pp

YEAR_START, YEAR_END = date(2025, 1, 1), date(2025, 12, 31)


class ProceduralPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.year = pp.day_series(YEAR_START, YEAR_END)

    def test_population_covers_every_age_range_and_both_sexes(self):
        profiles = pp.population()
        self.assertGreater(len(profiles), 1200)  # YouTube users among 1,500
        cells = {(p.age_range, p.sex) for p in profiles}
        self.assertEqual(len(cells), len(demographics.AGE_RANGES) * 2)

    def test_the_same_day_always_gives_the_same_values(self):
        # Also when asked as part of a different range.
        march = pp.day_series(date(2025, 3, 1), date(2025, 3, 31))
        column = (date(2025, 3, 10) - YEAR_START).days
        np.testing.assert_allclose(march.hours[:, 9], self.year.hours[:, column])

    def test_weeks_do_not_repeat(self):
        # The old 7-day baseline repeated every week exactly.
        median = np.median(self.year.hours, axis=0)
        weeks = median[: 52 * 7].reshape(52, 7)
        self.assertGreater(len({tuple(np.round(week, 4)) for week in weeks}), 50)

    def test_weekends_and_seasons_show_up_in_the_population(self):
        means = self.year.hours.mean(axis=0)
        weekend = [i for i, day in enumerate(self.year.days) if day.weekday() >= 5]
        workday = [i for i, day in enumerate(self.year.days) if day.weekday() < 4]
        self.assertGreater(means[weekend].mean(), means[workday].mean())

        teens = [i for i, p in enumerate(self.year.profiles) if p.model_group == "adolescent"]
        august = [i for i, day in enumerate(self.year.days) if day.month == 8]
        may = [i for i, day in enumerate(self.year.days) if day.month == 5]
        self.assertGreater(self.year.hours[np.ix_(teens, august)].mean(), self.year.hours[np.ix_(teens, may)].mean())

    def test_habits_drift_over_months(self):
        monthly = np.stack(
            [self.year.hours[:, [i for i, d in enumerate(self.year.days) if d.month == m]].mean(1) for m in range(1, 13)],
            axis=1,
        )
        # Most people's busiest month is clearly above their quietest one.
        ratio = monthly.max(1) / np.maximum(monthly.min(1), 1e-6)
        self.assertGreater(np.median(ratio), 1.5)

    def test_volume_is_calibrated_per_group(self):
        averages = self.year.hours.mean(1) * 60
        def median(group, sex):
            rows = [i for i, p in enumerate(self.year.profiles) if p.model_group == group and p.sex == sex]
            return float(np.median(averages[rows]))
        # Adolescents use YouTube more than older adults; a tail of heavy users exists.
        self.assertGreater(median("adolescent", "male"), median("older", "male"))
        self.assertTrue(15 <= median("young_adult", "female") <= 90)
        self.assertGreater(np.percentile(averages, 90), 3 * np.median(averages))

    def test_metrics_stay_in_range(self):
        self.assertTrue((self.year.hours >= 0).all() and (self.year.hours <= pp.MAX_DAILY_HOURS).all())
        self.assertTrue((self.year.late_night_hours <= self.year.hours + 1e-9).all())
        self.assertTrue(((self.year.fragmentation >= 0) & (self.year.fragmentation <= 1)).all())
        np.testing.assert_allclose(self.year.hourly_seconds.sum(1), self.year.hours.sum(1) * 3600, rtol=1e-6)

    def test_long_ranges_use_a_spread_subset(self):
        decade = pp.day_series(date(2016, 1, 1), date(2025, 12, 31))
        self.assertLessEqual(decade.hours.size, pp.MAX_CELLS)
        self.assertGreater(len(decade.profiles), 100)
        self.assertGreater(len({p.age_range for p in decade.profiles}), 10)


if __name__ == "__main__":
    unittest.main()
