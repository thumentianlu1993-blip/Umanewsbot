"""Unmounted Q03 HTTP adapters; no URL, service identity or cache policy.

Direct invocation is not a decision to expose an unauthenticated external API.
If-None-Match is not interpreted; there is no ETag/304/TTL implementation here.
"""
from datetime import datetime, timezone
from django.db import DatabaseError
from django.http import JsonResponse
from .services import public_news_snapshot_loader as loader
from .services.public_news_snapshot import InvalidRequest, NewsNotFound, SnapshotDataError


def _error(code, status):
    return JsonResponse({'error': {'code': code}}, status=status)


def _success(**payload):
    return {
        'api_version': '1',
        'observed_at': datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z'),
        **payload,
    }


def _get_response(request, read):
    if request.method != 'GET':
        response = _error('method_not_allowed', 405)
        response['Allow'] = 'GET'
        return response
    try:
        return JsonResponse(read())
    except InvalidRequest as error:
        code = error.code if error.code in {'invalid_request', 'invalid_cursor'} else 'invalid_request'
        return _error(code, 400)
    except NewsNotFound:
        return _error('not_found', 404)
    except (DatabaseError, SnapshotDataError):
        # Neither a failed read nor a malformed window is an empty/withdrawn set.
        return _error('service_unavailable', 503)


def news_snapshot_list(request):
    def read():
        page = loader.load_news_page(request.GET)
        return _success(results=page.results, next_cursor=page.next_cursor)
    return _get_response(request, read)


def news_snapshot_detail(request, news_id):
    def read():
        if request.GET:
            raise InvalidRequest()
        return _success(result=loader.load_news_detail(news_id))
    return _get_response(request, read)
