# fastmcp 升級調查(T0.2)

## 結論

**升級目標:`fastmcp>=2.13.3,<3`**(uv 實際解析到 2.x 系列最新版 **2.14.7**;上界 `<3` 擋掉 3.x breaking changes)。

| 問題 | 答案 |
|---|---|
| 目前依賴 | `mcp>=1.8.0`(使用 MCP SDK 內建的 FastMCP 1.x,`mcp.server.fastmcp`)|
| `GoogleProvider` 最低版本 | fastmcp **2.12.0**(OAuth Proxy 首發);**2.13.0** 加入 `jwt_signing_key` 與 `client_storage`;**2.13.2** 修正 Google provider token refresh |
| 為何不用 3.x | 3.x(3.0 於 2025 年末發布,目前 3.4.x)有大量 breaking changes(建構子移除 16 個 kwargs、auth provider 不再自動讀環境變數、`ctx.set_state` 改 async 等),且發布時間尚短。tasks.md 風險表明示「必要時鎖定次要版本」。2.13.x 已含本專案所需全部功能(GoogleProvider、OAuthProxy、DCR、middleware、JWT signing key)。 |

## GoogleProvider API(官方文件 gofastmcp.com/integrations/google 確認)

```python
from fastmcp.server.auth.providers.google import GoogleProvider

auth = GoogleProvider(
    client_id=...,            # 必填,*.apps.googleusercontent.com
    client_secret=...,        # 必填,GOCSPX-*
    base_url=...,             # 必填,對外 HTTPS URL
    required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
    redirect_path="/auth/callback",   # 預設值;Google Console 註冊 {base_url}/auth/callback
    jwt_signing_key=...,      # 選配(2.13.0+),重啟後 token 存活
)
mcp = FastMCP(name=..., auth=auth)
```

- 取得使用者身分:`from fastmcp.server.dependencies import get_access_token` → `token.claims.get("email")`
- Middleware:`from fastmcp.server.middleware import Middleware, MiddlewareContext`,`mcp.add_middleware(...)`,拒絕請求以拋例外實作(一般請求用 `McpError`)

## Breaking changes:`mcp.server.fastmcp`(1.x)→ `fastmcp` 2.13

| # | 變更 | 受影響位置 | 處置 |
|---|---|---|---|
| 1 | import 路徑:`from mcp.server.fastmcp import FastMCP, Context` → `from fastmcp import FastMCP, Context` | `src/mcp_google_sheets/server.py:18` | 改 import |
| 2 | `FastMCP(dependencies=[...])` 已棄用 | `server.py:183-187` | 移除該參數(僅為安裝中繼資料,無行為影響)|
| 3 | `FastMCP(host=..., port=...)` 於 2.x 棄用(3.x 移除) | `server.py:183-187` | host/port 改於 `mcp.run(transport=..., host=..., port=...)` 傳入(僅 HTTP 類 transport)|
| 4 | `mcp.tool()(func)` 回傳 `FunctionTool` 物件而非原函式 | `server.py:190-218` 的 `tool()` wrapper 與所有 19 個工具;`tests/test_server_unit.py` 直接呼叫這些函式 | wrapper 改為「註冊後回傳原函式」,對測試與模組 API 零破壞 |
| 5 | transport 名稱:2.x 建議 `"http"`(`"streamable-http"` 為相容別名),`"sse"` 屬 legacy | `server.py:1740-1746`(`--transport` CLI 參數)| 沿用使用者輸入值;README 範例改用 `streamable-http`/`http` |
| 6 | lifespan:`FastMCP(lifespan=...)` 簽名相同(async contextmanager, yield 值經 `ctx.request_context.lifespan_context` 取得)| `server.py:84-170`、所有工具的 `ctx.request_context.lifespan_context` | 不需改(已以 in-memory client 實測確認)|
| 7 | `ToolAnnotations` 仍自 `mcp.types` 匯入(mcp SDK 為 fastmcp 的依賴) | `server.py:19` | 不需改 |

## 現況盤點(進入點與機制位置)

- **Transport 選擇**:`server.py:1740-1746` `main()` 解析 `--transport` CLI 參數,預設 `stdio`,傳入 `mcp.run(transport=...)`
- **Host/Port**:`server.py:175-180` 讀 `HOST`/`FASTMCP_HOST`、`PORT`/`FASTMCP_PORT`,現傳入建構子(升級後改傳 `run()`)
- **`ENABLED_TOOLS` 過濾**:`server.py:50-74` `_parse_enabled_tools()`(env `ENABLED_TOOLS` 或 `--include-tools`)+ `server.py:190-218` 自訂 `tool()` decorator,未列名的工具不註冊
- **`CREDENTIALS_CONFIG` 解析**:`server.py:33`(讀 env)與 `server.py:90-91`(lifespan 內 base64 → service account credentials)
- **測試**:`tests/test_server_unit.py`(22 個單元測試,直接呼叫工具函式、mock Google services);`tests/test_google_integration.py`(需真實憑證,無憑證時 skip)

## 受影響檔案清單

1. `pyproject.toml` — `mcp>=1.8.0` → `fastmcp>=2.13.3,<3`;新增 dev dependency group(pytest)
2. `src/mcp_google_sheets/server.py` — import、建構子參數、`tool()` wrapper、`main()` 的 run 參數
3. `tests/test_server_unit.py` — 預期不需大改(wrapper 保留原函式);`main()` 的 `mcp.run` 斷言需含 host/port 參數變更
4. `uv.lock` — 重新解析
5. `Dockerfile` / `README.md` — transport 範例(於 T2.1/T1.4 處理)
