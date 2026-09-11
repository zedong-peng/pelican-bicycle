# Pelican Bicycle / 鹈鹕骑自行车

收集不同 **model + effort + provider + harness** 生成的「鹈鹕骑自行车」SVG 2D 动画。欢迎通过 Pull Request 提交自己的结果，包括不完美或失败的尝试。

这是作品档案，不是模型排行榜。相同模型在不同服务商、推理强度、工具环境及随机采样下都可能产生不同结果；作品表现不能单独归因于模型。

## 统一 Prompt

原文保存在 [`prompt.txt`](prompt.txt)：

```text
不要联网 不查看本地其他文件，创建一个 HTML，内容是 SVG 绘制一个鹈鹕骑自行车的 2D 动画
```

生成与投稿要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 浏览作品

- 在线：[作品画廊](https://zedongpeng.com/pelican-bicycle/)。合并新投稿后由 GitHub Actions 自动更新。
- 本地：运行 `python3 build.py`，用浏览器打开 `site/index.html`，无需安装依赖或启动服务。
- 原始 HTML 存在 `results/<run-id>/artwork.html`，也可单独打开。

画廊可按四个维度筛选，每个预览在限制网络和浏览器权限的 iframe 内播放。

## 目录结构

```text
results/
  <id>/                   # HTML 的 SHA-256 前 12 位
    artwork.html          # 原始生成结果，单文件、资源内联
    metadata.json         # 运行信息
prompt.txt                # 统一 prompt（pelican-bicycle-v1）
gallery.html              # 画廊模板，内含 CSS 和 JS
build.py                  # 校验记录并生成静态画廊
.github/                  # PR 模板、校验和 Pages 部署
```

目录 ID 不包含运行配置；更正 metadata 无需重命名。命名命令与重复输出规则见 [投稿指南](CONTRIBUTING.md#目录-id)。画廊按 metadata 中的配置排序。

## 元数据约定

| 字段 | 含义 |
| --- | --- |
| `model` | 模型本身的标识，保留版本；不混入服务商路由前缀或 effort。例如 `opencode-go/deepseek-v4.1-flash` 记为 `deepseek-v4.1-flash`，原始路由标识保留在 `notes` |
| `effort` | 原始设置值，例如 `max`、`xhigh`；未知填 `unknown`，不适用填 `not-applicable` |
| `provider` | 提供模型访问的服务，例如 `deepseek-api`、`opencode-go`；不是模型开发商的推测值 |
| `harness` | 执行生成任务的应用/工具，例如 `codex`、`claude-code`、`opencode`、`dsh` |
| `harness_version` | 可确认的版本字符串，未知填 `null` |
| `prompt_id` | 当前为 `pelican-bicycle-v1` |
| `prompt_verified` | 是否确认使用了该 prompt 原文 |
| `created_at` | 生成日期 `YYYY-MM-DD`，未知填 `null` |
| `contributor` | 投稿者 GitHub 用户名 |
| `generation` | `single-turn`、`multi-turn` 或 `unknown` |
| `notes` | 重试、挑选、系统提示、非默认配置、失败现象等补充说明 |

初始 6 个作品直接从原有 HTML 导入，文件内容未修改。模型和环境信息仅由文件名提取；日期、版本、生成轮次及 prompt 是否完全一致未确认，已明确标注。`unknown` 不代表官方直连。不同 provider 的 effort 标签也不保证具有相同含义。

## 参与

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，其中包含元数据模板。PR 会自动检查目录、必填字段和 HTML 基本结构。校验不证明作品质量、prompt 遵循情况或代码安全，维护者仍需审阅原始 HTML。

## 使用与许可

本项目暂未授予统一的开源许可证；公开可见不等于可以任意再分发。投稿表示你有权公开提交这些文件，并同意仓库及其 Pages 展示作品。第三方内容及服务条款仍适用；需要在其他项目复用时，请先确认相关权利与许可。
