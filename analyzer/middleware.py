"""Small request profiler that logs only requests above a duration threshold."""
import logging
import time

from django.conf import settings
from django.db import connection
from analyzer.performance import RequestProfile, current_profile


logger = logging.getLogger("performance.requests")


class RequestPerformanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        database_seconds = 0.0
        query_count = 0
        response = None
        # Resolve later in process_view: authentication middleware has not run
        # when this middleware's __call__ starts.
        profile = RequestProfile() if getattr(settings, 'SERVER_TIMING_ENABLED', False) else None
        token = current_profile.set(profile)

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
            if profile is not None and getattr(request, '_show_server_timing', False):
                metrics = [
                    f'total;dur={(time.perf_counter() - started) * 1000:.2f}',
                    f'db;dur={database_seconds * 1000:.2f};desc="SQL execute time"',
                    f'db_queries;desc="{query_count} queries"',
                ]
                metrics.extend(f'{name};dur={seconds * 1000:.2f}'
                               for name, seconds in profile.seconds.items())
                existing = response.get('Server-Timing')
                response['Server-Timing'] = ', '.join(([existing] if existing else []) + metrics)
                # Detailed diagnostics must not be served from shared caches.
                from django.utils.cache import patch_cache_control
                patch_cache_control(response, private=True, no_store=True)
            return response
        finally:
            current_profile.reset(token)
            elapsed_ms = (time.perf_counter() - started) * 1000
            threshold = getattr(settings, "SLOW_REQUEST_LOG_THRESHOLD_MS", 500)
            if elapsed_ms >= threshold:
                logger.warning(
                    "slow_request method=%s path=%s status=%s duration_ms=%.1f "
                    "db_ms=%.1f db_queries=%d stages_ms=%s",
                    request.method,
                    request.path_info,
                    getattr(response, "status_code", "error"),
                    elapsed_ms,
                    database_seconds * 1000,
                    query_count,
                    ({name: round(seconds * 1000, 1) for name, seconds in profile.seconds.items()}
                     if profile is not None else {}),
                )

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        target = match and match.url_name in {'market_short_term', 'market_long_term', 'waiver_wire'}
        user = getattr(request, 'user', None)
        authorized = settings.DEBUG or (user is not None and user.is_authenticated and user.is_staff)
        enabled = getattr(settings, 'SERVER_TIMING_ENABLED', False) and target and authorized
        request._show_server_timing = bool(enabled)
        if not enabled:
            # Skip stage collection on unrelated routes and for nonstaff users.
            current_profile.set(None)
