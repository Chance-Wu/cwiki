// cwiki C4 System Context Diagram
// Audience: system stakeholders, onboarding developers
// Scope: cwiki and its external actors/systems
// Evidence: adapters/mcp/mcp_server.py, apps/api/main.py, docs/memory-system.md

workspace "cwiki" "Personal Knowledge Workstation & Agent Memory Infrastructure" {
    model {
        // --- Actors ---
        person "Coding Agent" "AI coding assistant (Qoder, Codex, etc.)" $tags="external"
        person "Developer" "Single local user" $tags="external"

        // --- System ---
        softwareSystem "cwiki" "Personal knowledge workstation: store → retrieve → evolve" {
            tags "system-boundary"
        }

        // --- External Systems ---
        softwareSystem "GitHub Private Repos" "Code repo (cwiki.git) + Data repo (cwiki-data.git)" $tags="external"
        softwareSystem "Local Filesystem" "cwiki-data/ (MD + _meta + SQLite + vectors)" $tags="external"

        // --- Containers ---
        container "MCP Adapter" "JSON-RPC 2.0 over stdio; 19 tools" $technology="Python" $tags="container"
        container "Hook Adapter" "Agent event capture (session hooks)" $technology="Python" $tags="container"
        container "REST API" "FastAPI backend; all business endpoints" $technology="Python / Uvicorn :5172" $tags="container"
        container "Worker Queue" "In-process async task queue (2 workers)" $technology="Python / asyncio" $tags="container"
        container "Web UI" "React 18 SPA; TanStack Query + Tailwind" $technology="TypeScript / Vite :5173" $tags="container"
        container "Storage Engine" "FileStore + MemoryIndexer + VectorIndex" $technology="Python / SQLite / numpy" $tags="container"
        container "Retrieval Engine" "BM25 + Vector cosine + RRF fusion + reranker" $technology="Python / fastembed ONNX" $tags="container"

        // --- Relationships ---
        codingAgent -> mcpAdapter "tools/call (stdin/stdout JSON-RPC)" $tags="sync"
        codingAgent -> hookAdapter "session hooks (shell events)" $tags="async"
        developer -> webUI "browser :5173" $tags="sync"
        developer -> restAPI "curl / health check :5172" $tags="sync"

        mcpAdapter -> restAPI "HTTP POST/GET /v1/*" $tags="sync"
        hookAdapter -> restAPI "HTTP POST /v1/events" $tags="async"
        webUI -> restAPI "HTTP /v1/*" $tags="sync"

        restAPI -> storageEngine "SQLAlchemy async + file I/O" $tags="sync"
        restAPI -> retrievalEngine "search_ranked() / retrieve()" $tags="sync"
        restAPI -> workerQueue "enqueue tasks" $tags="async"

        workerQueue -> storageEngine "dual-write (DB + vectors.npz)" $tags="sync"
        workerQueue -> retrievalEngine "warm-up / reindex" $tags="async"

        storageEngine -> localFilesystem "cwiki-data/ MD + _meta + cwiki.db" $tags="sync"
        storageEngine -> githubRepos "git sync (cwiki-data/sync.py)" $tags="batch"
    }

    views {
        systemContext cwiki "System Context" {
            include *
            autoLayout LR
        }
        container cwiki "Container" {
            include *
            autoLayout TB
        }
    }
}
