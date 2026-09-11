# 投稿指南

## 生成作品

1. 使用空目录和新会话，记录 model、effort、provider、harness 与可确认的版本。
2. 原样提交 `prompt.txt` 中的 prompt；禁用网络工具，不允许读取目录外的文件。不添加额外的用户指令。
3. 保留模型输出的原始 HTML，不手动修复、重画或美化。输出有问题也可投稿；如有重试、后续修复指令或挑选，必须在 `notes` 中披露，修复后的记录用 `multi-turn`。

## 提交 Pull Request

1. Fork 仓库并创建分支。
2. 计算原始 HTML 的 SHA-256，取前 12 位小写十六进制作为 ID，在 `results/<id>/` 新建目录；命令见下方。目录不包含模型或运行配置。
3. 将原始结果放入 `artwork.html`，按下方模板创建同目录下的 `metadata.json` 并填写。无法确认的信息使用 `unknown` 或 `null`，不要猜测。
4. 执行 `python3 build.py`，打开 `site/index.html` 检查预览与标签；构建产物不提交。
5. 提交 PR，填写模板并披露非标准运行条件。

单个 HTML 上限 2 MiB，必须含 SVG，CSS、脚本及资源应内联。不要提交 API key、账号凭据、本地绝对路径、个人信息、跟踪代码、远程依赖或与作品无关的文件。不要修改已有投稿；同配置的重复运行用新的目录记录。截图或运行日志不是必需项，敏感信息不得提交。

## 目录 ID

在原始 HTML 所在目录运行（文件名不是 `artwork.html` 时替换最后一个参数）：

```sh
python3 -c "import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()[:12])" artwork.html
```

例如输出 `ad3184984a90`，就提交 `results/ad3184984a90/artwork.html` 和 `metadata.json`。只需这两个文件，无需修改索引或画廊；CI 会校验 ID 与 HTML 内容是否匹配。

- model、effort、provider、harness 只写在 metadata 中；更正元数据时保留目录 ID，并在 PR 说明依据。
- 不重复提交同一次运行。如果独立运行恰好输出相同 HTML，或短哈希碰撞，使用 `<id>-2`、`<id>-3` 等未占用后缀，并在 `notes` 说明原因。不要覆盖或合并运行记录。
- PR 合并前同步 `main`；如果 ID 已被另一份独立记录占用，按上述规则添加后缀。
- 哈希基于原始文件字节。不要格式化 HTML 或转换换行；仓库通过 `.gitattributes` 禁用作品文件的自动换行转换。

## 元数据模板

```json
{
  "model": "exact-model-id",
  "effort": "unknown",
  "provider": "unknown",
  "harness": "harness-name",
  "harness_version": null,
  "prompt_id": "pelican-bicycle-v1",
  "prompt_verified": true,
  "created_at": null,
  "contributor": "your-github-handle",
  "generation": "single-turn",
  "notes": ""
}
```

字段含义见 [README](README.md#元数据约定)。`prompt.txt` 对应 `pelican-bicycle-v1`。

## 维护者审阅

- 核对元数据与作者的运行说明，区分事实和未知信息。
- 检查 HTML 的脚本、资源及链接是否仅用于动画；自动结构校验不能代替源码审阅。
- 优先通过画廊的 sandbox 预览审查，不直接在具有登录状态的浏览器中打开未经审查的 HTML。
- 接受不完美作品，不按美观程度筛除失败结果。
- 合并后自动部署 Pages。PR 工作流只校验并构建，不部署、不访问密钥。

提交者须有权公开投稿，并同意在仓库和 Pages 中展示。当前仓库没有统一开源许可证，投稿不自动授予其他用途的再许可。
