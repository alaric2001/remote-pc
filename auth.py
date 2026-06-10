"""
auth.py — Logika autentikasi JWT.
Digunakan oleh server untuk memvalidasi token dari client browser.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

import config

log = logging.getLogger(__name__)


def buat_access_token(data: dict, expire_menit: Optional[int] = None) -> str:
    """
    Membuat JWT access token dari payload `data`.
    Token akan kedaluwarsa setelah `expire_menit` menit (default dari config).
    """
    payload = data.copy()
    durasi = expire_menit or config.JWT_EXPIRE_MINUTES
    kedaluwarsa = datetime.now(timezone.utc) + timedelta(minutes=durasi)
    payload.update({"exp": kedaluwarsa})

    token = jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
    return token


def verifikasi_token(token: str) -> Optional[dict]:
    """
    Memverifikasi dan mendekode JWT token.
    Mengembalikan payload dict jika valid, None jika tidak valid atau kedaluwarsa.
    """
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        log.warning("Token tidak valid: %s", e)
        return None


def verifikasi_agent_token(token: str) -> bool:
    """
    Memverifikasi token sederhana milik agent.
    Menggunakan perbandingan langsung dengan AGENT_TOKEN di config.
    """
    return token == config.AGENT_TOKEN
