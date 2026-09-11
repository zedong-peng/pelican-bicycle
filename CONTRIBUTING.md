# 投稿指南

## 生成作品

1. 使用空目录和新会话，记录 model、effort、provider、harness 与可确认的版本。
2. 原样提交 `prompt.txt` 中的 prompt；禁用网络工具，不允许读取目录外的文件。不添加额外的用户指令。
3. 保留模型输出的原始 HTML，不手动修复、重画或美化。输出有问题也可投稿；如有重试、后续修复指令或挑选，必须在 PR 描述里披露。

## 提交 Pull Request

1. Fork 仓库并创建分支。
2. 在 `results/<slug>/` 新建目录，`slug` 自取、可读，例如 `deepseek-v4-1-flash-opencode-go-opencode-01`。只能用小写字母、数字和连字符，1–64 字符，首尾必须是字母或数字；不要用纯 12 位十六进制（那是旧 hash 目录，已废弃）。目录名不包含运行配置以外的语义负担，冲突时加 `-02`、`-03` 后缀。
3. 将原始结果放入 `artwork.html`，按下方模板创建同目录下的 `metadata.json` 并填写，一共 4 个字段。无法确认的信息使用 `unknown`，不要猜测。
4. 本地可选执行 `python3 build.py`，打开 `site/index.html` 检查预览与标签；构建产物不提交。PR 和合并后的画廊都由 GitHub Actions 自动校验与构建（参见 `.github/workflows/pages.yml`），本地不跑也不影响。
5. 提交 PR，填写模板并披露非标准运行条件。

单个 HTML 上限 2 MiB，必须含 SVG，CSS、脚本及资源应内联。不要提交 API key、账号凭据、本地绝对路径、个人信息、跟踪代码、远程依赖或与作品无关的文件。不要修改已有投稿；同配置的重复运行用新的目录记录。截图或运行日志不是必需项，敏感信息不得提交。

## 目录 slug

参考 ccfddl 的 `conference/<类别>/<会议名>.yml`：路径应该是人类可读的，PR 里一眼看出改的是谁。

```sh
mkdir -p results/deepseek-v4-1-flash-opencode-go-opencode-01
cp /path/to/output.html results/deepseek-v4-1-flash-opencode-go-opencode-01/artwork.html
# 再按模板新建同目录下的 metadata.json
```

- 建议格式：`<model>-<provider>-<harness>-<序号>`，全部小写，非字母数字转连字符，例如 `muse-spark-1-3-opencode-go-opencode`。model、effort、provider、harness 只写在 metadata 中，目录名只是方便 review 的别名，更正元数据时保留目录名。
- 不重复提交同一次运行。独立运行恰好输出相同 HTML 是允许的，用不同目录记录，并在 PR 描述里说明原因；CI 只会打印 warning，不会因此失败。不要覆盖或合并运行记录。
- PR 合并前同步 `main`；如果 slug 已被占用，换一个未占用的名字。
- 不要格式化 HTML 或转换换行；仓库通过 `.gitattributes` 禁用作品文件的自动换行转换。

## 元数据模板

```json
{
  "model": "exact-model-id",
  "effort": "unknown",
  "provider": "unknown",
  "harness": "harness-name"
}
```

字段含义见 [README](README.md#元数据约定)。所有作品都使用当前 `prompt.txt` 生成；重试、挑选、系统提示、非默认配置、失败现象等补充说明写在 PR 描述的运行说明里。

`model` 填模型标识，`provider` 单独填服务商。例如运行环境显示 `opencode-go/deepseek-v4.1-flash`，应填 `model: deepseek-v4.1-flash`、`provider: opencode-go`。优先使用仓库已有的同模型名称；不同版本不能合并，也不要盲目删除模型名称中的斜杠或开发商命名空间。

## 维护者审阅

- 核对元数据与作者的运行说明，区分事实和未知信息。
- 检查 HTML 的脚本、资源及链接是否仅用于动画；自动结构校验不能代替源码审阅。
- 优先通过画廊的 sandbox 预览审查，不直接在具有登录状态的浏览器中打开未经审查的 HTML。
- 接受不完美作品，不按美观程度筛除失败结果。
- 合并后自动部署 Pages。PR 工作流只校验并构建，不部署、不访问密钥。

提交者须有权公开投稿，并同意在仓库和 Pages 中展示。当前仓库没有统一开源许可证，投稿不自动授予其他用途的再许可。
