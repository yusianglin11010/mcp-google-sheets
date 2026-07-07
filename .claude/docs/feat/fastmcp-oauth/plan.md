# Plan: FastMCP OAuth for claude.ai custom connector

Source of truth for requirements: `tasks.md` (repo root). This doc records the design
decisions made during implementation. See `verification.md` for acceptance criteria.

## Architecture

```
claude.ai ──(MCP OAuth, inbound)──> mcp-google-sheets (fastmcp 2.13 + GoogleProvider)
                                        ──(Service Account, outbound)──> Google Sheets API
Deployed: Synology Docker + Cloudflare Tunnel sidecar
```

## Key decisions

1. **fastmcp pinned `>=2.13.3,<3`** — GoogleProvider needs ≥2.12; `jwt_signing_key` needs ≥2.13;
   v3.x too new + breaking changes. Full analysis: `docs/upgrade-notes.md`.
2. **Opt-in auth**: all new behavior behind `AUTH_ENABLED` (default `false`). With auth off,
   behavior must be identical to upstream xing5 (eases upstream merges).
3. **Auth module isolation**: new code lives in `src/mcp_google_sheets/auth.py`;
   `server.py` changes are minimal (build `auth=` and middleware conditionally).
4. **Email whitelist as FastMCP middleware** (`on_request`, via `get_access_token()` claims):
   the documented FastMCP-native layer. Rejection raises an MCP error labeled 403/Forbidden;
   fail-closed at startup when `AUTH_ENABLED=true` and whitelist empty.
5. **`tool()` wrapper returns the original function** after registering with fastmcp
   (fastmcp 2.x `mcp.tool()` returns `FunctionTool`), keeping unit tests and module API intact.
6. **Deferred FastMCP construction**: `server.py` module-level `mcp` is built by a factory
   `_build_mcp()` so env vars are read at import time exactly as upstream, but auth wiring is testable.

## Task breakdown (one commit per task)

- T0.2: `docs/upgrade-notes.md` (this phase) — version decision
- T1.1: `pyproject.toml` + `server.py` migration to fastmcp 2.13; tests stay green;
  verify stdio + http startup and 3 tools via in-memory client
- T1.2: `auth.py` with `build_auth_provider()`; env vars AUTH_ENABLED, AUTH_GOOGLE_CLIENT_ID/SECRET,
  AUTH_BASE_URL, AUTH_JWT_SIGNING_KEY; verify 401/metadata/DCR endpoints live
- T1.3: `EmailWhitelistMiddleware` + AUTH_ALLOWED_EMAILS + fail-closed startup + unit tests
- T1.4: share_spreadsheet warning; README default ENABLED_TOOLS list; tools/list verification
- T1.5: GitHub Actions (lint ruff + pytest) on PR
- T2.1: Multi-stage non-root Dockerfile, docker-compose (sheets-mcp + cloudflared, internal
  network only), `.env.example`
- T2.2/T2.3/T3.1: human checklists in `docs/`; `docs/runbook.md`; README architecture/env table

## Env var summary (new)

| Var | Default | Purpose |
|---|---|---|
| `AUTH_ENABLED` | `false` | Master switch for inbound MCP OAuth |
| `AUTH_GOOGLE_CLIENT_ID` | — | Google OAuth client (inbound) |
| `AUTH_GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret (inbound) |
| `AUTH_BASE_URL` | — | Public HTTPS base URL of this server |
| `AUTH_JWT_SIGNING_KEY` | — | Optional; tokens survive restarts |
| `AUTH_ALLOWED_EMAILS` | — | Comma-separated whitelist; required when auth on |
