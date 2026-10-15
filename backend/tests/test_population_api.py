from __future__ import annotations

from datetime import date, timedelta
import unittest

from backend.app import create_app
from backend.population_api import MIN_POPULATION_SIZE, _baseline_day


def auth_headers(ldihk_id: str = "demo_user") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


SYNTHETIC_WINDOW = (date(2026, 5, 1), date(2026, 5, 14))


class PopulationConnection:
    """Scenario for 2026-06-01..2026-06-02 (hours per UTC day).

    requester u-me: 1 h, 2 h
    r1 (covers both days): 1 h, 0 h       r2: 2 h, 2 h
    r3 (history starts 2026-06-02): -, 3 h
    synthetic s1: 1 h every day of May 1-14, s2: 0.5 h every day
    """

    usage_columns = ["user_id", "date", "hour", "seconds"]

    def __init__(self, *, requester_exists: bool = True):
        self.calls: list[tuple[str, list[object]]] = []
        self.closed = False
        self.requester_exists = requester_exists

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
                    ("u-me", "2025-01-01", "2026-06-30"),
                    ("r1", "2026-01-01", "2026-06-30"),
                    ("r2", "2026-05-01", "2026-06-02"),
                    ("r3", "2026-06-02", "2026-07-01"),
                    ("r-old", "2020-01-01", "2020-12-31"),
                ],
            )
        if "population_synthetic_window" in sql:
            return FakeCursor(["first_date", "last_date"], [tuple(day.isoformat() for day in SYNTHETIC_WINDOW)])
        if "population_synthetic_usage" in sql:
            rows = []
            day = SYNTHETIC_WINDOW[0]
            while day <= SYNTHETIC_WINDOW[1]:
                rows.append(("s1", day.isoformat(), None, 3600))
                rows.append(("s2", day.isoformat(), None, 1800))
                day += timedelta(days=1)
            rows.append(("s1", None, 0, 14 * 3600))
            rows.append(("s2", None, 23, 7 * 3600))
            return FakeCursor(self.usage_columns, rows)
        raise AssertionError(f"Unexpected query: {sql[:80]}")

    def close(self):
        self.closed = True


def _request(client, *, include_synthetic: bool = True, platforms=("youtube",)):
    return client.post(
        "/api/population",
        headers=auth_headers(),
        json={
            "platforms": list(platforms),
            "startDate": "2026-06-01",
            "endDate": "2026-06-02",
            "includeSynthetic": include_synthetic,
            "customPercentile": 90,
        },
    )


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
        self.assertEqual(payload["syntheticBaseline"], {"startDate": "2026-05-01", "endDate": "2026-05-14"})
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
        self.assertFalse(any("population_synthetic" in sql for sql, _ in connection.calls))

    def test_population_query_rejects_non_youtube_platforms(self):
        response = _request(
            create_app(query_connection_factory=PopulationConnection).test_client(),
            platforms=("youtube", "tiktok"),
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


class SyntheticBaselineTests(unittest.TestCase):
    def test_dates_inside_the_window_are_unchanged(self):
        self.assertEqual(_baseline_day(date(2026, 5, 7), SYNTHETIC_WINDOW), date(2026, 5, 7))

    def test_dates_outside_the_window_keep_their_weekday(self):
        for day in (date(2026, 6, 1), date(2025, 12, 24), date(2027, 3, 9)):
            with self.subTest(day=day):
                mapped = _baseline_day(day, SYNTHETIC_WINDOW)
                self.assertTrue(SYNTHETIC_WINDOW[0] <= mapped <= SYNTHETIC_WINDOW[1])
                self.assertEqual(mapped.weekday(), day.weekday())

    def test_short_windows_still_map_into_the_window(self):
        window = (date(2026, 5, 1), date(2026, 5, 3))
        mapped = _baseline_day(date(2026, 6, 1), window)
        self.assertTrue(window[0] <= mapped <= window[1])


if __name__ == "__main__":
    unittest.main()
