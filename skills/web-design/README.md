# Web 设计技能 v1.0

面向 Codex、Qoder、Claude Code、OpenCode 等 AI 编码 Agent 的可复用 Web 设计技能。

## 包含内容

- 核心设计原则
- 布局 / 排版 / 色彩 / 间距 / 层级 / 密度
- 响应式设计
- 交互与动效
- 开发者工具类界面范式
- 仪表盘 / 表格 / 详情 / 设置 / 命令中心范式
- 反 AI 套路（anti-AI-slop）规则
- 视觉审查
- 可访问性审查
- 响应式审查
- 新页面与改版工作流
- 设计简报与审查模板

## 推荐用法

将 `web-design` 目录安装/复制到你的 Agent 技能目录。

最重要的工作流是：

```text
设计 → 实现 → 渲染 → 截图 → 审查 → 修复 → 再次渲染
```

该技能刻意保持技术无关，但优先复用项目已有的技术栈与设计系统。

## 建议命令

如果你的 Agent 支持自定义命令，可映射为：

- `/design` → workflows/new-page.md
- `/design-review` → review/visual-review.md
- `/design-redesign` → workflows/redesign.md
- `/design-polish` → workflows/visual-iteration.md
