from __future__ import annotations

from decimal import Decimal
import unittest

from backend.app import create_app


def auth_headers(ldihk_id: str = "demo_user") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


class PopulationConnection:
    def __init__(self):
        self.calls: list[tuple[str, list[object]]] = []
        self.closed = False

    def execute(self, sql: str, parameters: list[object]):
        self.calls.append((sql, parameters))
        if "population_user_daily" in sql:
            return FakeCursor(
                ["date", "watch_hours"],
                [
                    ("2026-06-01", Decimal("1.0")),
                    ("2026-06-02", Decimal("2.0")),
                ],
            )
        if "population_user_hourly" in sql:
            return FakeCursor(
                ["hour", "watch_hours"],
                [
                    (0, Decimal("0.25")),
                    (23, Decimal("0.5")),
                ],
            )
        if "population_daily_percentiles" in sql:
            return FakeCursor(
                [
                    "date",
                    "bottom10",
                    "median",
                    "top10",
                    "custom_percentile_hours",
                ],
                [
                    (
                        "2026-06-01",
                        Decimal("0.4"),
                        Decimal("1.0"),
                        Decimal("2.0"),
                        Decimal("2.0"),
                    ),
                    (
                        "2026-06-02",
                        Decimal("0.5"),
                        Decimal("1.5"),
                        Decimal("2.5"),
                        Decimal("2.5"),
                    ),
                ],
            )
        if "population_hourly_averages" in sql:
            return FakeCursor(
                ["hour", "population_avg"],
                [
                    (0, Decimal("0.2")),
                    (23, Decimal("0.4")),
                ],
            )
        if "population_distribution" in sql:
            return FakeCursor(
                ["hours", "density"],
                [
                    (0, 1),
                    (1, 1),
                    (2, 1),
                ],
            )
        if "population_average_hours" in sql:
            return FakeCursor(
                ["average_hours"],
                [
                    (Decimal("0.5"),),
                    (Decimal("1.5"),),
                    (Decimal("2.0"),),
                ],
            )
        raise AssertionError(f"Unexpected query: {sql}")

    def close(self):
        self.closed = True


class EmptyUserPopulationConnection(PopulationConnection):
    def execute(self, sql: str, parameters: list[object]):
        self.calls.append((sql, parameters))
        if "population_user_daily" in sql:
            return FakeCursor(["date", "watch_hours"], [])
        raise AssertionError(f"Unexpected query after not-ready user: {sql}")


class PopulationApiTests(unittest.TestCase):
    def test_population_query_returns_youtube_benchmark_payload(self):
        connection = PopulationConnection()
        app = create_app(query_connection_factory=lambda: connection)

        response = app.test_client().post(
            "/api/population",
            headers=auth_headers(),
            json={
                "platforms": ["youtube"],
                "startDate": "2026-06-01",
                "endDate": "2026-06-02",
                "includeSynthetic": True,
                "customPercentile": 90,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schema_version"], "youtube_usage.population.v1")
        self.assertEqual(payload["dataset"], "youtube_usage")
        self.assertEqual(payload["platforms"], ["youtube"])
        self.assertEqual(payload["userDailyAverageHours"], 1.5)
        self.assertEqual(payload["userPercentile"], 67)
        self.assertTrue(payload["includeSynthetic"])
        self.assertEqual(payload["customPercentile"], 90)
        self.assertEqual(
            payload["deciles"],
            [
                {
                    "date": "2026-06-01",
                    "user": 1.0,
                    "median": 1.0,
                    "top10": 2.0,
                    "bottom10": 0.4,
                    "customPercentileHours": 2.0,
                },
                {
                    "date": "2026-06-02",
                    "user": 2.0,
                    "median": 1.5,
                    "top10": 2.5,
                    "bottom10": 0.5,
                    "customPercentileHours": 2.5,
                },
            ],
        )
        self.assertEqual(payload["distribution"][0], {"hours": 0.0, "density": 1})
        self.assertEqual(payload["distribution"][24], {"hours": 24.0, "density": 0})
        self.assertEqual(
            payload["hourlyAverages"][0],
            {"hour": "00:00", "populationAvg": 0.2, "userAvg": 0.25},
        )
        self.assertEqual(
            payload["hourlyAverages"][23],
            {"hour": "23:00", "populationAvg": 0.4, "userAvg": 0.5},
        )
        self.assertTrue(connection.closed)
        self.assertEqual(len(connection.calls), 6)
        self.assertIn(
            "(ue.is_synthetic = true OR u.is_synthetic = false)",
            connection.calls[2][0],
        )
        self.assertIn("ue.platform = 'youtube'", connection.calls[2][0])

    def test_population_query_rejects_non_youtube_platforms(self):
        app = create_app(query_connection_factory=PopulationConnection)

        response = app.test_client().post(
            "/api/population",
            headers=auth_headers(),
            json={
                "platforms": ["youtube", "tiktok"],
                "startDate": "2026-06-01",
                "endDate": "2026-06-02",
                "includeSynthetic": True,
                "customPercentile": 90,
            },
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
            {
                "error": "invalid_payload",
                "fields": {"ldihk_id": "not_allowed"},
            },
        )

    def test_population_query_returns_not_ready_when_user_has_no_youtube_rows(self):
        connection = EmptyUserPopulationConnection()
        app = create_app(query_connection_factory=lambda: connection)

        response = app.test_client().post(
            "/api/population",
            headers=auth_headers(),
            json={
                "platforms": ["youtube"],
                "startDate": "2026-06-01",
                "endDate": "2026-06-02",
                "includeSynthetic": True,
                "customPercentile": 90,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "schema_version": "youtube_usage.population.v1",
                "ready": False,
                "message": "Dataset not ready. Please ingest YouTube data first.",
            },
        )
        self.assertTrue(connection.closed)
        self.assertEqual(len(connection.calls), 1)


if __name__ == "__main__":
    unittest.main()
