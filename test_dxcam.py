# test_dxcam.py
import dxcam, time, io, base64
from PIL import Image

camera = dxcam.create(output_color="RGB")
camera.start(target_fps=60)

time.sleep(0.5)  # warmup

t = time.monotonic()
count = 0
while time.monotonic() - t < 3:
    frame = camera.get_latest_frame()
    if frame is not None:
        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=35)
        base64.b64encode(buf.getvalue())
        count += 1

camera.stop()
print(f"dxcam fps: {count/3:.1f} fps")