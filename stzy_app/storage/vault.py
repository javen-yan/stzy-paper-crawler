from __future__ import annotations

import base64
import os
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

PREFIX = "enc:v1:"


class CredentialVault:
    def __init__(self, key_path: Path, *, env_key: str = "") -> None:
        self.key_path = key_path
        self.key = self._load_key(env_key)

    def encrypt(self, value: str) -> str:
        if not value or value.startswith(PREFIX):
            return value
        nonce = get_random_bytes(12)
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(value.encode("utf-8"))
        packed = nonce + tag + ciphertext
        return PREFIX + base64.urlsafe_b64encode(packed).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value or not value.startswith(PREFIX):
            return value
        packed = base64.urlsafe_b64decode(value[len(PREFIX) :].encode("ascii"))
        nonce = packed[:12]
        tag = packed[12:28]
        ciphertext = packed[28:]
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")

    def _load_key(self, env_key: str) -> bytes:
        if env_key:
            decoded = base64.urlsafe_b64decode(env_key.encode("ascii"))
            if len(decoded) != 32:
                raise ValueError("STZY_SECRET_KEY must decode to 32 bytes")
            return decoded
        if self.key_path.exists():
            data = base64.urlsafe_b64decode(self.key_path.read_text(encoding="utf-8").strip())
            if len(data) == 32:
                return data
        key = get_random_bytes(32)
        self.key_path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key
