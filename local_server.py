"""Serve the gallery and forward candy requests on loopback, without saved keys."""
import argparse
from functools import partial
import http.client
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit

from build import build

ROOT = Path(__file__).resolve().parent
MAX_REQUEST = 128 * 1024
MAX_RESPONSE = 4 * 1024 * 1024


class Handler(SimpleHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        # URLs, bodies and credentials must not enter access/error logs.
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def local_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.local_host():
            return self.reply(403, {'error': '请使用启动时显示的本地地址。'})
        if urlsplit(self.path).path in ('/', '/index.html'):
            page = (ROOT / 'site/index.html').read_text(encoding='utf-8')
            page = page.replace('<head>', '<head><meta name="candy-local-proxy" content="/api/candy">', 1)
            return self.reply(200, page.encode(), 'text/html; charset=utf-8')
        # Serve only the generated site, including its sandboxed previews.
        return super().do_GET()

    def do_POST(self):
        expected_origin = f'http://127.0.0.1:{self.server.server_port}'
        if not self.local_host() or self.headers.get('Origin') != expected_origin:
            return self.reply(403, {'error': '仅接受本地页面发起的请求。'})
        if self.path != '/api/candy':
            return self.reply(404, {'error': 'Not found'})
        connection = None
        timer = None
        try:
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise ValueError
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_REQUEST:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            url = urlsplit(payload['url'])
            key = payload['key']
            timeout = payload['timeout']
            body = payload['body']
            if (url.scheme not in ('https', 'http') or not url.hostname
                    or url.username or url.password or url.query or url.fragment
                    or not url.path.endswith(('/responses', '/chat/completions'))
                    or not isinstance(key, str) or not key.strip()
                    or any(ord(c) < 32 or ord(c) > 126 for c in key)
                    or not isinstance(timeout, (int, float)) or not 10 <= timeout <= 600
                    or not isinstance(body, dict) or body.get('stream') is not False):
                raise ValueError
            # No redirects, retries, environment proxy, disk cache or request logging.
            cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
            connection = cls(url.hostname, url.port, timeout=timeout)
            expired = threading.Event()
            upstream_socket = None

            def expire():
                expired.set()
                if upstream_socket:
                    try:
                        upstream_socket.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            timer = threading.Timer(timeout, expire)
            timer.daemon = True
            timer.start()
            connection.connect()
            upstream_socket = connection.sock
            if expired.is_set():
                raise TimeoutError
            connection.request('POST', url.path, body=json.dumps(body).encode(), headers={
                'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                'Accept': 'application/json',
            })
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                return self.reply(502, {'error': f'上游 HTTP {response.status}；请检查地址、Key、额度和模型权限。'})
            data = response.read(MAX_RESPONSE + 1)
            if expired.is_set():
                return self.reply(504, {'error': '上游请求超时。'})
            if len(data) > MAX_RESPONSE:
                return self.reply(502, {'error': '上游响应超过 4 MiB 限制。'})
            try:
                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise ValueError
            except (ValueError, UnicodeError):
                return self.reply(502, {'error': '上游未返回 JSON 对象，请检查接口地址。'})
            self.reply(200, parsed)
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
            self.reply(400, {'error': '请求参数无效，请检查 URL、Key 和超时设置。'})
        except (TimeoutError, socket.timeout):
            self.reply(504, {'error': '上游请求超时。'})
        except (OSError, http.client.HTTPException):
            self.reply(502, {'error': '无法完成上游请求，请检查网络、地址与 TLS 证书。'})
        finally:
            if timer:
                timer.cancel()
            if connection:
                connection.close()


def make_server(port=8766):
    return ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(ROOT / 'site')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    build()
    try:
        server = make_server(args.port)
    except OSError:
        parser.exit(1, '无法启动本地服务；端口可能被占用，请用 --port 指定其他端口。\n')
    with server:
        print(f'打开 http://127.0.0.1:{server.server_port}/#model-tests （Ctrl+C 停止）', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
