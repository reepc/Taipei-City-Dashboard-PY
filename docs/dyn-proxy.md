# Dynamic Reverse Proxy 規格書

執行階段註冊型反向代理。下游服務在啟動後呼叫 BE 註冊自己，BE 驗證健康後將指定 prefix 之流量整段轉發至下游。Gin 既有靜態路由永遠優先，因此「打賭不會撞」是有保險的。

---

## 1. 設計目標

| # | 目標 |
|---|------|
| 1 | 下游服務可在 BE 已啟動的情況下動態接上 / 拔掉 |
| 2 | 不需事先在 BE 程式碼裡寫死下游 prefix |
| 3 | 與既有路由共存：撞名時以 BE 原本程式碼註冊之路由為準 |
| 4 | 對外行為（method / body / query / header / streaming）等同於直連下游 |

---

## 2. 控制端點

所有控制端點皆於程式啟動時靜態註冊於 `RouterGroup` (`/api/v1`)，套用 `ComponentLimit*` 之頻率限制。

| 方法 | 路徑 | 用途 |
|------|------|------|
| `POST` | `/api/v1/proxy/register` | 驗證下游 ping 後註冊一筆 entry |
| `POST` | `/api/v1/proxy/detach` | 依 `name` 移除一筆 entry |
| `GET`  | `/api/v1/proxy/list` | 列出目前所有 entry |

### 2.1 `POST /api/v1/proxy/register`

#### Request body

```json
{
  "name":     "chat",
  "addr":     "127.0.0.1:7000",
  "prefix":   "/api/v1/chat",
  "upstream": "/api/dev/chat",
  "ping":     "/api/dev/ping"
}
```

| 欄位 | 必填 | 預設 | 說明 |
|------|------|------|------|
| `name` | Y | — | entry 識別名稱，detach 時用此值 |
| `addr` | Y | — | 下游 host:port，可帶 `http://` / `https://` scheme，預設 `http://` |
| `prefix` | N | `/api/v1/<name>` | BE 端要攔截的請求路徑 prefix |
| `upstream` | N | `/api/dev/<name>` | 轉發至下游時改寫的路徑 prefix |
| `ping` | N | `/api/dev/ping` | 健康檢查路徑（GET，body 須為 `pong`） |

#### 流程

1. Parse body，trim 空白，驗證 `name` 與 `addr` 非空。
2. 補齊 scheme，組出 base URL。
3. 對 `<base><ping>` 發 `GET`，timeout 3 秒，讀取最多 64 bytes。
4. body 經 trim 後須等於字串 `pong`，否則回 502。
5. 通過則建立 `proxyEntry` 並寫入記憶體 map（mutex 保護）。同名 entry 直接覆蓋。

#### Response

成功：

```json
{
  "status":   "success",
  "name":     "chat",
  "target":   "http://127.0.0.1:7000",
  "prefix":   "/api/v1/chat",
  "upstream": "/api/dev/chat"
}
```

| HTTP | 條件 |
|------|------|
| 200 | 註冊成功 |
| 400 | body 無法解析 / `name` 或 `addr` 缺失 / `addr` 格式錯 |
| 502 | ping 連線失敗 / 讀取失敗 / body ≠ `pong` |

### 2.2 `POST /api/v1/proxy/detach`

#### Request body

```json
{ "name": "chat" }
```

#### Response

```json
{
  "status":   "success",
  "detached": "chat",
  "target":   "http://127.0.0.1:7000"
}
```

| HTTP | 條件 |
|------|------|
| 200 | 移除成功 |
| 400 | body 無法解析 / `name` 缺失 |
| 404 | 該 `name` 不存在 |

### 2.3 `GET /api/v1/proxy/list`

```json
{
  "status": "success",
  "data": [
    {
      "name":     "chat",
      "target":   "http://127.0.0.1:7000",
      "prefix":   "/api/v1/chat",
      "upstream": "/api/dev/chat"
    }
  ]
}
```

---

## 3. 代理派送（NoRoute）

代理本體掛在 `Router.NoRoute(controllers.DynProxyNoRoute)`。**僅在 Gin 靜態路由樹完全沒有命中時才會被叫到**，故任何 BE 程式碼裡已存在的路由皆優先於動態 entry。

### 3.1 匹配規則

對請求路徑 `reqPath`，掃描所有 entry，挑出滿足下列條件且 `Prefix` 最長者：

```
reqPath == entry.Prefix
  || strings.HasPrefix(reqPath, entry.Prefix + "/")
```

無命中則回 404。

### 3.2 路徑改寫

```
sub      = strings.TrimPrefix(reqPath, entry.Prefix)   // 例: "" / "/foo" / "/foo/bar"
new path = entry.Upstream + sub
```

### 3.3 轉發語意

使用 `net/http/httputil.NewSingleHostReverseProxy`：

| 項目 | 行為 |
|------|------|
| Method | 原樣保留 |
| Header | 原樣保留（含 `Authorization` 等） |
| Body | 原樣串流轉發（含大檔 / 串流） |
| Query string | 原樣保留 |
| Host header | 改為下游 host |
| Upstream 連線錯 | 回 502 + JSON `{"status":"error","message":"upstream error: ..."}` |

WebSocket / SSE 由 `ReverseProxy` 透過 hijacker 與長連結支援，但本 spec 未做迴歸驗證。

---

## 4. 撞名行為（重要）

由於代理走 `NoRoute`，下列情境保證以 BE 既有路由為準：

| 範例註冊 | BE 既有路由 | 結果 |
|----------|-------------|------|
| `prefix=/api/v1/component` | `GET /api/v1/component/` (controllers.GetAllComponents) | 既有路由勝；entry 永遠不會收到流量 |
| `prefix=/api/v1/agent/search` | `POST /api/v1/agent/search` | 既有路由勝（同方法亦同） |
| `prefix=/api/v1/proxy` | `POST /api/v1/proxy/register` 等 | 控制端點勝 |

被撞掉的 entry 不會自動移除，`/proxy/list` 仍能看到它，但對外無感。要清掉得呼叫 `detach`。

---

## 5. 認證與限制

- 控制端點 (`/api/v1/proxy/*`) 套用 `ComponentLimitAPIRequestsTimes` / `ComponentLimitTotalRequestsTimes`。
- 全 router 之 `middleware.ValidateJWT` 仍會跑，未登入會被視為公開檢視者；目前控制端點未強制登入。**正式環境若不希望任意人註冊代理，需追加 `IsSysAdm()` 等中介層。**
- NoRoute 派送之代理請求亦會經過 `ValidateJWT` 與其他 router-level middleware，不會經過 group middleware。

---

## 6. 持久化

無。entry 僅存在於 process 記憶體 (`var proxyEntries map[string]*proxyEntry`)，BE 重啟即清空，下游需自行重新註冊。

---

## 7. 並行安全

- `proxyEntries` 由 `sync.RWMutex` 保護。
- 讀（matchEntry / list）走 RLock；寫（register / detach）走 Lock。
- 每次代理請求建立新的 `*httputil.ReverseProxy`，無共享狀態問題。

---

## 8. 範例：把 chat 服務接上

```bash
# 下游服務在 7000 port，提供 /api/dev/ping 與 /api/dev/chat[/...]
curl -X POST http://localhost:8080/api/v1/proxy/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"chat","addr":"127.0.0.1:7000"}'

# 之後流量自動轉發
curl http://localhost:8080/api/v1/chat            # -> http://127.0.0.1:7000/api/dev/chat
curl http://localhost:8080/api/v1/chat/foo?x=1    # -> http://127.0.0.1:7000/api/dev/chat/foo?x=1

# 拔掉
curl -X POST http://localhost:8080/api/v1/proxy/detach \
  -H 'Content-Type: application/json' \
  -d '{"name":"chat"}'
```

---

## 9. 測試

E2E Node.js 腳本：[chat-proxy-test.js](chat-proxy-test.js)

涵蓋 21 個 assertion：register / list / proxy GET-POST-nested+query / 撞名（靜態勝）/ detach / 拔掉後 404 / 壞 ping 502 / mock 流量計數。

執行：

```bash
# 1. BE on :8080
go run .

# 2. 測試（自帶 mock 下游）
node docs/chat-proxy-test.js --be http://127.0.0.1:8080
```

註：上面執行的 BE 需 DB / Redis / ONNX。開發階段可改建立極簡 Gin harness（只掛 `controllers.DynProxy*` + `Router.NoRoute`）以驗證代理本體邏輯。

---

## 10. 已知限制

| # | 限制 |
|---|------|
| 1 | 無持久化，BE 重啟清空 |
| 2 | 控制端點無權限要求，需於部署層或追加 middleware 控管 |
| 3 | 未做 prefix 衝突檢查；註冊 `/api/v1` 之類過寬 prefix 會吃掉所有 NoRoute |
| 4 | WebSocket / SSE / HTTPS 下游未做迴歸測試 |
| 5 | ping 僅檢查一次；下游事後掛掉，BE 不會主動 detach（會以 502 回給呼叫端） |

---

## 11. 程式進入點

| 檔案 | 內容 |
|------|------|
| [app/controllers/dynProxy.go](../app/controllers/dynProxy.go) | 控制端點 + NoRoute 派送 + entries map |
| [app/routes/router.go](../app/routes/router.go) | `configureDynProxyRoutes()` + `Router.NoRoute(...)` 掛載 |
| [docs/chat-proxy-test.js](chat-proxy-test.js) | E2E Node 測試腳本 |
