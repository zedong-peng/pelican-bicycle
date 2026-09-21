# VPS 实测数据

生产站点：`https://sytoken.org/ai-recommend/`。静态模板仍由 `build.py` 构建，原作品保持不变。

## 统计口径

- 滚动 7×24 小时，五分钟汇总一次；仅配置的站长 user_ids、请求模型 `gpt-6-astra`。
- 渠道通过明确的 account_ids 映射；不能仅凭请求域名判断供应商，例如 tokenshop 的 API 使用其他域名。示例 account_ids 是占位值，部署前必须替换。
- 可用性：按 `(api_key_id, request_id, channel)` 去重。同站重试最终成功算成功；失败转移到另一站，原站计失败，目标站独立计结果。来源为 `usage_logs` 及 `ops_error_logs.upstream_errors`，没有请求 ID 时保留各日志行。没有渠道归属的网关路由错误不算到任意上游。
- 输入缓存率：`sum(cache_read_tokens) / sum(input_tokens + cache_read_tokens + cache_creation_tokens)`，Sub2API 的 input_tokens 为非缓存输入；不是逐次请求百分比的平均。
- 没有数据返回 null。错误监控覆盖未经确认时关闭可用性百分比，不能以仅成功日志报告 100%。当前监控启用也不证明历史日志绝对无缺失，此数字描述留存日志中的可用性。
- Input 倍率直接读取主站保存的 `accounts.extra.upstream_billing_probe.data.effective_rate_multiplier`，不读取内部计费倍率，也不额外请求上游。`received_at` 是主站接收探测结果的时间，页面按北京时间显示；`fresh_until` 和探测状态用于判断是否有效。
- 价格来源账号默认复用该渠道的 `eval_account_id`，可用 `price_account_id` 明确指定，必须属于本渠道的 account_ids。仅公开白名单倍率/时间/状态，不公开完整 extra。
- 购买力使用各渠道过去一周实际非缓存输入、缓存输入和输出 token 数，按有效上游声明倍率计算每百万总 token 成本；相同预算可买总 token 数与 Pro 20x 样本月度总量比较。不再借用 Pro 输入输出比例。仍假设输入/缓存/输出统一倍率、1¥ 充值 1$ 额度，非历史账单实付金额。过期、失败或缺失倍率时暂停显示购买力。

## 糖果检测

使用原始脚本 commit `4dde0a9e8043c9f84e5e810c4f7cdd555751a20c`，部署时下载并固定版本，不在每次检测时下载 main。

`evaluate.py` 调用原脚本 `run_codex('gpt-6-astra', 'low')` 和原 `ANSWER_PATTERN`，串行运行五次，只有五次全部成功判勾才通过。原脚本只检查独立数字 21，不是完整模型能力鉴定。每次请求独立临时 CODEX_HOME、禁用记忆，保留 Codex 默认网络重试配置，使用渠道独立凭据；VPS 直接测该上游，避免 Sub2API 自动故障转移污染结果。这些探测请求不进入个人网关用量统计。

每天北京时间 08:00 触发。一次最多一个检测任务（跨进程文件锁）；无任何启动检测的 HTTP 接口，手动检测仅通过 SSH 执行。单次样本 240 秒超时，失败保存为异常；不将异常误称为模型降智。

服务器 `/var/lib/ai-benchmark/history/` 保存每次完整记录（私有），`latest-*.json` 保存最新结果。公开接口仅返回汇总和最新检测答案，不暴露数据库、账号 ID、API key、原始用量或错误日志。

## 部署文件

- `/opt/ai-benchmark/monitor/`：服务代码，Codex CLI 固定安装版本。
- `/etc/ai-benchmark/config.json`：统计账号和站点映射。
- `/etc/ai-benchmark/credentials.json`：检测凭据，仅 root 和服务用户可读。
- `/var/www/ai-benchmark/`：仅构建后的静态站点。
- `deploy/`：systemd 服务、五分钟汇总 timer、北京时间每日 timer、Nginx 路由片段。

统计器通过 VPS 本地 Docker 执行只读 SQL，有 statement timeout。公开服务使用独立非特权用户，只读取统计和已保存结果，不加载上游凭据；监听 127.0.0.1:8765，Nginx 只公开 `/ai-recommend/api/stats`。GitHub Pages 镜像允许从 `https://zedongpeng.com` 读取统计。

更新凭据或渠道后同步修改私有配置并重启服务。网页更新：`python3 build.py` 后复制 `site/` 内容到静态目录。不要复制私有配置到静态目录。

```bash
python3 build.py
python3 -m unittest discover -s monitor -p 'test_*.py'
systemctl status ai-benchmark ai-benchmark-collect.timer ai-benchmark-daily.timer
systemctl start ai-benchmark-collect.service
```

回滚：恢复部署前的 Nginx 配置，`nginx -t` 后 reload；停止并禁用三个 ai-benchmark 服务/定时器。主站 Sub2API 无代码或数据库结构变更。

## SSH 手动检测

```bash
ssh syvps 'systemctl start --no-block ai-benchmark-daily.service'
ssh syvps 'journalctl -u ai-benchmark-daily.service -n 30 --no-pager'
```

第一条命令启动所有已配置渠道各五次检测，完成后网页自动显示最新结果。每日 timer 使用同一个本地 CLI，不经过 HTTP。HTTP POST `/tests` 已删除，旧公网路径返回 404；没有 Tailscale 私有网页或 8088 监听。旧管理口令已移除。
