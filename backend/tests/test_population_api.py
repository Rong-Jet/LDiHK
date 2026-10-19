from __future__ import annotations

from datetime import date, timedelta
import unittest
from unittest import mock

import numpy as np

from backend import procedural_population
from backend.app import create_app
from backend.population_api import MIN_POPULATION_SIZE


def auth_headers(ldihk_id: str = "demo_user") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


def _fake_series(start: date, end: date, profiles=None, *, platforms=("youtube",)):
    """Synthetic s1: 1 h every day (hour 0), s2: 0.5 h every day (hour 23)."""
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    flat = tuple([0.0] * 24)
    people = tuple(
        procedural_population.SyntheticProfile(
            index=index, age_range="20-24", sex="female", model_group="young_adult",
            platform_minutes=(("youtube", 60.0),), sessions_per_day=2.0, weekday_hours=flat, weekend_hours=flat,
            drift=(), block_offset=0,
        )
        for index in (1, 2)
    )
    hours = np.array([[1.0] * len(days), [0.5] * len(days)])
    hourly = np.zeros((2, 24))
    hourly[0, 0] = 3600 * len(days)
    hourly[1, 23] = 1800 * len(days)
    return procedural_population.DaySeries(
        profiles=people, days=days, hours=hours, late_night_hours=hours * 0,
        fragmentation=hours * 0, hourly_seconds=hourly,
    )


class PopulationConnection:
    """Scenario for 2026-06-01..2026-06-02 (hours per UTC day).

    requester u-me: 1 h, 2 h
    r1 (covers both days): 1 h, 0 h       r2: 2 h, 2 h
    r3 (history starts 2026-06-02): -, 3 h
    synthetic s1: 1 h every day, s2: 0.5 h every day (see _fake_series)
    """

    usage_columns = ["user_id", "date", "hour", "seconds"]

    def __init__(self, *, requester_exists: bool = True, requester_first_day: str = "2025-01-01"):
        self.calls: list[tuple[str, list[object]]] = []
        self.closed = False
        self.requester_exists = requester_exists
        self.requester_first_day = requester_first_day

    def execute(self, sql: str, parameters: list[object]):
        self.calls.append((sql, parameters))
        if "population_requester" in sql:
            return FakeCursor(["user_id"], [("u-me",)] if self.requester_exists else [])
        if "population_real_usage" in sql:
            return FakeCursor(
                self.usage_columns,
                [
                    ("u-me", "2026-06-01", None, 3600),
                    ("u-me", "2026-06-02", None, 7200),
                    ("u-me", None, 0, 3600),
                    ("u-me", None, 23, 7200),
                    ("r1", "2026-06-01", None, 3600),
                    ("r1", None, 0, 3600),
                    ("r2", "2026-06-01", None, 7200),
                    ("r2", "2026-06-02", None, 7200),
                    ("r2", None, 0, 7200),
                    ("r2", None, 23, 7200),
                    ("r3", "2026-06-02", None, 10800),
                    ("r3", None, 23, 10800),
                ],
            )
        if "population_real_coverage" in sql:
            return FakeCursor(
                ["user_id", "first_date", "last_date"],
                [
                    ("u-me", self.requester_first_day, "2026-06-30"),
                    ("r1", "2026-01-01", "2026-06-30"),
                    ("r2", "2026-05-01", "2026-06-02"),
                    ("r3", "2026-06-02", "2026-07-01"),
                    ("r-old", "2020-01-01", "2020-12-31"),
                ],
            )
        raise AssertionError(f"Unexpected query: {sql[:80]}")

    def close(self):
        self.closed = True


def _request(client, *, include_synthetic: bool = True, platforms=("youtube",), start="2026-06-01", end="2026-06-02", **extra):
    return client.post(
        "/api/population",
        headers=auth_headers(),
        json={
            "platforms": list(platforms),
            "startDate": start,
            "endDate": end,
            "includeSynthetic": include_synthetic,
            "customPercentile": 90,
            **extra,
        },
    )


@mock.patch.object(procedural_population, "day_series", _fake_series)
class PopulationApiTests(unittest.TestCase):
    def test_population_query_returns_youtube_benchmark_payload(self):
        connection = PopulationConnection()
        response = _request(create_app(query_connection_factory=lambda: connection).test_client())

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["schema_version"], "youtube_usage.population.v1")
        self.assertEqual(payload["platforms"], ["youtube"])
        # Requester excluded; r-old's history does not overlap the range.
        self.assertEqual(payload["populationSize"], 5)
        # Synthetic profiles cover the requested days themselves.
        self.assertIsNone(payload["syntheticBaseline"])
        self.assertEqual(payload["syntheticModel"]["profiles"], 2)
        self.assertEqual(payload["userDailyAverageHours"], 1.5)
        # Member averages 0.5, 2.0, 3.0, 1.0, 0.5 -> three are <= 1.5.
        self.assertEqual(payload["userPercentile"], 60)
        self.assertEqual(
            payload["deciles"],
            [
                # [0.5, 1, 1, 2]: r3 is not counted before its history starts.
                {"date": "2026-06-01", "user": 1.0, "median": 1.0, "top10": 1.7, "bottom10": 0.65, "customPercentileHours": 1.7},
                # [0, 0.5, 1, 2, 3]: r1's day without watching counts as 0.
                {"date": "2026-06-02", "user": 2.0, "median": 1.0, "top10": 2.6, "bottom10": 0.2, "customPercentileHours": 2.6},
            ],
        )
        density = {item["hours"]: item["density"] for item in payload["distribution"]}
        self.assertEqual((density[0.0], density[1.0], density[2.0], density[3.0], density[24.0]), (2, 1, 1, 1, 0))
        self.assertEqual(payload["hourlyAverages"][0], {"hour": "00:00", "populationAvg": 0.5, "userAvg": 0.5})
        self.assertEqual(payload["hourlyAverages"][23], {"hour": "23:00", "populationAvg": 0.9, "userAvg": 1.0})
        self.assertTrue(connection.closed)
        real_usage_sql = next(sql for sql, _ in connection.calls if "population_real_usage" in sql)
        self.assertIn("GROUPING SETS", real_usage_sql)
        self.assertIn("ue.platform = 'youtube'", real_usage_sql)
        self.assertIn("SELECT MIN(next_ue.occurred_at)", real_usage_sql)

    def test_small_real_only_population_is_refused(self):
        connection = PopulationConnection()
        response = _request(
            create_app(query_connection_factory=lambda: connection).test_client(),
            include_synthetic=False,
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["reason"], "insufficient_population")
        self.assertEqual(payload["populationSize"], 3)
        self.assertEqual(payload["minPopulationSize"], MIN_POPULATION_SIZE)
        self.assertNotIn("deciles", payload)
        self.assertIsNone(payload.get("syntheticModel"))

    def test_total_source_compares_with_social_media_and_gaps_the_user_line(self):
        connection = PopulationConnection(requester_first_day="2026-06-02")
        response = _request(
            create_app(query_connection_factory=lambda: connection).test_client(),
            platforms=("youtube", "instagram"),
            populationSource="total",
        )
        payload = response.get_json()
        self.assertEqual(payload["platforms"], ["youtube", "instagram"])
        self.assertEqual(payload["comparisonPlatforms"], ["youtube", "tiktok", "instagram", "linkedin"])
        # u-me's history starts 2026-06-02: no user value before it, and the
        # average counts only that day.
        self.assertEqual([day["user"] for day in payload["deciles"]], [None, 2.0])
        self.assertEqual(payload["userCoverage"], {"startDate": "2026-06-02", "endDate": "2026-06-02"})
        self.assertEqual(payload["userDailyAverageHours"], 2.0)
        comparison_sql = next(sql for sql, _ in connection.calls if "population_real_usage_comparison" in sql)
        self.assertIn("ue.platform IN ('youtube', 'tiktok', 'instagram', 'linkedin')", comparison_sql)

    def test_population_query_rejects_unsupported_platforms(self):
        response = _request(
            create_app(query_connection_factory=PopulationConnection).test_client(),
            platforms=("youtube", "spotify"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "unsupported_platform"})

    def test_population_query_rejects_body_identity_fields(self):
        app = create_app(query_connection_factory=PopulationConnection)

        response = app.test_client().post(
            "/api/population",
            headers=auth_headers(),
            json={
                "ldihk_id": "spoofed_user",
                "platforms": ["youtube"],
                "startDate": "2026-06-01",
                "endDate": "2026-06-02",
                "includeSynthetic": True,
                "customPercentile": 90,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"error": "invalid_payload", "fields": {"ldihk_id": "not_allowed"}},
        )

    def test_population_query_returns_not_ready_when_user_has_no_youtube_rows(self):
        connection = PopulationConnection(requester_exists=False)
        response = _request(create_app(query_connection_factory=lambda: connection).test_client())

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["reason"], "no_user_data")
        self.assertTrue(connection.closed)
        self.assertEqual(len(connection.calls), 1)


if __name__ == "__main__":
    unittest.main()
