# 我的 AI 使用实况

个人 AI 使用记录：公开已接入的用量、使用手记和工具实验，不是模型排行榜或渠道购买指南。在线地址保持为 [`sytoken.org/ai-recommend/`](https://sytoken.org/ai-recommend/)。

## 页面与数据

- **使用实况**：各来源独立展示模型、工具、统计区间、请求和 Token、缓存率与费用。当前适配已有 VPS 个人 GPT 统计，Claude 显示待接入，不填假数据。
- **使用手记**：在 [`usage-notes.json`](usage-notes.json) 中维护实际任务、结果和取舍；初始为空，不代写未经确认的个人体验。
- **工具与实验**：原有渠道明细、成本试算、糖果题和作品档案折叠保留；公共测试和社区作品不冒充个人使用记录。

新接口为只读 `GET /ai-recommend/api/usage`，旧 `/api/stats` 不变。前端遇到新接口 404 会兼容旧统计接口，并明确标注扩展接口尚未上线；其他错误会保留旧快照并标记更新失败。未知用量为 `null`，不是零；不跨来源合并日期、币种或重复采集的数据。

**后续接入 Claude：** 采集器在 `$BENCH_STATE/usage-sources.json` 原子发布 `schema_version: 1` 的脱敏聚合快照，来源使用 `id: "claude"`，首页会自动替换待接入卡片，无需修改页面。没有公开上传接口，也不会读取本地会话或调用模型。完整字段、缓存读写口径、费用区分和示例见 [`monitor/USAGE_API.md`](monitor/USAGE_API.md)。

### 添加使用手记

`usage-notes.json` 是数组，每条需要 `date`（`YYYY-MM-DD`）、`title`、`body`，可选 `tags` 字符串数组。正文按纯文本显示，保留换行；构建时验证并按日期倒序排列、转义 HTML。只填写可公开的真实体验，不放提示词原文、凭据或私人项目路径。

本地预览：`python3 local_server.py`，打开 `http://127.0.0.1:8766/`。用量默认读取公开服务；未部署新接口时仍可显示旧 VPS 数据。

验证：

```bash
python3 build.py
python3 -m unittest discover -s monitor -p 'test_*.py'
python3 -m unittest discover -s tests -v
node --test tests/test_usage_ui.js
node --check usage.js
node --check benchmark.js
node --check candy.js
```

## 生成作品档案：Pelican Bicycle / 鹈鹕骑自行车

收集不同 **model + effort + provider + harness** 生成的「鹈鹕骑自行车」SVG 2D 动画。欢迎通过 Pull Request 提交自己的结果，包括不完美或失败的尝试。

这是作品档案，不是模型排行榜。相同模型在不同服务商、推理强度、工具环境及随机采样下都可能产生不同结果；作品表现不能单独归因于模型。

### 统一 Prompt

原文保存在 [`prompt.txt`](prompt.txt)：

```text
不要联网 不查看本地其他文件，创建一个 HTML，内容是 SVG 绘制一个鹈鹕骑自行车的 2D 动画
```

生成与投稿要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 实时渠道统计

VPS 部署与数据口径见 [monitor/README.md](monitor/README.md)。页面读取最近七天个人调用统计，糖果检测按北京时间每天 08:00 运行，服务器手动检测通过 SSH 执行。

## 网页糖果题测试

推荐在项目目录启动本地服务（仅 Python 标准库，无需安装依赖）：

```bash
python3 local_server.py
```

打开 `http://127.0.0.1:8766/#model-tests`，填写 API URL、Key、模型与可选渠道备注，选择 Responses 或 Chat Completions 后开始测试。脚本自动构建网页，由本机转发请求，无需渠道开启 CORS。按 Ctrl+C 停止服务；端口被占用时使用 `python3 local_server.py --port 8767` 并打开对应地址。

支持连续测试、停止与单次超时；URL 可填根地址、API 基地址或完整接口地址。停止会终止浏览器等待和后续测试，已发送的上游请求可能继续至完成或超时，并可能计费。服务仅监听 `127.0.0.1`，仅接受同源页面请求，不记录请求日志，不保存 Key，不跟随上游重定向。Key 只用于当前请求，输入框在开始后清空，浏览器整批测试结束后释放。

时间戳、备注、耗时、回复和 Token 用量可展开查看，仅在当前页面保留最近 100 条记录，刷新清空。默认折叠的“已测站点”表格按地址、备注、模型、接口和推理强度保留最近一次结果（最多 100 项）。网页结果不写入服务器渠道统计。直接打开静态页面时仍使用浏览器直连模式，此模式需要渠道支持 CORS。

验证：`python3 build.py`、`python3 -m unittest discover -s tests -v`、`node --check candy.js`。

题目沿用原脚本，回复出现独立数字 `21` 即命中，并非模型身份或综合能力鉴定。测试直接调用 API，不包含 Codex CLI 的上下文。

## 公共自动收录

公共版由 `public_candy.py` 执行测试并存入 SQLite，任何访客读取同一张表。测试前使用当前 API Key 请求 `GET /v1/sub2api/billing`（`Authorization: Bearer <key>`），读取 `effective_rate_multiplier`。依据 Sub2API 的 `sub2api.key_billing` v1、token 计费响应；这是上游对该 Key 声明的生效倍率，可能包含用户专属倍率和高峰倍率，不是对实际扣费的独立审计。

按规范化 API 基地址＋倍率去重（例如完整 `/v1/responses` 与 `/v1` 合并）。同倍率下模型、备注和推理强度也会随最新一次记录更新，不额外拆行；较早发起的慢请求不会覆盖较新发起且已完成的结果。倍率探测失败时仍执行测试，但不公开收录；没有有效回复或服务端检测到停止的批次不覆盖已存记录。

保存 URL、倍率、模型、推理强度、备注、测试参数、时间和判分计数，以及脱敏后的逐次回复、耗时和结果（每次回复最多 20,000 字符，超出会标注）。Key 和原始接口响应对象不写数据库；公开表格显示最近 200 项，结果以“✓ 5/5”或“✗ 4/5”等形式呈现，点击“检测记录”按需加载逐次详情。服务端固定题目并判分，不接受客户端自报分数。仍可能有人配置自有接口返回固定答案，公开收录不是渠道认证。

本机预览公共版：

```bash
python3 public_candy.py
# 打开 http://127.0.0.1:8767/#model-tests
```

默认数据库在 `~/.local/share/pelican-bicycle/community.sqlite3`，不进入仓库或静态目录；可用 `--database` 指定。公网部署见 [monitor/README.md](monitor/README.md#公共糖果测试服务)。

## 浏览作品

- 在线：[我的 AI 使用实况](https://sytoken.org/ai-recommend/)。旧网址 `https://zedongpeng.com/pelican-bicycle/` 自动跳转到此处；页面与数据统一由 VPS 提供。GitHub Actions 负责校验和发布跳转页，VPS 页面更新需部署 `site/`。
- 本地：可选运行 `python3 build.py`，用浏览器打开 `site/index.html`，无需安装依赖或启动服务。
- 原始 HTML 存在 `results/<slug>/artwork.html`，也可单独打开。

画廊可按四个维度筛选，每个预览在限制网络和浏览器权限的 iframe 内播放。

## 目录结构

```text
results/
  <slug>/                  # 由元数据四字段推导，如 deepseek-v4-1-flash-max-opencode-go-opencode-02
    artwork.html          # 原始生成结果，单文件、资源内联
    metadata.json         # 运行信息
prompt.txt                # 统一 prompt（pelican-bicycle-v1）
gallery.html              # 页面模板与作品筛选
usage.js / usage.css      # 多来源个人用量界面
usage-notes.json          # 公开使用手记（纯文本，初始为空）
monitor/usage.py          # v1 聚合用量适配与扩展来源校验
monitor/USAGE_API.md      # 后续 Claude 等来源的接入契约
candy.js                  # 糖果题界面，本地转发或浏览器直连
local_server.py           # 仅本机访问的网页与转发服务（不保存 Key）
build.py                  # 校验记录并生成静态画廊
.github/                  # PR 模板、校验和 Pages 部署
```

目录 slug 必须与 metadata 四字段严格对应（推导规则见投稿指南），不包含其他语义；走实验室网关再路由上游时 provider 记为 `网关(上游)`（如 `zlab(fengchao-api.com)`，slug 取 `zlab-fengchao-api`）；更正 metadata 时须用 `git mv` 同步重命名目录。命名规则与重复输出处理见 [投稿指南](CONTRIBUTING.md#目录-slug)。画廊按 metadata 中的配置排序。去重靠构建时内部计算的 SHA-256（重复只 warning，不阻塞），不再要求目录名等于 hash。

## 元数据约定

| 字段 | 含义 |
| --- | --- |
| `model` | 模型本身的标识，保留版本；不混入服务商路由前缀或 effort。例如 `opencode-go/deepseek-v4.1-flash` 记为 `deepseek-v4.1-flash` |
| `effort` | 原始设置值，例如 `max`、`xhigh`；未知填 `unknown`，不适用填 `not-applicable` |
| `provider` | 提供模型访问的服务，例如 `deepseek-api`、`opencode-go`；走实验室网关再路由上游时记为 `网关(上游)`，如 `zlab(fengchao-api.com)`；不是模型开发商的推测值 |
| `harness` | 执行生成任务的应用/工具，例如 `codex`、`claude-code`、`opencode`、`dsh` |

投稿人信息以 git 提交和 PR 作者为准；重试、挑选、系统提示、非默认配置等补充说明写在 PR 描述的运行说明里，不单独存字段。初始 6 个作品直接从原有 HTML 导入，文件内容未修改，模型和环境信息仅由文件名提取。`unknown` 不代表官方直连。不同 provider 的 effort 标签也不保证具有相同含义。

## 参与

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，其中包含元数据模板。PR 会自动检查目录、必填字段和 HTML 基本结构。校验不证明作品质量、prompt 遵循情况或代码安全，维护者仍需审阅原始 HTML。

## 使用与许可

本项目暂未授予统一的开源许可证；公开可见不等于可以任意再分发。投稿表示你有权公开提交这些文件，并同意仓库及其 Pages 展示作品。第三方内容及服务条款仍适用；需要在其他项目复用时，请先确认相关权利与许可。
