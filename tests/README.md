# tests 测试套件

pytest（`asyncio_mode = "auto"`，`testpaths = ["tests"]`）+ 前端 Vitest。测试使用内存 SQLite 与依赖覆盖，不触碰真实数据库和外部服务。

## 目录

| 目录 | 覆盖范围 |
|------|----------|
| `adapter/` | MCP 工具契约、本地索引降级、hook 运行时、host profile、workspace 注入 |
| `api/` | 路由行为：事件、候选、审核、检索、配置、工作区、鉴权、导出 |
| `integration/` | 跨模块链路：MCP stdio、outbox、golden 场景、hook 演练、安装脚本、技能发布 |
| `unit/domain/` | 配置、任务队列、写入决策/策略、规则匹配、调度器、密钥脱敏 |
| `unit/memory/` | 质量门控、去重黄金集、健康、生命周期、SM-2、关系强化、标签 |
| `unit/retrieval/` | 检索管线、BM25、重排、多样性、上下文组装与压缩、评估器 |
| `unit/ranking/` | 时态过滤等排序纯函数 |
| `unit/storage/` | FileStore、MetaStore、索引、重建、一致性、`_meta` 导出、标签持久化 |
| `worker/` | 评分、自动审核状态机、episode 回填、快照 |

`tests/conftest.py` 提供：内存数据库 `db_session`、覆盖 `get_db` / 身份依赖的 `client`，以及把全局任务队列与导出状态重定向到临时目录的会话级隔离。

## 运行

```bash
python tasks.py test                 # 全量（scripts/run_pytest.py tests/ -v）
python -m pytest tests/unit/retrieval -q
```

前端测试在 `apps/web/` 下运行：

```bash
npm run test:run
```

## 约定

- 单元测试不连真实 DB、不写 `~/.cwiki/state`；需要数据库时用内存库或 `tmp_path`
- 涉及进程、网络、时钟的用例必须 mock
- 修复缺陷先补回归用例；重复检测等门槛类测试保留黄金集
- 快照（`tests/worker/snapshots/`）仅在确认行为变更有意时更新
