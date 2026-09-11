## 新增记录

- Model:
- Effort:
- Provider:
- Harness / version:
- 结果目录（`results/<slug>/`，如 `deepseek-v4-1-flash-opencode-go-opencode-01`）:

## 运行说明

是否一次生成？是否重试或挑选？是否存在额外提示、工具权限或配置？

## 检查

- [ ] 元数据真实填写，未知项明确标注
- [ ] model 与已有同模型命名一致，服务商路由前缀单独记入 provider，原始标识保留在 notes
- [ ] 目录 slug 可读且未占用，配置仅写入 metadata
- [ ] 未覆盖已有运行；如输出与已有记录字节相同，已在 notes 解释并同步 main
- [ ] 原始 HTML 未手动改动；如有后续生成轮次已披露
- [ ] 已说明是否使用统一 prompt、禁用联网及读取其他文件
- [ ] 没有凭据、隐私数据、跟踪代码或外部依赖
- [ ] 有权公开投稿并同意在仓库及 Pages 展示
- [ ] CI 校验通过（本地可选跑 `python3 build.py` 预览）
