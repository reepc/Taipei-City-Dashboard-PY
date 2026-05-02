# Dynamic Reverse Proxy — 下游服務串接規格

寫給「想把自己掛到 BE 底下」的下游服務開發者。BE 內部設計請參考 [dyn-proxy.md](dyn-proxy.md)；這份只講你要做什麼、會收到什麼、要怎麼接。

---

## 1. 一句話

你跑一支 HTTP server，跟 BE 講「我在 `host:port`」，之後 BE 上 `/api/v1/<name>` 開頭的流量都會被轉到你的 `/api/dev/<name>`。

---

## 2. 你要實作的端點

下游服務至少要提供兩種端點：

### 2.1 健康檢查（必填）

| 方法 | 路徑 | Response |
|------|------|----------|
| `GET` | `/api/dev/ping` | body 純文字 `pong`，HTTP 200 |

- BE 註冊時會打這支，**body 必須等於 `pong`**（trim 後比對）。
- 只讀前 64 bytes，不要回大物件。
- timeout 3 秒，超時即註冊失敗。
- 若你想自訂路徑，註冊時帶 `ping` 欄位（見 §4）。

### 2.2 業務端點（必填）

| 方法 | 路徑 | 說明 |
|------|------|------|
| 任意 | `/api/dev/<name>` | 對應 BE 的 `/api/v1/<name>` |
| 任意 | `/api/dev/<name>/<...>` | 對應 BE 的 `/api/v1/<name>/<...>`，sub-path 原樣保留 |

範例：`name=chat`

| BE 端收到 | 你會收到 |
|-----------|----------|
| `GET  /api/v1/chat` | `GET  /api/dev/chat` |
| `POST /api/v1/chat` | `POST /api/dev/chat` |
| `GET  /api/v1/chat/sessions/42?x=1` | `GET  /api/dev/chat/sessions/42?x=1` |

Method、query string、body、headers 原樣保留。

---

## 3. 註冊流程

下游服務啟動完成、可以接 ping 之後，自己呼叫 BE：

```bash
curl -X POST http://<BE>/api/v1/proxy/register \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "chat",
    "addr": "10.0.0.5:7000"
  }'
```

BE 會立刻回打你的 `http://10.0.0.5:7000/api/dev/ping`，body 必須是 `pong`。通過後 200，未通過 502（含詳細錯誤訊息）。

註冊成功 response：

```json
{
  "status":   "success",
  "name":     "chat",
  "target":   "http://10.0.0.5:7000",
  "prefix":   "/api/v1/chat",
  "upstream": "/api/dev/chat"
}
```

### 何時註冊

- 你的 server **listen 完成、可受理 ping** 之後立刻打。
- BE 重啟會清空所有 entry —— 你需要能偵測「為什麼流量不來了」並重打註冊。最簡單：定時重打（idempotent，同 name 直接覆蓋）。

### 重打與覆蓋

同 `name` 重複呼叫 register 會覆蓋既有 entry。沒有冷卻時間。建議下游每 30 秒～數分鐘重打一次當 keep-alive，藉此自動恢復「BE 重啟」的狀態。

---

## 4. 自訂 prefix / upstream / ping

預設值：

| 欄位 | 預設 |
|------|------|
| `prefix` | `/api/v1/<name>` |
| `upstream` | `/api/dev/<name>` |
| `ping` | `/api/dev/ping` |

需要時可覆寫，例如想被掛在 `/api/v1/foo` 但下游內部走 `/internal/foo`：

```json
{
  "name":     "foo",
  "addr":     "10.0.0.5:7000",
  "prefix":   "/api/v1/foo",
  "upstream": "/internal/foo",
  "ping":     "/internal/health"
}
```

注意事項：

- 路徑前面沒 `/` 會自動補上；尾端 `/` 會被 trim。
- `prefix` 撞到 BE 既有靜態路由，BE 那邊勝、你永遠收不到那筆流量（見 §7）。
- `name` 是 entry 的 key，不是 prefix。覆寫 `prefix` 不會影響到 `name`。

---

## 5. 拔掉

```bash
curl -X POST http://<BE>/api/v1/proxy/detach \
  -H 'Content-Type: application/json' \
  -d '{"name":"chat"}'
```

| HTTP | 條件 |
|------|------|
| 200 | 移除成功 |
| 404 | 該 name 沒註冊 |

下游服務「正常下線」前建議呼叫 detach；若你掛了沒 detach，BE 會在下一次代理請求拿到 connection refused，回 502 給呼叫端。BE 不會自動把死掉的 entry 清掉。

---

## 6. 你會收到什麼樣的請求

### 6.1 路徑

`new path = upstream + (reqPath - prefix)`

| BE prefix | upstream | BE 端 reqPath | 你收到 |
|-----------|----------|---------------|--------|
| `/api/v1/chat` | `/api/dev/chat` | `/api/v1/chat` | `/api/dev/chat` |
| `/api/v1/chat` | `/api/dev/chat` | `/api/v1/chat/foo` | `/api/dev/chat/foo` |
| `/api/v1/chat` | `/api/dev/chat` | `/api/v1/chat/foo/bar?x=1` | `/api/dev/chat/foo/bar?x=1` |
| `/api/v1/foo` | `/internal/foo` | `/api/v1/foo/x` | `/internal/foo/x` |

### 6.2 Headers

- 原 client 帶的 headers 原樣轉給你（含 `Authorization`、`Cookie`、`Content-Type` …）。
- `Host` header 會被改成你的 host。
- BE router-level middleware（含 `ValidateJWT`）已經跑過，但 **JWT 結果不會以 header 形式傳給你**——若你要做存取控管，自己再 parse 一次 `Authorization`。

### 6.3 Body / Method / Query

全部原樣保留，包含串流上傳。

### 6.4 你回什麼，client 就拿什麼

response status / headers / body 原樣回給原 client。回應大小、Content-Type 自由。

---

## 7. 撞到 BE 既有路由怎麼辦

BE 內部代理走 `Router.NoRoute`，**只有 BE 程式碼裡完全沒註冊到的路徑才會落到代理**。

| 你想註冊的 prefix | BE 既有 | 結果 |
|-------------------|---------|------|
| `/api/v1/chat` | 無 | OK，正常生效 |
| `/api/v1/component` | `GET /api/v1/component/` 等 | register 會成功（200），但你**永遠收不到流量** |
| `/api/v1/agent/search` | `POST /api/v1/agent/search` | 同上 |
| `/api/v1/proxy` | 控制端點本身 | 同上 |

### 上線前自我檢查

```bash
# 確認 BE 沒事先佔住你想要的 prefix
curl -i http://<BE>/api/v1/<your-name>
```

預期回應：

- `404` + `{"status":"error","message":"not found"}` → 沒人佔，安全。
- 任何其他 status → BE 已有靜態路由，換一個 prefix。

註冊成功後再打一次同樣的 URL，應收到從你下游回來的內容；沒有的話表示撞到、被靜態路由吃掉。

---

## 8. 錯誤處理

| 情境 | client 看到 |
|------|-------------|
| 下游離線、connection refused | `502` + `{"status":"error","message":"upstream error: ..."}` |
| 下游回 5xx | 原樣轉發（你的 status / body 原封不動） |
| 沒註冊 / 已 detach | `404` + `{"status":"error","message":"not found"}` |
| BE 重啟、entry 沒了 | `404`（同上） |

下游可以正常回 4xx / 5xx，BE 不會干涉你的 status code。

---

## 9. 不要做的事

- **不要**靠 IP 白名單擋住「只收 BE 的請求」——BE 在 K8s 內部時，cluster 內任何人都打得到你。需要授權的話自己驗 `Authorization`。
- **不要**靠 `Host` header 判斷來源，會被 BE 改寫成你的 host。
- **不要**把 ping 寫成需要查 DB / 等下游依賴的 deep health check。BE 那邊只給 3 秒。把 deep check 開另一條路徑、不要當 ping 用。
- **不要**期待 BE 幫你做認證——`ValidateJWT` 跑過但不會 forward 結果，做為 trust boundary 不安全。
- **不要**在 prefix 用過寬路徑（如 `/api/v1`），會吃掉所有 NoRoute 流量。

---

## 10. 最小可動範例（Node.js）

```js
const http = require("http");

const BE = process.env.BE || "http://127.0.0.1:8080";
const NAME = "chat";
const PORT = 7000;

const server = http.createServer((req, res) => {
    if (req.url === "/api/dev/ping") {
        res.writeHead(200, { "Content-Type": "text/plain" });
        return res.end("pong");
    }
    if (req.url.startsWith("/api/dev/chat")) {
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ ok: true, path: req.url }));
    }
    res.writeHead(404);
    res.end();
});

server.listen(PORT, "0.0.0.0", async () => {
    // 啟動完成 → 自己向 BE 註冊
    const r = await fetch(BE + "/api/v1/proxy/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: NAME, addr: "127.0.0.1:" + PORT }),
    });
    console.log("register:", r.status, await r.text());
});

// 下線時記得 detach
process.on("SIGINT", async () => {
    await fetch(BE + "/api/v1/proxy/detach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: NAME }),
    });
    process.exit(0);
});
```

---

## 11. FAQ

**Q: BE 重啟後我的 entry 沒了怎麼辦？**
A: 自己重打 register。建議起一個 30s ~ 60s 的 keep-alive timer 持續 register（同 name 覆蓋），順便當 self-healing。

**Q: 同一個 name 可以多副本嗎？**
A: 不行。後註冊的會覆蓋前一個，BE 不做負載分流。如要多副本，請在下游前面自己擺 LB，BE 只指到 LB 的 host:port。

**Q: 我的下游需要看到原 client IP？**
A: 目前 `httputil.ReverseProxy` 預設行為會幫你加 `X-Forwarded-For`。若要更精確，自己讀這個 header（注意 BE 也跑了 `SanitizeXForwardedFor` middleware）。

**Q: 可以代理 WebSocket 嗎？**
A: 程式碼層面 `httputil.ReverseProxy` 支援，但本系統未做迴歸測試。先在 staging 確認再上線。

**Q: 可以用 HTTPS 下游嗎？**
A: `addr` 可帶 `https://...`，註冊時 ping 會走 HTTPS。憑證需是受信任的（BE 走預設 `http.Client`）。
