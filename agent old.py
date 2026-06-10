"""
agent.py — Dijalankan di PC target.
Menangkap screenshot layar dan mengirimkannya ke relay server via WebSocket.
Juga menerima perintah input (mouse/keyboard) dari server dan mengeksekusinya.
"""

import asyncio
import base64
import io
import json
import logging
import os
import sys
import time

import pyautogui
import websockets
from dotenv import load_dotenv
from PIL import ImageGrab

load_dotenv()

# Konfigurasi dari environment variable
SERVER_URL = os.getenv("SERVER_URL", "ws://localhost:8000/ws/agent")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
SCREENSHOT_FPS = int(os.getenv("SCREENSHOT_FPS", "10"))
SCREENSHOT_QUALITY = int(os.getenv("SCREENSHOT_QUALITY", "50"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "3"))

# Nonaktifkan failsafe pyautogui agar tidak berhenti di sudut layar
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AGENT] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def ambil_screenshot() -> str:
    """
    Menangkap seluruh layar utama menggunakan PIL.ImageGrab.
    ImageGrab otomatis menyertakan kursor mouse dalam tangkapan layar.
    Mengembalikan string base64 JPEG yang siap dikirim via WebSocket.
    """
    img = ImageGrab.grab().convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=SCREENSHOT_QUALITY, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def eksekusi_input(data: dict) -> None:
    """
    Mengeksekusi perintah input yang diterima dari server.
    Mendukung: mouse_move, mouse_click, mouse_scroll, key_press, key_type.
    Parameter `data` adalah dict hasil parse JSON dari pesan WebSocket.
    """
    aksi = data.get("action")

    try:
        if aksi == "mouse_move":
            x, y = data["x"], data["y"]
            pyautogui.moveTo(x, y, duration=0)

        elif aksi == "mouse_click":
            x, y = data["x"], data["y"]
            tombol = data.get("button", "left")
            double = data.get("double", False)
            if double:
                pyautogui.doubleClick(x, y, button=tombol)
            else:
                pyautogui.click(x, y, button=tombol)

        elif aksi == "mouse_down":
            x, y = data["x"], data["y"]
            tombol = data.get("button", "left")
            pyautogui.mouseDown(x, y, button=tombol)

        elif aksi == "mouse_up":
            x, y = data["x"], data["y"]
            tombol = data.get("button", "left")
            pyautogui.mouseUp(x, y, button=tombol)

        elif aksi == "mouse_scroll":
            x, y = data["x"], data["y"]
            dx, dy = data.get("dx", 0), data.get("dy", 0)
            pyautogui.moveTo(x, y, duration=0)
            # pyautogui scroll: positif = atas, negatif = bawah
            if dy != 0:
                pyautogui.scroll(int(dy / 100))
            if dx != 0:
                pyautogui.hscroll(int(dx / 100))

        elif aksi == "key_press":
            kunci = data["key"]
            pyautogui.press(kunci)

        elif aksi == "key_down":
            kunci = data["key"]
            pyautogui.keyDown(kunci)

        elif aksi == "key_up":
            kunci = data["key"]
            pyautogui.keyUp(kunci)

        elif aksi == "key_type":
            teks = data["text"]
            # typewrite tidak mendukung unicode, gunakan pyperclip jika perlu
            pyautogui.write(teks, interval=0.02)

        else:
            log.warning("Aksi tidak dikenal: %s", aksi)

    except Exception as e:
        log.error("Gagal eksekusi input '%s': %s", aksi, e)


def bersihkan_state_input() -> None:
    """
    Melepaskan semua tombol modifier dan tombol mouse yang mungkin tersangkut.
    Dipanggil saat koneksi terputus atau program dihentikan.
    """
    log.info("Membersihkan state input (melepaskan semua tombol modifier & mouse)...")
    
    # Modifier keys yang rawan stuck
    modifier_keys = ["ctrl", "shift", "alt", "win"]
    for kunci in modifier_keys:
        try:
            pyautogui.keyUp(kunci)
        except Exception:
            pass

    # Tombol mouse
    tombol_mouse = ["left", "right", "middle"]
    for tombol in tombol_mouse:
        try:
            pyautogui.mouseUp(button=tombol)
        except Exception:
            pass


async def kirim_screenshot(ws) -> None:
    """
    Loop pengiriman screenshot secara periodik sesuai SCREENSHOT_FPS.
    Berjalan sebagai coroutine terpisah bersamaan dengan penerima perintah.
    """
    interval = 1.0 / SCREENSHOT_FPS

    while True:
        mulai = time.monotonic()
        try:
            frame = ambil_screenshot()
            pesan = json.dumps({"type": "frame", "data": frame})
            await ws.send(pesan)
        except websockets.ConnectionClosed:
            # Koneksi terputus, biarkan loop utama menangani reconnect
            break
        except Exception as e:
            log.error("Gagal kirim screenshot: %s", e)

        # Jaga framerate agar tidak melebihi FPS yang dikonfigurasi
        sisa = interval - (time.monotonic() - mulai)
        if sisa > 0:
            await asyncio.sleep(sisa)


async def terima_perintah(ws) -> None:
    """
    Loop penerimaan perintah input dari server.
    Setiap pesan JSON yang masuk dieksekusi oleh eksekusi_input().
    """
    async for pesan in ws:
        try:
            data = json.loads(pesan)
            tipe = data.get("type")

            if tipe == "input":
                eksekusi_input(data)
            elif tipe == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            else:
                log.debug("Pesan tidak dikenal: %s", tipe)

        except json.JSONDecodeError:
            log.warning("Pesan bukan JSON yang valid")
        except websockets.ConnectionClosed:
            break


async def jalankan_agent() -> None:
    """
    Fungsi utama agent: menghubungkan ke server, mengirim header autentikasi,
    lalu menjalankan loop screenshot dan penerima perintah secara bersamaan.
    Otomatis reconnect jika koneksi terputus.
    """
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}

    while True:
        try:
            log.info("Menghubungkan ke server: %s", SERVER_URL)
            async with websockets.connect(
                SERVER_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                log.info("Terhubung ke server. Memulai stream layar...")

                # Kirim info resolusi layar saat koneksi berhasil
                lebar, tinggi = pyautogui.size()
                resolusi = {"type": "info", "width": lebar, "height": tinggi}
                await ws.send(json.dumps(resolusi))

                # Jalankan screenshot sender dan command receiver secara bersamaan
                await asyncio.gather(
                    kirim_screenshot(ws),
                    terima_perintah(ws),
                )
            
            # Bersihkan input jika loop normal selesai/terputus
            bersihkan_state_input()

        except websockets.exceptions.InvalidStatus as e:
            log.error("Koneksi ditolak server (status %s). Cek AGENT_TOKEN.", e.response.status_code)
            await asyncio.sleep(RECONNECT_DELAY * 2)

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log.warning("Koneksi terputus: %s. Mencoba reconnect dalam %ds...", e, RECONNECT_DELAY)
            bersihkan_state_input()
            await asyncio.sleep(RECONNECT_DELAY)

        except Exception as e:
            log.error("Error tidak terduga: %s. Reconnect dalam %ds...", e, RECONNECT_DELAY)
            bersihkan_state_input()
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    # Validasi token sebelum mulai
    if not AGENT_TOKEN:
        log.error("AGENT_TOKEN belum diset. Tambahkan ke file .env")
        sys.exit(1)

    log.info("Remote PC Agent dimulai (FPS=%d, Quality=%d%%)", SCREENSHOT_FPS, SCREENSHOT_QUALITY)
    try:
        asyncio.run(jalankan_agent())
    except KeyboardInterrupt:
        log.info("Agent dihentikan oleh pengguna.")
    finally:
        bersihkan_state_input()
