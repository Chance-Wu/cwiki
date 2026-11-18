"""文件存储配置，从 config.yaml 加载。

初始值在 import 时从 domain 配置快照计算；config PATCH 后由
``reload_storage_config()`` 重算（``reload_yaml_config()`` 调用），
保证运行中的进程热更新 memory_dir / 索引路径。所有消费方都必须通过
``storage_config.<attr>`` 运行时属性访问，不要 from-import 常量。
"""

from pathlib import Path

from packages.domain.config import _yaml_config

# 记忆 Markdown 文件的根目录
memory_dir: str = ""

# 本地 ONNX embedding 模型缓存；放在系统临时目录之外，重启后缓存仍可复用
embedding_cache_dir: str = ""

# 派生路径：索引库与向量索引均存放在 memory_dir 内
index_db_path: str = ""
vector_index_path: str = ""

# VectorIndex.save() 写出的向量 id/元数据伴随文件。npz 只保存原始矩阵，
# 缺少此 JSON 时向量索引无法加载（见 VectorIndex._load），
# 因此一个"完整"的索引必须三个文件齐备。
vector_meta_path: str = ""

# 是否启用文件监听以自动更新索引
enable_file_watch: bool = True

# 每记忆 _meta 导出的版本快照上限（memory_version 行按 version 降序截断，
# 保留最新、丢弃最旧）：既控制 _meta JSON 体积，也保住最常被回溯的近期版本
meta_version_limit: int = 10


def reload_storage_config() -> None:
    """从当前 ``_yaml_config`` 重算全部存储配置（含派生路径）。"""
    global memory_dir, embedding_cache_dir, index_db_path, vector_index_path
    global vector_meta_path, enable_file_watch, meta_version_limit

    _storage_cfg = _yaml_config.get("storage", {})
    memory_dir = _storage_cfg.get("memory_dir", "./cwiki-data")
    embedding_cache_dir = _storage_cfg.get("embedding_cache_dir", "./data/models/fastembed_cache")
    index_db_path = str(Path(memory_dir) / "index.db")
    vector_index_path = str(Path(memory_dir) / "vectors.npz")
    vector_meta_path = str(Path(vector_index_path).with_suffix(".json"))
    enable_file_watch = _storage_cfg.get("enable_file_watch", True)
    meta_version_limit = _storage_cfg.get("meta_version_limit", 10)


reload_storage_config()
