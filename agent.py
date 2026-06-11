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
from PIL import Image, ImageGrab

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

# Coba import win32 untuk capture kursor — opsional
try:
    import win32gui
    import win32ui
    import win32con
    import win32api
    WIN32_TERSEDIA = True
    log.info("win32 tersedia — kursor akan ikut tercapture.")
except ImportError:
    WIN32_TERSEDIA = False
    log.warning("pywin32 tidak terinstall — kursor tidak akan muncul di stream.")
    log.warning("Jalankan: pip install pywin32")


def ambil_screenshot_win32() -> Image.Image:
    """
    Capture layar beserta kursor menggunakan win32gui.
    Menggambar kursor secara manual di atas screenshot.
    """
    lebar, tinggi = pyautogui.size()

    # Ambil screenshot via win32
    hdesktop = win32gui.GetDesktopWindow()
    hdc = win32gui.GetWindowDC(hdesktop)
    dc_obj = win32ui.CreateDCFromHandle(hdc)
    mem_dc = dc_obj.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(dc_obj, lebar, tinggi)
    mem_dc.SelectObject(bitmap)
    mem_dc.BitBlt((0, 0), (lebar, tinggi), dc_obj, (0, 0), win32con.SRCCOPY)

    # Gambar kursor di atas screenshot
    try:
        flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
        if flags:  # kursor terlihat
            win32gui.DrawIconEx(
                mem_dc.GetSafeHdc(), cx, cy, hcursor,
                0, 0, 0, None, win32con.DI_NORMAL
            )
    except Exception:
        pass  # gagal gambar kursor, lanjut tanpa kursor

    # Konversi ke PIL Image
    bmp_info = bitmap.GetInfo()
    bmp_str = bitmap.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGB",
        (bmp_info["bmWidth"], bmp_info["bmHeight"]),
        bmp_str, "raw", "BGRX", 0, 1
    )

    # Bersihkan resource
    mem_dc.DeleteDC()
    dc_obj.DeleteDC()
    win32gui.ReleaseDC(hdesktop, hdc)
    win32gui.DeleteObject(bitmap.GetHandle())

    return img


def ambil_screenshot() -> str:
    """
    Menangkap seluruh layar beserta kursor.
    Menggunakan win32 jika tersedia, fallback ke ImageGrab.
    Mengembalikan string base64 JPEG siap kirim via WebSocket.
    """
    if WIN32_TERSEDIA:
        img = ambil_screenshot_win32()
    else:
        img = ImageGrab.grab().convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=SCREENSHOT_QUALITY, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _mouse_event_absolut(x: int, y: int, flags: int, data: int = 0) -> None:
    """
    Kirim event mouse dengan koordinat absolut menggunakan win32api.mouse_event.
    Koordinat dinormalisasi ke rentang 0-65535 agar kompatibel dengan game
    yang menggunakan raw/direct input (seperti Roblox).
    Fallback ke pyautogui jika win32 tidak tersedia.
    """
    if WIN32_TERSEDIA:
        lebar, tinggi = pyautogui.size()
        nx = int(x * 65535 / lebar)
        ny = int(y * 65535 / tinggi)
        # Pindahkan mouse ke posisi absolut terlebih dahulu
        win32api.mouse_event(
            win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE,
            nx, ny, 0, 0
        )
        # Kirim event klik/down/up jika ada
        if flags:
            win32api.mouse_event(flags, nx, ny, data, 0)
    else:
        # Fallback pyautogui — tidak semua game mendukung ini
        pyautogui.moveTo(x, y, duration=0)


# Mapping nama tombol ke flag win32con untuk mouse down dan mouse up
_TOMBOL_FLAGS = {
    "left":   (win32con.MOUSEEVENTF_LEFTDOWN,   win32con.MOUSEEVENTF_LEFTUP)   if WIN32_TERSEDIA else (0, 0),
    "right":  (win32con.MOUSEEVENTF_RIGHTDOWN,  win32con.MOUSEEVENTF_RIGHTUP)  if WIN32_TERSEDIA else (0, 0),
    "middle": (win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP) if WIN32_TERSEDIA else (0, 0),
}


def eksekusi_input(data: dict) -> None:
    """
    Mengeksekusi perintah input yang diterima dari server.
    Operasi mouse menggunakan win32api untuk kompatibilitas game (Roblox, dll).
    Keyboard tetap menggunakan pyautogui.
    """
    aksi = data.get("action")

    try:
        if aksi == "mouse_move":
            x, y = data["x"], data["y"]
            _mouse_event_absolut(x, y, 0)

        elif aksi == "mouse_down":
            x, y = data["x"], data["y"]
            tombol = data.get("button", "left")
            flag_down, _ = _TOMBOL_FLAGS.get(tombol, (0, 0))
            if WIN32_TERSEDIA and flag_down:
                _mouse_event_absolut(x, y, flag_down)
            else:
                pyautogui.mouseDown(x, y, button=tombol)

        elif aksi == "mouse_up":
            x, y = data["x"], data["y"]
            tombol = data.get("button", "left")
            _, flag_up = _TOMBOL_FLAGS.get(tombol, (0, 0))
            if WIN32_TERSEDIA and flag_up:
                _mouse_event_absolut(x, y, flag_up)
            else:
                pyautogui.mouseUp(x, y, button=tombol)

        elif aksi == "mouse_click":
            x, y = data["x"], data["y"]
            tombol = data.get("button", "left")
            double = data.get("double", False)
            flag_down, flag_up = _TOMBOL_FLAGS.get(tombol, (0, 0))
            if WIN32_TERSEDIA and flag_down:
                ulang = 2 if double else 1
                for _ in range(ulang):
                    _mouse_event_absolut(x, y, flag_down)
                    time.sleep(0.02)
                    _mouse_event_absolut(x, y, flag_up)
                    if double:
                        time.sleep(0.05)
            else:
                if double:
                    pyautogui.doubleClick(x, y, button=tombol)
                else:
                    pyautogui.click(x, y, button=tombol)

        elif aksi == "mouse_scroll":
            x, y = data["x"], data["y"]
            dx, dy = data.get("dx", 0), data.get("dy", 0)
            _mouse_event_absolut(x, y, 0)
            if WIN32_TERSEDIA:
                if dy != 0:
                    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, int(dy), 0)
                if dx != 0:
                    win32api.mouse_event(win32con.MOUSEEVENTF_HWHEEL, 0, 0, int(dx), 0)
            else:
                if dy != 0:
                    pyautogui.scroll(int(dy / 100))

        elif aksi == "key_press":
            pyautogui.press(data["key"])

        elif aksi == "key_down":
            pyautogui.keyDown(data["key"])

        elif aksi == "key_up":
            pyautogui.keyUp(data["key"])

        elif aksi == "key_type":
            pyautogui.write(data["text"], interval=0.02)

        else:
            log.warning("Aksi tidak dikenal: %s", aksi)

    except Exception as e:
        log.error("Gagal eksekusi input '%s': %s", aksi, e)


def bersihkan_state_input() -> None:
    """
    Melepaskan semua tombol modifier dan tombol mouse yang mungkin tersangkut.
    """
    log.info("Membersihkan state input...")
    for kunci in ["ctrl", "shift", "alt", "win"]:
        try:
            pyautogui.keyUp(kunci)
        except Exception:
            pass
    for tombol in ["left", "right", "middle"]:
        try:
            pyautogui.mouseUp(button=tombol)
        except Exception:
            pass


async def kirim_screenshot(ws) -> None:
    """
    Loop pengiriman screenshot secara periodik sesuai SCREENSHOT_FPS.
    ambil_screenshot() dijalankan di thread pool agar tidak memblokir
    event loop — penting di FPS tinggi agar penerimaan input tetap responsif.
    """
    interval = 1.0 / SCREENSHOT_FPS
    loop = asyncio.get_event_loop()

    while True:
        mulai = time.monotonic()
        try:
            # Capture layar di thread terpisah, tidak memblokir coroutine lain
            frame = await loop.run_in_executor(None, ambil_screenshot)
            await ws.send(json.dumps({"type": "frame", "data": frame}))
        except websockets.ConnectionClosed:
            break
        except Exception as e:
            log.error("Gagal kirim screenshot: %s", e)

        sisa = interval - (time.monotonic() - mulai)
        if sisa > 0:
            await asyncio.sleep(sisa)


async def terima_perintah(ws) -> None:
    """Loop penerimaan perintah input dari server."""
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
    Fungsi utama agent: koneksi ke server, kirim info resolusi,
    lalu jalankan loop screenshot dan penerima perintah bersamaan.
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

                lebar, tinggi = pyautogui.size()
                await ws.send(json.dumps({"type": "info", "width": lebar, "height": tinggi}))

                await asyncio.gather(
                    kirim_screenshot(ws),
                    terima_perintah(ws),
                )

            bersihkan_state_input()

        except websockets.exceptions.InvalidStatus as e:
            log.error("Koneksi ditolak (status %s). Cek AGENT_TOKEN.", e.response.status_code)
            await asyncio.sleep(RECONNECT_DELAY * 2)

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log.warning("Koneksi terputus: %s. Reconnect dalam %ds...", e, RECONNECT_DELAY)
            bersihkan_state_input()
            await asyncio.sleep(RECONNECT_DELAY)

        except Exception as e:
            log.error("Error tidak terduga: %s. Reconnect dalam %ds...", e, RECONNECT_DELAY)
            bersihkan_state_input()
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
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