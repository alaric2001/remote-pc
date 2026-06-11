import time
from PIL import Image
import win32gui, win32ui, win32con
import pyautogui, io, base64

lebar, tinggi = pyautogui.size()

# Test 1: Seberapa cepat capture saja
t = time.monotonic()
for _ in range(30):
    hdesktop = win32gui.GetDesktopWindow()
    hdc = win32gui.GetWindowDC(hdesktop)
    dc_obj = win32ui.CreateDCFromHandle(hdc)
    mem_dc = dc_obj.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(dc_obj, lebar, tinggi)
    mem_dc.SelectObject(bitmap)
    mem_dc.BitBlt((0,0),(lebar,tinggi),dc_obj,(0,0),win32con.SRCCOPY)
    bmp_str = bitmap.GetBitmapBits(True)
    mem_dc.DeleteDC(); dc_obj.DeleteDC()
    win32gui.ReleaseDC(hdesktop, hdc)
    win32gui.DeleteObject(bitmap.GetHandle())
print(f"Capture: {30/(time.monotonic()-t):.1f} fps max")

# Test 2: Capture + compress JPEG
t = time.monotonic()
for _ in range(30):
    img = Image.frombuffer("RGB",(lebar,tinggi),bmp_str,"raw","BGRX",0,1)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=35, optimize=True)
    base64.b64encode(buf.getvalue())
print(f"Capture+compress+encode: {30/(time.monotonic()-t):.1f} fps max")