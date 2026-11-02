# docs 文档

面向使用者的说明文档，与代码同步维护。根目录 [README.md](../README.md) 提供总览，这里按主题展开。

## 文档索引

| 文档 | 内容 |
|------|------|
| [architecture.md](architecture.md) | 系统架构、项目结构、技术栈、数据库 Schema |
| [memory-system.md](memory-system.md) | 记忆生命周期、候选流水线、演化、健康状态机、评分体系、写入契约 |
| [retrieval.md](retrieval.md) | 检索流程、Rerank 信号权重、各阶段详解 |
| [agent-onboarding.md](agent-onboarding.md) | MCP 最小配置、HTTP API 直连、兼容性验证、故障排查 |
| [git-sync.md](git-sync.md) | 多设备同步、冲突处理、数据库重建与迁移 |
| [api-reference.md](api-reference.md) | 路由模块、核心接口、反馈与冲突 |
| [development.md](development.md) | 安装配置、开发命令、`config.yaml` 完整参考 |

## 子目录

- `architecture/`：架构图源文件（C4 DSL、数据流 / 依赖 / 部署拓扑 DOT）
- `images/`：根 README 使用的界面截图

## 约定

- 文档中的命令、路径、配置项必须可直接执行或对照 `config.yaml`
- 接口、表结构、配置项变更时同步更新对应文档；根 README 的索引表一并检查
