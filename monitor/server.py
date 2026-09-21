"""Read-only HTTP statistics; candy runs are local CLI jobs only."""
from datetime import datetime, timezone
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import re
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from collect import atomic_json

ROOT = Path(__file__).resolve().parent


def now():
    return datetime.now(timezone.utc).isoformat()


def sample(channel, script):
    # Each invocation gets a fresh Codex home: no login, memory or user config.
    with tempfile.TemporaryDirectory(prefix='candy-') as directory:
        home = Path(directory)
        config = ('model_provider = "benchmark"\n'
                  'model = "gpt-6-astra"\nmodel_reasoning_effort = "low"\n'
                  '[model_providers.benchmark]\nname = "benchmark"\n'
                  f'base_url = {json.dumps(channel["base_url"])}\n'
                  'env_key = "BENCH_UPSTREAM_KEY"\nwire_api = "responses"\n')
        (home / 'config.toml').write_text(config)
        env = {k: v for k, v in os.environ.items()
               if k in ('PATH', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
        env.update(HOME=directory, CODEX_HOME=directory,
                   BENCH_UPSTREAM_KEY=channel['api_key'], CANDY_SCRIPT=script)
        proc = subprocess.Popen([sys.executable, str(ROOT / 'evaluate.py')],
                                cwd=directory, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=240)
            if proc.returncode:
                status = re.search(r'(?i)(?:status(?: code)?[: =]*|HTTP[/ 0-9.]* )([45][0-9]{2})\b', stderr)
                category = 'HTTP ' + status.group(1) if status else (
                    '连接/流中断' if any(word in stderr.lower() for word in ('stream', 'connection', 'connect')) else 'CLI 执行失败')
                logging.warning('Candy subprocess exited with code %s (%s)', proc.returncode, category)
                return {'ok': None, 'error': '调用失败：' + category}
            return json.loads(stdout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            return {'ok': None, 'error': '调用超时（240 秒）'}
        except (ValueError, OSError) as error:
            logging.warning('Candy output failure: %s', type(error).__name__)
            return {'ok': None, 'error': '检测输出无效'}


class Monitor:
    def __init__(self, state, credentials, script):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.credentials = credentials
        self.script = script

    def public(self):
        try:
            stats = json.loads((self.state / 'stats.json').read_text())
        except (OSError, ValueError):
            stats = {'channels': {}, 'updated_at': None}
        stats['running'] = []
        with (self.state / 'evaluation.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    stats['running'] = json.loads((self.state / 'running.json').read_text())
                except (OSError, ValueError):
                    pass
        stats['tests'] = {}
        for path in self.state.glob('latest-*.json'):
            stats['tests'][path.stem.removeprefix('latest-')] = json.loads(path.read_text())
        return stats

    def run(self, channels):
        if not channels or any(c not in self.credentials for c in channels):
            raise ValueError('Unknown channel')
        with (self.state / 'evaluation.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A detection job is already running') from None
            atomic_json(self.state / 'running.json', channels)
            self.work(channels)

    def work(self, channels):
        try:
            history = self.state / 'history'
            history.mkdir(exist_ok=True)
            for channel in channels:
                record = {'channel': channel, 'started_at': now(),
                          'model': 'gpt-6-astra', 'effort': 'low', 'samples': [],
                          'status': 'running', 'passed': False}
                path = history / f'{time.time_ns()}-{channel}.json'
                atomic_json(path, record, 0o600)
                try:
                    for _ in range(5):
                        record['samples'].append(sample(self.credentials[channel], self.script))
                        atomic_json(path, record, 0o600)
                    record['status'] = ('error' if any(s['ok'] is None for s in record['samples'])
                                        else 'completed')
                except Exception as error:
                    logging.warning('Candy job %s failed: %s', channel, type(error).__name__)
                    record['status'] = 'error'
                record['finished_at'] = now()
                record['passed'] = len(record['samples']) == 5 and all(
                    s['ok'] is True for s in record['samples'])
                atomic_json(path, record, 0o600)
                atomic_json(self.state / f'latest-{channel}.json', record)
        finally:
            atomic_json(self.state / 'running.json', [])


def serve(monitor, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != '/stats':
                return self.reply(404, {'error': 'Not found'})
            self.reply(200, monitor.public())

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.serve_forever()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['serve', 'daily'], nargs='?', default='serve')
    parser.add_argument('--channel', default='all')
    args = parser.parse_args()
    state = os.environ['BENCH_STATE']
    if args.command == 'daily':
        credentials = json.loads(Path(os.environ['BENCH_CREDENTIALS_FILE']).read_text())
        channels = list(credentials) if args.channel == 'all' else [args.channel]
        Monitor(state, credentials, os.environ['CANDY_SCRIPT']).run(channels)
    else:
        serve(Monitor(state, {}, ''))
