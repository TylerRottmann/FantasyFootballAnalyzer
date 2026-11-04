"""Small request profiler that logs only requests above a duration threshold."""
import logging
import time

from django.conf import settings
from django.db import connection


logger = logging.getLogger("performance.requests")


class RequestPerformanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        database_seconds = 0.0
        query_count = 0
        response = None

        def record_query(execute, sql, params, many, context):
            nonlocal database_seconds, query_count
            query_count += 1
            query_started = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                database_seconds += time.perf_counter() - query_started

        try:
            with connection.execute_wrapper(record_query):
                response = self.get_response(request)
            return response
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            threshold = getattr(settings, "SLOW_REQUEST_LOG_THRESHOLD_MS", 500)
            if elapsed_ms >= threshold:
                logger.warning(
                    "slow_request method=%s path=%s status=%s duration_ms=%.1f "
                    "db_ms=%.1f db_queries=%d",
                    request.method,
                    request.path_info,
                    getattr(response, "status_code", "error"),
                    elapsed_ms,
                    database_seconds * 1000,
                    query_count,
                )
