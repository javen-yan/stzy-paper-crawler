from __future__ import annotations

import json
import re
import shlex
from datetime import datetime
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.http import StzyHttpClient
from stzy_app.security import encrypt_text
from stzy_app.storage import AccountCredential


COOKIE_TOKEN_CONSOLE_SCRIPT = r"""(async () => {
  const tokenKeys = ['ACCESS_TOKEN', 'access-token', 'accessToken', 'token'];
  const decodeExp = token => {
    try {
      const payload = token.split('.')[1];
      return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/'))).exp || 0;
    } catch (e) {
      return 0;
    }
  };
  const candidates = [];
  for (const storage of [localStorage, sessionStorage]) {
    for (const key of tokenKeys) {
      const value = storage.getItem(key);
      if (value) candidates.push({ source: key, access_token: value, exp: decodeExp(value) });
    }
  }
  (document.cookie || '')
    .split(';')
    .map(v => v.trim())
    .filter(v => v.startsWith('ACCESS_TOKEN='))
    .forEach(v => {
      const token = v.split('=').slice(1).join('=');
      candidates.push({ source: 'cookie.ACCESS_TOKEN', access_token: token, exp: decodeExp(token) });
    });
  const unique = Object.values(Object.fromEntries(candidates.map(item => [item.access_token, item])));
  unique.sort((a, b) => (b.exp || 0) - (a.exp || 0));
  const result = {
    access_token: unique[0]?.access_token || '',
    exp: unique[0]?.exp || null,
    source: unique[0]?.source || '',
    cookie: document.cookie || '',
    user_agent: navigator.userAgent || '',
    tokens: unique,
    api_check: null,
  };
  if (result.access_token) {
    try {
      const response = await fetch('https://qms.stzy.com/matrix/zw-zzw/api/v1/zzw/user/detail', {
        method: 'GET',
        headers: {
          token: result.access_token,
          'X-Plat-Type': 'pt_stw',
          accept: 'application/json, text/plain, */*',
        },
      });
      const data = await response.json();
      result.api_check = {
        ok: data?.code === 200 || data?.code === '200',
        code: data?.code ?? null,
        message: data?.message || '',
        user: data?.data?.nickName || data?.data?.phone || data?.data?.id || '',
      };
    } catch (e) {
      result.api_check = { ok: false, code: 'NETWORK', message: String(e), user: '' };
    }
  }
  console.log(JSON.stringify(result, null, 2));
  copy(JSON.stringify(result, null, 2));
  alert(result.api_check?.ok
    ? 'Token 已通过官网接口验证并复制，请粘贴到 STZY Paper Crawler。'
    : 'Token 已复制，但官网接口验证未通过；请重新登录网页后再复制。');
})();"""


def credential_from_auth_import(
    raw_value: str,
    *,
    name: str = "",
    enabled: bool = True,
    settings: AppSettings | None = None,
) -> AccountCredential:
    parsed_auth = parse_auth_import(raw_value)
    if settings and parsed_auth["cookie"] and not parsed_auth["access_token"]:
        account = AccountCredential(
            name="probe",
            cookie=parsed_auth["cookie"],
            user_agent=parsed_auth["user_agent"],
            request_headers_json=json.dumps(
                parsed_auth["request_headers"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        if StzyHttpClient(settings).refresh_account_from_cookie(account, persist=False):
            parsed_auth["cookie"] = account.cookie
            parsed_auth["access_token"] = account.access_token
            parsed_auth["request_headers"] = account.request_headers
    validation_error = auth_validation_error(
        parsed_auth["cookie"],
        parsed_auth["access_token"],
        user_agent=parsed_auth["user_agent"],
        request_headers=parsed_auth["request_headers"],
        settings=settings,
    )
    if validation_error:
        raise ValueError(validation_error)

    label = name.strip() or StzyHttpClient.account_label_from_auth(
        cookie_header=parsed_auth["cookie"],
        access_token=parsed_auth["access_token"],
    )
    if not label:
        label = "手动导入账号"

    return AccountCredential(
        name=label,
        cookie=parsed_auth["cookie"],
        access_token=parsed_auth["access_token"],
        user_agent=parsed_auth["user_agent"],
        request_headers_json=json.dumps(
            parsed_auth["request_headers"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        import_method=parsed_auth["import_method"],
        enabled=enabled,
        last_checked_at=datetime.now().isoformat(timespec="seconds"),
    )


def normalize_auth_import(raw_value: str) -> tuple[str, str, str]:
    parsed = parse_auth_import(raw_value)
    return parsed["cookie"], parsed["access_token"], parsed["user_agent"]


def parse_auth_import(raw_value: str) -> dict[str, Any]:
    value = raw_value.strip()
    if not value:
        raise ValueError("请粘贴 Network 复制的 fetch/cURL、Token 或 Cookie")

    cookie = ""
    token = ""
    user_agent = ""
    request_headers: dict[str, str] = {}
    import_method = "cookie"
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("导入 JSON 格式不正确") from exc
        if not isinstance(parsed, dict):
            raise ValueError("导入 JSON 必须是对象格式")
        request_headers = normalized_header_map(parsed.get("headers") or {})
        cookie = str(parsed.get("cookie") or request_headers.get("cookie") or "").strip()
        user_agent = str(
            parsed.get("user_agent")
            or parsed.get("userAgent")
            or parsed.get("ua")
            or request_headers.get("user-agent")
            or ""
        ).strip()
        token = str(
            parsed.get("access_token")
            or parsed.get("accessToken")
            or parsed.get("ACCESS_TOKEN")
            or parsed.get("token")
            or request_headers.get("token")
            or ""
        ).strip()
        token = best_token([token, *tokens_from_json(parsed)]) or token
        import_method = str(parsed.get("import_method") or parsed.get("importMethod") or "json")
    elif value.lstrip().startswith("fetch("):
        request_headers, token, cookie, user_agent = parse_fetch_import(value)
        import_method = "network_fetch"
    elif value.lstrip().startswith("curl"):
        request_headers, token, cookie, user_agent = parse_curl_import(value)
        import_method = "network_curl"
    elif _looks_like_jwt(value):
        token = value
        import_method = "token"
    else:
        cookie = value

    token = token or StzyHttpClient._token_from_cookie_header(cookie)
    if token:
        cookie = cookie_with_access_token(cookie, token)
    request_headers = merge_auth_headers(
        request_headers,
        token=token,
        cookie=cookie,
        user_agent=user_agent,
    )
    user_agent = user_agent or request_headers.get("user-agent", "")
    return {
        "cookie": cookie,
        "access_token": token,
        "user_agent": user_agent,
        "request_headers": request_headers,
        "import_method": import_method,
    }


def parse_fetch_import(value: str) -> tuple[dict[str, str], str, str, str]:
    options_text = extract_fetch_options(value)
    if not options_text:
        raise ValueError("没有识别到 fetch 请求配置，请复制完整 fetch(...)")
    try:
        options = json.loads(options_text)
    except json.JSONDecodeError as exc:
        raise ValueError("fetch 内容不是 DevTools 默认 JSON 格式，请改用复制 cURL") from exc
    if not isinstance(options, dict):
        raise ValueError("fetch 请求配置格式不正确")
    headers = normalized_header_map(options.get("headers") or {})
    token = headers.get("token", "")
    cookie = headers.get("cookie", "")
    user_agent = headers.get("user-agent", "")
    referrer = str(options.get("referrer") or "").strip()
    if referrer and "referer" not in headers:
        headers["referer"] = referrer
    return headers, token, cookie, user_agent


def extract_fetch_options(value: str) -> str:
    match = re.search(r"fetch\s*\(\s*(['\"])(?:\\.|(?!\1).)*\1\s*,", value, re.S)
    if not match:
        return ""
    start = value.find("{", match.end())
    if start < 0:
        return ""
    end = find_matching_brace(value, start)
    return value[start : end + 1] if end >= 0 else ""


def find_matching_brace(value: str, start: int) -> int:
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(value)):
        char = value[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def parse_curl_import(value: str) -> tuple[dict[str, str], str, str, str]:
    try:
        parts = shlex.split(value.replace("\\\n", " "), posix=True)
    except ValueError as exc:
        raise ValueError("cURL 格式解析失败，请重新复制完整 cURL") from exc
    if not parts or parts[0] != "curl":
        raise ValueError("请粘贴以 curl 开头的请求")
    headers: dict[str, str] = {}
    index = 1
    while index < len(parts):
        part = parts[index]
        if part in {"-H", "--header"} and index + 1 < len(parts):
            add_header(headers, parts[index + 1])
            index += 2
            continue
        if part.startswith("-H") and len(part) > 2:
            add_header(headers, part[2:].strip())
        index += 1
    token = headers.get("token", "")
    cookie = headers.get("cookie", "")
    user_agent = headers.get("user-agent", "")
    return headers, token, cookie, user_agent


def add_header(headers: dict[str, str], header_line: str) -> None:
    if ":" not in header_line:
        return
    name, value = header_line.split(":", 1)
    name = name.strip().lower()
    value = value.strip()
    if name:
        headers[name] = value


def normalized_header_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    headers = {}
    for key, item in value.items():
        if item is None:
            continue
        headers[str(key).strip().lower()] = str(item).strip()
    return headers


def merge_auth_headers(
    headers: dict[str, str],
    *,
    token: str,
    cookie: str,
    user_agent: str,
) -> dict[str, str]:
    merged = {
        key: value
        for key, value in headers.items()
        if key not in {"host", "content-length"} and value
    }
    if token:
        merged["token"] = token
    if cookie:
        merged["cookie"] = cookie
    if user_agent:
        merged["user-agent"] = user_agent
    merged.setdefault("accept", "application/json, text/plain, */*")
    merged.setdefault("x-plat-type", "pt_stw")
    return merged


def cookie_with_access_token(cookie: str, token: str) -> str:
    if not token:
        return cookie
    pairs = [pair.strip() for pair in cookie.split(";") if pair.strip()]
    updated = False
    for index, pair in enumerate(pairs):
        if "=" not in pair:
            continue
        name, _value = pair.split("=", 1)
        if name.strip() == "ACCESS_TOKEN":
            pairs[index] = f"ACCESS_TOKEN={token}"
            updated = True
            break
    if not updated:
        pairs.append(f"ACCESS_TOKEN={token}")
    return "; ".join(pairs)


def best_token(tokens: list[str]) -> str:
    valid_tokens = [token.strip() for token in tokens if token and token.strip()]
    if not valid_tokens:
        return ""

    def sort_key(token: str) -> float:
        return StzyHttpClient.token_expires_at(token) or 0

    return max(valid_tokens, key=sort_key)


def tokens_from_json(parsed: dict[str, object]) -> list[str]:
    tokens = parsed.get("tokens")
    if not isinstance(tokens, list):
        return []
    values = []
    for item in tokens:
        if isinstance(item, dict):
            values.append(str(item.get("access_token") or item.get("token") or ""))
        else:
            values.append(str(item or ""))
    return values


def auth_validation_error(
    cookie: str,
    token: str,
    *,
    user_agent: str = "",
    request_headers: dict[str, str] | None = None,
    settings: AppSettings | None = None,
) -> str:
    if not token and not StzyHttpClient._token_from_cookie_header(cookie):
        return "没有识别到 Token，请重新复制网页 Console 脚本输出"

    access_token = token or StzyHttpClient._token_from_cookie_header(cookie)
    expires_at = StzyHttpClient.token_expires_at(access_token)
    expires_text = ""
    if expires_at is None:
        expires_text = ""
    elif expires_at <= datetime.now().timestamp() + 60:
        expires_text = datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M:%S")
    if settings:
        try:
            StzyHttpClient(settings).probe_auth(
                cookie_header=cookie,
                access_token=token,
                user_agent=user_agent,
                request_headers=request_headers or {},
            )
            return ""
        except Exception as exc:  # noqa: BLE001
            if expires_text:
                return f"Token 已于 {expires_text} 过期，官网用户信息接口也验证失败；请重新登录网页后再复制"
            return f"官网用户信息接口验证失败：{exc}"
    if expires_at is not None and expires_at <= datetime.now().timestamp() + 60:
        return f"Token 已于 {expires_text} 过期，请重新登录网页后再复制"
    return ""


def _looks_like_jwt(value: str) -> bool:
    return value.count(".") >= 2 and " " not in value and ";" not in value


def login_with_phone_password(
    settings: AppSettings,
    phone: str,
    password: str | None = None,
) -> AccountCredential:
    normalized_phone = "".join(ch for ch in phone.strip() if ch.isdigit())
    if len(normalized_phone) != 11:
        raise ValueError("请输入 11 位手机号")

    login_password = (password or "").strip() or normalized_phone[-6:]
    if not login_password:
        raise ValueError("请输入密码")

    client = StzyHttpClient(settings)
    response = client.post_json(
        "/zw-auth/oauth/passwordLogin",
        {
            "loginName": encrypt_text(normalized_phone),
            "password": encrypt_text(login_password),
        },
        headers={},
    )
    data = response.get("data") or {}
    access_token = str(data.get("access_token") or data.get("accessToken") or data.get("token") or "")
    if not access_token:
        raise RuntimeError("登录成功但没有返回 Access Token")

    label = StzyHttpClient.account_label_from_auth(access_token=access_token) or normalized_phone
    cookie = f"ACCESS_TOKEN={access_token}"
    request_headers = merge_auth_headers(
        {},
        token=access_token,
        cookie=cookie,
        user_agent=settings.user_agent,
    )
    return AccountCredential(
        name=f"手机号登录-{label}",
        cookie=cookie,
        access_token=access_token,
        user_agent=settings.user_agent,
        request_headers_json=json.dumps(request_headers, ensure_ascii=False, sort_keys=True),
        import_method="phone",
        login_phone=normalized_phone,
        login_password=login_password,
        enabled=True,
        last_checked_at=datetime.now().isoformat(timespec="seconds"),
    )
