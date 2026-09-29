"""Shared candy testing: server-scored results, automatic Sub2API billing lookup."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
import http.client
from http.server import ThreadingHTTPServer
import ipaddress
import json
import math
from pathlib import Path
import queue
import re
import socket
import sqlite3
import threading
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit, urlunsplit

from build import build
from local_server import Handler, MAX_REQUEST, MAX_RESPONSE, ROOT

PROMPT = (ROOT / 'candy_prompt.txt').read_text(encoding='utf-8')
DNS_SLOTS = threading.BoundedSemaphore(8)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def base_url(raw):
    url = urlsplit(raw)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.port not in (None, 443)):
        raise ValueError('公开测试仅支持不含凭据和查询参数的 HTTPS 地址（443 端口）。')
    path = re.sub(r'/(responses|chat/completions)$', '', url.path.rstrip('/'))
    path = path or '/v1'
    # Percent-encoded paths remain encoded; never decode/reinterpret an upstream route.
    return urlunsplit(('https', url.hostname.lower(), path, '', ''))


def public_address(host, timeout=5):
    # A stuck system resolver must not hold a testing slot or spawn unbounded threads.
    if not DNS_SLOTS.acquire(blocking=False):
        raise ValueError('地址解析繁忙，请稍后再试。')
    results = queue.Queue(maxsize=1)

    def resolve():
        try:
            results.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            results.put(None)
        finally:
            DNS_SLOTS.release()

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = results.get(timeout=timeout)
    except queue.Empty:
        raise ValueError('地址解析超时。') from None
    if not addresses:
        raise ValueError('无法解析渠道地址。')
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise ValueError('公开测试不能访问内网或本机地址。')
    if not addresses:
        raise ValueError('无法解析渠道地址。')
    return addresses[0][4][0]


def request_json(url, key, timeout, body=None):
    """Pin a validated public IP while retaining hostname verification/TLS SNI."""
    target = urlsplit(url)
    started = time.monotonic()
    ip = public_address(target.hostname, min(5, timeout))
    timeout = max(0.01, timeout - (time.monotonic() - started))
    connection = http.client.HTTPSConnection(target.hostname, 443, timeout=timeout)
    connection._create_connection = lambda address, timeout, source_address=None: socket.create_connection((ip, 443), timeout, source_address)
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
    try:
        connection.connect()
        upstream_socket = connection.sock
        if expired.is_set():
            raise TimeoutError
        connection.request('POST' if body is not None else 'GET', target.path,
                           body=json.dumps(body).encode() if body is not None else None,
                           headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json',
                                    'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'上游 HTTP {response.status}')
        data = response.read(MAX_RESPONSE + 1)
        if expired.is_set():
            raise TimeoutError
        if len(data) > MAX_RESPONSE:
            raise ValueError('上游响应过大。')
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError('上游响应格式无效。')
        return parsed
    except (OSError, http.client.HTTPException):
        raise ValueError('上游请求超时或连接失败。') from None
    finally:
        timer.cancel()
        connection.close()


def billing_rate(data):
    rate = data.get('effective_rate_multiplier')
    if (data.get('object') != 'sub2api.key_billing' or data.get('schema_version') != 1
            or data.get('billing_scope') != 'token' or isinstance(rate, bool)
            or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0):
        raise ValueError('未获取到有效的 Sub2API 倍率。')
    return format(Decimal(str(rate)).normalize(), 'f')


def answer_text(data, api):
    if data.get('error'):
        raise ValueError('上游返回错误，未判分。')
    if api == 'responses':
        if data.get('status', 'completed') != 'completed':
            raise ValueError('响应未完成，未判分。')
        answer = '\n'.join(part.get('text', '') for item in data.get('output', [])
                           if item.get('type') == 'message' for part in item.get('content', [])
                           if part.get('type') == 'output_text') or data.get('output_text', '')
    else:
        choice = data.get('choices', [{}])[0]
        if choice.get('finish_reason', 'stop') != 'stop':
            raise ValueError('响应未完成，未判分。')
        answer = choice.get('message', {}).get('content', '')
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('未返回有效文本，未判分。')
    return answer


class Records:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sites (url TEXT, rate TEXT, started TEXT, record TEXT, PRIMARY KEY(url, rate))')
            db.execute('CREATE INDEX IF NOT EXISTS sites_started ON sites(started DESC)')
            db.execute('CREATE TABLE IF NOT EXISTS site_samples (url TEXT, rate TEXT, started TEXT, samples TEXT, PRIMARY KEY(url, rate))')

    def save(self, record, samples=None):
        # Caller provides an explicit whitelist, never a request/response object or key.
        samples = samples or []
        record = dict(record, has_samples=bool(samples))
        with sqlite3.connect(self.path, timeout=10) as db:
            cursor = db.execute('''INSERT INTO sites VALUES (?, ?, ?, ?)
                ON CONFLICT(url, rate) DO UPDATE SET started=excluded.started, record=excluded.record
                WHERE excluded.started > sites.started''',
                       (record['url'], record['multiplier'], record['started_at'], json.dumps(record, ensure_ascii=False)))
            changed = cursor.rowcount > 0
            if changed:
                db.execute('INSERT OR REPLACE INTO site_samples VALUES (?, ?, ?, ?)',
                           (record['url'], record['multiplier'], record['started_at'], json.dumps(samples, ensure_ascii=False)))
            return changed

    def detail(self, url, rate, started):
        with sqlite3.connect(self.path, timeout=10) as db:
            row = db.execute('SELECT samples FROM site_samples WHERE url=? AND rate=? AND started=?',
                             (url, rate, started)).fetchone()
            return json.loads(row[0]) if row else []

    def latest(self):
        with sqlite3.connect(self.path, timeout=10) as db:
            return [json.loads(row[0]) for row in db.execute('SELECT record FROM sites ORDER BY started DESC LIMIT 200')]


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError('请求格式无效。')
    key = payload.get('key')
    if not isinstance(key, str) or not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('请输入有效 Key。')
    result = {'url': base_url(payload.get('url', ''))}
    for name, limit in [('model', 120), ('note', 120)]:
        value = payload.get(name, '')
        if not isinstance(value, str) or len(value) > limit or key in value:
            raise ValueError('配置无效，请勿把 Key 填入备注或模型。')
        result[name] = value.strip()
    if not result['model'] or key in result['url']:
        raise ValueError('请输入模型，并检查地址不含 Key。')
    for name, choices in [('api', ('responses', 'chat/completions')), ('effort', ('', 'low', 'medium', 'high', 'xhigh'))]:
        if payload.get(name) not in choices:
            raise ValueError('接口或推理强度无效。')
        result[name] = payload[name]
    for name, low, high in [('runs', 1, 20), ('timeout', 10, 600)]:
        value = payload.get(name)
        if type(value) is not int or not low <= value <= high:
            raise ValueError('次数或超时设置无效。')
        result[name] = value
    return result, key


def run_test(config, key, records, emit, stopped):
    started = now()
    rate = None
    warning = ''
    try:
        rate = billing_rate(request_json(config['url'] + '/sub2api/billing', key, 15))
    except (ValueError, TypeError, KeyError):
        warning = '倍率探测失败：本次仍可测试，但不写入公开表格。'
    emit({'type': 'billing', 'multiplier': rate, 'warning': warning})
    hits = completed = errors = 0
    samples = []
    body = {'model': config['model'], 'stream': False}
    if config['api'] == 'responses':
        body.update(input=PROMPT, store=False)
        if config['effort']:
            body['reasoning'] = {'effort': config['effort']}
    else:
        body['messages'] = [{'role': 'user', 'content': PROMPT}]
        if config['effort']:
            body['reasoning_effort'] = config['effort']
    for index in range(config['runs']):
        if stopped.is_set():
            break
        sample = {'type': 'sample', 'index': index + 1, 'timestamp': now()}
        begin = time.monotonic()
        try:
            data = request_json(config['url'] + '/' + config['api'], key, config['timeout'], body)
            answer = answer_text(data, config['api'])
            hit = bool(re.search(r'(?<!\d)21(?!\d)', unicodedata.normalize('NFKC', answer)))
            hits += int(hit)
            completed += 1
            sample.update(answer=answer.replace(key, '[已隐藏 Key]'), hit=hit)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            errors += 1
            sample['error'] = '请求失败或未返回完整文本，请检查地址、Key、模型和超时。'
        sample['seconds'] = round(time.monotonic() - begin, 1)
        stored = {name: sample[name] for name in ('index', 'timestamp', 'seconds', 'hit', 'answer', 'error') if name in sample}
        if len(stored.get('answer', '')) > 20000:
            stored['answer'] = stored['answer'][:20000]
            stored['truncated'] = True
        samples.append(stored)
        emit(sample)
    record = dict(config, multiplier=rate, started_at=started, timestamp=now(),
                  hits=hits, completed=completed, errors=errors, stopped=stopped.is_set())
    # Failed/cancelled attempts do not replace a completed public test.
    saved = rate is not None and completed > 0 and not stopped.is_set()
    if saved:
        try:
            saved = records.save(record, samples)
            if not saved:
                warning = '已存在更新发起的测试，本次未覆盖公开记录。'
        except sqlite3.Error:
            saved = False
            warning = '测试完成，但公共记录保存失败，请稍后重试。'
    elif not warning:
        warning = '本次没有完整有效回复或已停止，未更新公开记录。'
    emit({'type': 'done', 'record': record, 'saved': saved, 'warning': warning})


class PublicHandler(Handler):
    def valid_host(self):
        return self.headers.get('Host') == urlsplit(self.server.origin).netloc

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': '无效访问地址。'})
        route = urlsplit(self.path)
        if route.path == self.server.prefix + '/sites':
            if route.query:
                params = parse_qs(route.query)
                if set(params) != {'url', 'multiplier', 'started_at'} or any(len(values) != 1 for values in params.values()):
                    return self.reply(400, {'error': '检测记录参数无效。'})
                samples = self.server.records.detail(params['url'][0], params['multiplier'][0], params['started_at'][0])
                return self.reply(200, {'samples': samples})
            return self.reply(200, {'sites': self.server.records.latest()})
        if urlsplit(self.path).path in ('/', '/index.html'):
            page = (ROOT / 'site/index.html').read_text(encoding='utf-8')
            page = page.replace('<head>', f'<head><meta name="candy-shared-api" content="{self.server.prefix}">', 1)
            return self.reply(200, page.encode(), 'text/html; charset=utf-8')
        # Static serving inherited without the local-only proxy's Host policy.
        from http.server import SimpleHTTPRequestHandler
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin') != self.server.origin:
            return self.reply(403, {'error': '仅接受本站页面请求。'})
        if self.path != self.server.prefix + '/test':
            return self.reply(404, {'error': 'Not found'})
        if not self.server.slots.acquire(blocking=False):
            return self.reply(429, {'error': '测试繁忙，请稍后再试。'})
        streaming = False
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_REQUEST or self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise ValueError('请求格式无效。')
            config, key = validate(json.loads(self.rfile.read(length)))
            public_address(urlsplit(config['url']).hostname)
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            streaming = True
            stopped = threading.Event()
            events = queue.Queue()

            def work():
                try:
                    run_test(config, key, self.server.records, events.put, stopped)
                except Exception:
                    events.put({'type': 'error', 'error': '测试服务暂不可用。'})
                finally:
                    self.server.slots.release()

            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            try:
                while True:
                    try:
                        event = events.get(timeout=5)
                        content = json.dumps(event, ensure_ascii=False).encode() + b'\n'
                    except queue.Empty:
                        event = None
                        content = b'\n'
                    self.wfile.write(content)
                    self.wfile.flush()
                    if event and event['type'] in ('done', 'error'):
                        break
            finally:
                stopped.set()
        except (ValueError, TypeError, OSError):
            if not streaming:
                self.reply(400, {'error': '请求无效或地址不可访问；请检查 URL、Key 和配置。'})
        finally:
            if not streaming:
                self.server.slots.release()


def make_server(port, origin, database, prefix='/api/community'):
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or parsed.path or parsed.query or parsed.fragment or parsed.username or not parsed.netloc:
        raise ValueError('origin 必须是完整的站点来源，例如 https://sytoken.org')
    if not re.fullmatch(r'/[a-zA-Z0-9/_-]+', prefix):
        raise ValueError('无效 API 前缀')
    server = ThreadingHTTPServer(('127.0.0.1', port), partial(PublicHandler, directory=str(ROOT / 'site')))
    server.origin = origin
    server.prefix = prefix.rstrip('/')
    server.records = Records(database)
    server.slots = threading.BoundedSemaphore(3)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--origin', default='http://127.0.0.1:8767')
    parser.add_argument('--prefix', default='/api/community')
    parser.add_argument('--no-build', action='store_true', help='Use an existing site build')
    parser.add_argument('--database', default=str(Path.home() / '.local/share/pelican-bicycle/community.sqlite3'))
    args = parser.parse_args()
    if not args.no_build:
        build()
    with make_server(args.port, args.origin, args.database, args.prefix) as server:
        print(f'公共收录服务已启动：{args.origin}/#model-tests', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
