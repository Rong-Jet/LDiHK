from __future__ import annotations

import unittest
from datetime import date

from backend.population_api import (
    COHORT_TARGET_SIZE,
    MIN_POPULATION_SIZE,
    _PopulationMember,
    _UsageProfile,
    select_comparison_group,
)
from backend.user_profile import ProfileValidationError, validate_profile_payload


def _members(spec: dict[tuple[str, str], int]) -> list[_PopulationMember]:
    members = []
    for (age_range, sex), count in spec.items():
        for index in range(count):
            members.append(
                _PopulationMember(
                    profile=_UsageProfile(),
                    covered_days=7,
                    first_day=date(2026, 10, 1),
                    last_day=date(2026, 10, 7),
                    synthetic=True,
                    user_id=f"{age_range}-{sex}-{index}",
                    age_range=age_range,
                    sex=sex,
                )
            )
    return members


class ComparisonGroupTests(unittest.TestCase):
    def test_same_age_range_and_sex_when_the_group_is_large_enough(self):
        members = _members({("20-24", "female"): COHORT_TARGET_SIZE, ("20-24", "male"): 40, ("25-29", "female"): 40})
        group, payload = select_comparison_group(members, age_range="20-24", sex="female")
        self.assertEqual(len(group), COHORT_TARGET_SIZE)
        self.assertEqual(payload, {"basis": "cohort", "ageRanges": ["20-24", "20-24"], "sex": "female", "size": COHORT_TARGET_SIZE})

    def test_widens_to_neighbouring_age_ranges_first(self):
        members = _members({("20-24", "female"): 10, ("15-19", "female"): 12, ("25-29", "female"): 12, ("20-24", "male"): 50})
        group, payload = select_comparison_group(members, age_range="20-24", sex="female")
        self.assertEqual(payload["ageRanges"], ["15-19", "25-29"])
        self.assertEqual(payload["sex"], "female")
        self.assertTrue(all(member.sex == "female" for member in group))

    def test_drops_sex_when_too_few_of_that_sex_exist(self):
        members = _members({("20-24", "female"): MIN_POPULATION_SIZE - 1, ("20-24", "male"): 40})
        _, payload = select_comparison_group(members, age_range="20-24", sex="female")
        self.assertIsNone(payload["sex"])
        self.assertEqual(payload["basis"], "cohort")

    def test_diverse_or_no_sex_compares_across_sexes(self):
        members = _members({("30-34", "female"): 20, ("30-34", "male"): 20})
        for sex in ("diverse", None):
            group, payload = select_comparison_group(members, age_range="30-34", sex=sex)
            self.assertEqual((len(group), payload["sex"]), (40, None))

    def test_no_profile_compares_with_everyone(self):
        members = _members({("30-34", "female"): 3, ("60-64", "male"): 3})
        group, payload = select_comparison_group(members, age_range=None, sex=None)
        self.assertEqual(payload["basis"], "everyone")
        self.assertEqual(len(group), 6)


class ProfileValidationTests(unittest.TestCase):
    def test_accepts_ranges_sexes_and_clearing(self):
        update = validate_profile_payload({"age_range": "70+", "sex": "prefer_not_to_say"})
        self.assertEqual((update.age_range, update.sex, update.fields), ("70+", None, frozenset({"age_range", "sex"})))
        self.assertEqual(validate_profile_payload({"sex": "diverse"}).fields, frozenset({"sex"}))

    def test_rejects_exact_ages_and_unknown_values(self):
        for payload in ({"age_range": 23}, {"age_range": "21-25"}, {"sex": "other"}, {}):
            with self.subTest(payload=payload):
                with self.assertRaises(ProfileValidationError):
                    validate_profile_payload(payload)


if __name__ == "__main__":
    unittest.main()
