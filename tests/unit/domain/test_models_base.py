"""JSONBType 的落库语义测试。

回归防线：Python ``None`` 必须落库为 SQL NULL，而非 JSON 'null' 文本。
历史上 ``impl = JSON``（none_as_null=False）会把 ORM flush 的 None 序列化
成字符串 'null'，与列默认 NULL 混存——重建对账时同一逻辑值呈现两种
存储形态（W7 审计 3.2 的根因）。
"""

from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, text

from packages.domain.models.base import JSONBType


def test_none_binds_as_sql_null(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    metadata = MetaData()
    table = Table(
        "t",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("data", JSONBType),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(table).values(id=1, data=None))
        # 绕过 ORM 直读原始存储：None 必须是 SQL NULL 而非 'null' 文本
        raw = conn.execute(text("SELECT data FROM t WHERE id = 1")).scalar()
    assert raw is None
