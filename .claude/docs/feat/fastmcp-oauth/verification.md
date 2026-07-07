# Verification: FastMCP OAuth for claude.ai custom connector

Acceptance criteria per task (from `tasks.md`), with how each is proven.

## T0.1 — DONE
- [x] `uv sync` succeeds; `uv run mcp-google-sheets` executes (fails only on missing Google creds)
- [x] Baseline tests: 22 passed, 1 skipped

## T0.2 — DONE
- [x] `docs/upgrade-notes.md` answers: upgrade to `fastmcp>=2.13.3,<3`; affected files listed

## T1.1
- [x] All pre-existing unit tests pass on fastmcp 2.13
- [x] Server starts with `--transport stdio` and `--transport streamable-http` (no AUTH_* vars set)
- [x] `list_sheets`, `get_sheet_data`, `update_cells` invoked successfully through a local MCP
      client (fastmcp in-memory Client, mocked Google services via lifespan)

## T1.2 (auth on, streamable HTTP)
- [x] Request to `/mcp` without token → 401 + `WWW-Authenticate` header
- [x] `GET /.well-known/oauth-protected-resource*` → 200, points at this server's auth server
- [x] Authorization server metadata (`/.well-known/oauth-authorization-server`) contains
      `registration_endpoint` (DCR)
- [x] `AUTH_ENABLED=false` → those endpoints 404, `/mcp` reachable without token (upstream parity)

## T1.3 (unit tests)
- [x] Whitelisted email passes through middleware
- [x] Non-whitelisted email → rejected with Forbidden/403 error; email logged, token never logged
- [x] `AUTH_ENABLED=true` + empty whitelist → startup raises (fail-closed)
- [x] Case-insensitive email match; whitespace tolerated

## T1.4
- [x] With default `ENABLED_TOOLS` list, tools/list excludes `share_spreadsheet`
- [x] `AUTH_ENABLED=true` + `share_spreadsheet` enabled → prominent startup warning

## T1.5
- [x] `.github/workflows/ci.yml` runs ruff + pytest on PR; green locally via same commands
      (actual GitHub run pending first PR)

## T2.1
- [x] `docker compose config` passes
- [x] Container runs as non-root
- [x] In-container curl reproduces T1.2 401/metadata checks (documented commands)

## T2.2/T2.3/T3.1/T3.2 — HUMAN
- [x] Checklists produced in `docs/deployment-checklist.md`; runbook in `docs/runbook.md`
- [ ] E2E items in tasks.md §T3.2 executed by human after backfill
