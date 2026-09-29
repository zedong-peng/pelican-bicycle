"""Collect token usage from every configured machine and publish tokens.json.

Runs ``ai_tokens.py`` locally or over ssh (the script is piped to ``python3 -``,
nothing is installed remotely), keeps a per-host history so days survive log
cleanup, prices rows at official API rates and uploads one public JSON file.

Cron (hourly; publishes at most once per 20 hours):
  15 * * * * python3 ~/.local/share/ai-tokens/publish.py --min-hours 20 >> ~/.local/state/ai-tokens/publish.log 2>&1

Config (outside the repo): ~/.config/ai-tokens/config.json
  {"hosts": [{"name": "au-linux"}, {"name": "mac", "ssh": "mac"}],
   "upload": "syvps:/var/www/ai-benchmark/data/tokens.json"}
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import re
import subprocess
import sys

from ai_tokens import TZ, Totals, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.expanduser("~/.config/ai-tokens/config.json")
STATE = os.path.expanduser("~/.local/state/ai-tokens")
FIELDS = ("requests", "input", "cache_read", "cache_write", "output")


def model_name(raw):
    """Drop routing prefixes and relay suffixes: openai/gpt-4o-mini -> gpt-4o-mini."""
    name = raw.strip().lower().rsplit("/", 1)[-1]
    return re.sub(r"-cc-format$", "", name) or "unknown"


def collect(host, script, timeout):
    command = ["python3", "-", "--host", host["name"]]
    if host.get("ssh"):
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host["ssh"]] + command
    result = subprocess.run(command, input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip()[-300:])
    return json.loads(result.stdout)


def merge_history(name, snapshot):
    """Keep the larger count per day, tool and model: past days only shrink when logs are pruned."""
    path = os.path.join(STATE, "hosts", name + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            history = json.load(handle)
    except (OSError, ValueError):
        history = {"rows": {}}
    rows = history["rows"]
    if snapshot is not None:
        for day, tool, model, requests, fresh, read, write, output, cost in snapshot["rows"]:
            key = "|".join((day, tool, model))
            row = [requests, fresh, read, write, output, cost]
            old = rows.get(key)
            if old is None or sum(row[1:5]) >= sum(old[1:5]):
                rows[key] = row
        history["updated_at"] = snapshot["generated_at"]
        write_json(path, history)
    return history


def api_cost(prices, model, row, aliases=None):
    """Official list price. A cost the tool recorded (OpenCode, Cursor) is only a fallback:
    OpenCode's can reflect a subscription's discounted rate rather than the API price."""
    price = prices.get((aliases or {}).get(model, model))
    if price is not None:
        return sum(tokens * rate for tokens, rate in zip(row[1:5], price)) / 1e6
    return row[5]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--output", default=os.path.join(STATE, "tokens.json"))
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--min-hours", type=float, default=0,
                        help="skip if the last publish is newer; lets an hourly cron catch up after sleep")
    args = parser.parse_args()
    try:
        age = (datetime.now().timestamp() - os.path.getmtime(args.output)) / 3600
    except OSError:
        age = None
    if age is not None and age < args.min_hours:
        return
    with open(CONFIG, encoding="utf-8") as handle:
        config = json.load(handle)
    with open(os.path.join(HERE, "prices.json"), encoding="utf-8") as handle:
        table = json.load(handle)
    prices = {key: value for key, value in table.items() if not key.startswith("_")}
    aliases = {key: value for key, value in table.get("_aliases", {}).items() if not key.startswith("_")}

    with open(os.path.join(HERE, "ai_tokens.py"), "rb") as handle:
        script = handle.read()
    hosts = config["hosts"]
    # Hosts are independent ssh round trips; collect them at once, merge in config order.
    with ThreadPoolExecutor(len(hosts)) as pool:
        pending = [pool.submit(collect, host, script, args.timeout) for host in hosts]
    combined, stale = Totals(), 0
    for host, future in zip(hosts, pending):
        try:
            snapshot = future.result()
            if snapshot.get("errors"):
                print("%s: %s" % (host["name"], "; ".join(snapshot["errors"])), file=sys.stderr)
        except Exception as error:  # unreachable host: publish its last known history
            print("%s: %s" % (host["name"], error), file=sys.stderr)
            snapshot, stale = None, stale + 1
        for key, row in merge_history(host["name"], snapshot)["rows"].items():
            day, tool, model = key.split("|", 2)
            model = model_name(model)
            combined.merge([[day, tool, model] + row[:5] + [api_cost(prices, model, row, aliases)]])

    rows = [row for row in combined.export("") if sum(row[4:8]) > 0]
    public = {"schema_version": 1, "updated_at": datetime.now(TZ).isoformat(timespec="seconds"),
              "timezone": "Asia/Shanghai", "columns": ["date", "tool", "model"] + list(FIELDS) + ["api_usd"],
              "rows": rows, "machines": len(config["hosts"]), "stale_machines": stale}
    write_json(args.output, public, ensure_ascii=False, separators=(",", ":"))
    print("%d rows, %d machines, %d stale -> %s" % (len(rows), len(config["hosts"]), stale, args.output))

    if not args.no_upload and config.get("upload"):
        remote, path = config["upload"].split(":", 1)
        temporary = path + ".tmp"
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", args.output, "%s:%s" % (remote, temporary)], check=True)
        subprocess.run(["ssh", "-o", "BatchMode=yes", remote,
                        "chmod 644 '%s' && mv '%s' '%s'" % (temporary, temporary, path)], check=True)
        print("uploaded to " + config["upload"])


if __name__ == "__main__":
    main()
