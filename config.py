"""
config.py — Konfigurasi terpusat aplikasi.
Semua nilai dibaca dari environment variable (.env).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# Agent
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")

# Screenshot
SCREENSHOT_FPS = int(os.getenv("SCREENSHOT_FPS", "10"))
SCREENSHOT_QUALITY = int(os.getenv("SCREENSHOT_QUALITY", "50"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "3"))
