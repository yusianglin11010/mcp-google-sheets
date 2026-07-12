# 部署操作清單([HUMAN] 任務)

依序完成 A → B → C → D。每一節結尾有「回填」欄位;全部回填後即可執行 D 的啟動步驟。

---

## A. GCP 設定(對應 tasks.md T2.2)

1. **建立或沿用 GCP 專案**
   - https://console.cloud.google.com/ → 選擇專案或「新增專案」

2. **啟用 API**(APIs & Services → Library)
   - 啟用 **Google Sheets API**
   - 啟用 **Google Drive API**

3. **OAuth 同意畫面**(APIs & Services → OAuth consent screen)
   - User type:**External**
   - Publishing status:**維持 Testing,不要送審發佈**
   - Test users:僅加入允許使用連接器的 Google 帳號(需與 `AUTH_ALLOWED_EMAILS` 完全一致)
   - Scopes:加入 `openid`、`.../auth/userinfo.email`

4. **OAuth Client(入站認證用)**(APIs & Services → Credentials → Create credentials → OAuth client ID)
   - Application type:**Web application**
   - Authorized redirect URI:`{AUTH_BASE_URL}/auth/callback`
     - 例:`https://sheets-mcp.example.com/auth/callback`(網域確定後再填;之後可回來補)
   - 記下 **Client ID**(`*.apps.googleusercontent.com`)與 **Client secret**(`GOCSPX-*`)

5. **Service Account(出站打 Sheets API 用)**(IAM & Admin → Service Accounts)
   - Create service account(名稱例:`sheets-mcp-bot`),不需要授予專案角色
   - Keys → Add key → JSON,下載 key 檔
   - 轉 base64(單行):`base64 -w0 service_account.json`
   - **下載後的 JSON 檔妥善保存或刪除,不要放進 repo**

6. **共用目標試算表給 service account**
   - 開啟每一份要操作的試算表(業績追蹤表等)→「共用」→ 貼上 service account 的 email
     (形如 `sheets-mcp-bot@<project>.iam.gserviceaccount.com`)
   - 唯讀需求給「檢視者」,要寫入給「編輯者」

**回填 `.env`:**

| 變數 | 值來源 |
|---|---|
| `AUTH_GOOGLE_CLIENT_ID` | 步驟 4 Client ID |
| `AUTH_GOOGLE_CLIENT_SECRET` | 步驟 4 Client secret |
| `CREDENTIALS_CONFIG` | 步驟 5 base64 字串(僅 service_account 模式需要) |
| `AUTH_ALLOWED_EMAILS` | 步驟 3 Test users 名單(逗號分隔) |
| `AUTH_OUTBOUND_MODE` | `service_account`(預設)或 `user` |

### 選用:per-user 出站模式(`AUTH_OUTBOUND_MODE=user`)

若要讓「每位使用者存取自己的 Sheets」(而非共用 service account):

- 步驟 3 的 **Scopes 需再加**:`.../auth/spreadsheets` 與 `.../auth/drive.readonly`。
- 步驟 5、6 的 **service account 可略過**(user 模式不使用)。
- **必須** `AUTH_ENABLED=true`,否則啟動即 fail-closed。
- ⚠️ **Testing 模式限制**:同意畫面維持 Testing 時,Google 對 sensitive scope 發的
  **refresh token 會在使用者同意後約 7 天過期**,屆時使用者需重新授權。若要長期免重授,
  需將 OAuth app **發佈(Publish)**,而 sensitive scope 的發佈需經 Google 驗證——
  上線前再評估是否送審。

---

## B. Cloudflare Tunnel(對應 tasks.md T2.3)

前提:網域已在 Cloudflare、已有(或新建)一條 tunnel。

1. Zero Trust dashboard → Networks → Tunnels → 選擇既有 tunnel(或 Create a tunnel,connector 選 Docker)
2. **Public Hostname** 新增:
   - Subdomain:`sheets-mcp`(或自選)→ 完整網域例 `sheets-mcp.example.com`
   - Service:**HTTP** → URL:`sheets-mcp:8000`(compose 服務名:port,經 Docker 內部網路)
3. **不要**在此 hostname 掛 Cloudflare Access 應用程式
   - 入站認證由 MCP OAuth 負責;Access 的登入頁會擋掉 claude.ai 的 OAuth 流程
4. 複製 tunnel token(`eyJ...` 長字串)

**回填 `.env`:**

| 變數 | 值 |
|---|---|
| `TUNNEL_TOKEN` | 步驟 4 的 token |
| `AUTH_BASE_URL` | `https://sheets-mcp.<你的網域>` |

⚠️ `AUTH_BASE_URL` 確定後,回到 A-4 把 redirect URI 補成 `https://sheets-mcp.<你的網域>/auth/callback`。

---

## C. 部署到 Synology(對應 tasks.md T2.4)

1. 上傳 `docker-compose.yml` 與填好的 `.env` 至 NAS(同一資料夾;`.env` 權限建議 600)
2. Container Manager(或 SSH)建立專案並啟動:
   ```bash
   docker compose up -d --build     # NAS 上若拉不到 build 環境,可先在他處 build 後推私有 registry
   ```
3. 驗收:
   ```bash
   docker compose logs sheets-mcp | tail -50    # 應無 ERROR;無 secret 出現在 log
   docker stats --no-stream                     # 記錄記憶體基線(參考值:~100MiB)
   curl https://sheets-mcp.<網域>/.well-known/oauth-protected-resource/mcp   # 期望 200
   curl -i -X POST https://sheets-mcp.<網域>/mcp \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{}'                                    # 期望 401 + WWW-Authenticate
   ```

---

## D. claude.ai 自訂連接器(對應 tasks.md T3.1)

1. claude.ai → Settings → Connectors → **Add custom connector**
2. URL:`https://sheets-mcp.<網域>/mcp`
3. 先不填 client ID/secret,讓 DCR 自動完成;若 claude.ai 明確要求,才填入 A-4 的 client ID/secret
4. 點 Connect → 跳轉 Google 登入 → 用 **Test users 名單內** 的帳號授權
5. Desktop 與 Mobile 以同一帳號登入即共用此連接器

### 端到端驗收(tasks.md T3.2,逐項打勾)

- [ ] 連接器顯示已連線,工具清單 = `ENABLED_TOOLS` 白名單,無 `share_spreadsheet`
- [ ] 「列出試算表 X 的工作表」回傳正確
- [ ] 「讀取 A1:C10」資料正確
- [ ] 「把 B2 改成 123」實際寫入成功
- [ ] 未共用給 service account 的試算表 → 明確權限錯誤(而非資料外洩)
- [ ] 以白名單外的 Google 帳號跑授權流程 → 被拒
- [ ] 直接 curl MCP 端點(無 token)→ 401
- [ ] Desktop 與 Mobile 端同一連接器可用

疑難排解見 `docs/runbook.md`。
