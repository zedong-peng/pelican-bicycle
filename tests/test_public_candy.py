import contextlib
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_candy as app


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'records.sqlite3'
        self.records = app.Records(self.path)
        self.config, self.key = app.validate(dict(url='https://EXAMPLE.com/v1/responses/',
            key='test-secret', model='model-a', note='渠道 A', api='responses', effort='low', runs=2, timeout=10))

    def run_sample(self, rate=0.5, fail=False):
        events = []
        def upstream(url, key, timeout, body=None):
            self.assertEqual(key, self.key)
            if url.endswith('/sub2api/billing'):
                if rate is None:
                    raise ValueError('unsupported')
                return dict(object='sub2api.key_billing', schema_version=1, billing_scope='token', effective_rate_multiplier=rate)
            self.assertEqual(body['input'], app.PROMPT)
            if fail:
                raise ValueError('failed')
            return dict(status='completed', output_text='答案 21 test-secret')
        with patch.object(app, 'request_json', side_effect=upstream):
            app.run_test(self.config, self.key, self.records, events.append, threading.Event())
        return events

    def test_automatic_billing_score_and_no_key_saved(self):
        events = self.run_sample()
        self.assertTrue(events[-1]['saved'])
        record = self.records.latest()[0]
        self.assertEqual(record['url'], 'https://example.com/v1')
        self.assertEqual(record['multiplier'], '0.5')
        self.assertEqual((record['hits'], record['completed']), (2, 2))
        self.assertNotIn('test-secret', self.path.read_bytes().decode(errors='ignore'))
        self.assertNotIn('test-secret', json.dumps(events))
        self.assertNotIn('answer', record)
        self.assertNotIn('samples', record)
        self.assertTrue(record['has_samples'])
        samples = self.records.detail(record['url'], record['multiplier'], record['started_at'])
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]['answer'], '答案 21 [已隐藏 Key]')
        self.assertNotIn('type', samples[0])
        self.assertEqual(len(app.Records(self.path).latest()), 1)

    def test_merge_url_and_rate_latest_model_replaces(self):
        self.run_sample()
        self.config['model'] = 'model-b'
        self.config['note'] = 'new note'
        self.run_sample(rate=0.50)
        rows = self.records.latest()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['model'], 'model-b')
        self.assertEqual(self.records.detail(rows[0]['url'], rows[0]['multiplier'], '2000-01-01'), [])
        self.run_sample(rate=1)
        self.assertEqual(len(self.records.latest()), 2)
        old = dict(rows[0], started_at='2000-01-01T00:00:00+00:00', model='old')
        self.records.save(old)
        self.assertNotIn('old', [r['model'] for r in self.records.latest()])

    def test_unknown_rate_and_no_valid_answers_do_not_publish(self):
        self.assertFalse(self.run_sample(rate=None)[-1]['saved'])
        self.assertFalse(self.run_sample(fail=True)[-1]['saved'])
        self.assertEqual(self.records.latest(), [])

    def test_private_dns_and_bad_urls_rejected(self):
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1'):
            result = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
            with patch.object(socket, 'getaddrinfo', return_value=result), self.assertRaises(ValueError):
                app.public_address('example.com')
        for url in ('http://example.com', 'https://example.com:8080', 'https://u:p@example.com', 'https://example.com?key=x'):
            with self.assertRaises(ValueError):
                app.base_url(url)
        for rate in (True, -1, float('nan'), float('inf'), '0.5'):
            with self.assertRaises(ValueError):
                app.billing_rate(dict(object='sub2api.key_billing', schema_version=1, billing_scope='token', effective_rate_multiplier=rate))

    def test_saved_samples_bounded_and_redacted_before_truncation(self):
        def upstream(url, key, timeout, body=None):
            if body is None:
                return dict(object='sub2api.key_billing', schema_version=1, billing_scope='token', effective_rate_multiplier=1)
            return dict(output_text='21 ' + 'a' * 19993 + self.key + 'z' * 100)
        with patch.object(app, 'request_json', side_effect=upstream):
            app.run_test(self.config, self.key, self.records, lambda event: None, threading.Event())
        row = self.records.latest()[0]
        sample = self.records.detail(row['url'], row['multiplier'], row['started_at'])[0]
        self.assertEqual(len(sample['answer']), 20000)
        self.assertTrue(sample['truncated'])
        self.assertNotIn(self.key, self.path.read_bytes().decode(errors='ignore'))

    def test_dns_errors_are_normalized(self):
        with patch.object(socket, 'getaddrinfo', side_effect=socket.gaierror('failed')):
            with self.assertRaises(ValueError):
                app.request_json('https://example.com/v1/sub2api/billing', 'test-secret', 10)

    def test_chat_parser_and_fixed_prompt(self):
        self.assertEqual(app.answer_text({'choices':[{'finish_reason':'stop', 'message':{'content':'21'}}]}, 'chat/completions'), '21')
        with self.assertRaises(ValueError):
            app.answer_text({'status':'incomplete', 'output_text':'21'}, 'responses')
        with contextlib.redirect_stdout(io.StringIO()):
            app.build()
        js = (app.ROOT / 'site/candy.js').read_text()
        literal = js.split('const prompt = ', 1)[1].split(';\n', 1)[0]
        self.assertEqual(json.loads(literal), app.PROMPT)

    def test_stream_and_shared_read_from_separate_clients(self):
        server = app.make_server(0, 'http://127.0.0.1:1', self.path)
        server.origin = f'http://127.0.0.1:{server.server_port}'
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def mock_upstream(url, key, timeout, body=None):
            if body is None:
                return dict(object='sub2api.key_billing', schema_version=1, billing_scope='token', effective_rate_multiplier=1)
            return dict(output_text='21')
        logs = io.StringIO()
        with patch.object(app, 'public_address', return_value='8.8.8.8'), patch.object(app, 'request_json', side_effect=mock_upstream), contextlib.redirect_stderr(logs):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            payload = dict(self.config, key=self.key)
            conn.request('POST', '/api/community/test', json.dumps(payload), {'Content-Type':'application/json', 'Origin':server.origin})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            events = [json.loads(line) for line in response.read().splitlines() if line]
            self.assertTrue(events[-1]['saved'])
            conn.close()
            other = http.client.HTTPConnection('127.0.0.1', server.server_port)
            other.request('GET', '/api/community/sites')
            records = json.loads(other.getresponse().read())['sites']
            self.assertEqual(len(records), 1)
            from urllib.parse import urlencode
            row = records[0]
            params = urlencode({'url': row['url'], 'multiplier': row['multiplier'], 'started_at': row['started_at']})
            other.request('GET', '/api/community/sites?' + params)
            detail = json.loads(other.getresponse().read())
            self.assertEqual(len(detail['samples']), 2)
            self.assertEqual(detail['samples'][0]['answer'], '21')
            other.close()
            forbidden = http.client.HTTPConnection('127.0.0.1', server.server_port)
            forbidden.request('POST', '/api/community/test', '{}', {'Content-Type':'application/json', 'Origin':'https://other.example'})
            response = forbidden.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            forbidden.close()
        self.assertEqual(logs.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
