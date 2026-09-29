import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from server import Monitor, make_server
from usage import (MAX_BYTES, MAX_SAFE_INTEGER, MAX_SOURCES, extension_sources,
                   legacy_source, normalize_source, public_usage)


def legacy_fixture():
    return {
        'model': 'gpt-6-astra', 'availability_verified': True,
        'start': '2026-09-22T08:00:00Z', 'end': '2026-09-29T08:00:00Z',
        'updated_at': '2026-09-29T08:00:01Z',
        'channels': {
            'a': {'requests': 10, 'successes': 8, 'input_tokens': 1000,
                  'cached_tokens': 700, 'output_tokens': 100},
            'b': {'requests': 2, 'successes': 2, 'input_tokens': 100,
                  'cached_tokens': 10, 'output_tokens': 20},
        },
    }


def claude_fixture():
    return {
        'id': 'claude', 'label': 'Claude', 'provider': 'Anthropic',
        'tool': 'Claude Code', 'models': ['example-model'],
        'scope': 'Synthetic test data; not personal usage.', 'status': 'ready',
        'updated_at': '2026-09-29T08:00:01Z',
        'period': {'start': '2026-09-22T08:00:00Z', 'end': '2026-09-29T08:00:00Z'},
        'freshness_seconds': 3600, 'availability_verified': False,
        'metrics': {
            'requests': 20, 'successes': None, 'total_input_tokens': 1500,
            'cache_read_tokens': 1000, 'cache_creation_tokens': 200,
            'output_tokens': 200,
            'cost': {'amount': 1.25, 'currency': 'USD', 'basis': 'estimate'},
        },
    }


class UsageTests(unittest.TestCase):
    def write(self, root, name, value):
        (Path(root) / name).write_text(json.dumps(value), encoding='utf-8')

    def test_legacy_adapter_aggregates_without_double_counting_cache(self):
        result = legacy_source(legacy_fixture())
        self.assertEqual(result['id'], 'gpt-vps')
        self.assertEqual(result['models'], ['gpt-6-astra'])
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['availability_verified'])
        self.assertEqual(result['metrics'], {
            'requests': 12, 'successes': 10, 'total_input_tokens': 1100,
            'cache_read_tokens': 710, 'cache_creation_tokens': None,
            'output_tokens': 120, 'cost': None,
        })
        self.assertIsNone(result['tool'])
        fixture = legacy_fixture()
        fixture['availability_verified'] = False
        self.assertFalse(legacy_source(fixture)['availability_verified'])

    def test_unknown_and_empty_counts_are_not_reported_as_zero(self):
        fixture = legacy_fixture()
        del fixture['channels']['a']['output_tokens']
        self.assertIsNone(legacy_source(fixture)['metrics']['output_tokens'])
        fixture['channels'] = {}
        self.assertTrue(all(value is None for value in legacy_source(fixture)['metrics'].values()))
        fixture['channels'] = {'a': {'requests': 0, 'successes': 0,
                                    'input_tokens': 0, 'cached_tokens': 0, 'output_tokens': 0}}
        zero = legacy_source(fixture)['metrics']
        self.assertEqual(zero['requests'], 0)
        self.assertEqual(zero['total_input_tokens'], 0)
        self.assertIsNone(zero['cost'])

    def test_missing_sources_are_pending_and_no_global_totals(self):
        with tempfile.TemporaryDirectory() as root:
            result = public_usage(root)
            self.assertEqual(result['schema_version'], 1)
            self.assertEqual(result['extensions_status'], 'missing')
            self.assertEqual([source['id'] for source in result['sources']], ['gpt-vps', 'claude'])
            self.assertNotIn('totals', result)
            for source in result['sources']:
                self.assertEqual(source['status'], 'pending')
                self.assertIsNone(source['metrics'])
                self.assertIsNone(source['period'])
                self.assertIsNone(source['updated_at'])
            self.write(root, 'stats.json', {'channels': {}, 'updated_at': None})
            self.assertEqual(public_usage(root)['sources'][0]['status'], 'pending')

    def test_ready_claude_replaces_placeholder_and_extra_source_keeps_own_period(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root, 'stats.json', legacy_fixture())
            claude = claude_fixture()
            other = copy.deepcopy(claude)
            other.update(id='other-tool', label='Other tool', tool='Other tool')
            other['period']['start'] = '2026-09-28T08:00:00Z'
            other['metrics']['cost'] = {'amount': 10, 'currency': 'CNY', 'basis': 'actual'}
            self.write(root, 'usage-sources.json', {'schema_version': 1, 'sources': [claude, other]})
            result = public_usage(root)
            self.assertEqual(result['extensions_status'], 'ok')
            self.assertEqual([source['id'] for source in result['sources']], ['gpt-vps', 'claude', 'other-tool'])
            self.assertEqual(result['sources'][1], normalize_source(claude))
            self.assertNotEqual(result['sources'][1]['period'], result['sources'][2]['period'])
            self.assertEqual(result['sources'][2]['metrics']['cost']['currency'], 'CNY')

    def test_unknown_fields_are_not_published_at_any_level(self):
        fixture = claude_fixture()
        fixture.update(api_key='private-key', sessions=['private-session'], account_id=123)
        fixture['period']['raw_log'] = 'private-period'
        fixture['metrics']['billing'] = 'private-billing'
        fixture['metrics']['cost']['raw_response'] = 'private-cost'
        result = extension_sources({'schema_version': 1, 'sources': [fixture], 'credentials': 'private-root'})
        encoded = json.dumps(result)
        self.assertNotIn('private-', encoded)
        self.assertNotIn('account_id', encoded)
        with tempfile.TemporaryDirectory() as root:
            legacy = legacy_fixture()
            legacy['channels']['a']['upstream_price'] = {'api_key': 'private-price'}
            legacy['channels']['a']['raw_log'] = 'private-log'
            self.write(root, 'stats.json', legacy)
            self.assertNotIn('private-', json.dumps(public_usage(root)))

    def test_bad_counts_costs_and_boolean_values_are_rejected(self):
        for value in [True, False, -1, 1.5, float('nan'), float('inf'), '10', MAX_SAFE_INTEGER + 1]:
            with self.subTest(count=value):
                fixture = claude_fixture()
                fixture['metrics']['requests'] = value
                with self.assertRaises(ValueError):
                    normalize_source(fixture)
        for value in [True, -1, float('nan'), float('inf'), '1.25', MAX_SAFE_INTEGER + 1, 10 ** 400]:
            with self.subTest(cost=value):
                fixture = claude_fixture()
                fixture['metrics']['cost']['amount'] = value
                with self.assertRaises(ValueError):
                    normalize_source(fixture)
        for key, value in [('currency', 'usd'), ('currency', 'US'), ('basis', 'paid')]:
            fixture = claude_fixture()
            fixture['metrics']['cost'][key] = value
            with self.assertRaises(ValueError):
                normalize_source(fixture)
        for key, value in [('availability_verified', 1), ('freshness_seconds', True),
                           ('freshness_seconds', 0), ('freshness_seconds', 604801)]:
            fixture = claude_fixture()
            fixture[key] = value
            with self.assertRaises(ValueError):
                normalize_source(fixture)

    def test_cached_input_and_success_count_must_be_subsets(self):
        for change in [{'successes': 21}, {'cache_read_tokens': 1501},
                       {'cache_creation_tokens': 501}]:
            fixture = claude_fixture()
            fixture['metrics'].update(change)
            with self.assertRaises(ValueError):
                normalize_source(fixture)
        fixture = legacy_fixture()
        fixture['channels']['b']['cached_tokens'] = 101
        with self.assertRaises(ValueError):
            legacy_source(fixture)
        fixture = legacy_fixture()
        fixture['channels']['a']['requests'] = MAX_SAFE_INTEGER
        with self.assertRaises(ValueError):
            legacy_source(fixture)

    def test_periods_require_timezone_and_order(self):
        for bad in ['2026-09-22T08:00:00', '2026-13-22T08:00:00Z',
                    '2026-09-29', None, 123]:
            fixture = claude_fixture()
            fixture['period']['start'] = bad
            with self.assertRaises(ValueError):
                normalize_source(fixture)
        for key, value in [('start', '2026-09-29T08:00:00Z'),
                           ('end', '2026-09-30T08:00:00Z')]:
            fixture = claude_fixture()
            fixture['period'][key] = value
            with self.assertRaises(ValueError):
                normalize_source(fixture)
        fixture = claude_fixture()
        fixture['updated_at'] = '2026-09-29T16:00:01.123456789+08:00'
        self.assertEqual(normalize_source(fixture)['updated_at'], fixture['updated_at'])

    def test_reserved_duplicate_ids_and_unsupported_versions_are_rejected(self):
        fixture = claude_fixture()
        for sources in [[fixture, fixture], [dict(fixture, id='gpt-vps')],
                        [dict(fixture, id='../private')], [fixture] * (MAX_SOURCES + 1), None]:
            with self.subTest(sources=sources):
                with self.assertRaises(ValueError):
                    extension_sources({'schema_version': 1, 'sources': sources})
        for version in [True, '1', 2, None]:
            with self.assertRaises(ValueError):
                extension_sources({'schema_version': version, 'sources': [fixture]})

    def test_pending_sources_cannot_publish_stale_metrics(self):
        fixture = claude_fixture()
        fixture['status'] = 'pending'
        result = normalize_source(fixture)
        self.assertIsNone(result['metrics'])
        self.assertIsNone(result['period'])
        self.assertIsNone(result['updated_at'])

    def test_invalid_extension_does_not_hide_gpt_or_leak_private_errors(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root, 'stats.json', legacy_fixture())
            path = Path(root) / 'usage-sources.json'
            for bad in ['not json private-token', '{"schema_version":1,"sources":[null]}',
                        '{"schema_version":1,"sources":[]}' + ' ' * MAX_BYTES]:
                path.write_text(bad)
                result = public_usage(root)
                self.assertEqual(result['extensions_status'], 'error')
                self.assertEqual(result['sources'][0]['status'], 'ready')
                self.assertEqual(result['sources'][1]['status'], 'pending')
                self.assertNotIn(root, json.dumps(result))
                self.assertNotIn('private-token', json.dumps(result))
            path.unlink()
            (Path(root) / 'stats.json').write_text('private-invalid-json')
            result = public_usage(root)
            self.assertEqual(result['sources'][0]['status'], 'error')
            self.assertNotIn('private-invalid-json', json.dumps(result))

    def test_usage_does_not_read_candy_records(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root, 'stats.json', legacy_fixture())
            (Path(root) / 'latest-a.json').write_text('broken candy record')
            monitor = Monitor(root, {'private': {'api_key': 'secret'}}, 'unused')
            self.assertEqual(monitor.usage()['sources'][0]['status'], 'ready')
            self.assertNotIn('secret', json.dumps(monitor.usage()))
            self.assertFalse((Path(root) / 'evaluation.lock').exists())

    def test_example_is_only_a_pending_placeholder(self):
        example = json.loads((Path(__file__).parent / 'usage-sources.example.json').read_text())
        self.assertEqual(extension_sources(example)[0]['status'], 'pending')
        self.assertIsNone(extension_sources(example)[0]['metrics'])

    def test_loopback_http_contract_and_old_stats_compatibility(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = legacy_fixture()
            self.write(root, 'stats.json', fixture)
            monitor = Monitor(root, {}, '')
            with make_server(monitor, port=0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    connection.request('GET', '/usage')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                    self.assertEqual(response.getheader('X-Content-Type-Options'), 'nosniff')
                    data = json.loads(response.read())
                    self.assertEqual(data, monitor.usage())
                    connection.request('GET', '/stats')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    data = json.loads(response.read())
                    self.assertEqual(data, dict(fixture, tests={}, running=[]))
                    for path in ['/usage-sources.json', '/usage?file=private', '/tests']:
                        connection.request('GET', path)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 404)
                        response.read()
                    connection.request('POST', '/usage', body='{}')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 501)
                    response.read()
                finally:
                    connection.close()
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
