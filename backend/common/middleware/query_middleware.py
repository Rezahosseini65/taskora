
import logging
from time import perf_counter

from django.db import connection, reset_queries

logger = logging.getLogger("django.request")


class QueryCountMiddleware:
    """
    Log database query count and total response time for API requests.
    Development only.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        
        reset_queries()
        
        start_time = perf_counter()

        response = self.get_response(request)

        total_time_ms = (perf_counter() - start_time) * 1000

        query_count = len(connection.queries)

        query_time_ms = sum(
            float(query.get("time", 0))
            for query in connection.queries
        ) * 1000

        logger.info(
            "API Performance | method=%s path=%s status=%s "
            "queries=%s query_time_ms=%.2f total_time_ms=%.2f",
            request.method,
            request.path,
            response.status_code,
            query_count,
            query_time_ms,
            total_time_ms,
        )

        return response
