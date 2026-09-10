"""MCP server exposing ACTRIS Monitor's data to AI agents over Streamable HTTP.

Mounted by `main.py` at `/mcp` on the same FastAPI app, sharing the same process,
the same SQLite connection and the same container. See `docs/mcp-server-plan.md`
for the full design and the roadmap beyond the tool implemented here.

Two rules hold this package together:

1. `tools.py` imports `database` and `variables` — never `fastapi`, never `main`,
   never a route handler. That boundary is what would make a standalone stdio
   package a day of work rather than a rewrite.
2. The surface is **read-only**. `start_fetch`, `db/reset` and `backfill-networks`
   stay on the authenticated REST side: agents retry on ambiguity, and a retried
   reset is unrecoverable.
"""
