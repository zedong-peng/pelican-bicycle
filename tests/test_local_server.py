import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_server import make_server
from build import build


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.seen.append((self.path, self.headers['Authorization'], body))
        if self.path.startswith('/redirect/'):
            self.send_response(307)
            self.send_header('Location', '/v1/responses')
            self.end_headers()
            return
        if self.path.startswith('/error/'):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'secret-test-key')
            return
        if self.path.startswith('/slow/'):
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(50):
                    self.wfile.write(b' ')
                    self.wfile.flush()
                    time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'output_text': '21', 'received': body}).encode())


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            build()
        cls.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.upstream.seen = []
        cls.local = make_server(0)
        for server in (cls.upstream, cls.local):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.local, cls.upstream):
            server.shutdown()
            server.server_close()

    def call(self, path='/v1/responses', origin=None, host=None, **changes):
        payload = {'url': f'http://127.0.0.1:{self.upstream.server_port}{path}',
                   'key': 'secret-test-key', 'timeout': 10,
                   'body': {'model': 'test', 'stream': False, 'input': 'question'}}
        payload.update(changes)
        connection = http.client.HTTPConnection('127.0.0.1', self.local.server_port)
        headers = {'Content-Type': 'application/json',
                   'Origin': origin or f'http://127.0.0.1:{self.local.server_port}'}
        if host:
            headers['Host'] = host
        connection.request('POST', '/api/candy', json.dumps(payload), headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        connection.close()
        return result

    def test_both_interfaces_without_cors(self):
        for path in ('/v1/responses', '/v1/chat/completions'):
            status, data = self.call(path)
            self.assertEqual(status, 200)
            self.assertEqual(data['output_text'], '21')
            self.assertEqual(self.upstream.seen[-1][0], path)
            self.assertEqual(self.upstream.seen[-1][1], 'Bearer secret-test-key')

    def test_reject_foreign_origin_and_host(self):
        count = len(self.upstream.seen)
        self.assertEqual(self.call(origin='https://other.example')[0], 403)
        self.assertEqual(self.call(origin='null')[0], 403)
        self.assertEqual(self.call(host='other.example')[0], 403)
        self.assertEqual(len(self.upstream.seen), count)

    def test_no_redirect_or_raw_error_and_no_logs(self):
        logs = io.StringIO()
        with contextlib.redirect_stderr(logs), contextlib.redirect_stdout(logs):
            count = len(self.upstream.seen)
            status, data = self.call('/redirect/responses')
            self.assertEqual(status, 502)
            self.assertIn('307', data['error'])
            self.assertEqual(len(self.upstream.seen), count + 1)
            status, data = self.call('/error/responses')
            self.assertEqual(status, 502)
            self.assertIn('401', data['error'])
            self.assertNotIn('secret-test-key', json.dumps(data))
        self.assertEqual(logs.getvalue(), '')

    def test_invalid_parameters_not_forwarded(self):
        count = len(self.upstream.seen)
        for changes in ({'key': 'key\r\nX: bad'}, {'timeout': 601},
                        {'url': 'file:///tmp/responses'}, {'body': {'stream': True}},
                        {'url': 'https://example.com/v1/responses?key=secret'}):
            self.assertEqual(self.call(**changes)[0], 400)
        self.assertEqual(len(self.upstream.seen), count)

    def test_absolute_timeout_on_connection_close_response(self):
        real_timer = threading.Timer
        started = time.monotonic()
        with patch('local_server.threading.Timer', side_effect=lambda seconds, callback: real_timer(0.1, callback)):
            status, data = self.call('/slow/responses')
        self.assertEqual(status, 504)
        self.assertLess(time.monotonic() - started, 0.8)

    def test_local_page_enables_proxy(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.local.server_port)
        connection.request('GET', '/')
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b'name="candy-local-proxy"', response.read())
        connection.close()


if __name__ == '__main__':
    unittest.main()
