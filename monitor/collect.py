"""Read-only Sub2API aggregation. Run on VPS; publish aggregates only."""
from datetime import datetime, timezone
import json
import math
import re
import os
from pathlib import Path
import subprocess
import sys


def query(sql):
    result = subprocess.run(
        ['docker', 'exec', '-i', 'sub2api-postgres', 'psql', '-X', '-qAt',
         '-v', 'ON_ERROR_STOP=1', '-U', 'sub2api', '-d', 'sub2api'],
        input="BEGIN READ ONLY; SET LOCAL statement_timeout='30s';\n" + sql + '\nCOMMIT;',
        text=True, capture_output=True, check=True, timeout=45)
    return json.loads(result.stdout)


def atomic_json(path, data, mode=0o644):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False) + '\n')
    temporary.chmod(mode)
    os.replace(temporary, path)


def upstream_price(probe, now=None):
    """Publish only validated rate and timestamps, never arbitrary upstream data."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(probe, dict):
        return {'status': 'missing', 'multiplier': None}
    result = {'status': 'invalid', 'multiplier': None}
    timestamps = {}
    for key in ('received_at', 'observed_at', 'fresh_until', 'last_attempt_at'):
        value = probe.get(key)
        if isinstance(value, str):
            try:
                # Go emits nanoseconds; Python 3.9/3.10 accept microseconds only.
                normalized = re.sub(r'(\.\d{6})\d+', r'\1', value)
                parsed = datetime.fromisoformat(normalized.replace('Z', '+00:00'))
                if parsed.tzinfo is not None:
                    timestamps[key] = parsed
                    result[key] = value
            except ValueError:
                pass
    rate = probe.get('effective_rate_multiplier')
    if (probe.get('billing_scope') != 'token' or isinstance(rate, bool)
            or not isinstance(rate, (int, float)) or not math.isfinite(rate)
            or rate < 0 or 'received_at' not in timestamps):
        return result
    result['multiplier'] = rate
    result['status'] = ('error' if probe.get('status') != 'ok' else
                        'stale' if timestamps.get('fresh_until', now) <= now else 'ok')
    return result


def collect(config):
    users = ','.join(str(int(i)) for i in config['user_ids'])
    if not users:
        raise ValueError('user_ids must explicitly select the owner')
    mapping = []
    price_mapping = []
    seen = set()
    for channel in config['channels']:
        if not channel['id'].isascii() or not channel['id'].replace('-', '').isalnum():
            raise ValueError('Invalid channel ID')
        for account in channel['account_ids']:
            account = int(account)
            if account in seen:
                raise ValueError('An account cannot belong to two channels')
            seen.add(account)
            mapping.append(f"({account}, '{channel['id']}')")
        price_account = int(channel.get('price_account_id', channel.get('eval_account_id', channel['account_ids'][0])))
        if price_account not in channel['account_ids']:
            raise ValueError('Price source must belong to the channel')
        price_mapping.append(f"({price_account}, '{channel['id']}')")
    model = config['model'].replace("'", "''")
    # One outcome per (API key, request, site). A retry recovered on the SAME
    # site counts as success; failover to another site leaves the first failed.
    # Event lists may contain repeated retry markers, so deduplicate by request.
    sql = f"""
WITH bounds AS (SELECT now() AS finish, now()-interval '7 days' AS start),
 mapping(account_id,channel) AS (VALUES {','.join(mapping)}),
 price_mapping(account_id,channel) AS (VALUES {','.join(price_mapping)}),
 prices AS (
  SELECT m.channel, a.extra->'upstream_billing_probe' AS probe
  FROM price_mapping m LEFT JOIN accounts a ON a.id=m.account_id
 ),
 usage AS (
  SELECT u.*, m.channel, COALESCE(NULLIF(request_id,''),'usage-'||u.id) AS rid
  FROM usage_logs u JOIN mapping m USING(account_id), bounds b
  WHERE u.created_at >= b.start AND u.created_at < b.finish
    AND u.user_id IN ({users})
    AND COALESCE(NULLIF(u.requested_model,''),u.model)='{model}'
 ), errors AS (
  SELECT e.*, COALESCE(NULLIF(request_id,''),'error-'||e.id) AS rid
  FROM ops_error_logs e, bounds b
  WHERE e.created_at >= b.start AND e.created_at < b.finish
    AND e.user_id IN ({users}) AND NOT e.is_count_tokens
    AND COALESCE(NULLIF(e.requested_model,''),e.model)='{model}'
 ), failed AS (
  SELECT DISTINCT e.api_key_id,e.rid,m.channel
  FROM errors e CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(NULLIF(e.upstream_errors,'null'::jsonb),'[]'::jsonb)) ev
  JOIN mapping m ON m.account_id=CASE WHEN ev->>'account_id' ~ '^[0-9]+$'
    THEN (ev->>'account_id')::bigint END
  UNION
  SELECT e.api_key_id,e.rid,m.channel FROM errors e JOIN mapping m USING(account_id)
  WHERE e.status_code>=400
 ), outcomes AS (
  SELECT api_key_id,rid,channel,bool_or(ok) AS ok FROM (
   SELECT api_key_id,rid,channel,true AS ok FROM usage
   UNION ALL SELECT api_key_id,rid,channel,false FROM failed
  ) r GROUP BY api_key_id,rid,channel
 ), counts AS (
  SELECT channel,count(*) AS requests,count(*) FILTER (WHERE ok) AS successes
  FROM outcomes GROUP BY channel
 ), tokens AS (
  SELECT channel,count(*) AS usage_requests,sum(input_tokens)::bigint AS uncached,
    sum(cache_read_tokens)::bigint AS cached,
    sum(cache_creation_tokens)::bigint AS created,
    sum(output_tokens)::bigint AS output FROM usage GROUP BY channel
 )
SELECT json_build_object('start',b.start,'end',b.finish,'updated_at',b.finish,
 'channels',(SELECT json_object_agg(c.channel,json_build_object(
  'requests',COALESCE(n.requests,0),'successes',COALESCE(n.successes,0),
  'usage_requests',COALESCE(t.usage_requests,0),'cached_tokens',COALESCE(t.cached,0),
  'input_tokens',COALESCE(t.uncached+t.cached+t.created,0),
  'output_tokens',COALESCE(t.output,0),
  'upstream_probe',json_build_object(
    'status',p.probe->>'status',
    'received_at',p.probe->>'received_at',
    'fresh_until',p.probe->>'fresh_until',
    'last_attempt_at',p.probe->>'last_attempt_at',
    'observed_at',p.probe->'data'->>'observed_at',
    'billing_scope',p.probe->'data'->>'billing_scope',
    'effective_rate_multiplier',p.probe->'data'->'effective_rate_multiplier')))

 FROM (SELECT DISTINCT channel FROM mapping) c LEFT JOIN counts n USING(channel)
 LEFT JOIN tokens t USING(channel) LEFT JOIN prices p USING(channel))) FROM bounds b;
"""
    result = query(sql)
    result['model'] = config['model']
    result['availability_verified'] = bool(config.get('error_logging_verified'))
    for row in result['channels'].values():
        row['upstream_price'] = upstream_price(row.pop('upstream_probe', None))
        row['availability'] = (row['successes'] / row['requests']
                               if row['requests'] and result['availability_verified'] else None)
        row['cache_rate'] = (row['cached_tokens'] / row['input_tokens']
                             if row['input_tokens'] else None)
    return result


if __name__ == '__main__':
    config = json.loads(Path(sys.argv[1]).read_text())
    atomic_json(sys.argv[2], collect(config))
