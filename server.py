"""
server.py — Relay server utama (FastAPI + WebSocket).
Bertugas sebagai jembatan antara agent (PC target) dan client (browser).

Arsitektur koneksi:
    agent.py  ←→  /ws/agent   (WebSocket, auth: AGENT_TOKEN)
    browser   ←→  /ws/client  (WebSocket, auth: JWT)
    browser   →   /auth/login (HTTP POST, mendapat JWT)
"""

import json
import logging
import sys
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import config

# ─── Setup logging ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SERVER] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Validasi konfigurasi kritis ──────────────────────────────────────────────

if not config.JWT_SECRET:
    log.error("JWT_SECRET belum diset di .env. Server tidak bisa dimulai.")
    sys.exit(1)

if not config.AGENT_TOKEN:
    log.error("AGENT_TOKEN belum diset di .env. Server tidak bisa dimulai.")
    sys.exit(1)

# ─── State global koneksi ─────────────────────────────────────────────────────

# Hanya satu agent yang terhubung dalam satu waktu
agent_ws: Optional[WebSocket] = None

# Daftar semua client browser yang sedang menonton
client_list: list[WebSocket] = []

# ─── Inisialisasi aplikasi FastAPI ────────────────────────────────────────────

app = FastAPI(title="Remote PC Control Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sajikan file statis frontend dari folder /client
app.mount("/static", StaticFiles(directory="client"), name="static")


# ─── Model request ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


# ─── Endpoint HTTP ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Redirect pengguna ke halaman utama frontend."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@app.post("/auth/login")
async def login(body: LoginRequest):
    """
    Endpoint login untuk client browser.
    Menerima password, jika cocok dengan AGENT_TOKEN maka mengembalikan JWT.
    JWT ini dipakai oleh browser saat membuka koneksi WebSocket /ws/client.
    """
    if not auth.verifikasi_agent_token(body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password salah",
        )

    token = auth.buat_access_token({"sub": "viewer"})
    log.info("Login berhasil, JWT diterbitkan.")
    return JSONResponse({"access_token": token, "token_type": "bearer"})


@app.get("/status")
async def cek_status():
    """Mengembalikan status koneksi agent dan jumlah client yang terhubung."""
    return {
        "agent_connected": agent_ws is not None,
        "client_count": len(client_list),
    }


# ─── WebSocket: Agent ─────────────────────────────────────────────────────────

@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    """
    Endpoint WebSocket untuk agent.py yang berjalan di PC target.
    Autentikasi menggunakan AGENT_TOKEN di header Authorization.
    Setelah terhubung, agent mengirim frame screenshot dan menerima perintah input.
    """
    global agent_ws

    # Verifikasi token agent dari header
    token = _ambil_bearer_token(websocket)
    if not auth.verifikasi_agent_token(token):
        await websocket.close(code=4001, reason="Token agent tidak valid")
        log.warning("Koneksi agent ditolak: token tidak valid")
        return

    await websocket.accept()
    agent_ws = websocket
    log.info("Agent terhubung dari %s", websocket.client)

    # Beritahu semua client bahwa agent sudah online
    await broadcast_ke_client({"type": "agent_status", "connected": True})

    try:
        async for pesan in websocket.iter_text():
            try:
                data = json.loads(pesan)
            except json.JSONDecodeError:
                continue

            tipe = data.get("type")

            if tipe == "frame":
                # Forward frame screenshot ke semua client yang terhubung
                await broadcast_ke_client(data)

            elif tipe == "info":
                # Informasi resolusi layar dari agent, broadcast ke client
                log.info("Info layar agent: %dx%d", data.get("width", 0), data.get("height", 0))
                await broadcast_ke_client(data)

            elif tipe == "pong":
                pass  # keepalive response, abaikan

    except WebSocketDisconnect:
        log.info("Agent terputus.")
    finally:
        agent_ws = None
        await broadcast_ke_client({"type": "agent_status", "connected": False})


# ─── WebSocket: Client (browser) ──────────────────────────────────────────────

@app.websocket("/ws/client")
async def ws_client(websocket: WebSocket):
    """
    Endpoint WebSocket untuk browser client.
    Autentikasi menggunakan JWT yang didapat dari /auth/login.
    Client menerima frame screenshot dan mengirim perintah input ke agent.
    """
    # Verifikasi JWT dari query param atau header
    token = _ambil_bearer_token(websocket)
    if not token:
        # Coba ambil dari query parameter ?token=...
        token = websocket.query_params.get("token", "")

    payload = auth.verifikasi_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Token JWT tidak valid atau kedaluwarsa")
        log.warning("Koneksi client ditolak: JWT tidak valid")
        return

    await websocket.accept()
    client_list.append(websocket)
    log.info("Client terhubung. Total client: %d", len(client_list))

    # Kirim status agent saat ini ke client yang baru konek
    await websocket.send_text(json.dumps({
        "type": "agent_status",
        "connected": agent_ws is not None,
    }))

    try:
        async for pesan in websocket.iter_text():
            try:
                data = json.loads(pesan)
            except json.JSONDecodeError:
                continue

            tipe = data.get("type")

            if tipe == "input":
                # Forward perintah input dari client ke agent
                await kirim_ke_agent(data)
            elif tipe == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        log.info("Client terputus.")
    finally:
        if websocket in client_list:
            client_list.remove(websocket)
        log.info("Total client tersisa: %d", len(client_list))


# ─── Helper functions ─────────────────────────────────────────────────────────

def _ambil_bearer_token(websocket: WebSocket) -> str:
    """
    Mengambil Bearer token dari header Authorization.
    Mengembalikan string token atau string kosong jika tidak ada.
    """
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    return ""


async def broadcast_ke_client(data: dict) -> None:
    """
    Mengirim pesan JSON ke semua client browser yang sedang terhubung.
    Client yang terputus secara diam-diam dikeluarkan dari daftar.
    """
    if not client_list:
        return

    pesan = json.dumps(data)
    putus = []

    for client in client_list:
        try:
            await client.send_text(pesan)
        except Exception:
            putus.append(client)

    for client in putus:
        client_list.remove(client)


async def kirim_ke_agent(data: dict) -> None:
    """
    Mengirim perintah input ke agent yang sedang terhubung.
    Jika agent tidak terhubung, perintah diabaikan.
    """
    if agent_ws is None:
        log.debug("Perintah input diabaikan: agent tidak terhubung")
        return

    try:
        await agent_ws.send_text(json.dumps(data))
    except Exception as e:
        log.warning("Gagal kirim perintah ke agent: %s", e)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Memulai Remote PC Control Server...")
    log.info("Buka browser: http://localhost:%d", config.PORT)
    uvicorn.run(
        "server:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )
