"""Publish provider-neutral usage snapshots without reading sessions or credentials."""
from datetime import datetime
import json
import math
from pathlib import Path
import re

SCHEMA_VERSION = 1
MAX_BYTES = 1024 * 1024
MAX_SOURCES = 16
MAX_SAFE_INTEGER = 2 ** 53 - 1
COUNTS = ('requests', 'successes', 'total_input_tokens', 'cache_read_tokens',
          'cache_creation_tokens', 'output_tokens')
ID = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
                       r'(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})')


def read_snapshot(path):
    with Path(path).open('rb') as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('Snapshot too large')
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError('Snapshot must be an object')
    return value


def text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid public text')
    return value


def timestamp(value):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise ValueError('Timezone-aware ISO 8601 timestamp required')
    normalized = re.sub(r'(\.\d{6})\d+', r'\1', value)
    return datetime.fromisoformat(normalized.replace('Z', '+00:00'))


def count(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER):
        raise ValueError('Invalid count')
    return value


def metrics(value):
    if not isinstance(value, dict):
        raise ValueError('Metrics must be an object')
    result = {key: count(value.get(key)) for key in COUNTS}
    requests, successes = result['requests'], result['successes']
    if requests is not None and successes is not None and successes > requests:
        raise ValueError('Successes exceed requests')
    total = result['total_input_tokens']
    cached, created = result['cache_read_tokens'], result['cache_creation_tokens']
    if total is not None:
        known_cache = [v for v in (cached, created) if v is not None]
        if sum(known_cache) > total:
            raise ValueError('Cached input exceeds total input')
    cost = value.get('cost')
    result['cost'] = None
    if cost is not None:
        if not isinstance(cost, dict):
            raise ValueError('Invalid cost')
        amount, currency, basis = (cost.get(key) for key in ('amount', 'currency', 'basis'))
        if (type(amount) not in (int, float) or not 0 <= amount <= MAX_SAFE_INTEGER
                or not math.isfinite(amount)):
            raise ValueError('Invalid cost amount')
        if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
            raise ValueError('Invalid currency')
        if basis not in ('actual', 'estimate'):
            raise ValueError('Invalid cost basis')
        result['cost'] = {'amount': amount, 'currency': currency, 'basis': basis}
    return result


def normalize_source(value):
    """Copy an explicit public allowlist; never forward an input object wholesale."""
    if not isinstance(value, dict):
        raise ValueError('Source must be an object')
    source_id = value.get('id')
    if not isinstance(source_id, str) or not ID.fullmatch(source_id):
        raise ValueError('Invalid source ID')
    status = value.get('status')
    if status not in ('ready', 'pending', 'error'):
        raise ValueError('Invalid source status')
    tool = value.get('tool')
    models = value.get('models', [])
    if not isinstance(models, list) or len(models) > 32:
        raise ValueError('Invalid model list')
    freshness = value.get('freshness_seconds', 900)
    if type(freshness) is not int or not 60 <= freshness <= 604800:
        raise ValueError('Invalid freshness interval')
    verified = value.get('availability_verified', False)
    if type(verified) is not bool:
        raise ValueError('Invalid availability coverage')
    result = {
        'id': source_id,
        'label': text(value.get('label')),
        'provider': text(value.get('provider')),
        'tool': None if tool is None else text(tool),
        'models': [text(model) for model in models],
        'scope': text(value.get('scope'), 2000),
        'status': status,
        'updated_at': None,
        'period': None,
        'freshness_seconds': freshness,
        'availability_verified': verified,
        'metrics': None,
    }
    if status == 'ready':
        period = value.get('period')
        if not isinstance(period, dict):
            raise ValueError('Ready sources require a period')
        start, end = period.get('start'), period.get('end')
        updated_at = value.get('updated_at')
        if not timestamp(start) < timestamp(end) <= timestamp(updated_at):
            raise ValueError('Invalid snapshot time order')
        result['period'] = {'start': start, 'end': end}
        result['updated_at'] = updated_at
        result['metrics'] = metrics(value.get('metrics'))
    return result


def gpt_source(status='pending'):
    return {
        'id': 'gpt-vps', 'label': 'GPT · VPS', 'provider': 'OpenAI',
        'tool': None, 'models': [],
        'scope': '仅统计我经 VPS 调用的已配置模型；请求数按渠道尝试计数，跨渠道切换分别计数，不等于任务数。',
        'status': status, 'updated_at': None, 'period': None,
        'freshness_seconds': 900, 'availability_verified': False, 'metrics': None,
    }


def claude_source():
    return {
        'id': 'claude', 'label': 'Claude', 'provider': 'Anthropic',
        'tool': None, 'models': [],
        'scope': 'Claude 用量尚未接入；不计入当前统计。',
        'status': 'pending', 'updated_at': None, 'period': None,
        'freshness_seconds': 900, 'availability_verified': False, 'metrics': None,
    }


def legacy_source(stats):
    if not isinstance(stats, dict):
        raise ValueError('Invalid legacy snapshot')
    channels = stats.get('channels')
    if not isinstance(channels, dict):
        raise ValueError('Invalid legacy channels')
    if stats.get('updated_at') is None and not channels:
        return gpt_source()
    source = gpt_source('ready')
    source['models'] = [text(stats['model'])] if stats.get('model') is not None else []
    source['period'] = {'start': stats.get('start'), 'end': stats.get('end')}
    source['updated_at'] = stats.get('updated_at')
    source['availability_verified'] = stats.get('availability_verified', False)
    rows = []
    for row in channels.values():
        if not isinstance(row, dict):
            raise ValueError('Invalid legacy channel')
        rows.append(metrics({
            'requests': row.get('requests'), 'successes': row.get('successes'),
            'total_input_tokens': row.get('input_tokens'),
            'cache_read_tokens': row.get('cached_tokens'),
            'output_tokens': row.get('output_tokens'),
        }))
    source['metrics'] = {
        key: (sum(row[key] for row in rows)
              if rows and all(row[key] is not None for row in rows) else None)
        for key in COUNTS
    }
    source['metrics']['cost'] = None
    return normalize_source(source)


def extension_sources(snapshot):
    if type(snapshot.get('schema_version')) is not int or snapshot['schema_version'] != SCHEMA_VERSION:
        raise ValueError('Unsupported usage schema')
    sources = snapshot.get('sources')
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError('Invalid source list')
    normalized = []
    seen = {'gpt-vps'}
    for value in sources:
        source = normalize_source(value)
        if source['id'] in seen:
            raise ValueError('Duplicate or reserved source ID')
        seen.add(source['id'])
        normalized.append(source)
    return normalized


def public_usage(state):
    state = Path(state)
    try:
        gpt = legacy_source(read_snapshot(state / 'stats.json'))
    except FileNotFoundError:
        gpt = gpt_source()
    except (OSError, ValueError, UnicodeError, OverflowError, RecursionError):
        gpt = gpt_source('error')
    extensions = []
    try:
        extensions = extension_sources(read_snapshot(state / 'usage-sources.json'))
        extensions_status = 'ok'
    except FileNotFoundError:
        extensions_status = 'missing'
    except (OSError, ValueError, UnicodeError, OverflowError, RecursionError):
        extensions_status = 'error'
    if not any(source['id'] == 'claude' for source in extensions):
        extensions.insert(0, claude_source())
    return {'schema_version': SCHEMA_VERSION, 'sources': [gpt, *extensions],
            'extensions_status': extensions_status}
