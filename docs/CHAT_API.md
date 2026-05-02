# Chat API

台北儀表板對話助手的串流 API。Server 透過 **Server-Sent Events (SSE)** 回應,
client 依 `event:` 欄位區分不同類型的訊息。

---

## Endpoint

```
POST /api/dev/chat
Content-Type: application/json
Accept:       text/event-stream
```

### Request body

| 欄位         | 型別    | 必填 | 說明                                                  |
|--------------|---------|------|-------------------------------------------------------|
| `prompt`     | string  | 是   | 使用者訊息。                                          |
| `session_id` | string  | 否   | 上一輪回應給的 UUID。第一次呼叫時不要帶。             |

```json
{
  "prompt": "聚焦到信義區並查詢人口",
  "session_id": "464f7930-2732-47fd-8df1-9d8049813ef1"
}
```

### Response

`Content-Type: text/event-stream` — 連線會保持開啟,直到 server 發出
`done` (成功) 或 `error` (異常) 為止。

---

## Session 管理

* **第一次對話**:不要帶 `session_id`。Server 會產生一個新 UUID,並透過
  `session` event 回傳。前端拿到後存起來。
* **後續對話**:帶上同一個 `session_id`,model 才有上下文記憶。
* 若 server 找不到該 `session_id` (例如 server 重啟、被 LRU 淘汰、或 id
  根本沒發過),server 會發新 UUID 並送 `notice` event 通知前端,
  原本的對話歷史已遺失。
* Session 存在 process 記憶體中,**重啟即消失**,且不跨 worker process。

### 手動清除 session

```
DELETE /api/dev/chat/session/{session_id}
```

回傳 `{"ok": true}`。使用者按「新對話」時呼叫。

---

## SSE Event 類型

每個 event 格式:

```
event: <type>
data: <json payload>

```

(兩個換行結束一個 event。)

### `notice`

Server 發出的軟性警告。目前只在 session 被重置時觸發。

```json
{
  "level": "warn",
  "code": "SESSION_EMPTY" | "SESSION_NOT_FOUND",
  "message": "UUID IS EMPTY, NOW IS NEW SESSION"
}
```

| Code                 | 意義                                            |
|----------------------|-------------------------------------------------|
| `SESSION_EMPTY`      | Client 沒帶 `session_id`,server 自動產生。     |
| `SESSION_NOT_FOUND`  | Client 帶的 `session_id` 不存在。               |

收到此 event 時,前端應清除本地對話紀錄,並改存接下來 `session` event
給的新 id。

### `session`

每次回應**必定發出**,且永遠在 model 輸出之前。告訴 client 接下來要用
哪個 id。

```json
{
  "session_id": "464f7930-2732-47fd-8df1-9d8049813ef1",
  "is_new": true,
  "requested": null
}
```

| 欄位         | 型別            | 說明                                              |
|--------------|-----------------|---------------------------------------------------|
| `session_id` | string (UUID)   | 下一輪要帶的 id。                                 |
| `is_new`     | bool            | `true` 表示這是 server 新生的 UUID。              |
| `requested`  | string \| null  | Client 原本送的 id (回傳給前端對照,可能為 null)。|

### `text`

Assistant 回覆的串流片段。依到達順序串接 `delta`,即可組出完整訊息。

```json
{ "delta": "信義區" }
```

同一次 HTTP response 內所有 `text` 片段屬於同一輪 assistant 回覆,
無需另外的 message id。

### `tool_used`

純通知。Server 端執行了一個內部資料查詢 tool。前端**不需動作**,
server 已自行用掉結果。可拿來做「思考中」指示燈或 tool trace UI。

```json
{ "name": "get_district_stats", "args": { "district": "信義區" } }
```

### `frontend_action`

Model 要求 UI 做某件事 (聚焦地圖、開啟面板、切換圖層...)。前端**必須**
執行這個動作,server 不會等回呼。

```json
{
  "id":     "fa_1e32cf1f",
  "action": "focus_district",
  "params": { "district": "信義區" }
}
```

| 欄位     | 型別   | 說明                                                          |
|----------|--------|---------------------------------------------------------------|
| `id`     | string | 此 action 的穩定 id,可用於去重。                             |
| `action` | string | Action 名稱。前端用 switch case 分派到對應 handler。          |
| `params` | object | Action 各自的參數。                                           |

#### 目前定義的 actions

| `action`           | `params`                                  | 效果                          |
|--------------------|-------------------------------------------|-------------------------------|
| `focus_district`   | `{ "district": string }`                  | 地圖平移/縮放到指定行政區。    |
| `open_dashboard`   | `{ "dashboard_id": string }`              | 開啟指定儀表板面板。           |
| `toggle_layer`     | `{ "layer": string, "visible": bool }`    | 顯示/隱藏地圖圖層。            |

未來會持續新增 action;前端遇到未知 `action` 視為 no-op (可選擇 log),
不要拋例外。

### `done`

成功結束時的最後一個 event。

```json
{
  "session_id":   "464f7930-2732-47fd-8df1-9d8049813ef1",
  "message_count": 8
}
```

收到 `done` 即可關閉 EventSource (或等下一次 request)。

### `error`

Server 端發生例外。連線之後會正常關閉。

```json
{ "message": "TimeoutError: ..." }
```

---

## Event 順序

每次 HTTP response 的 event 順序:

1. (可選) `notice`
2. `session` (一定有)
3. 零或多個 `tool_used` / `frontend_action` / `text`,順序依 model 實際
   產出穿插
4. 必定有一個 `done` 或 `error`

不要假設 `text` 是連續的:model 在 reply 中途可能 call tool,
此時 `tool_used` 或 `frontend_action` 會插在兩段 `text` 中間。

---

## 範例

### curl

```bash
# 第一輪 — 不帶 session_id
curl -N -X POST http://127.0.0.1:8000/api/dev/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "聚焦到信義區並查詢人口"}'

# 後續 — 沿用上一輪 `session` event 給的 id
curl -N -X POST http://127.0.0.1:8000/api/dev/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "那把空氣品質圖層打開", "session_id": "<貼上 UUID>"}'

# 重置 session
curl -X DELETE http://127.0.0.1:8000/api/dev/chat/session/<uuid>
```

### Browser (注意:EventSource 不支援 POST)

`EventSource` 只能 GET。POST + SSE 的常見作法是用 `fetch` 配 streaming
reader,或用小工具 [`@microsoft/fetch-event-source`](https://github.com/Azure/fetch-event-source)。

```ts
import { fetchEventSource } from '@microsoft/fetch-event-source';

let sessionId: string | null = localStorage.getItem('chat_session_id');
const fullText: string[] = [];

await fetchEventSource('/api/dev/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ prompt: userInput, session_id: sessionId }),
  onmessage(ev) {
    const data = JSON.parse(ev.data);
    switch (ev.event) {
      case 'notice':
        console.warn(data.code, data.message);
        // session 將被重置 — 清掉本地對話紀錄
        clearLocalHistory();
        break;

      case 'session':
        sessionId = data.session_id;
        localStorage.setItem('chat_session_id', sessionId);
        break;

      case 'text':
        fullText.push(data.delta);
        renderAssistantText(fullText.join(''));
        break;

      case 'tool_used':
        // 可選:顯示 tool trace
        showToolTrace(data.name, data.args);
        break;

      case 'frontend_action':
        dispatchFrontendAction(data.action, data.params, data.id);
        break;

      case 'done':
        // 該輪結束
        break;

      case 'error':
        showErrorToast(data.message);
        break;
    }
  },
});

function dispatchFrontendAction(action, params, id) {
  switch (action) {
    case 'focus_district':  map.focusDistrict(params.district); break;
    case 'open_dashboard':  panels.open(params.dashboard_id); break;
    case 'toggle_layer':    map.setLayerVisible(params.layer, params.visible); break;
    default:                console.warn('unknown action', action);
  }
}
```

### 純 `fetch` (無依賴)

```ts
const res = await fetch('/api/dev/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ prompt, session_id: sessionId }),
});

const reader = res.body!.getReader();
const decoder = new TextDecoder();
let buf = '';

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });

  // 用 SSE 分隔符切 frame
  let idx;
  while ((idx = buf.indexOf('\n\n')) !== -1) {
    const raw = buf.slice(0, idx);
    buf = buf.slice(idx + 2);
    handleSseFrame(parseSseFrame(raw));
  }
}

function parseSseFrame(raw: string) {
  let event = 'message';
  let data = '';
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data += line.slice(5).trim();
  }
  return { event, data: JSON.parse(data) };
}
```

---

## 限制與注意事項

* **Session 存記憶體** — Server 重啟所有對話都會消失。
* **Session 數量上限** — 預設保留 `MAX_SESSIONS = 1000` 個 session,
  超過時 LRU 淘汰最舊的。
* **單一 Session 訊息上限** — 預設保留 `MAX_MESSAGES_PER_SESSION = 40`
  則訊息,超過時從最舊的「使用者輪」邊界往後切,確保 tool_call /
  tool_return 配對不被拆開。
* **單 worker** — Session 不在 worker 之間共享,目前請用 `--workers 1`
  啟動,直到接上共享儲存 (Redis、DB) 為止。
* **無認證** — 任何能連到 server 的人都能呼叫 `/chat`。對外開放前
  記得加 API key header 或 reverse proxy 層 auth。
* **不會中斷** — 即使 client 斷線,server 還是會把 LLM call 跑完。
  之後可考慮 hook `request.is_disconnected()` 取消 runner task。

---

## 速查表

| Event             | 何時觸發                                       | 前端動作                                                       |
|-------------------|-----------------------------------------------|----------------------------------------------------------------|
| `notice`          | Session 被重置                                 | 清掉本地歷史;準備接收新 id。                                  |
| `session`         | 永遠,在 `notice` (若有) 之後立刻發            | 存下 `session_id`;下一輪請求帶上。                            |
| `text`            | Model 產出文字                                 | 把 `delta` 接到 assistant 訊息泡泡尾端。                       |
| `tool_used`       | 內部資料查詢 tool 執行                         | 可選 UI 提示;不需動作。                                       |
| `frontend_action` | Model 要求 UI 操作                             | 依 `action` 分派 handler,傳入 `params`。                      |
| `done`            | 該輪正常結束                                   | 關閉 stream;可送下一輪訊息。                                  |
| `error`           | Server 端例外                                  | 顯示錯誤;stream 已自動結束。                                  |
