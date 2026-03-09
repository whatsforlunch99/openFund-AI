# Product Requirements (Current Scope)

## Goal

Provide a live multi-agent investment research backend that can:
- accept authenticated/anonymous user queries
- orchestrate specialist agents over MCP tools
- return profile-adapted responses with compliance checks
- persist user memory for conversation continuity

## Functional Requirements

1. User registration/login with unique usernames and password verification
2. Chat endpoint with conversation create/resume behavior
3. Planner-driven multi-agent orchestration
4. Tool-backed retrieval via MCP (SQL/graph/vector/market/indicators)
5. Response formatting + compliance guardrail before final output
6. Conversation and user-memory persistence
7. CLI data ingestion/distribution into PostgreSQL/Neo4j/Milvus

## Non-Functional Requirements

- Idempotent data loading (upsert semantics)
- Graceful behavior when optional backends/tools are unavailable
- Single-command local run path (`scripts/run.sh`)
- Traceable flow events for API responses

## Out of Scope (Current Repo)

- Dedicated browser frontend
- Multi-tenant auth provider integration (OAuth/SAML)
- Distributed message bus deployment (beyond in-process bus)
