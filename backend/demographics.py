"""Age ranges, sex values and model groups shared by the API and the seeder.

Users give an age range in 5-year steps (never an exact age) and optionally a
sex. Comparisons and the risk model group people as follows; the groups follow
the age bands of the studies the model is based on (adolescents 12-17,
young adults 18-32, older adults).
"""

from __future__ import annotations

AGE_RANGES = (
    "13-14",
    "15-19",
    "20-24",
    "25-29",
    "30-34",
    "35-39",
    "40-44",
    "45-49",
    "50-54",
    "55-59",
    "60-64",
    "65-69",
    "70+",
)
# Studies only report female and male; "diverse" is compared with everyone.
SEX_VALUES = ("female", "male", "diverse")
MODEL_GROUPS = ("adolescent", "young_adult", "older")

_MODEL_GROUP_BY_RANGE = {
    "13-14": "adolescent",
    "15-19": "adolescent",
    "20-24": "young_adult",
    "25-29": "young_adult",
    "30-34": "young_adult",
}
# The legacy users.age_bucket / cohort columns name the middle group "adult".
_LEGACY_BUCKET = {"adolescent": "adolescent", "young_adult": "adult", "older": "older"}


def model_group(age_range: str) -> str:
    return _MODEL_GROUP_BY_RANGE.get(age_range, "older")


def legacy_age_bucket(age_range: str) -> str:
    return _LEGACY_BUCKET[model_group(age_range)]


def age_bounds(age_range: str) -> tuple[int, int]:
    """Inclusive bounds; "70+" is treated as 70-79."""
    if age_range.endswith("+"):
        low = int(age_range[:-1])
        return low, low + 9
    low, high = age_range.split("-")
    return int(low), int(high)


def representative_age(age_range: str) -> int:
    low, high = age_bounds(age_range)
    return (low + high) // 2


def age_range_for_age(age: int) -> str | None:
    for age_range in AGE_RANGES:
        low, high = age_bounds(age_range)
        if low <= age <= high or (age_range.endswith("+") and age >= low):
            return age_range
    return None


def neighbouring_ranges(age_range: str, distance: int) -> tuple[str, ...]:
    """The range itself plus up to `distance` ranges on each side."""
    index = AGE_RANGES.index(age_range)
    return AGE_RANGES[max(0, index - distance) : index + distance + 1]


def comparable_sex(sex: str | None) -> str | None:
    """The sex a comparison filters on, or None to compare with everyone."""
    return sex if sex in ("female", "male") else None
