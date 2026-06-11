# test_kursor2.py
import win32gui, win32ui, win32con
import numpy as np
from PIL import Image
import dxcam, time

camera = dxcam.create(output_color="BGR")
camera.start(target_fps=30)
time.sleep(0.5)

frame = camera.get_latest_frame().copy()
tinggi, lebar = frame.shape[:2]

flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
print(f"Sebelum: pixel di kursor = {frame[cy, cx]}")

# Gambar kursor
hdc_screen = win32gui.GetDC(0)
dc_src     = win32ui.CreateDCFromHandle(hdc_screen)
mem_dc     = dc_src.CreateCompatibleDC()
bitmap     = win32ui.CreateBitmap()
bitmap.CreateCompatibleBitmap(dc_src, lebar, tinggi)
mem_dc.SelectObject(bitmap)

import ctypes
flipped = frame[::-1].tobytes()
ctypes.windll.gdi32.SetBitmapBits(bitmap.GetHandle(), len(flipped), flipped)

win32gui.DrawIconEx(mem_dc.GetSafeHdc(), cx, cy, hcursor, 0, 0, 0, None, win32con.DI_NORMAL)

hasil_bits = bitmap.GetBitmapBits(True)
hasil = np.frombuffer(hasil_bits, dtype=np.uint8).reshape(tinggi, lebar, 4)
frame_hasil = hasil[::-1, :, :3]

print(f"Sesudah: pixel di kursor = {frame_hasil[cy, cx]}")

# Simpan untuk cek visual
img_sebelum = Image.fromarray(frame[:, :, ::-1])
img_sesudah = Image.fromarray(frame_hasil[:, :, ::-1])
img_sebelum.save("sebelum.png")
img_sesudah.save("sesudah.png")

print("Tersimpan: sebelum.png dan sesudah.png")
print("Cek apakah kursor muncul di sesudah.png")

camera.stop()