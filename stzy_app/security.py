from __future__ import annotations

import json
from base64 import b64decode, b64encode
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


STZY_AES_KEY = "abADefg234cdegsd"


def encrypt_text(value: str) -> str:
    key = STZY_AES_KEY.encode()
    cipher = AES.new(key, AES.MODE_CBC, iv=key)
    return b64encode(cipher.encrypt(pad(value.encode(), AES.block_size))).decode()


def encrypt_json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return encrypt_text(payload)


def decrypt_text(value: str) -> str:
    key = STZY_AES_KEY.encode()
    cipher = AES.new(key, AES.MODE_CBC, iv=key)
    return unpad(cipher.decrypt(b64decode(value)), AES.block_size).decode()
