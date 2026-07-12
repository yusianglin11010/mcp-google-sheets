# Runbook(維運手冊)

服務:mcp-google-sheets(Synology Docker + Cloudflare Tunnel)
組成:`sheets-mcp`(MCP server)+ `cloudflared`(tunnel sidecar)

## 日常操作

### 重啟服務
```bash
docker compose restart sheets-mcp        # 只重啟 MCP server
docker compose restart                   # 連同 cloudflared
```
- 若 **未設定** `AUTH_JWT_SIGNING_KEY`:重啟後所有已發 token 失效,
  claude.ai 端重新連線/重新授權即可(通常自動完成)。
- 設定了 signing key 則 token 存活,無感重啟。

### 看log / 健康檢查
```bash
docker compose logs -f sheets-mcp
curl https://sheets-mcp.<網域>/.well-known/oauth-protected-resource/mcp   # 200 = 活著
docker stats --no-stream                 # 記憶體基線 ~100MiB,異常升高再排查
```

## 加/移除白名單成員

1. 編輯 `.env` 的 `AUTH_ALLOWED_EMAILS`(逗號分隔,大小寫不拘)
2. GCP Console → OAuth consent screen → Test users **同步增删**(兩邊必須一致:
   白名單擋 MCP 請求,Test users 擋 Google 登入)
3. `docker compose up -d`(重新讀 .env 需重建容器,restart 不會重讀)
4. 移除成員時,同時執行下方「撤銷授權」

## 撤銷授權(revoke)

- **立即擋掉某帳號**:自 `AUTH_ALLOWED_EMAILS` 移除 + `docker compose up -d`。
  即使其 token 尚未過期,email 白名單 middleware 會擋下每一個請求(403)。
- **全面撤銷所有 token**:更換 `AUTH_JWT_SIGNING_KEY`(或清空後重啟,若原本未設)。
- **使用者端**:claude.ai → Settings → Connectors → 該連接器 → Disconnect;
  Google 帳號端可在 https://myaccount.google.com/permissions 移除授權。
- **per-user 模式(`AUTH_OUTBOUND_MODE=user`)額外注意**:出站是用「使用者本人的
  Google token」,所以要真正切斷某人對其資料的存取,除了移出白名單,該使用者(或你)
  需在 https://myaccount.google.com/permissions **移除本 app 的授權**,使其 refresh
  token 失效。移出白名單只擋連接器入口,不會撤銷 Google 端已授予的權限。

## 換 key / secret

| 要換的東西 | 步驟 |
|---|---|
| **Service account key**(出站) | GCP → Service Accounts → Keys → 新增新 key → `base64 -w0 新key.json` 更新 `.env` 的 `CREDENTIALS_CONFIG` → `docker compose up -d` → 確認可讀寫後,回 GCP 刪除舊 key |
| **OAuth client secret**(入站) | GCP → Credentials → 該 OAuth client → 新增 secret → 更新 `AUTH_GOOGLE_CLIENT_SECRET` → `docker compose up -d` → claude.ai 重新授權 → 刪除舊 secret |
| **JWT signing key** | `openssl rand -hex 32` → 更新 `AUTH_JWT_SIGNING_KEY` → `docker compose up -d`(所有既有 token 立即失效) |
| **Tunnel token** | Zero Trust → Tunnels → rotate token → 更新 `TUNNEL_TOKEN` → `docker compose up -d cloudflared` |

## 常見故障

| 症狀 | 排查 |
|---|---|
| claude.ai 顯示連線失敗 | `curl https://.../.well-known/oauth-protected-resource/mcp`;404/timeout → cloudflared 或 DNS 問題;200 → 看 sheets-mcp log |
| 授權後仍 403 | 該帳號不在 `AUTH_ALLOWED_EMAILS`(log 會記錄被拒 email);改 .env 後要 `up -d` 不是 restart |
| Google 登入顯示「應用程式未經驗證/存取遭封鎖」 | 帳號不在 OAuth consent screen 的 Test users |
| redirect_uri_mismatch | GCP OAuth client 的 redirect URI 必須完全等於 `{AUTH_BASE_URL}/auth/callback`(含 https、無尾斜線差異) |
| 工具回權限錯誤 | 該試算表未共用給 service account email,或只給了檢視者卻要寫入 |
| 啟動即退出:`AUTH_ENABLED=true requires a non-empty AUTH_ALLOWED_EMAILS` | 這是 fail-closed 防呆,補上白名單再啟動 |
| 重啟後 claude.ai 要求重新授權 | 未設 `AUTH_JWT_SIGNING_KEY`(可接受)或 key 變了 |

## 安全原則(不可退讓)

- `.env` 永不進 repo;GCP consent 維持 **Testing**
- `ENABLED_TOOLS` 白名單永遠排除 `share_spreadsheet`(啟動時有警告防呆)
- 白名單空 + auth 開啟 = 啟動失敗(fail-closed),不要為了「先跑起來」關掉 auth
- log 只記被拒的 email,永不記 token
