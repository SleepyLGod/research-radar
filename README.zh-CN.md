# ResearchRadar

![ResearchRadar](docs/assets/research-radar-plus.png)

ResearchRadar 是一个本地优先的研究情报系统：每天发现新的论文和技术来源，精读关键论文，
核验证据，再生成可在微信公众号草稿箱审阅的长文日报。

`本地优先` · `证据门控` · `论文精读` · `微信公众号草稿` · `定时任务` · `Tavily 搜索` ·
`DeepSeek` · `Codex verifier`

[English README](README.md) · [详细使用说明](docs/usage.md) · [架构](docs/architecture.md) ·
[安全说明](docs/security.md)

## 它解决什么问题

ResearchRadar 的目标不是简单摘要网页，而是把“发现新研究 -> 精读论文 -> 检查事实 -> 生成可读文章”
串成一条可审计的工作流。它会保留完整运行产物，但公众号正文只使用已经通过证据核验的内容。

默认日报链路是：

1. 用 paper-first ranking 和 Tavily 补充召回；
2. 用 DeepSeek v4 Pro 精读选中的论文；
3. 用 Codex `gpt-5.5` 检查可发布 claim；
4. 渲染成可读的中文长文；
5. 创建微信公众号草稿，只进草稿箱，不自动发布。

## 快速开始

安装依赖并初始化本地配置：

```bash
uv sync --extra dev
uv run research-radar init
```

把本地密钥存进 Keychain，并检查状态：

```bash
uv run research-radar secrets set deepseek
uv run research-radar secrets set web-search
uv run research-radar secrets set wechat
uv run research-radar secrets status
```

运行一次日报：

```bash
uv run research-radar run daily \
  --topic agent-memory \
  --config config.example.yaml \
  --root research-radar-data \
  --language zh \
  --model-cache
```

创建微信公众号草稿：

```bash
uv run research-radar publish wechat-draft \
  --run runs/<date-topic> \
  --title "ResearchRadar 日报：<topic>" \
  --digest "今日精选 <topic> 相关论文精读。" \
  --thumb-media-id "<wechat-thumb-media-id>"
```

生成本地定时任务：

```bash
uv run research-radar schedule daily-draft \
  --topic agent-memory \
  --time 09:00 \
  --config config.example.yaml \
  --root research-radar-data \
  --thumb-media-id "<wechat-thumb-media-id>" \
  --language zh \
  --model-cache
```

## 质量边界

公开报告只展示 supported 且 evidence anchor 完整的 claim。弱证据、拒绝项、调试信息和审计记录会留在
本地 artifacts 里，不会混进普通读者看到的正文。

Xiaomi `mimo-v2.5-pro` 已作为可选 OpenAI-compatible provider 接入，可以显式替代 DeepSeek 路由；
默认路径仍保持 DeepSeek reader 和 Codex verifier。

## 更多文档

- [详细使用说明](docs/usage.md)：安装、密钥、日报、单篇论文、微信草稿、scheduler、隐私检查。
- [架构](docs/architecture.md)：从 source discovery 到 article draft 的数据流。
- [安全说明](docs/security.md)：本地 secret、隐私扫描和发布边界。
- [路线图](docs/todo.md)：产品和工程 TODO。

## License

MIT
