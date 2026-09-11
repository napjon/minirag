# MCP adapter

Marketdesk MCP is a thin, authenticated client of the HTTP API. It does not run a second copy of retrieval, analytics, catalog, or drafting logic.

Start the API on port 8130, obtain a demo bearer token, then run the adapter:

```bash
uv sync --extra mcp
export MARKETDESK_API=http://127.0.0.1:8130
export MARKETDESK_TOKEN='demo-access-token'
uv run marketdesk-mcp
```

The tool list lives in `backend/integrations/mcp_manifest.json` and is registered by `create_server()` in `backend/integrations/mcp_server.py`.

| Tool | HTTP |
|---|---|
| `search_knowledge` | `POST /v1/questions` |
| `read_evidence` | `GET /v1/documents/{document_id}` |
| `query_operational_data` | `POST /v1/analytics/queries` |
| `search_products` | `POST /v1/products/search` |
| `compare_products` | `POST /v1/products/compare` |
| `get_price_references` | `GET /v1/products/{product_id}/references` |
| `get_finding` | `GET /v1/findings/{finding_id}` |
| `get_draft_status` | `GET /v1/drafts/{draft_id}` |

MCP cannot approve drafts, publish documents, change permissions, run SQL, or access the network. “Cannot access the network” means the adapter has no tool for arbitrary URLs, mail, or shell; it does call `MARKETDESK_API` over HTTP. Those forbidden actions are absent from the tool list; draft approval, publication, and permission changes stay on the HTTP API with their existing role checks.

The inbound bearer token is sent only to `MARKETDESK_API`. The adapter does not register `approve_draft`, `execute_sql`, or `send_email`.
