# Git 同步指南

cwiki 支持通过 GitHub 私有仓库在多台设备间同步数据。

## 架构概述

- **两个独立仓库**：代码仓库（如 `cwiki`，含 apps/packages/docs/config.yaml 等）与数据仓库（如 `cwiki-data`）各自拥有 `.git`、远端与提交历史；`cwiki-data/` 是代码仓库内的目录，但被根仓库 `.gitignore` 忽略，其版本历史完全由数据仓库管理
- **数据主源**：`cwiki-data/`（Markdown 记忆 + `_meta/` 关系数据 JSON + SQLite 数据库），随数据仓库同步
- **可重建**：`cwiki.db`、`index.db`、`vectors.npz`、`vectors.json`（丢失或冲突时可从 MD + _meta 重建）
- **设备本地**：`config.local.yaml`（位于代码仓库根目录，覆盖共享配置，不进入 git）
- **永不跟踪**：`*.db-wal` / `*.db-shm` / `*.db-journal`（SQLite WAL 临时侧车文件，由 `cwiki-data/.gitignore` 排除）

```
cwiki/                      # 代码仓库（cwiki.git）
├── apps/ packages/ docs/ ...
├── .gitignore              # 含 cwiki-data/（整体忽略）
└── cwiki-data/             # 独立数据仓库（cwiki-data.git）——目录内自带 .git
    ├── sync.py             # 数据侧同步工具（随数据仓库版本化，代码侧无同步入口）
    ├── .gitignore          # WAL 侧车 / tmp* 排除规则
    ├── {workspace}/{type}/ # Markdown 记忆文件（frontmatter + 内容）
    │   └── <id前8位>_<标题>.md
    ├── cwiki.db            # SQLite 主库（WAL 模式，sync 前自动 checkpoint）
    ├── index.db            # BM25 索引（可重建）
    ├── vectors.npz         # 向量索引（可重建）
    ├── vectors.json        # 向量 id/metadata 侧车（缺失时向量索引不可加载，会触发重建）
    └── _meta/
        ├── <memory_id_1>.json   # 关系数据：feedback, usage, review_schedule 等
        ├── <memory_id_2>.json
        ├── _workspaces.json     # workspace 元数据（name/id/时间戳，含无记忆的空 workspace）
        ├── _review_queue.json   # 候选 + 评审留痕（候选不经 Markdown 承载）
        └── _capture_notes.json  # Agent 会话 + 待整理笔记全文（不经 Markdown 承载）
```

## 首次 Setup

### 1. 创建两个 GitHub 私有仓库

- 代码仓库（如 `cwiki`）
- 数据仓库（如 `cwiki-data`）——**包含个人知识，务必用私有仓库**

两者都不要初始化 README / .gitignore。

### 2. 克隆代码仓库

```bash
git clone git@github.com:YOUR_USERNAME/cwiki.git
cd cwiki
```

### 3. 准备数据仓库

**新设备（已有数据仓库）——直接克隆到 `cwiki-data/`**：

```bash
git clone git@github.com:YOUR_USERNAME/cwiki-data.git cwiki-data
```

**全新起步（从本地 SQLite 导出）**：

```bash
# 从 SQLite 导出到 MD + _meta
python tasks.py migrate-to-git

# 初始化数据仓库并推送初始快照
cd cwiki-data
git init -b master
git add -A
git commit -m "init: 独立数据仓库初始快照"
git remote add origin git@github.com:YOUR_USERNAME/cwiki-data.git
git push -u origin master
```

### 4. 配置设备本地覆盖（可选）

如果需要在不同设备使用不同端口或其他配置：

```yaml
# config.local.yaml（键名结构与 config.yaml 一致，仅覆盖需要变更的项）
app:
  api_port: 5173  # 覆盖 config.yaml 的 app.api_port（如设备端口冲突）
```

`config.local.yaml` 不会被 git 跟踪，每台设备独立维护。

### 5. 启动

```bash
python tasks.py start
```

`start` 会自动 pull 代码仓库；`cwiki-data/cwiki.db` 缺失时从 MD + `_meta` 重建。数据更新与上报由数据仓库自带脚本完成：`python cwiki-data/sync.py`（见「日常使用」）。

## 日常使用

### 同步数据（数据仓库自管）

```bash
# 数据仓库自带同步脚本（随 cwiki-data.git 版本化分发，任意目录执行均可）
python cwiki-data/sync.py
```

`sync.py` 的 git 操作全部在**数据仓库**内执行（不触碰代码仓库），流程：
1. 执行 WAL checkpoint（`PRAGMA wal_checkpoint(TRUNCATE)`）：把 `-wal` 中的写入并入 `cwiki.db` 主文件并清空 `-wal`，保证提交的 .db 含全部数据；服务正在写入导致 checkpoint 未完成时，本次跳过并提示稍后重试
2. 检查是否有未提交变化：
   - **无变化**：跳过导出与 commit（日志显示 `本机无未提交变化`）
   - **有变化**：调用代码仓库的导出脚本把 SQLite 中的记忆导出到 `cwiki-data/`（MD + _meta）→ `git add -A` → `git commit`（带时间戳）
3. `git pull --rebase` 拉取远端数据——在本地改动已提交、工作区干净后执行，避免覆盖本机未提交数据（离线时提示并继续；rebase 冲突会明确提示手动解决）
4. `git push`（失败不丢数据，commit 保留在本地；无变化时仅补推离线留下的 commit）
5. 代码改动不走 `sync.py`：代码仓库照常 `git add` / `git commit` / `git push`

> 前置条件：代码仓库位于 `cwiki-data/` 上一级（标准布局 `cwiki/cwiki-data/`），且已通过 `python tasks.py install` 备好 `.venv`——`sync.py` 会自动定位 `../.venv` 解释器调用导出脚本。
> checkpoint 若有 WAL 合并会改写 `cwiki.db`，`git status` 因此显示变化，走正常导出路径（正确行为）。

### 启动服务

```bash
# 自动 pull 代码仓库 + 检测 DB 缺失触发 rebuild
python tasks.py start
```

`start` 命令会（不触碰数据仓库；数据更新请先运行 `python cwiki-data/sync.py`）：
1. `git pull --rebase` 代码仓库（拉取最新代码）
2. 检测 `cwiki-data/cwiki.db` 是否存在，若缺失则自动从 MD + _meta 重建；重建时：
   - 索引文件（`index.db` + `vectors.npz` + `vectors.json`）存在且与记忆数一致 → 跳过 embedding 重建（数秒完成）
   - `_meta` 已恢复 review_schedule → 跳过 recompute（日志显示 `Skipped: review schedules restored from _meta`）
3. 检测索引文件是否缺失（DB 正常但索引丢了，如 git 冲突解决、手动删除）：仅重建索引，不重建 DB（日志显示 `[sync] index files missing ..., rebuilding index only ...`；失败不阻塞启动）
4. 启动全栈服务

### 运行中拉取远端更新

服务运行中拉到新的 `cwiki.db` 后，运行中的服务不会自动加载新文件；且本地未同步的数据改动会让数据仓库 pull 失败。正确姿势：

```bash
# 1. 同步数据：sync.py 自动提交本机改动、拉取远端数据并推送
python cwiki-data/sync.py

# 2. 重启以加载新 DB（restart 前会自动 pull 代码仓库）
python tasks.py restart
```

### 手动重建数据库

```bash
# 从 MD + _meta 重建 SQLite
python tasks.py rebuild-db

# 强制重新生成向量索引（embedding 推理很慢，仅在怀疑索引过期时使用）
python tasks.py rebuild-db --force-index

# 只重建索引（index.db + vectors.npz + vectors.json），不重建 DB
python tasks.py rebuild-db --index-only

# 校验重建结果：比对 MD/_meta 与 DB 的记忆数量与关键字段
python scripts/verify_rebuild.py
```

重建默认是轻量化的：

- **跳过索引重建**：`index.db` + `vectors.npz` + `vectors.json` 都在且索引 active 行数与记忆 active 数一致时，跳过 embedding 重建（日志显示 `Skipped: index files present (use --force-index to rebuild)`），rebuild 从秒/分钟级降到数秒；不一致时自动重建并提示原因
- **跳过 recompute**：`_meta` 导入已恢复 review_schedule（重建日志 `review_schedule: 23`）时跳过 recompute（日志显示 `Skipped: review schedules restored from _meta`）；仅当调度为空（旧数据未导出过调度）时才自动跑 recompute
- `python tasks.py recompute` 手动命令不受影响，始终执行

### 重算派生数据

```bash
# 重算 SM-2 调度等派生字段
python tasks.py recompute
```

适用场景：手动修改了 `_meta/` 中的 review_history 或 feedback 数据后，需要重新计算派生字段。

## 多设备工作流

### 设备 A -> 设备 B

1. 设备 A：`python cwiki-data/sync.py`（含 WAL checkpoint，DB + MD 一并提交到数据仓库）
2. 设备 B：`python cwiki-data/sync.py`（拉取最新数据）→ `python tasks.py start`（自动 pull 代码仓库；DB 已随数据仓库同步，直接使用；若缺失则自动 rebuild）

### 离线工作

- 离线时 `sync.py` 的 pull/push 会失败并提示，但数据已 commit 到本地数据仓库
- 下次联网时 `python cwiki-data/sync.py` 会补推之前的 commit

### 多设备注意事项

- 每次切换设备前先在旧设备运行 `python cwiki-data/sync.py`；新设备先 `python cwiki-data/sync.py` 再 `python tasks.py start`
- 避免两台设备同时离线修改同一记忆（冲突概率低但非零）

## 从单仓库迁移（旧设备一次性）

历史版本中代码与数据位于同一仓库；现拆分为两个独立仓库。**已按新布局同步过的旧设备**需要执行以下一次性迁移（本机已完成拆分并由其推送了数据仓库初始快照）：

> 迁移前：先在旧布局下 `python tasks.py sync` 一次，并停止在其他设备写入数据，尽量减少两端差异。

```bash
# ① 为 cwiki-data 建立独立仓库，快照并同步本地数据（保护本机数据）
cd cwiki-data
git init -b master
git add -A
git commit -m "import: 本地数据快照"
git remote add origin git@github.com:YOUR_USERNAME/cwiki-data.git
git fetch origin
git merge --allow-unrelated-histories origin/master   # 两端数据一致时瞬时完成
git push -u origin master

# ② 回到主目录，拉取拆分提交
cd ..
git pull --rebase     # 若因本地数据改动报错：数据已安全存入 ① 的快照，可 git checkout -- cwiki-data 后重试

# ③ 从独立仓库快照恢复数据文件（父仓库 pull 会移除其旧跟踪的 cwiki-data 文件）
git -C cwiki-data checkout -- .

# ④ 验证（代码侧 pull 后 tasks.py 已无 sync，数据同步由数据仓库自带脚本完成）
python cwiki-data/sync.py
```

**有本地独有记忆时的合并冲突**：`cwiki.db` / 索引为二进制，可能出现 add/add 冲突——任选一端（`git -C cwiki-data checkout --ours -- cwiki.db`（取本机快照）或 `--theirs`（取远端））后 `git -C cwiki-data add cwiki.db`，或删除 DB 与索引后 `python tasks.py rebuild-db` 从 MD + `_meta` 重建；Markdown 与 `_meta` 按内容正常合并。

## 冲突处理

以下命令均作用于**数据仓库**（`git -C cwiki-data ...` 在项目根目录执行）。

### Markdown 文件冲突

Git 会标记冲突，手动编辑解决后：

```bash
# 编辑解决冲突
# ...

# 标记已解决并在数据仓库提交
git -C cwiki-data add -A
git -C cwiki-data commit
python cwiki-data/sync.py
```

### _meta/ JSON 冲突

罕见（按 memory_id 分文件）。如果发生：

1. 比较两个版本的关系数据
2. 保留较新的（看 `updated_at` 时间戳）
3. 或合并（如两端的 feedback 列表合并去重）

```bash
# 查看冲突文件
git -C cwiki-data diff -- _meta/<memory_id>.json

# 解决后
git -C cwiki-data add _meta/
git -C cwiki-data commit
python cwiki-data/sync.py
```

### cwiki.db 二进制冲突

SQLite 数据库与索引文件是二进制，git 无法合并。若数据仓库 pull/rebase 时出现 `cwiki.db` 冲突：

1. **二选一**：保留某一端的版本（`git -C cwiki-data checkout --ours -- cwiki.db`（本机）或 `--theirs`（远端），或手动从另一台设备复制）。另一端的记忆若已 sync 过，仍完整存在于 MD + _meta 中；
2. **兜底重建**（两端数据需要取并集时推荐）：删除本地库，从 MD + _meta 重建。索引文件与 DB 内容可能不匹配，重建时会自动检测并重新生成索引。

```bash
# 先确保 cwiki-data/ 下 MD + _meta 是想要的数据（必要时手动解决 Markdown 冲突）

# 删除冲突的二进制文件（索引文件与 DB 同步冲突时才需删除；只删 DB 的话索引会被复用）
rm cwiki-data/cwiki.db cwiki-data/index.db cwiki-data/vectors.npz cwiki-data/vectors.json

# 从 MD + _meta 重建（review_schedule 从 _meta 恢复时跳过 recompute）
python tasks.py rebuild-db

# 提交重建结果
python cwiki-data/sync.py
```

## 故障排查

### DB 损坏

```bash
# 删除损坏的 DB——索引文件尽量保留：重建时可复用，避免重新 embedding
rm cwiki-data/cwiki.db

# 若索引文件（index.db / vectors.npz / vectors.json）也损坏或缺失再一并删除
rm cwiki-data/index.db cwiki-data/vectors.npz cwiki-data/vectors.json

# 重建（自动从 MD + _meta 恢复；索引完好且一致时跳过 embedding 重建，数秒完成）
python tasks.py rebuild-db

# 校验 MD/_meta/DB 三方一致
python scripts/verify_rebuild.py
```

DB 文件缺失或损坏时，重建会经 Alembic 自动创建完整 schema（含非记忆表），无需手工建表或先执行迁移。workspace 表从 `_meta/_workspaces.json` 恢复（保留原 id 与时间戳，含无记忆的空 workspace）；该文件缺失时（旧版本导出）回退为从 MD frontmatter 恢复有记忆的 workspace，记忆的 workspace 归属不会丢失。候选与待整理笔记分别从 `_meta/_review_queue.json`、`_meta/_capture_notes.json` 恢复；旧版导出缺这两个文件时对应表为空，不影响记忆本体重建。

若只是索引文件丢失（DB 完好），无需任何手工操作：`python tasks.py start` 检测到后会只重建索引（不重建 DB，日志 `[sync] index files missing ..., rebuilding index only ...`）；手动等价命令：

```bash
python tasks.py rebuild-db --index-only
```

### 同步后数据不一致

```bash
# 检查 MD + _meta 文件数量
find cwiki-data -name "*.md" | wc -l
ls cwiki-data/_meta/*.json | wc -l

# 重新导出
python tasks.py migrate-to-git

# 重建 DB
python tasks.py rebuild-db

# 校验 MD/_meta/DB 三方一致
python scripts/verify_rebuild.py
```

### Git pull 失败

- 检查网络连接
- 检查 SSH key 或 GitHub token
- 本机有未提交的 DB/MD 改动时手动 `pull --rebase` 会失败；运行 `python cwiki-data/sync.py`（会自动提交本机改动再拉取）即可
- 手动 `git -C cwiki-data pull --rebase` 查看详细错误信息

### pull 后数据未生效

`cwiki.db` 以文件替换方式更新，运行中的服务不会自动重新加载。重启即可生效：

```bash
python tasks.py restart   # 重启前自动 pull 代码仓库；数据由 python cwiki-data/sync.py 拉取
```

### recompute 失败

recompute 失败不阻塞启动。如需手动重算：

```bash
python tasks.py recompute
```

## 注意事项

- **不要手动编辑 cwiki.db**：SQLite 是二进制，无法 git 合并；数据变更走 API，由 `python cwiki-data/sync.py` 统一提交
- **切换设备前先 sync.py**：未提交的 DB 改动会让 `sync.py` 跳过 pull（日志会提示），先在旧设备完成同步再切新设备
- **WAL 侧车不跟踪**：`*.db-wal` / `*.db-shm` / `*.db-journal` 由 `cwiki-data/.gitignore` 排除，`sync` 自动 checkpoint 保证提交的 .db 完整
- **定期运行 `python cwiki-data/sync.py`**：避免多设备离线工作太久导致冲突
- **备份**：首次迁移或重建前备份 `cwiki-data/cwiki.db`
- **私有仓库**：数据仓库（`cwiki-data.git`）包含个人知识，务必用私有仓库
- **config.local.yaml 不同步**：每台设备独立配置，不进入 git
