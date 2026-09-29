# AI 使用实况

我日常用 AI 的用量和手记。在线：[`sytoken.org/ai-board/`](https://sytoken.org/ai-board/)。

## 目录

| 目录 | 内容 |
| --- | --- |
| [`web/`](web/) | 页面：`index.html` 模板、`style.css`，看板 `tokens.js`、中转站 `relay.js`、成本试算 `cost.js`、糖果题 `candy.js`、作品筛选 `gallery.js`，手记 `notes.json` |
| [`collector/`](collector/) | token 用量采集：读各机器的 Claude Code、Codex、OpenCode 日志和 Cursor 后台记录，按官方价折算，每天发布 `tokens.json` |
| [`monitor/`](monitor/) | 中转站统计与每日糖果检测（VPS 服务） |
| [`candy/`](candy/) | 糖果题：固定题、本地转发服务、公共收录服务 |
| [`pelican/`](pelican/) | 鹈鹕骑自行车作品档案：prompt 与投稿 |
| [`tests/`](tests/) | 全部测试 |
| `build.py` | 校验作品，生成 `site/`（不提交） |
| [`pages-redirect/`](pages-redirect/) | 旧 GitHub Pages 地址的跳转页 |

## 手记

写在 [`web/notes.json`](web/notes.json)：数组，每条 `date`（`YYYY-MM-DD`）、`title`、`body`，可选 `tags`。正文是纯文本，保留换行；只有 `[文字](https://…)` 会变成链接。构建时校验、转义并按日期倒序。

## 预览与测试

```bash
python3 candy/local_server.py      # 构建并打开 http://127.0.0.1:8766/；用量和中转站数据只在线上有
python3 build.py
python3 -m unittest discover -s tests
node --test tests/test_tokens_ui.js
for f in web/*.js; do node --check "$f"; done
# 可选，需要 Playwright：python3 candy/local_server.py --port 18766 & node tests/browser.cjs
```

## 部署

`python3 build.py` 后把 `site/` 同步到 VPS 的 `/var/www/ai-benchmark/`，排除 `data/`（`tokens.json` 由 collector 每天写入）。服务端配置见 [`monitor/README.md`](monitor/README.md)。

## 使用与许可

本项目暂未授予统一的开源许可证；公开可见不等于可以任意再分发。投稿表示你有权公开提交这些文件，并同意仓库及其 Pages 展示作品。第三方内容及服务条款仍适用；需要在其他项目复用时，请先确认相关权利与许可。
