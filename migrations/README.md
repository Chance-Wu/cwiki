# migrations 数据库迁移

基于 Alembic 的 schema 版本管理，目标库为 `config.yaml` 中 `database.url` 指向的 SQLite（默认 `cwiki-data/cwiki.db`）。

## 结构

- `env.py`：异步迁移环境；用应用配置覆盖 `alembic.ini` 的连接串，`target_metadata` 取 `packages.domain.database.Base.metadata`
- `script.py.mako`：新迁移模板
- `versions/`：迁移脚本。按 `001_…` 起的序号命名，另有 autogenerate 生成的哈希版本；`down_revision` 串成单一 head

## 命令

```bash
python tasks.py migrate-up      # 升级到 head
python tasks.py migrate-down    # 回退一个版本
python tasks.py migrate-init    # 用全部迁移初始化（migrate-up 别名）
python tasks.py migrate-create "描述"   # 生成新迁移
```

`tasks.py` 通过 `scripts/run_alembic.py` 调用 Alembic，以规避本机透明加密软件破坏 `entry_points.txt` 的问题。`python tasks.py start/restart` 会先执行 `upgrade head`。

## 约定

- 修改 ORM 模型后必须生成迁移，不允许只改模型不落迁移
- 不对已发布的迁移做破坏性改写；修正走新迁移
- 迁移内避免依赖运行时业务代码，保持可在空库上从 `001` 顺序执行到 head
