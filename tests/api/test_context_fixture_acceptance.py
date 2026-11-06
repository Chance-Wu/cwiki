"""Optional synthetic-fixture acceptance through the real context API and engine.

No personal database or running service is used. Missing optional fixture skips.
Usage/trace writes go to the ordinary isolated test database.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Memory, MemoryUsage, Workspace
from packages.retrieval.context.token_counter import estimate_tokens
from packages.retrieval.engine import RetrievalEngine


@pytest.mark.parametrize("budget", [1000, 2000, 4000])
async def test_real_context_endpoint_with_negative_fixture(client, db_session, monkeypatch, budget):
    import apps.api.routes.context as route
    from benchmarks.fixtures.generate_fixture import WORKSPACE_NAME
    from benchmarks.runners.retrieval_runner import load_gold_dataset

    root = Path(__file__).resolve().parents[2]
    fixture = root / "benchmarks/fixtures/eval_fixture.db"
    if not fixture.is_file():
        pytest.skip("optional synthetic fixture database is not installed")

    # 检查 fixture 数据库实际 schema（同步操作，在异步上下文外执行）
    from datetime import datetime
    from sqlalchemy import inspect as sa_inspect, text
    from sqlalchemy.engine import create_engine

    sync_engine = create_engine("sqlite:///" + fixture.as_posix())
    insp = sa_inspect(sync_engine)
    fixture_cols = {col["name"] for col in insp.get_columns("memory")}
    sync_engine.dispose()

    source = create_async_engine(
        URL.create(
            "sqlite+aiosqlite",
            database="file:" + fixture.as_posix(),
            query={"mode": "ro", "uri": "true"},
        )
    )
    try:
        async with async_sessionmaker(source, expire_on_commit=False)() as src:
            ws_id = await src.scalar(select(Workspace.id).where(Workspace.name == WORKSPACE_NAME))
            assert ws_id is not None
            # 用原始 SQL 避免 SQLAlchemy 模型查询不存在的列
            col_list = ", ".join(f'"{c}"' for c in sorted(fixture_cols) if c != "workspace_id")
            query = text(f"SELECT {col_list} FROM memory WHERE workspace_id = :ws_id")
            rows = (await src.execute(query, {"ws_id": str(ws_id)})).fetchall()
            ws = Workspace(name="fixture-api-" + uuid.uuid4().hex)
            db_session.add(ws)
            await db_session.flush()
            # 日期字段需要转换为 datetime 对象
            date_fields = {"created_at", "updated_at", "last_used_at", "valid_from", "valid_to"}
            for row in rows:
                values = dict(row._mapping)
                values["workspace_id"] = ws.id
                values["project_id"] = None
                # 转换日期字符串为 datetime 对象
                for field in date_fields:
                    if field in values and isinstance(values[field], str):
                        values[field] = datetime.fromisoformat(values[field])
                # 只传入目标表存在的列
                target_cols = {c.key for c in Memory.__table__.columns}
                values = {k: v for k, v in values.items() if k in target_cols}
                db_session.add(Memory(**values))
            await db_session.flush()
    finally:
        await source.dispose()

    engine = RetrievalEngine()  # no production file-backed vector source
    observed = {}

    class ObservedEngine:
        async def retrieve(self, **kwargs):
            result = await engine.retrieve(**kwargs)
            observed["result"] = result
            return result

    monkeypatch.setattr(route, "get_retrieval_engine", lambda: ObservedEngine())
    route.invalidate_context_cache()
    golds = [
        gold
        for gold in load_gold_dataset(
            root / "benchmarks/datasets/retrieval/eval-fixture-extended.jsonl"
        )
        if gold.query_id in {"C9-q1", "C9-q2"}
    ]
    assert {gold.query_id for gold in golds} == {"C9-q1", "C9-q2"}
    try:
        for gold in golds:
            session_id = uuid.uuid4()
            response = await client.post(
                "/v1/context",
                json={
                    "workspace_id": str(ws.id),
                    "agent_id": str(uuid.uuid4()),
                    "session_id": str(session_id),
                    "keyword": gold.query,
                    "max_items": 20,
                    "max_tokens": budget,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            selected = [item["memory_id"] for item in body["items"]]
            assert body["total"] == len(selected)
            assert body["sources"] == [f"memory:{mid}" for mid in selected]
            assert [c["memory_id"] for c in body["citations"]] == selected
            assert estimate_tokens(body["context"]) <= budget
            usage = (
                await db_session.scalars(
                    select(MemoryUsage)
                    .where(
                        MemoryUsage.workspace_id == ws.id,
                        MemoryUsage.session_id == session_id,
                        MemoryUsage.stage == "used",
                    )
                    .order_by(MemoryUsage.position)
                )
            ).all()
            assert [str(row.memory_id) for row in usage] == selected
            for item in body["items"]:
                assert f'id="{item["memory_id"]}"' in body["context"]
                assert item["content"] in body["context"]
            weak = [mid for mid, grade in gold.judgments.items() if grade == 1]
            candidates = [m["id"] for m in observed["result"].get("memories", [])]
            print(
                {
                    "query_id": gold.query_id,
                    "budget": budget,
                    "candidate_count": len(candidates),
                    "delivered_count": len(selected),
                    "weak_candidate": [mid for mid in weak if mid in candidates],
                    "weak_delivered": [mid for mid in weak if mid in selected],
                    "degraded": body["degraded"],
                    "engine_selected_ids": candidates,
                    "response": body,
                }
            )
    finally:
        route.invalidate_context_cache()
