# packages/domain — 领域基础

全项目共享的模型、schema、配置与工具，不包含具体业务流程。

## 模块

| 模块 | 职责 |
|------|------|
| `config.py` | 从 `config.yaml` 加载数据库、应用、检索、演化、调度等配置（`settings` 单例） |
| `settings.py` | 应用设置访问入口（`get_settings()`） |
| `database.py` | 异步 SQLAlchemy 引擎、`async_session_maker`、`Base` 声明基类 |
| `models/` | ORM 模型：`memory.py`（Memory / MemoryVersion / CandidateMemory / Evidence 等）、`session.py`（Session / Event / Episode / AgentSession / SessionNote）、`workspace.py`（Workspace / Agent / AgentProfile）、`retrieval.py`（检索追踪） |
| `schemas/` | API 请求/响应 Pydantic v2 schema：memory、search、session、workspace、agent_capture、candidate_contract、task_queue |
| `task_queue.py` | 轻量后台任务队列：内存调度 + 磁盘持久化、重试、死信 |
| `scheduler.py` | `PeriodicScheduler`：在 FastAPI lifespan 内按间隔触发队列任务 |
| `write_decisions.py` | 写入决策：`write` / `skip` / `update` |
| `write_policy.py` | 写入策略：自动生效 / 人工审核 / 拒绝 |
| `rule_match.py` | 写入决策与写入策略共用的规则匹配语义 |
| `errors.py` | 统一错误层级（`AppError` 等） |
| `export_import.py` | 数据导入/导出服务 |
| `secrets.py` | 密钥脱敏与敏感文件识别 |
| `paths.py` | 跨平台路径/文件名组件校验与清洗 |
| `types.py`、`text_utils.py`、`time_utils.py` | 记忆类型定义、文本与时间工具 |
| `version.py` | 统一版本号（读取 `pyproject.toml` 的 `app_version()`） |

## 约定

- workspace 是唯一组织维度，不引入 project/scope 概念
- schema 与 ORM 模型分开维护，schema 只描述接口形状
- 新增配置项写入 `config.yaml` 并在 `config.py` 补解析，不新增环境变量开关

测试：`tests/unit/domain/`。
