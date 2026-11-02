# scripts 运维与安装脚本

围绕 `tasks.py` 的底层实现。日常优先使用 `python tasks.py <命令>`，脚本本身一般不需要直接调用。

## 安装与接入

| 脚本 | 用途 |
|------|------|
| `install.py` | 一站式安装：环境预检、`.venv`、依赖、数据库初始化 |
| `setup.py` | Qoder 插件与全局 MCP / AGENTS / skill 接入（含插件缓存同步） |
| `setup_agent.py` | 非 Qoder 宿主（Claude / Cursor / Codex 等）的 MCP 配置写入 |
| `setup_dsh.py` | DeepSeek Harness（dsh）接入 |
| `install_meta_export_task.py` | 注册每日 `_meta` 导出的系统计划任务 |
| `fix_dlp_entry_points.py` | 修复被本机透明加密软件破坏的 venv `entry_points.txt` |

## 运行与进程

| 脚本 | 用途 |
|------|------|
| `run_alembic.py` | Alembic 包装器（规避被加密的 entry_points） |
| `run_pytest.py` | pytest 包装器（同上） |
| `run_utils`：`port_utils.py`、`process_utils.py` | 跨平台端口管理、子进程/进程树管理 |
| `start`：`start.py`（仓库根） | 同时启动前后端，`tasks.py start` 调用 |
| `restart_watcher.py` | 脱离 API 进程的重启守护：结束旧 API 后等待健康检查，必要时兜底重启 |
| `common.py` | 上述脚本的公共工具 |

## 数据与一致性

| 脚本 | 用途 |
|------|------|
| `migrate_to_git.py` | SQLite → Markdown + `_meta` 的一次性迁移/导出 |
| `rebuild_db.py` | 从 Markdown + `_meta` 重建 `cwiki.db` |
| `recompute.py` | 重算派生字段 |
| `verify_rebuild.py` | 校验重建前后 MD / `_meta` / DB 一致性 |
| `check_integrity.py` | 存储一致性巡检（`tasks.py doctor`）：内容漂移、`_meta`、向量维度/模型；`--fix-drift` 以 MD 为准修复 |
| `meta_export_daily.py` | 计划任务入口：每日导出 MD + `_meta` |

## 评测与导入

| 脚本 | 用途 |
|------|------|
| `export_eval_queries.py` | 从检索追踪导出待人工标注的评测查询（见 `benchmarks/README.md`） |
| `import_qoder_memory.py` | 导入 Qoder Auto-Memory 数据 |

## 约定

- 需要新建脚本时优先复用 `common.py`、`port_utils.py`、`process_utils.py`
- 对外入口仍统一挂到 `tasks.py`，保持跨平台一致
