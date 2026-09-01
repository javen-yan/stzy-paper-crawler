from __future__ import annotations

import base64
import json
import time
import unittest

from stzy_app.http.client import StzyHttpClient


class HttpClientAuthTest(unittest.TestCase):
    def test_expired_jwt_is_not_valid(self) -> None:
        token = self._jwt({"exp": time.time() - 60})

        self.assertFalse(StzyHttpClient.auth_is_valid(access_token=token))

    def test_future_jwt_reports_expiration(self) -> None:
        expires_at = time.time() + 3600
        token = self._jwt({"exp": expires_at})

        self.assertTrue(StzyHttpClient.auth_is_valid(access_token=token))
        self.assertAlmostEqual(StzyHttpClient.auth_expires_at(access_token=token), expires_at)

    @staticmethod
    def _jwt(payload: dict[str, object]) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{encoded}.signature"
