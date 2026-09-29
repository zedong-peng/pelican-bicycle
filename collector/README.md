# 用量采集

每天把各台机器的本地日志汇总成一张表，公开到 `https://sytoken.org/ai-board/data/tokens.json`。

| 文件 | 作用 |
| --- | --- |
| `ai_tokens.py` | 在一台机器上读日志，输出按「北京时间日期 × 工具 × 模型」汇总的 JSON。Python 3.8+，只用标准库，可经 ssh 管道运行，远端不用装任何东西 |
| `publish.py` | 逐台运行 `ai_tokens.py`，保留历史，按 `prices.json` 折算 API 价，合并后上传 |
| `prices.json` | 官方标价，美元 / 百万 token：`[输入, 缓存读, 缓存写, 输出]` |

## 读哪些日志

| 工具 | 位置 | 规则 |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/**/*.jsonl` | 同一回复按「message id + request id」去重（一条回复会拆成多行，也会被复制进多个会话）；sidechain 日志重放的父消息丢弃；advisor 按自己的模型单独计 |
| Codex | `~/.codex/sessions/`、`archived_sessions/` | 子 agent 文件先重放父会话历史，从 `task_started` 或 `trigger_turn` 之后才算；第一个 `turn_context` 之前没有模型，不计；重复的累计快照跳过。`input_tokens` 含缓存，拆成非缓存输入 + 缓存读 |
| OpenCode | `~/.local/share/opencode/opencode*.db` | 只读 assistant 消息；reasoning 单独记录，按输出计；带 OpenCode 自己记录的费用 |
| Cursor | Cursor 后台的用量事件 | 本地没有可靠的 token 数，用已登录 Cursor 的 access token 调 dashboard 接口拉取；后台只留约 3.5 个月。按账号计，同一账号只在一台机器上登录，否则会重复。模型名去掉档位后缀（`claude-opus-5-thinking-medium` → `claude-opus-5`），`default` 记为 `cursor-auto`。token 过期（约 50 天没打开 Cursor）时这台机器报错，历史不受影响 |

去重规则参考 [ccusage](https://github.com/ccusage/ccusage) 的 adapter 说明，`tests/test_collector.py` 固定了这些行为。

## 口径

- **API 价**：按 `prices.json` 的官方标价折算，不是实付。Anthropic 缓存写按 5 分钟档（输入价 1.25 倍）；OpenAI 缓存写按输入价；长上下文加价不计。没有官方价时，OpenCode 和 Cursor 行用它们自己记录的费用。没有官方价的模型不计入，页面会标出占比。
- **历史**：Claude Code 默认只留 30 天日志。`publish.py` 在 `~/.local/state/ai-tokens/hosts/` 按机器保存历史，同一天同一模型取较大值，所以日志清理后旧数据仍在。
- **离线机器**：连不上时沿用它上次的历史，页面显示「N 台未连上」。

## 部署

```bash
mkdir -p ~/.local/share/ai-tokens && cp collector/{ai_tokens.py,publish.py,prices.json} ~/.local/share/ai-tokens/
# ~/.config/ai-tokens/config.json（不进仓库）
# {"hosts": [{"name": "au-linux"}, {"name": "mac", "ssh": "mac"}],
#  "upload": "syvps:/var/www/ai-benchmark/data/tokens.json"}
python3 ~/.local/share/ai-tokens/publish.py --no-upload   # 先本地看结果
crontab -e  # 15 * * * * python3 ~/.local/share/ai-tokens/publish.py --min-hours 20 >> ~/.local/state/ai-tokens/publish.log 2>&1
```

每小时检查一次，距上次发布满 20 小时才采集，机器睡眠后能补上。部署 `site/` 时不要删掉 VPS 上的 `data/` 目录。
