"""Offline release regression for the own-goods listing detail and thumbnail path."""
from contextlib import ExitStack
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SUITE = ('test_own_goods_cover_fill', 'test_own_goods_lookup', 'test_own_goods', 'test_own_goods_research',
         'test_kalodata_integration', 'test_task_feedback', 'test_exception_center',
         'test_comment_samples', 'test_case_consent_routes', 'test_video_consent',
         'test_video_case_presentation', 'test_mobile_http', 'test_mobile_transfer',
         'test_mobile_progress', 'test_static_revalidation',
         'test_audit_round1_fixes.CoverSecurityTests', 'test_audit_round3_fixes.WorkerTests')
# Optional wider compatibility diagnostics, including pre-native-consent case fixtures.
EXTENDED = ('test_video_cases', 'test_video_case_recovery', 'test_video_case_fast_data')


def main():
    attempts = []
    original_dns = socket.getaddrinfo

    def blocked(*args, **kwargs):
        attempts.append('outbound')
        raise AssertionError('Unmocked network use is forbidden in the release regression')

    def dns(host, *args, **kwargs):
        if host in ('localhost', '127.0.0.1', '::1', None):
            return original_dns(host, *args, **kwargs)
        return blocked()

    with ExitStack() as guards:
        guards.enter_context(patch('httpx._client.get_environment_proxies', return_value={}))
        guards.enter_context(patch('socket.getaddrinfo', side_effect=dns))
        for target in ('socket.create_connection', 'httpx.HTTPTransport.handle_request',
                       'httpx.AsyncHTTPTransport.handle_async_request', 'urllib.request.OpenerDirector.open'):
            guards.enter_context(patch(target, side_effect=blocked))
        tests = SUITE + EXTENDED if '--extended' in sys.argv[1:] else SUITE
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(tests))
    print('Unmocked outbound attempts:', len(attempts), flush=True)
    return int(not result.wasSuccessful() or bool(attempts))


if __name__ == '__main__':
    sys.exit(main())
