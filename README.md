# Remote PC Control

> Kendalikan PC dari mana saja — hanya dengan browser.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-Real--time-4A90D9?style=flat-square)
![JWT](https://img.shields.io/badge/Auth-JWT-F7B731?style=flat-square&logo=jsonwebtokens&logoColor=white)
![Vanilla JS](https://img.shields.io/badge/Frontend-Vanilla%20JS-F7DF1E?style=flat-square&logo=javascript&logoColor=black)
![Ngrok](https://img.shields.io/badge/Tunnel-Ngrok-1F1F1F?style=flat-square&logo=ngrok&logoColor=white)

---

## Apa ini?

**Remote PC Control** adalah sistem kendali jarak jauh berbasis web yang dibangun dari nol — tanpa library remote desktop pihak ketiga. Pengguna bisa melihat layar PC target secara real-time dan mengendalikan mouse serta keyboard langsung dari browser, melewati NAT dan firewall menggunakan tunnel Ngrok.

Proyek ini mendemonstrasikan kemampuan membangun sistem real-time end-to-end: dari capture layar di level OS, streaming via WebSocket, hingga rendering di canvas browser dengan sinkronisasi koordinat input.

---

## Demo

```
Browser (client)                Server (relay)               Agent (PC target)
     │                               │                               │
     │── POST /auth/login ──────────►│                               │
     │◄── JWT token ─────────────────│                               │
     │                               │◄─── WS /ws/agent ────────────│
     │── WS /ws/client?token=... ───►│                               │
     │◄── agent_status + info ───────│  (re-sent even if late join)  │
     │                               │◄─── frame (base64 JPEG) ─────│
     │◄── frame ─────────────────────│                               │
     │── input (mouse/keyboard) ────►│                               │
     │                               │──── input ──────────────────►│
     │                               │                    pyautogui executes
```

---

## Fitur

- **Live screen streaming** — screenshot diambil dengan `PIL.ImageGrab`, dikompresi JPEG, dikirim via WebSocket, dirender ke `<canvas>`
- **Full mouse control** — move, click, double-click, klik kanan, scroll (horizontal & vertikal)
- **Full keyboard control** — key down/up dengan deduplication, intercept shortcut browser (Ctrl+C, Ctrl+V, F5, dll.)
- **Hotkey buttons** — Ctrl+Alt+Del, Win, Alt+Tab, dan lainnya langsung dari UI
- **JWT authentication** — sesi browser dengan token short-lived, otomatis logout saat tab ditutup
- **Auto-reconnect** — agent dan browser reconnect otomatis jika koneksi terputus
- **Multi-viewer** — beberapa browser bisa menonton sekaligus
- **Late-join safe** — server menyimpan info resolusi terakhir dan mengirimnya ke client yang konek belakangan
- **Tunnel support** — siap deploy via Ngrok static domain tanpa config tambahan
- **FPS & latency monitor** — statistik real-time di toolbar

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Relay server | Python · FastAPI · Uvicorn · WebSocket |
| Agent | Python · Pillow (ImageGrab) · pyautogui |
| Auth | python-jose (JWT HS256) |
| Frontend | HTML5 · Vanilla JS · Canvas API |
| Tunnel | Ngrok static domain |
| Config | python-dotenv |

---

## Arsitektur

Tiga proses berjalan secara independen dan berkomunikasi lewat relay server:

```
┌─────────────┐     WS /ws/agent     ┌──────────────┐     WS /ws/client    ┌─────────────┐
│  agent.py   │ ──────────────────►  │  server.py   │ ◄──────────────────  │   Browser   │
│  (target)   │ ◄────────────────── │   (relay)    │ ──────────────────►  │  (viewer)   │
└─────────────┘    input commands    └──────────────┘    frame + status    └─────────────┘
  ImageGrab                            FastAPI                               Canvas API
  pyautogui                            JWT Auth                              Vanilla JS
```

**Alur screen stream:**
`ImageGrab.grab()` → JPEG compress → base64 encode → JSON `{type:"frame"}` → WebSocket → `broadcast_ke_client()` → `renderFrame()` → `canvas.drawImage()`

**Alur input:**
Canvas event → `hitungKoordinat()` (scale ke resolusi agent) → `kirimInput()` → WebSocket → `eksekusi_input()` → `pyautogui`

**Scaling koordinat** adalah inti dari sinkronisasi input. Saat pertama konek, agent mengirim resolusi layarnya (`{type:"info", width, height}`). Server menyimpan info ini dan mengirimnya ke setiap browser client yang konek — termasuk yang konek belakangan setelah agent sudah online. Setiap koordinat mouse dikalikan `remoteWidth / canvas.width` sebelum dikirim.

---

## Instalasi & Menjalankan

### Prasyarat
- Python 3.11+
- Akun Ngrok (untuk akses dari luar jaringan)

### Setup

```bash
# 1. Clone repo
git clone https://github.com/username/remote-pc.git
cd remote-pc

# 2. Install dependencies
pip install -r requirements.txt

# 3. Salin dan isi konfigurasi
cp .env.example .env
```

Edit `.env` — generate nilai untuk `JWT_SECRET` dan `AGENT_TOKEN`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
# Jalankan dua kali: hasil pertama → JWT_SECRET, kedua → AGENT_TOKEN
```

### Menjalankan (lokal)

```bash
# Terminal 1 — relay server
python server.py

# Terminal 2 — agent di PC target
python agent.py
```

Buka browser: **`http://localhost:8000`**

Login menggunakan nilai `AGENT_TOKEN` dari file `.env` sebagai password.

### Deploy dengan Ngrok

Jalankan ketiga proses di terminal terpisah, **urutan ini penting**:

```bash
# Terminal 1
python server.py

# Terminal 2
ngrok http 8000 --domain=your-static-domain.ngrok-free.app

# Terminal 3 (PC target — pastikan SERVER_URL di .env sudah pakai wss://)
python agent.py
```

Update `SERVER_URL` di `.env` pada PC target:
```
SERVER_URL=wss://your-static-domain.ngrok-free.app/ws/agent
```

> **Penting:** Ngrok selalu menggunakan HTTPS/WSS. Gunakan `wss://` bukan `ws://` — menggunakan `ws://` akan menyebabkan error koneksi di agent.

Buka browser ke: **`https://your-static-domain.ngrok-free.app`**

---

## Konfigurasi

| Variable | PC Server | PC Target | Default | Keterangan |
|---|---|---|---|---|
| `JWT_SECRET` | ✅ | — | — | Secret key JWT (**wajib**) |
| `AGENT_TOKEN` | ✅ | ✅ | — | Token auth & password login (**wajib, harus sama**) |
| `HOST` | ✅ | — | `0.0.0.0` | Bind address server |
| `PORT` | ✅ | — | `8000` | Port server |
| `SERVER_URL` | — | ✅ | `ws://localhost:8000/ws/agent` | URL relay server untuk agent |
| `SCREENSHOT_FPS` | — | ✅ | `10` | Frame per detik |
| `SCREENSHOT_QUALITY` | — | ✅ | `50` | Kualitas JPEG (1–100) |
| `RECONNECT_DELAY` | — | ✅ | `3` | Detik sebelum reconnect |
| `JWT_EXPIRE_MINUTES` | ✅ | — | `60` | Masa berlaku JWT |

---

## Struktur Project

```
remote-pc/
├── server.py          ← Relay server (FastAPI + WebSocket)
├── agent.py           ← Dijalankan di PC target
├── auth.py            ← JWT & token authentication
├── config.py          ← Semua config dari environment variable
├── requirements.txt
├── .env.example
└── client/
    ├── index.html     ← Login + viewer UI
    ├── app.js         ← WebSocket, canvas render, input capture
    └── style.css      ← Dark theme UI
```

---

## Catatan Keamanan

- **Jangan expose server langsung ke internet** tanpa HTTPS — gunakan Ngrok atau reverse proxy dengan TLS.
- `AGENT_TOKEN` dan `JWT_SECRET` harus berbeda dan memiliki entropi tinggi (minimal 32 byte acak).
- JWT disimpan di `sessionStorage` (bukan `localStorage`) — otomatis terhapus saat tab ditutup.
- WS close code `4001` digunakan sebagai sinyal auth failure — browser tidak akan reconnect dan langsung kembali ke halaman login.

---

## License

MIT
