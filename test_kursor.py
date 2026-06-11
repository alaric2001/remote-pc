# test_kursor.py
import win32gui, win32ui, win32con
import numpy as np
from PIL import Image
import dxcam, time

camera = dxcam.create(output_color="BGR")
camera.start(target_fps=30)
time.sleep(0.5)

frame = camera.get_latest_frame()
print("Frame shape:", frame.shape)

# Cek cursor info
flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
print(f"Cursor flags={flags}, handle={hcursor}, pos=({cx},{cy})")

camera.stop()