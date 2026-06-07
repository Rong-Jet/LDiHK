from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from backend.app import create_app
from backend.query_api import (
    MAX_RESULT_LIMIT,
    QueryValidationError,
    compile_aggregate_query,
    compile_quality_query,
    validate_query_request,
)


def auth_headers(ldihk_id: str = "demo_user") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


class RecordingConnection:
    def __init__(self):
        self.calls: list[tuple[str, list[object]]] = []
        self.closed = False

    def execute(self, sql: str, parameters: list[object]):
        self.calls.append((sql, parameters))
        if "FROM fact_rows" in sql:
            return FakeCursor(
                [
                    "date",
                    "event_type",
                    "event_count",
                    "estimated_watch_seconds",
                    "api_watch_seconds",
                    "estimated_event_count",
                    "unique_video_count",
                ],
                [
                    ("2026-06-06", "watch", 3, 960, 120, 2, 3),
                ],
            )
        return FakeCursor(
            [
                "events_counted",
                "events_with_api_duration",
                "events_with_user_average_estimate",
                "events_with_global_default_estimate",
                "videos_unavailable",
                "videos_capped",
            ],
            [(3, 1, 1, 1, 2, 0)],
        )

    def close(self):
        self.closed = True


class StructuredQueryApiTests(unittest.TestCase):
    def test_query_requires_authorization(self):
        app = create_app(query_connection_factory=RecordingConnection)

        response = app.test_client().post(
            "/api/query",
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count"],
                "dimensions": [],
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "missing_authorization"})

    def test_query_rejects_malformed_authorization(self):
        app = create_app(query_connection_factory=RecordingConnection)

        response = app.test_client().post(
            "/api/query",
            headers={"Authorization": "Bearer demo_user extra"},
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count"],
                "dimensions": [],
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "invalid_authorization"})

    def test_query_rejects_body_identity_fields(self):
        cases = [
            ("user_id", {"user_id": "spoofed_user"}),
            ("person_id", {"person_id": "spoofed_user"}),
            ("ldihk_id", {"ldihk_id": "spoofed_user"}),
            ("user_id", {"filters": {"user_id": "spoofed_user"}}),
        ]

        for field, identity_payload in cases:
            with self.subTest(field=field, identity_payload=identity_payload):
                app = create_app(query_connection_factory=RecordingConnection)
                payload = {
                    "dataset": "youtube_usage",
                    "metrics": ["event_count"],
                    "dimensions": [],
                    "filters": {},
                }
                payload.update(identity_payload)

                response = app.test_client().post(
                    "/api/query",
                    headers=auth_headers(),
                    json=payload,
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json(),
                    {
                        "error": "invalid_payload",
                        "fields": {field: "not_allowed"},
                    },
                )

    def test_valid_grouped_query_returns_rows_and_quality(self):
        connection = RecordingConnection()
        app = create_app(query_connection_factory=lambda: connection)

        response = app.test_client().post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": [
                    "event_count",
                    "estimated_watch_seconds",
                    "api_watch_seconds",
                    "estimated_event_count",
                    "unique_video_count",
                ],
                "dimensions": ["date", "event_type"],
                "filters": {
                    "start_date": "2026-06-06",
                    "end_date": "2026-06-06",
                    "event_type": "watch",
                },
                "options": {"limit": 500},
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schema_version"], "youtube_usage.structured_query.v1")
        self.assertEqual(payload["dataset"], "youtube_usage")
        self.assertEqual(payload["ldihk_id"], "demo_user")
        self.assertNotIn("user_id", payload)
        self.assertNotIn("user_id", payload["query"]["filters"])
        self.assertEqual(
            payload["rows"],
            [
                {
                    "date": "2026-06-06",
                    "event_type": "watch",
                    "event_count": 3,
                    "estimated_watch_seconds": 960,
                    "api_watch_seconds": 120,
                    "estimated_event_count": 2,
                    "unique_video_count": 3,
                }
            ],
        )
        self.assertEqual(
            payload["quality"],
            {
                "events_counted": 3,
                "events_with_api_duration": 1,
                "events_with_user_average_estimate": 1,
                "events_with_global_default_estimate": 1,
                "videos_unavailable": 2,
                "videos_capped": 0,
            },
        )
        self.assertTrue(connection.closed)
        self.assertEqual(connection.calls[0][1][0], "demo_user")
        self.assertEqual(connection.calls[0][1][2], "demo_user")

    def test_raw_sql_unknown_fields_and_invalid_limit_are_rejected(self):
        app = create_app(query_connection_factory=RecordingConnection)
        client = app.test_client()

        raw_sql_response = client.post(
            "/api/query",
            headers=auth_headers(),
            json={"sql": "SELECT * FROM usage_events"},
        )
        unknown_metric_response = client.post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": ["raw_video_ids"],
                "dimensions": ["date"],
                "filters": {},
            },
        )
        unknown_dimension_response = client.post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count"],
                "dimensions": ["title"],
                "filters": {},
            },
        )
        unknown_filter_response = client.post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count"],
                "dimensions": ["date"],
                "filters": {"video_id": "private"},
            },
        )
        invalid_limit_response = client.post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count"],
                "dimensions": ["date"],
                "filters": {},
                "options": {"limit": 0},
            },
        )

        self.assertEqual(raw_sql_response.status_code, 400)
        self.assertEqual(raw_sql_response.get_json(), {"error": "raw_sql_not_allowed"})
        self.assertEqual(unknown_metric_response.status_code, 400)
        self.assertEqual(unknown_metric_response.get_json(), {"error": "invalid_metric"})
        self.assertEqual(unknown_dimension_response.status_code, 400)
        self.assertEqual(
            unknown_dimension_response.get_json(), {"error": "invalid_dimension"}
        )
        self.assertEqual(unknown_filter_response.status_code, 400)
        self.assertEqual(unknown_filter_response.get_json(), {"error": "invalid_filter"})
        self.assertEqual(invalid_limit_response.status_code, 400)
        self.assertEqual(invalid_limit_response.get_json(), {"error": "invalid_limit"})

    def test_video_id_dimension_is_allowed_by_default(self):
        query = validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user",
                "metrics": ["event_count"],
                "dimensions": ["video_id"],
                "filters": {},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertEqual(query.dimensions, ["video_id"])
        self.assertIn("ue.video_id AS video_id", compiled.sql)

    def test_platform_dimension_and_filter_are_allowed(self):
        query = validate_query_request(
            {
                "dataset": "usage_analytics",
                "user_id": "demo_user",
                "metrics": ["event_count", "estimated_usage_seconds"],
                "dimensions": ["platform"],
                "filters": {"platform": ["youtube", "tiktok"]},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertEqual(query.dataset, "usage_analytics")
        self.assertEqual(query.dimensions, ["platform"])
        self.assertIn("ue.platform AS platform", compiled.sql)
        self.assertIn("ue.platform = ANY(%s)", compiled.sql)
        self.assertIn(
            "COALESCE(ROUND(SUM(estimated_duration_seconds))::bigint, 0) "
            "AS estimated_usage_seconds",
            compiled.sql,
        )
        self.assertEqual(
            compiled.parameters,
            ["demo_user", 600, "demo_user", ["youtube", "tiktok"], 500],
        )

    def test_synthetic_filter_queries_population_without_exposing_user_ids(self):
        query = validate_query_request(
            {
                "dataset": "usage_analytics",
                "user_id": "demo_user",
                "metrics": ["event_count"],
                "dimensions": ["platform", "cohort"],
                "filters": {"is_synthetic": True, "sex": "male"},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertIn("ue.is_synthetic = true", compiled.sql)
        self.assertIn("u.sex = %s", compiled.sql)
        self.assertNotIn("u.external_id = %s AND ue.is_synthetic = true", compiled.sql)
        self.assertEqual(compiled.parameters, ["demo_user", 600, "male", 500])

    def test_is_synthetic_dimension_compares_self_against_population(self):
        query = validate_query_request(
            {
                "dataset": "usage_analytics",
                "user_id": "demo_user",
                "metrics": ["event_count"],
                "dimensions": ["is_synthetic"],
                "filters": {},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertIn("ue.is_synthetic AS is_synthetic", compiled.sql)
        self.assertIn("(u.external_id = %s OR ue.is_synthetic = true)", compiled.sql)
        self.assertEqual(compiled.parameters, ["demo_user", 600, "demo_user", 500])

    def test_identifier_dimensions_are_rejected_when_gate_is_disabled(self):
        for dimension in ("channel_id", "video_id"):
            with self.subTest(dimension=dimension), patch.dict(
                "os.environ",
                {"ALLOW_IDENTIFIER_DIMENSIONS": "false"},
                clear=False,
            ):
                with self.assertRaises(QueryValidationError) as error:
                    validate_query_request(
                        {
                            "dataset": "youtube_usage",
                            "user_id": "demo_user",
                            "metrics": ["event_count"],
                            "dimensions": [dimension],
                            "filters": {},
                        }
                    )

                self.assertEqual(error.exception.code, "invalid_dimension")

    def test_top_identifier_query_sorts_server_side(self):
        query = validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user",
                "metrics": ["event_count"],
                "dimensions": ["channel_id"],
                "filters": {},
                "options": {
                    "limit": 25,
                    "sort_by": "event_count",
                    "sort_direction": "desc",
                },
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertEqual(query.sort_by, "event_count")
        self.assertEqual(query.sort_direction, "desc")
        self.assertIn("ORDER BY event_count DESC, channel_id", compiled.sql)
        self.assertNotIn("ORDER BY channel_id LIMIT", compiled.sql)

    def test_invalid_sort_options_are_rejected(self):
        app = create_app(query_connection_factory=RecordingConnection)
        client = app.test_client()
        cases = [
            {"sort_by": "raw_video_ids", "sort_direction": "desc"},
            {"sort_by": "event_count", "sort_direction": "sideways"},
            {"sort_direction": "desc"},
        ]

        for options in cases:
            with self.subTest(options=options):
                response = client.post(
                    "/api/query",
                    headers=auth_headers(),
                    json={
                        "dataset": "youtube_usage",
                        "metrics": ["event_count"],
                        "dimensions": ["channel_id"],
                        "filters": {},
                        "options": options,
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "invalid_sort"})

    def test_sort_options_are_returned_in_public_query_contract(self):
        connection = RecordingConnection()
        app = create_app(query_connection_factory=lambda: connection)

        response = app.test_client().post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count"],
                "dimensions": ["channel_id"],
                "filters": {},
                "options": {
                    "limit": 25,
                    "sort_by": "event_count",
                    "sort_direction": "desc",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["query"]["options"],
            {
                "include_zero_buckets": False,
                "limit": 25,
                "sort_by": "event_count",
                "sort_direction": "desc",
            },
        )

    def test_compiled_sql_is_parameterized_and_enforces_limit(self):
        query = validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user'; DROP TABLE usage_events; --",
                "metrics": ["event_count"],
                "dimensions": ["date"],
                "filters": {
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-06",
                    "event_type": "watch'; DROP TABLE usage_events; --",
                    "product": "youtube_music",
                },
                "options": {"limit": 5000},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertEqual(query.limit, MAX_RESULT_LIMIT)
        self.assertEqual(
            compiled.parameters,
            [
                "demo_user'; DROP TABLE usage_events; --",
                600,
                "demo_user'; DROP TABLE usage_events; --",
                "2026-06-01",
                "2026-06-06",
                "watch'; DROP TABLE usage_events; --",
                "youtube_music",
                MAX_RESULT_LIMIT,
            ],
        )
        self.assertNotIn("demo_user'; DROP TABLE usage_events; --", compiled.sql)
        self.assertNotIn("watch'; DROP TABLE usage_events; --", compiled.sql)
        self.assertNotIn("youtube_music", compiled.sql)
        self.assertEqual(compiled.sql.count("%s"), len(compiled.parameters))
        self.assertIn("LIMIT %s", compiled.sql)

    def test_date_and_hour_buckets_compile_to_utc(self):
        query = validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user",
                "metrics": ["event_count"],
                "dimensions": ["date", "hour"],
                "filters": {
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-06",
                },
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertIn(
            "to_char(ue.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date",
            compiled.sql,
        )
        self.assertIn(
            "EXTRACT(HOUR FROM ue.occurred_at AT TIME ZONE 'UTC')::int AS hour",
            compiled.sql,
        )
        self.assertIn(
            "ue.occurred_at >= (%s::date::timestamp AT TIME ZONE 'UTC')",
            compiled.sql,
        )
        self.assertIn(
            "ue.occurred_at < ((%s::date + INTERVAL '1 day')::timestamp "
            "AT TIME ZONE 'UTC')",
            compiled.sql,
        )

    def test_estimated_duration_sql_falls_back_from_api_to_user_average_to_default(self):
        query = validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user",
                "metrics": ["estimated_watch_seconds", "unique_channel_count"],
                "dimensions": ["date", "channel_id"],
                "filters": {},
            }
        )

        aggregate = compile_aggregate_query(query)
        quality = compile_quality_query(query)

        self.assertIn("AVG(youtube_videos.duration_seconds)::numeric", aggregate.sql)
        self.assertIn("usage_events.event_type = 'watch'", aggregate.sql)
        self.assertRegex(
            aggregate.sql,
            re.compile(
                r"WHEN ue\.duration_seconds IS NOT NULL.*"
                r"THEN ue\.duration_seconds::numeric.*"
                r"WHEN yv\.availability_status = 'available'.*"
                r"THEN yv\.duration_seconds::numeric.*"
                r"WHEN ue\.is_synthetic = false "
                r"AND ue\.platform = 'youtube' "
                r"AND uds\.avg_api_duration_seconds IS NOT NULL.*"
                r"THEN uds\.avg_api_duration_seconds.*"
                r"WHEN ue\.platform = 'youtube'.*"
                r"AND ue\.product = 'shorts'.*"
                r"THEN 60::numeric.*"
                r"ELSE %s::numeric",
            ),
        )
        self.assertIn(
            "duration_bucket = 'user_average'",
            quality.sql,
        )
        self.assertIn(
            "duration_bucket = 'global_default'",
            quality.sql,
        )
        self.assertIn("AS metric_channel_id", aggregate.sql)
        self.assertIn(
            "COUNT(DISTINCT metric_channel_id)::bigint AS unique_channel_count",
            aggregate.sql,
        )

    def test_tiktok_duration_sql_uses_platform_default_not_youtube_user_average(self):
        query = validate_query_request(
            {
                "dataset": "usage_analytics",
                "user_id": "demo_user",
                "metrics": ["estimated_watch_seconds"],
                "dimensions": ["platform"],
                "filters": {"platform": "tiktok"},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertIn("ue.platform = %s", compiled.sql)
        self.assertIn("tiktok", compiled.parameters)
        self.assertIn(
            "WHEN ue.is_synthetic = false AND ue.platform = 'youtube' "
            "AND uds.avg_api_duration_seconds IS NOT NULL "
            "THEN uds.avg_api_duration_seconds",
            compiled.sql,
        )
        self.assertIn("WHEN ue.platform = 'tiktok' THEN 60::numeric", compiled.sql)

    def test_tiktok_watch_duration_sql_clips_to_next_tiktok_watch_start(self):
        query = validate_query_request(
            {
                "dataset": "usage_analytics",
                "user_id": "demo_user",
                "metrics": ["estimated_watch_seconds"],
                "dimensions": ["platform"],
                "filters": {"platform": "tiktok"},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertIn("WHEN ue.platform = 'tiktok' THEN 60::numeric", compiled.sql)
        self.assertIn("next_ue.platform = ue.platform", compiled.sql)
        self.assertIn("next_ue.event_type = 'watch'", compiled.sql)
        self.assertIn("next_ue.occurred_at > ue.occurred_at", compiled.sql)
        self.assertIn(
            "THEN LEAST( base_estimated_duration_seconds, "
            "GREATEST( 0::numeric, EXTRACT(EPOCH FROM next_watch_started_at "
            "- occurred_at)::numeric ) )",
            compiled.sql,
        )

    def test_watch_duration_sql_clips_to_next_watch_start(self):
        query = validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user",
                "metrics": ["estimated_watch_seconds", "api_watch_seconds"],
                "dimensions": ["date"],
                "filters": {},
            }
        )

        compiled = compile_aggregate_query(query)

        self.assertIn("event_base_rows AS", compiled.sql)
        self.assertIn("MIN(next_ue.occurred_at)", compiled.sql)
        self.assertIn("next_ue.user_id = ue.user_id", compiled.sql)
        self.assertIn("next_ue.platform = ue.platform", compiled.sql)
        self.assertIn("next_ue.event_type = 'watch'", compiled.sql)
        self.assertIn("next_ue.occurred_at > ue.occurred_at", compiled.sql)
        self.assertIn("LEAST( raw_api_duration_seconds", compiled.sql)
        self.assertIn("LEAST( base_estimated_duration_seconds", compiled.sql)
        self.assertIn(
            "EXTRACT(EPOCH FROM next_watch_started_at - occurred_at)::numeric",
            compiled.sql,
        )

    def test_duration_metrics_and_quality_are_watch_only_for_mixed_event_types(self):
        connection = RecordingConnection()

        def execute(sql: str, parameters: list[object]):
            connection.calls.append((sql, parameters))
            if "FROM fact_rows" in sql:
                return FakeCursor(
                    [
                        "event_count",
                        "estimated_watch_seconds",
                        "api_watch_seconds",
                        "estimated_event_count",
                        "unique_video_count",
                        "unique_channel_count",
                    ],
                    [(3, 120, 120, 0, 3, 3)],
                )
            return FakeCursor(
                [
                    "events_counted",
                    "events_with_api_duration",
                    "events_with_user_average_estimate",
                    "events_with_global_default_estimate",
                    "videos_unavailable",
                    "videos_capped",
                ],
                [(1, 1, 0, 0, 0, 0)],
            )

        connection.execute = execute
        app = create_app(query_connection_factory=lambda: connection)

        response = app.test_client().post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": [
                    "event_count",
                    "estimated_watch_seconds",
                    "api_watch_seconds",
                    "estimated_event_count",
                    "unique_video_count",
                    "unique_channel_count",
                ],
                "dimensions": [],
                "filters": {
                    "start_date": "2026-06-06",
                    "end_date": "2026-06-06",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload["rows"],
            [
                {
                    "event_count": 3,
                    "estimated_watch_seconds": 120,
                    "api_watch_seconds": 120,
                    "estimated_event_count": 0,
                    "unique_video_count": 3,
                    "unique_channel_count": 3,
                }
            ],
        )
        self.assertEqual(
            payload["quality"],
            {
                "events_counted": 1,
                "events_with_api_duration": 1,
                "events_with_user_average_estimate": 0,
                "events_with_global_default_estimate": 0,
                "videos_unavailable": 0,
                "videos_capped": 0,
            },
        )
        aggregate_sql = connection.calls[0][0]
        quality_sql = connection.calls[1][0]
        self.assertIn(
            "SUM(estimated_duration_seconds) FILTER "
            "(WHERE metric_event_type = 'watch')",
            aggregate_sql,
        )
        self.assertIn(
            "SUM(api_duration_seconds) FILTER "
            "(WHERE metric_event_type = 'watch')",
            aggregate_sql,
        )
        self.assertIn(
            "WHERE metric_event_type = 'watch' "
            "AND api_duration_seconds IS NULL",
            aggregate_sql,
        )
        self.assertIn("metric_event_type = 'watch'", quality_sql)

    def test_hourly_query_zero_fills_missing_buckets(self):
        connection = RecordingConnection()

        def execute(sql: str, parameters: list[object]):
            connection.calls.append((sql, parameters))
            if "FROM fact_rows" in sql:
                return FakeCursor(
                    [
                        "date",
                        "hour",
                        "event_count",
                        "estimated_watch_seconds",
                    ],
                    [
                        ("2026-06-06", 8, 2, 1200),
                        ("2026-06-06", 10, 1, 600),
                    ],
                )
            return FakeCursor(
                [
                    "events_counted",
                    "events_with_api_duration",
                    "events_with_user_average_estimate",
                    "events_with_global_default_estimate",
                    "videos_unavailable",
                    "videos_capped",
                ],
                [(3, 3, 0, 0, 0, 0)],
            )

        connection.execute = execute
        app = create_app(query_connection_factory=lambda: connection)

        response = app.test_client().post(
            "/api/query",
            headers=auth_headers(),
            json={
                "dataset": "youtube_usage",
                "metrics": ["event_count", "estimated_watch_seconds"],
                "dimensions": ["date", "hour"],
                "filters": {
                    "start_date": "2026-06-06",
                    "end_date": "2026-06-06",
                },
                "options": {"include_zero_buckets": True},
            },
        )

        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["rows"]
        self.assertEqual(len(rows), 24)
        self.assertEqual(
            rows[8],
            {
                "date": "2026-06-06",
                "hour": 8,
                "event_count": 2,
                "estimated_watch_seconds": 1200,
            },
        )
        self.assertEqual(
            rows[9],
            {
                "date": "2026-06-06",
                "hour": 9,
                "event_count": 0,
                "estimated_watch_seconds": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
