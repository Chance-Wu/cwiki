---
description: 把一条记忆标记为永久，使其在每次会话开始时自动注入
---

# 标记永久记忆

1. 用 `memory_search(keyword=..., limit=5)` 找到目标记忆，核对 `id`。
2. 调用 `memory_update(memory_id="<id>", is_permanent=true, permanent_reason="<为什么必须常驻>")`。
3. 需要取消时传 `is_permanent=false`。

永久记忆满足 `agent_policy.always_inject.include_permanent` 时会进入 SessionStart 常驻注入，
并在健康分计算中享受保底；仍受 `max_items` 与 `max_chars` 预算限制。
