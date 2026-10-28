---
description: 查看 cwiki 集成状态：服务连接、队列积压、今日统计
---

# Memory Status

Check the current status of cwiki integration.

## Usage
/memory-status

## Expected Output
cwiki Status
=================
Capture: ✓ Active
Queue: 0 pending, 0 failed
Server: ✓ Connected (http://127.0.0.1:5172)
MCP: ✓ Connected
Last Sync: 10 sec ago

Today:
  Sessions: 8
  Events: 1,284
  Candidates: 12
  Approved: 7

Run `python scripts/setup.py --check` for detailed diagnostics.
