from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collect import collect, upstream_price
from server import Monitor


class MonitorTests(unittest.TestCase):
    def test_upstream_price_uses_effective_rate_and_real_probe_time(self):
        probe = {'status': 'ok', 'billing_scope': 'token',
                 'effective_rate_multiplier': 0.15,
                 'received_at': '2026-09-21T14:39:27.547476508Z',
                 'fresh_until': '2026-09-21T15:39:27.547476508Z',
                 'group_rate_multiplier': 1.0, 'api_key': 'must-not-publish'}
        now = datetime(2026, 9, 21, 15, tzinfo=timezone.utc)
        result = upstream_price(probe, now)
        self.assertEqual(result['multiplier'], 0.15)
        self.assertEqual(result['received_at'], probe['received_at'])
        self.assertEqual(result['status'], 'ok')
        self.assertNotIn('api_key', result)
        self.assertNotIn('group_rate_multiplier', result)
        self.assertEqual(upstream_price(probe, now.replace(hour=16))['status'], 'stale')
        self.assertEqual(upstream_price(dict(probe, status='error'), now)['status'], 'error')
        for rate in [True, -1, float('nan'), float('inf'), '0.15', None]:
            self.assertIsNone(upstream_price(dict(probe, effective_rate_multiplier=rate), now)['multiplier'])
        self.assertIsNone(upstream_price(dict(probe, billing_scope='request'), now)['multiplier'])
        self.assertEqual(upstream_price(None, now)['status'], 'missing')

    def test_cache_rate_weights_tokens_not_requests(self):
        rows = {'channels': {'a': {'requests': 3, 'successes': 2,
                'cached_tokens': 900, 'input_tokens': 1100}}}
        with patch('collect.query', return_value=rows):
            result = collect({'user_ids': [1], 'model': 'gpt-6-astra',
                              'error_logging_verified': True,
                              'channels': [{'id': 'a', 'account_ids': [1]}]})
        self.assertAlmostEqual(result['channels']['a']['cache_rate'], 900 / 1100)
        self.assertAlmostEqual(result['channels']['a']['availability'], 2 / 3)

    def test_zero_requests_is_unknown(self):
        rows = {'channels': {'a': {'requests': 0, 'successes': 0,
                'cached_tokens': 0, 'input_tokens': 0}}}
        with patch('collect.query', return_value=rows):
            result = collect({'user_ids': [1], 'model': 'gpt-6-astra',
                              'channels': [{'id': 'a', 'account_ids': [1]}]})
        self.assertIsNone(result['channels']['a']['availability'])
        self.assertIsNone(result['channels']['a']['cache_rate'])

    def test_pass_requires_five_successful_answers(self):
        for verdicts, expected, status in [([True]*5, True, 'completed'),
                                           ([True]*4+[False], False, 'completed'),
                                           ([True]*4+[None], False, 'error')]:
            with self.subTest(verdicts=verdicts), tempfile.TemporaryDirectory() as tmp:
                monitor = Monitor(tmp, {'a': {}}, 'unused')
                with patch('server.sample', side_effect=[{'ok': v} for v in verdicts]):
                    monitor.run(['a'])
                result = json.loads((Path(tmp)/'latest-a.json').read_text())
                self.assertEqual(result['passed'], expected)
                self.assertEqual(result['status'], status)
                self.assertEqual(len(list((Path(tmp)/'history').glob('*.json'))), 1)
                self.assertEqual(monitor.public()['running'], [])

    def test_single_job_and_unknown_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = Monitor(tmp, {'a': {}}, 'unused')
            with self.assertRaises(ValueError):
                monitor.run(['unknown'])
            with (Path(tmp)/'evaluation.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(RuntimeError):
                    monitor.run(['a'])



if __name__ == '__main__':
    unittest.main()
