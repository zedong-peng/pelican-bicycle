# 个人 AI 用量接口 v1

`GET /ai-board/api/usage`（监控进程内部路径 `/usage`）是只读的多来源聚合接口。
原有 `/api/stats` 保持不变，继续提供渠道明细、倍率与糖果题结果。

这不是模型调用接口，不需要 Claude API Key，也不会自动扫描 Claude Code 会话、读取
凭据或向模型发请求。后续采集器只需生成本文约定的脱敏聚合 JSON，首页无需为每个
模型另写一套显示逻辑。

## 响应

```json
{
  "schema_version": 1,
  "sources": [],
  "extensions_status": "missing"
}
```

实际响应始终包含 `gpt-vps` 和 `claude`：

- `gpt-vps`：从同一状态目录的 `stats.json` 自动适配。模型名称来自现有统计；工具未知
  时为 `null`，不把探测时使用的 Codex CLI 冒充所有个人请求的工具。
- `claude`：未接入时为 `pending`，没有用量、日期或费用；导入同 ID 的来源后自动替换。
- 其他 ID：按扩展快照顺序显示，各自保留自己的区间、口径、工具和费用币种。

`extensions_status` 为 `missing`（尚无扩展文件）、`ok`（成功读取）或 `error`（扩展
文件无效/不可读）。扩展失败不影响 GPT 数据；失败时保留 Claude 待接入占位，不能
把失败快照当作实时数据。不会返回文件路径、异常详情或原始内容。

**没有跨来源总计。** 不同区间、不同币种、重叠采集器或不同计数口径不能直接相加。
接口返回 `Cache-Control: no-store`。数据是否新鲜由每个来源的 `updated_at` 和
`freshness_seconds` 判断；HTTP 200 不代表每个来源都已接入或采集成功。

## 来源对象

| 字段 | 约定 |
| --- | --- |
| `id` | 稳定的 1–64 位小写字母/数字/连字符 ID，首尾为字母或数字；`gpt-vps` 保留 |
| `label` | 公开展示名称 |
| `provider` | 模型提供方名称；不是接入渠道或工具名 |
| `tool` | 实际使用工具；未知时 `null` |
| `models` | 统计覆盖的模型标识数组；未知时空数组，不猜测模型版本 |
| `scope` | 公开的采集范围、去重方式及已知缺失说明 |
| `status` | `ready`、`pending` 或 `error` |
| `updated_at` | 快照生成时间，带时区的 ISO 8601 字符串；非 ready 时为 `null` |
| `period` | `{ "start": "…", "end": "…" }`，左闭右开 `[start, end)`；非 ready 时为 `null` |
| `freshness_seconds` | 正常更新间隔加适量延迟容限，整数 60–604800，默认 900 |
| `availability_verified` | 是否确认成功和失败日志均覆盖；默认 `false` |
| `metrics` | 下述聚合指标；非 ready 时为 `null` |

`label`、`provider`、`tool` 和模型名称不超过 200 字符，`scope` 不超过 2000 字符，
模型数组最多 32 项。ready 必须有有效的日期和 metrics；日期需满足
`start < end <= updated_at`。时间必须包含秒和时区，如 `2026-09-29T16:00:00+08:00`
或 `2026-09-29T08:00:00Z`，小数秒最多 9 位。

### Metrics

| 字段 | 约定 |
| --- | --- |
| `requests` | 该来源按 scope 定义的请求/尝试数；不是任务数或会话数 |
| `successes` | 成功请求/尝试数，不能大于 requests |
| `total_input_tokens` | 全部输入：非缓存输入 + 缓存读取 + 缓存写入 |
| `cache_read_tokens` | total_input_tokens 中的缓存读取部分 |
| `cache_creation_tokens` | total_input_tokens 中的缓存写入部分 |
| `output_tokens` | 输出 token，是否包含推理等需在 scope 中说明 |
| `cost` | `null` 或 `{ "amount": 1.25, "currency": "USD", "basis": "estimate" }` |

计数字段均为非负整数或 `null`，上限为 JavaScript 安全整数 `9007199254740991`。
**未知是 null，已确认没有消耗才是 0。** 缓存读取与缓存写入相加不能超过总输入；不要
把缓存 token 再加到总输入上。缺少某渠道的某项数据时，GPT 对应汇总项为 `null`，
而不是把缺失值当 0。

只有 `availability_verified: true` 且请求数大于 0、成功数已知时，前端才应计算
`successes / requests`；只有成功日志不能宣称 100% 可用性。缓存率为
`cache_read_tokens / total_input_tokens`，不是逐请求缓存率的平均。

cost 的 amount 必须为非负有限数，currency 为 3 位大写币种代码；basis 只允许
`actual`（该区间实际支出）或 `estimate`（估算）。不要把 API 标准价等值、账户充值额、
订阅价格或余额变化冒充该区间实付。未知成本使用 `null`。费用使用与来源相同的区间；
费用区间不一致时不要填入。接口不会换汇或聚合不同币种。

旧 VPS 统计只提供包含缓存的输入总数与缓存读取数，所以适配时 `cache_creation_tokens`
与 `cost` 为 `null`；旧页面的倍率/购买力估算不会被拿来充当账单实付。

## Claude 接入

采集器输出文件名固定为：

```text
$BENCH_STATE/usage-sources.json
```

默认生产状态目录为 `/var/lib/ai-benchmark/`，不是静态站点目录。文件根对象包含
`schema_version: 1` 和 `sources` 数组。使用 `id: "claude"` 就会替换占位；同一
文件也可加入其他来源。ID 不得重复，不得覆盖 `gpt-vps`。最多 16 个扩展来源，
整个文件不超过 1 MiB。未认识的字段按白名单丢弃，但这不代替采集端脱敏：公开字段
本身也不得包含 Key、提示词、会话正文、账户标识、私有项目路径等内容。

仓库中的 [`usage-sources.example.json`](usage-sources.example.json) 只有空占位，
可用于检查文件结构；不会展示任何虚构用量。

下面是 **仅用于开发测试的合成数据**，不是个人实况，不能原样发布为真实记录：

```json
{
  "schema_version": 1,
  "sources": [
    {
      "id": "claude",
      "label": "Claude",
      "provider": "Anthropic",
      "tool": "Claude Code",
      "models": ["example-model"],
      "scope": "合成测试数据；仅用于验证接口，不代表个人使用。",
      "status": "ready",
      "updated_at": "2026-09-29T08:00:01Z",
      "period": {
        "start": "2026-09-22T08:00:00Z",
        "end": "2026-09-29T08:00:00Z"
      },
      "freshness_seconds": 900,
      "availability_verified": false,
      "metrics": {
        "requests": 20,
        "successes": null,
        "total_input_tokens": 1500,
        "cache_read_tokens": 1000,
        "cache_creation_tokens": 200,
        "output_tokens": 200,
        "cost": {
          "amount": 1.25,
          "currency": "USD",
          "basis": "estimate"
        }
      }
    }
  ]
}
```

若采集的是 Claude API usage 字段，聚合前应转换为：

```text
total_input_tokens = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
cache_read_tokens = cache_read_input_tokens
cache_creation_tokens = cache_creation_input_tokens
```

这条转换只适用于原始 `input_tokens` **不包含缓存** 的来源。第三方日志若已把缓存
计入 input，不要再加一次；应由相应采集器显式转换。若会话日志重复保存同一响应、
流式分片或快照，先按来源的稳定请求标识去重再汇总，不要把重复记录全算进去。
如果无法确认失败请求覆盖情况，将 `availability_verified` 保持 `false`。

### 验证与发布快照

在项目根目录验证待发布的文件（只读，不发布）：

```bash
PYTHONPATH=monitor python3 -c 'import sys; from usage import read_snapshot, extension_sources; sources = extension_sources(read_snapshot(sys.argv[1])); print("Validated", len(sources), "usage sources")' /path/to/usage-sources.json
```

发布进程应先验证，再把完整新文件在**同一状态目录**内原子替换到固定文件名；不要
直接截断服务正在读取的文件。单发布者可以复用 `collect.atomic_json`：

```python
from pathlib import Path
from collect import atomic_json
from usage import extension_sources

extension_sources(snapshot)
atomic_json(Path(state_directory) / "usage-sources.json", snapshot, mode=0o640)
```

发布进程需以 `ai-benchmark` 用户运行，或显式设置文件的 owner/group，让该服务账户
能读取。父目录也需有遍历权限；文件不应开放给无关用户。每个快照必须包含希望保留的
**全部**扩展来源，因为这是原子替换，不是增量追加。多个采集器应由一个本地合并发布者
协调，避免相互覆盖或竞争同一个临时文件。不要把整个 BENCH_STATE、凭据文件或会话
目录复制进 `site/`。

服务每次读取 `/usage` 时加载快照，更新 JSON 不需要重启。只部署新版服务代码时需要
按现有服务流程重启，并在 Nginx 中添加 `/ai-board/api/usage` 到内部 `/usage`
的只读代理。没有 HTTP 写入/上传接口；HTTP 客户端不能选择本地文件路径。

采集暂时失败时，可保留上次 ready 快照，让前端根据时间显示“数据已过期”；若发布
`status: "error"`，该来源的 metrics/period/updated_at 会清空，不显示旧值为新数据。
采集器尚未实现时保持 `pending`，不填日期或假数据。

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_monitor*.py' -v
```

测试使用临时目录中的合成数据及 loopback HTTP，不读取实际会话、不调用模型。
