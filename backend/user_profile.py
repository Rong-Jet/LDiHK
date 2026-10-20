"""Self-reported profile (age range, sex) of a real user.

Both fields are optional. They are used only to compare a user with people of
similar age and sex (population benchmark, risk reference values).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.demographics import (
    AGE_RANGES,
    SEX_VALUES,
    legacy_age_bucket,
    representative_age,
)

PROFILE_FIELDS = ("age_range", "sex")


class ProfileValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("invalid_profile")
        self.errors = errors


@dataclass(frozen=True)
class ProfileUpdate:
    """Fields to change; a field absent from `fields` is left as it is."""

    age_range: str | None
    sex: str | None
    fields: frozenset[str]


def validate_profile_payload(payload: object, *, require_field: bool = True) -> ProfileUpdate:
    """`{"age_range": "20-24" | null, "sex": "female" | "male" | "diverse" | null}`.

    null (or "prefer_not_to_say" for sex) clears a field.
    """
    if not isinstance(payload, dict):
        raise ProfileValidationError({"body": "must_be_json_object"})
    errors: dict[str, str] = {}
    fields = frozenset(field for field in PROFILE_FIELDS if field in payload)
    age_range = payload.get("age_range")
    sex = payload.get("sex")
    if age_range is not None and age_range not in AGE_RANGES:
        errors["age_range"] = "invalid_value"
    if sex == "prefer_not_to_say":
        sex = None
    if sex is not None and sex not in SEX_VALUES:
        errors["sex"] = "invalid_value"
    if require_field and not fields:
        errors["body"] = "no_profile_fields"
    if errors:
        raise ProfileValidationError(errors)
    return ProfileUpdate(age_range=age_range, sex=sex, fields=fields)


def apply_profile(connection, *, user_id, update: ProfileUpdate) -> None:
    """Write the given fields; also keeps the older age/age_bucket/cohort columns."""
    if not update.fields:
        return
    current = connection.execute(
        "SELECT age_range, sex FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    age_range = update.age_range if "age_range" in update.fields else current[0]
    sex = update.sex if "sex" in update.fields else current[1]
    age_bucket = legacy_age_bucket(age_range) if age_range else None
    connection.execute(
        """
        UPDATE users
        SET age_range = %s,
            sex = %s,
            age = %s,
            age_bucket = %s,
            cohort = %s
        WHERE id = %s
        """,
        (
            age_range,
            sex,
            representative_age(age_range) if age_range else None,
            age_bucket,
            f"{age_bucket}_{sex}" if age_bucket and sex else None,
            user_id,
        ),
    )


def fetch_profile(connection, *, ldihk_id: str) -> tuple[object, dict[str, str | None]] | None:
    """(user id, profile) of a real user, or None if unknown."""
    row = connection.execute(
        """
        SELECT id, age_range, sex
        FROM users
        WHERE external_id = %s AND is_synthetic = false
        """,
        (ldihk_id,),
    ).fetchone()
    if row is None:
        return None
    return row[0], {"age_range": row[1], "sex": row[2]}
