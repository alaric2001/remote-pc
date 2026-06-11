# test_kursor5.py
import win32gui, win32ui, win32con
import numpy as np
from PIL import Image
import dxcam, time

camera = dxcam.create(output_color="RGB")
camera.start(target_fps=30)
time.sleep(0.5)

frame = camera.get_latest_frame().copy()
img_layar = Image.fromarray(frame)

flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
print(f"Kursor di ({cx},{cy})")

# Render kursor ke bitmap kecil 32x32
hdc_screen = win32gui.GetDC(0)
dc_src     = win32ui.CreateDCFromHandle(hdc_screen)
cursor_dc  = dc_src.CreateCompatibleDC()
cursor_bmp = win32ui.CreateBitmap()
cursor_bmp.CreateCompatibleBitmap(dc_src, 32, 32)
cursor_dc.SelectObject(cursor_bmp)

# Background hitam agar bisa dijadikan mask
cursor_dc.FillSolidRect((0, 0, 32, 32), 0x000000)
win32gui.DrawIconEx(cursor_dc.GetSafeHdc(), 0, 0, hcursor, 32, 32, 0, None, win32con.DI_NORMAL)

bits = cursor_bmp.GetBitmapBits(True)
arr  = np.frombuffer(bits, dtype=np.uint8).reshape(32, 32, 4)
# BGRX → RGBA
kursor_rgba = np.zeros((32, 32, 4), dtype=np.uint8)
kursor_rgba[:, :, 0] = arr[:, :, 2]  # R
kursor_rgba[:, :, 1] = arr[:, :, 1]  # G
kursor_rgba[:, :, 2] = arr[:, :, 0]  # B
# Pixel hitam = transparan, sisanya opak
mask = (arr[:, :, 0] > 10) | (arr[:, :, 1] > 10) | (arr[:, :, 2] > 10)
kursor_rgba[:, :, 3] = np.where(mask, 255, 0)

img_kursor = Image.fromarray(kursor_rgba, "RGBA")

# Tempel ke frame layar
img_layar = img_layar.convert("RGBA")
img_layar.paste(img_kursor, (cx, cy), img_kursor)
img_layar = img_layar.convert("RGB")
img_layar.save("hasil_dengan_kursor.png")

cursor_dc.DeleteDC()
dc_src.DeleteDC()
win32gui.ReleaseDC(0, hdc_screen)
win32gui.DeleteObject(cursor_bmp.GetHandle())
camera.stop()

print("Cek hasil_dengan_kursor.png")