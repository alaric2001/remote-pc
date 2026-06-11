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

import numpy as np
import pyautogui
import websockets
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

SERVER_URL         = os.getenv("SERVER_URL", "ws://localhost:8000/ws/agent")
AGENT_TOKEN        = os.getenv("AGENT_TOKEN", "")
SCREENSHOT_FPS     = int(os.getenv("SCREENSHOT_FPS", "30"))
SCREENSHOT_QUALITY = int(os.getenv("SCREENSHOT_QUALITY", "35"))
RECONNECT_DELAY    = int(os.getenv("RECONNECT_DELAY", "3"))

pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AGENT] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── win32 ───────────────────────────────────────────────────────────────────

try:
    import win32gui, win32ui, win32con, win32api
    WIN32_TERSEDIA = True
    log.info("win32 tersedia.")
except ImportError:
    WIN32_TERSEDIA = False
    log.warning("pywin32 tidak terinstall. Jalankan: pip install pywin32")

# ─── dxcam ───────────────────────────────────────────────────────────────────

try:
    import dxcam
    _camera = dxcam.create(output_color="RGB")
    _camera.start(target_fps=SCREENSHOT_FPS)
    DXCAM_TERSEDIA = True
    log.info("dxcam aktif — target %d FPS.", SCREENSHOT_FPS)
except Exception as e:
    DXCAM_TERSEDIA = False
    _camera = None
    log.warning("dxcam tidak tersedia: %s", e)

# ─── Render kursor ke PIL Image ──────────────────────────────────────────────

def _render_kursor() -> tuple:
    """
    Render kursor Windows ke PIL Image RGBA 32x32.
    Return: (img_kursor, cx, cy) atau None jika gagal/kursor tidak terlihat.
    """
    try:
        flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
        if not flags or hcursor == 0:
            return None

        hdc_screen = win32gui.GetDC(0)
        dc_src     = win32ui.CreateDCFromHandle(hdc_screen)
        cursor_dc  = dc_src.CreateCompatibleDC()
        cursor_bmp = win32ui.CreateBitmap()
        cursor_bmp.CreateCompatibleBitmap(dc_src, 32, 32)
        cursor_dc.SelectObject(cursor_bmp)

        # Background hitam agar bisa dijadikan mask transparansi
        cursor_dc.FillSolidRect((0, 0, 32, 32), 0x000000)
        win32gui.DrawIconEx(cursor_dc.GetSafeHdc(), 0, 0, hcursor,
                            32, 32, 0, None, win32con.DI_NORMAL)

        bits = cursor_bmp.GetBitmapBits(True)
        arr  = np.frombuffer(bits, dtype=np.uint8).reshape(32, 32, 4)

        # BGRX → RGBA, pixel hitam = transparan
        kursor_rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        kursor_rgba[:, :, 0] = arr[:, :, 2]  # R
        kursor_rgba[:, :, 1] = arr[:, :, 1]  # G
        kursor_rgba[:, :, 2] = arr[:, :, 0]  # B
        mask = (arr[:, :, 0] > 10) | (arr[:, :, 1] > 10) | (arr[:, :, 2] > 10)
        kursor_rgba[:, :, 3] = np.where(mask, 255, 0)

        img_kursor = Image.fromarray(kursor_rgba, "RGBA")

        cursor_dc.DeleteDC()
        dc_src.DeleteDC()
        win32gui.ReleaseDC(0, hdc_screen)
        win32gui.DeleteObject(cursor_bmp.GetHandle())

        return (img_kursor, cx, cy)

    except Exception as e:
        log.debug("Gagal render kursor: %s", e)
        return None


def _tempel_kursor(img: Image.Image) -> Image.Image:
    """Tempel kursor ke frame PIL. Return frame baru dengan kursor."""
    if not WIN32_TERSEDIA:
        return img

    hasil = _render_kursor()
    if hasil is None:
        return img

    img_kursor, cx, cy = hasil
    img_rgba = img.convert("RGBA")
    img_rgba.paste(img_kursor, (cx, cy), img_kursor)
    return img_rgba.convert("RGB")


# ─── Screenshot ──────────────────────────────────────────────────────────────

def ambil_screenshot() -> str:
    """
    Capture layar + tempel kursor.
    Prioritas: dxcam (GPU) → win32 GDI → ImageGrab.
    Return: string base64 JPEG.
    """
    if DXCAM_TERSEDIA and _camera is not None:
        frame = _camera.get_latest_frame()
        if frame is not None:
            img = Image.fromarray(frame)
        else:
            from PIL import ImageGrab
            img = ImageGrab.grab().convert("RGB")
    elif WIN32_TERSEDIA:
        img = _capture_win32()
    else:
        from PIL import ImageGrab
        img = ImageGrab.grab().convert("RGB")

    # Tempel kursor ke frame
    img = _tempel_kursor(img)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=SCREENSHOT_QUALITY, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _capture_win32() -> Image.Image:
    """Fallback capture via win32 GDI (tanpa kursor — kursor ditempel terpisah)."""
    lebar, tinggi = pyautogui.size()
    hdesktop = win32gui.GetDesktopWindow()
    hdc      = win32gui.GetWindowDC(hdesktop)
    dc_obj   = win32ui.CreateDCFromHandle(hdc)
    mem_dc   = dc_obj.CreateCompatibleDC()
    bitmap   = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(dc_obj, lebar, tinggi)
    mem_dc.SelectObject(bitmap)
    mem_dc.BitBlt((0, 0), (lebar, tinggi), dc_obj, (0, 0), win32con.SRCCOPY)
    bmp_info = bitmap.GetInfo()
    bmp_str  = bitmap.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (bmp_info["bmWidth"], bmp_info["bmHeight"]),
                           bmp_str, "raw", "BGRX", 0, 1)
    mem_dc.DeleteDC(); dc_obj.DeleteDC()
    win32gui.ReleaseDC(hdesktop, hdc)
    win32gui.DeleteObject(bitmap.GetHandle())
    return img


# ─── Input ───────────────────────────────────────────────────────────────────

_TOMBOL_FLAGS = {}
if WIN32_TERSEDIA:
    _TOMBOL_FLAGS = {
        "left":   (win32con.MOUSEEVENTF_LEFTDOWN,   win32con.MOUSEEVENTF_LEFTUP),
        "right":  (win32con.MOUSEEVENTF_RIGHTDOWN,  win32con.MOUSEEVENTF_RIGHTUP),
        "middle": (win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP),
    }


def _mouse_absolut(x: int, y: int, flags: int = 0, data: int = 0) -> None:
    if not WIN32_TERSEDIA:
        pyautogui.moveTo(x, y, duration=0)
        return
    lebar, tinggi = pyautogui.size()
    nx = int(x * 65535 / lebar)
    ny = int(y * 65535 / tinggi)
    win32api.mouse_event(
        win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE, nx, ny, 0, 0
    )
    if flags:
        win32api.mouse_event(flags, nx, ny, data, 0)


def eksekusi_input(data: dict) -> None:
    aksi = data.get("action")
    try:
        if aksi == "mouse_move":
            _mouse_absolut(data["x"], data["y"])

        elif aksi == "mouse_down":
            tombol = data.get("button", "left")
            flag_down, _ = _TOMBOL_FLAGS.get(tombol, (0, 0))
            if WIN32_TERSEDIA and flag_down:
                _mouse_absolut(data["x"], data["y"], flag_down)
            else:
                pyautogui.mouseDown(data["x"], data["y"], button=tombol)

        elif aksi == "mouse_up":
            tombol = data.get("button", "left")
            _, flag_up = _TOMBOL_FLAGS.get(tombol, (0, 0))
            if WIN32_TERSEDIA and flag_up:
                _mouse_absolut(data["x"], data["y"], flag_up)
            else:
                pyautogui.mouseUp(data["x"], data["y"], button=tombol)

        elif aksi == "mouse_click":
            tombol = data.get("button", "left")
            double = data.get("double", False)
            flag_down, flag_up = _TOMBOL_FLAGS.get(tombol, (0, 0))
            if WIN32_TERSEDIA and flag_down:
                for _ in range(2 if double else 1):
                    _mouse_absolut(data["x"], data["y"], flag_down)
                    time.sleep(0.02)
                    _mouse_absolut(data["x"], data["y"], flag_up)
                    if double: time.sleep(0.05)
            else:
                if double: pyautogui.doubleClick(data["x"], data["y"], button=tombol)
                else:      pyautogui.click(data["x"], data["y"], button=tombol)

        elif aksi == "mouse_scroll":
            x, y = data["x"], data["y"]
            dx, dy = data.get("dx", 0), data.get("dy", 0)
            _mouse_absolut(x, y)
            if WIN32_TERSEDIA:
                if dy != 0: win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL,  0, 0, int(dy), 0)
                if dx != 0: win32api.mouse_event(win32con.MOUSEEVENTF_HWHEEL, 0, 0, int(dx), 0)
            else:
                if dy != 0: pyautogui.scroll(int(dy / 100))

        elif aksi == "key_press":  pyautogui.press(data["key"])
        elif aksi == "key_down":   pyautogui.keyDown(data["key"])
        elif aksi == "key_up":     pyautogui.keyUp(data["key"])
        elif aksi == "key_type":   pyautogui.write(data["text"], interval=0.02)
        else: log.warning("Aksi tidak dikenal: %s", aksi)

    except Exception as e:
        log.error("Gagal eksekusi input '%s': %s", aksi, e)


def bersihkan_state_input() -> None:
    log.info("Membersihkan state input...")
    for k in ["ctrl", "shift", "alt", "win"]:
        try: pyautogui.keyUp(k)
        except Exception: pass
    for t in ["left", "right", "middle"]:
        try: pyautogui.mouseUp(button=t)
        except Exception: pass


# ─── Coroutines ──────────────────────────────────────────────────────────────

async def kirim_screenshot(ws) -> None:
    interval = 1.0 / SCREENSHOT_FPS
    loop = asyncio.get_event_loop()

    while True:
        mulai = time.monotonic()
        try:
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
    async for pesan in ws:
        try:
            data = json.loads(pesan)
            tipe = data.get("type")
            if tipe == "input":  eksekusi_input(data)
            elif tipe == "ping": await ws.send(json.dumps({"type": "pong"}))
            else: log.debug("Pesan tidak dikenal: %s", tipe)
        except json.JSONDecodeError:
            log.warning("Pesan bukan JSON yang valid")
        except websockets.ConnectionClosed:
            break


async def jalankan_agent() -> None:
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
                log.info("Terhubung. Memulai stream %d FPS...", SCREENSHOT_FPS)
                lebar, tinggi = pyautogui.size()
                await ws.send(json.dumps({"type": "info", "width": lebar, "height": tinggi}))
                await asyncio.gather(kirim_screenshot(ws), terima_perintah(ws))
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


# ─── Entry point ─────────────────────────────────────────────────────────────

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
        if _camera is not None:
            try: _camera.stop()
            except Exception: pass