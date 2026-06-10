# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

Copy `.env.example` to `.env` and fill in the values before running anything.

```bash
# Install dependencies (once)
pip install -r requirements.txt

# Start relay server (must be running before agent or browser connects)
python server.py

# Start agent on the target PC (separate terminal / separate machine)
python agent.py
```

Frontend is served as static files by the server at `http://localhost:8000` — no separate build step or dev server needed. Do **not** open `client/index.html` directly in the browser (`file://` protocol will break all fetch and WebSocket calls).

`HOST=0.0.0.0` is a bind address, not a browseable URL — always access via `http://localhost:PORT`.

Generate secrets for `.env`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Run twice: first output → `JWT_SECRET`, second → `AGENT_TOKEN`.

## Architecture

Three parties communicate via a central relay server:

```
agent.py  ──WS /ws/agent──►  server.py  ◄──WS /ws/client──  browser
  (target PC)                 (relay)                        (client/)
```

**Data flow — screen stream:**
`agent.py` captures screen with `PIL.ImageGrab` → compresses to JPEG → encodes base64 → sends JSON `{type:"frame", data:"..."}` → server broadcasts to all entries in `client_list` → browser decodes base64 in `renderFrame()` → draws to `<canvas>`.

**Data flow — input commands:**
Browser canvas events → `hitungKoordinat()` scales to agent screen resolution → `kirimInput()` sends JSON `{type:"input", action:"...", ...}` → server forwards to `agent_ws` → `eksekusi_input()` calls pyautogui.

**Resolution scaling** is the critical link between browser and agent. On connect, agent sends `{type:"info", width, height}` which the browser stores in `remoteWidth`/`remoteHeight`. Every mouse coordinate is multiplied by `remoteWidth / canvas.width` before being sent.

**Static file serving:** `server.py` mounts `client/` at `/static/` via FastAPI `StaticFiles`. The root route `/` redirects to `/static/index.html`.

## Auth model

Two separate auth mechanisms, do not confuse them:

| | `AGENT_TOKEN` | `JWT_SECRET` |
|---|---|---|
| Used by | `agent.py` connecting via WS header | Browser clients via `/auth/login` |
| Verified by | `verifikasi_agent_token()` — direct string compare | `verifikasi_token()` — jose JWT decode |
| Sent as | `Authorization: Bearer <token>` WS header | Query param `?token=` on WS connect |

Login password at `/auth/login` **is** the `AGENT_TOKEN` — the server issues a short-lived JWT in exchange. The JWT is stored in `sessionStorage` (cleared on tab close). WS close code `4001` means auth failure; the browser clears the token and returns to login instead of reconnecting.

Browser WebSocket sends JWT as query param (`?token=`) because the browser WebSocket API does not support custom headers.

## Module responsibilities

- `config.py` — single source of truth for all env vars; imported by `server.py` and `auth.py`. Never call `os.getenv()` directly outside this file.
- `auth.py` — JWT creation (`buat_access_token`) and verification (`verifikasi_token`, `verifikasi_agent_token`). Imported only by `server.py`.
- `server.py` — FastAPI app, WebSocket endpoints, global state, broadcast logic.
- `agent.py` — standalone process; reads config directly from `os.getenv` with `load_dotenv()` since it runs on a separate machine without importing `config.py`.

## Server state

`server.py` holds three module-level globals:
- `agent_ws: Optional[WebSocket]` — only one agent at a time; replaced if a new one connects
- `client_list: list[WebSocket]` — multiple browser viewers allowed simultaneously
- `agent_info: Optional[dict]` — last `{type:"info", width, height}` from agent; re-sent to any browser client that connects after the agent

`broadcast_ke_client()` silently removes dead connections during each broadcast — no explicit cleanup loop.

When a new browser client connects, the server immediately sends two messages: `agent_status` and (if available) `agent_info`. This ensures the browser always knows the agent's screen resolution even if it connects after the agent.

## Canvas sizing (client)

Canvas is sized **once** via `aturUkuranCanvas(w, h)` when the `info` message arrives — resizing on every frame would clear the canvas causing a black flash. A `canvasSudahDisizing` flag guards against double-sizing. If `info` somehow arrives late, `renderFrame()` has a fallback that sizes the canvas from the first frame's natural dimensions (`img.naturalWidth/Height`). The flag resets when the agent disconnects so the canvas is re-sized correctly on reconnect.

## Ngrok (remote access)

To expose the server to the internet:
```bash
ngrok http 8000 --domain=your-static-domain.ngrok-free.app
```
Then update `SERVER_URL` in `.env` on the agent machine:
```
SERVER_URL=wss://your-static-domain.ngrok-free.app/ws/agent
```
**Important:** Ngrok always uses HTTPS/WSS — use `wss://` not `ws://`. Using `ws://` with a ngrok domain causes a redirect to `https://` that the websockets library cannot follow, resulting in an invalid URI error.

Browser clients connect to the ngrok URL automatically — `app.js` derives the WS URL from `window.location.origin`.

## Startup order

```
python server.py  →  ngrok http 8000  →  python agent.py  →  open browser
```

Agent auto-reconnects every `RECONNECT_DELAY` seconds if server is not yet up — order matters but the agent is tolerant of a missing server.

## Conventions

- **All function names, variable names, log messages, and comments are in Indonesian.** This is intentional — maintain it when adding new code.
- All config values must come from environment variables via `config.py`. Never read `os.getenv()` directly in `server.py` or `auth.py`.
- Both `agent.py` and `server.py` validate their required env vars at startup and call `sys.exit(1)` if missing.
- Frontend auto-detects the server URL from `window.location.origin` — no hardcoded URLs in `app.js`.
- `pyautogui.FAILSAFE = False` is intentionally disabled in agent so the remote cursor near screen corners doesn't kill the process.

## WebSocket message types reference

| `type` | Direction | Payload |
|---|---|---|
| `frame` | agent → server → client | `{data: "<base64 JPEG>"}` |
| `info` | agent → server → client | `{width, height}` |
| `input` | client → server → agent | `{action, ...coords/key fields}` |
| `agent_status` | server → client | `{connected: bool}` |
| `ping` / `pong` | client ↔ server, agent ↔ server | — |

Input `action` values accepted by `eksekusi_input()`: `mouse_move`, `mouse_click`, `mouse_down`, `mouse_up`, `mouse_scroll`, `key_press`, `key_down`, `key_up`, `key_type`.

gunakan bahasa indonesia
