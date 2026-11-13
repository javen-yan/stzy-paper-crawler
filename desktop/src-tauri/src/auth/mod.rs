use std::collections::BTreeMap;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use chrono::{Local, TimeZone};
use regex::Regex;
use serde_json::{json, Value};

use crate::crypto::stzy_encrypt_text;
use crate::error::{AppError, AppResult};
use crate::models::{now_iso_seconds, AccountCredential, AppSettings};

pub const COOKIE_TOKEN_CONSOLE_SCRIPT: &str = r#"(async () => {
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
})();"#;

#[derive(Debug, Clone)]
pub struct ParsedAuthImport {
    pub cookie: String,
    pub access_token: String,
    pub user_agent: String,
    pub request_headers: BTreeMap<String, String>,
    pub import_method: String,
}

pub fn token_from_cookie_header(cookie_header: &str) -> String {
    for pair in cookie_header.split(';') {
        if let Some((name, val)) = pair.trim().split_once('=') {
            if name.trim() == "ACCESS_TOKEN" && !val.trim().is_empty() {
                return val.trim().to_string();
            }
        }
    }
    String::new()
}

pub fn cookie_with_access_token(cookie: &str, token: &str) -> String {
    if token.is_empty() {
        return cookie.to_string();
    }
    let mut pairs: Vec<String> = cookie
        .split(';')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .collect();
    let mut updated = false;
    for pair in &mut pairs {
        if let Some((name, _)) = pair.split_once('=') {
            if name.trim() == "ACCESS_TOKEN" {
                *pair = format!("ACCESS_TOKEN={token}");
                updated = true;
                break;
            }
        }
    }
    if !updated {
        pairs.push(format!("ACCESS_TOKEN={token}"));
    }
    pairs.join("; ")
}

pub fn decode_jwt_payload(token: &str) -> Value {
    let parts: Vec<&str> = token.split('.').collect();
    if parts.len() < 3 {
        return json!({});
    }
    let payload_b64 = parts[1].trim_end_matches('=');
    let Ok(bytes) = URL_SAFE_NO_PAD.decode(payload_b64) else {
        return json!({});
    };
    serde_json::from_slice::<Value>(&bytes).unwrap_or_else(|_| json!({}))
}

pub fn token_expires_at(token: &str) -> Option<f64> {
    let data = decode_jwt_payload(token);
    data.get("exp").and_then(|v| {
        v.as_f64()
            .or_else(|| v.as_i64().map(|i| i as f64))
            .or_else(|| v.as_str().and_then(|s| s.parse::<f64>().ok()))
    })
}

pub fn account_label_from_auth(cookie_header: &str, access_token: &str) -> String {
    let token = if !access_token.is_empty() {
        access_token.to_string()
    } else {
        token_from_cookie_header(cookie_header)
    };
    let data = decode_jwt_payload(&token);
    for key in [
        "nickName", "nickname", "userName", "username", "mobile", "phone", "id",
    ] {
        if let Some(val) = data.get(key) {
            let text = match val {
                Value::String(s) => s.trim().to_string(),
                Value::Number(n) => n.to_string(),
                _ => String::new(),
            };
            if !text.is_empty() {
                return text;
            }
        }
    }
    String::new()
}

pub fn merge_auth_headers(
    headers: &BTreeMap<String, String>,
    token: &str,
    cookie: &str,
    user_agent: &str,
) -> BTreeMap<String, String> {
    let mut merged = BTreeMap::new();
    for (k, v) in headers {
        let lower = k.to_lowercase();
        if lower != "host" && lower != "content-length" && !v.is_empty() {
            merged.insert(lower, v.clone());
        }
    }
    if !token.is_empty() {
        merged.insert("token".to_string(), token.to_string());
    }
    if !cookie.is_empty() {
        merged.insert("cookie".to_string(), cookie.to_string());
    }
    if !user_agent.is_empty() {
        merged.insert("user-agent".to_string(), user_agent.to_string());
    }
    merged
        .entry("accept".to_string())
        .or_insert_with(|| "application/json, text/plain, */*".to_string());
    merged
        .entry("x-plat-type".to_string())
        .or_insert_with(|| "pt_stw".to_string());
    merged
}

pub fn parse_auth_import(raw_value: &str) -> AppResult<ParsedAuthImport> {
    let value = raw_value.trim();
    if value.is_empty() {
        return Err(AppError::Validation(
            "请粘贴 Network 复制的 fetch/cURL、Token 或 Cookie".to_string(),
        ));
    }

    let mut cookie = String::new();
    let mut token = String::new();
    let mut user_agent = String::new();
    let mut request_headers = BTreeMap::new();
    let mut import_method = "cookie".to_string();

    if value.starts_with('{') {
        let parsed: Value = serde_json::from_str(value)
            .map_err(|_| AppError::Validation("导入 JSON 格式不正确".to_string()))?;
        let Value::Object(map) = parsed else {
            return Err(AppError::Validation("导入 JSON 必须是对象格式".to_string()));
        };
        if let Some(h) = map.get("headers") {
            request_headers = normalized_header_map(h);
        }
        cookie = map
            .get("cookie")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .or_else(|| request_headers.get("cookie").cloned())
            .unwrap_or_default();
        user_agent = ["user_agent", "userAgent", "ua"]
            .iter()
            .find_map(|k| map.get(*k).and_then(Value::as_str))
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .or_else(|| request_headers.get("user-agent").cloned())
            .unwrap_or_default();
        let primary_token = ["access_token", "accessToken", "ACCESS_TOKEN", "token"]
            .iter()
            .find_map(|k| map.get(*k).and_then(Value::as_str))
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .or_else(|| request_headers.get("token").cloned())
            .unwrap_or_default();
        let mut candidates = vec![primary_token.clone()];
        if let Some(Value::Array(tokens)) = map.get("tokens") {
            for item in tokens {
                if let Value::Object(obj) = item {
                    if let Some(t) = obj
                        .get("access_token")
                        .or_else(|| obj.get("token"))
                        .and_then(Value::as_str)
                    {
                        candidates.push(t.trim().to_string());
                    }
                } else if let Some(s) = item.as_str() {
                    candidates.push(s.trim().to_string());
                }
            }
        }
        token = best_token(&candidates).unwrap_or(primary_token);
        import_method = map
            .get("import_method")
            .or_else(|| map.get("importMethod"))
            .and_then(Value::as_str)
            .unwrap_or("json")
            .to_string();
    } else if value.starts_with("fetch(") || value.starts_with("fetch ") {
        let (h, t, c, ua) = parse_fetch_import(value)?;
        request_headers = h;
        token = t;
        cookie = c;
        user_agent = ua;
        import_method = "network_fetch".to_string();
    } else if value.starts_with("curl") {
        let (h, t, c, ua) = parse_curl_import(value)?;
        request_headers = h;
        token = t;
        cookie = c;
        user_agent = ua;
        import_method = "network_curl".to_string();
    } else if looks_like_jwt(value) {
        token = value.to_string();
        import_method = "token".to_string();
    } else {
        cookie = value.to_string();
    }

    if token.is_empty() {
        token = token_from_cookie_header(&cookie);
    }
    if !token.is_empty() {
        cookie = cookie_with_access_token(&cookie, &token);
    }
    request_headers = merge_auth_headers(&request_headers, &token, &cookie, &user_agent);
    if user_agent.is_empty() {
        user_agent = request_headers
            .get("user-agent")
            .cloned()
            .unwrap_or_default();
    }

    Ok(ParsedAuthImport {
        cookie,
        access_token: token,
        user_agent,
        request_headers,
        import_method,
    })
}

fn looks_like_jwt(value: &str) -> bool {
    value.matches('.').count() >= 2 && !value.contains(' ') && !value.contains(';')
}

fn best_token(tokens: &[String]) -> Option<String> {
    tokens
        .iter()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .max_by(|a, b| {
            let ea = token_expires_at(a).unwrap_or(0.0);
            let eb = token_expires_at(b).unwrap_or(0.0);
            ea.partial_cmp(&eb).unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(ToString::to_string)
}

fn normalized_header_map(value: &Value) -> BTreeMap<String, String> {
    let Value::Object(map) = value else {
        return BTreeMap::new();
    };
    let mut out = BTreeMap::new();
    for (k, v) in map {
        if let Some(s) = v.as_str() {
            out.insert(k.trim().to_lowercase(), s.trim().to_string());
        } else if !v.is_null() {
            out.insert(k.trim().to_lowercase(), v.to_string());
        }
    }
    out
}

fn parse_fetch_import(value: &str) -> AppResult<(BTreeMap<String, String>, String, String, String)> {
    let options_text = extract_fetch_options(value);
    if options_text.is_empty() {
        return Err(AppError::Validation(
            "没有识别到 fetch 请求配置，请复制完整 fetch(...)".to_string(),
        ));
    }
    let options: Value = serde_json::from_str(&options_text).map_err(|_| {
        AppError::Validation("fetch 内容不是 DevTools 默认 JSON 格式，请改用复制 cURL".to_string())
    })?;
    let Value::Object(map) = options else {
        return Err(AppError::Validation("fetch 请求配置格式不正确".to_string()));
    };
    let mut headers = map
        .get("headers")
        .map(normalized_header_map)
        .unwrap_or_default();
    if let Some(referrer) = map.get("referrer").and_then(Value::as_str) {
        let r = referrer.trim();
        if !r.is_empty() && !headers.contains_key("referer") {
            headers.insert("referer".to_string(), r.to_string());
        }
    }
    let token = headers.get("token").cloned().unwrap_or_default();
    let cookie = headers.get("cookie").cloned().unwrap_or_default();
    let user_agent = headers.get("user-agent").cloned().unwrap_or_default();
    Ok((headers, token, cookie, user_agent))
}

fn extract_fetch_options(value: &str) -> String {
    let re = Regex::new(r#"(?s)fetch\s*\(\s*(?:['"](?:\\.|[^'"])*['"])\s*,"#).unwrap();
    let Some(m) = re.find(value) else {
        return String::new();
    };
    let rest = &value[m.end()..];
    let Some(rel_start) = rest.find('{') else {
        return String::new();
    };
    let abs_start = m.end() + rel_start;
    if let Some(abs_end) = find_matching_brace(value, abs_start) {
        value[abs_start..=abs_end].to_string()
    } else {
        String::new()
    }
}

fn find_matching_brace(value: &str, start: usize) -> Option<usize> {
    let mut depth = 0usize;
    let mut quote: Option<char> = None;
    let mut escaped = false;
    for (offset, ch) in value[start..].char_indices() {
        if let Some(q) = quote {
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == q {
                quote = None;
            }
            continue;
        }
        match ch {
            '\'' | '"' => quote = Some(ch),
            '{' => depth += 1,
            '}' => {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    return Some(start + offset);
                }
            }
            _ => {}
        }
    }
    None
}

fn parse_curl_import(value: &str) -> AppResult<(BTreeMap<String, String>, String, String, String)> {
    let normalized = value.replace("\\\r\n", " ").replace("\\\n", " ");
    let parts = shlex::split(&normalized)
        .ok_or_else(|| AppError::Validation("cURL 格式解析失败，请重新复制完整 cURL".to_string()))?;
    if parts.first().map(String::as_str) != Some("curl") {
        return Err(AppError::Validation("请粘贴以 curl 开头的请求".to_string()));
    }
    let mut headers = BTreeMap::new();
    let mut idx = 1;
    while idx < parts.len() {
        let part = &parts[idx];
        if (part == "-H" || part == "--header") && idx + 1 < parts.len() {
            add_header_line(&mut headers, &parts[idx + 1]);
            idx += 2;
            continue;
        }
        if part.starts_with("-H") && part.len() > 2 {
            add_header_line(&mut headers, part[2..].trim());
        } else if (part == "-b" || part == "--cookie") && idx + 1 < parts.len() {
            headers.insert("cookie".to_string(), parts[idx + 1].trim().to_string());
            idx += 2;
            continue;
        }
        idx += 1;
    }
    let token = headers.get("token").cloned().unwrap_or_default();
    let cookie = headers.get("cookie").cloned().unwrap_or_default();
    let user_agent = headers.get("user-agent").cloned().unwrap_or_default();
    Ok((headers, token, cookie, user_agent))
}

fn add_header_line(headers: &mut BTreeMap<String, String>, line: &str) {
    if let Some((name, val)) = line.split_once(':') {
        let key = name.trim().to_lowercase();
        if !key.is_empty() {
            headers.insert(key, val.trim().to_string());
        }
    }
}

pub fn format_expiry_error_if_expired(token: &str) -> Option<String> {
    let exp = token_expires_at(token)?;
    let now = crate::proxy::now_unix_secs();
    if exp <= now + 60.0 {
        let formatted = Local
            .timestamp_opt(exp as i64, 0)
            .single()
            .map(|dt| dt.format("%Y-%m-%d %H:%M:%S").to_string())
            .unwrap_or_else(|| exp.to_string());
        Some(formatted)
    } else {
        None
    }
}

/// Normalizes phone & builds the encrypted `/zw-auth/oauth/passwordLogin` request body.
pub fn build_phone_login_payload(phone: &str, password: Option<&str>) -> AppResult<(String, String, Value)> {
    let digits: String = phone.trim().chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 11 {
        return Err(AppError::Validation("请输入 11 位手机号".to_string()));
    }
    let login_password = password
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .unwrap_or_else(|| digits[digits.len() - 6..].to_string());
    if login_password.is_empty() {
        return Err(AppError::Validation("请输入密码".to_string()));
    }
    let body = json!({
        "loginName": stzy_encrypt_text(&digits),
        "password": stzy_encrypt_text(&login_password),
    });
    Ok((digits, login_password, body))
}

pub fn account_from_phone_login_response(
    settings: &AppSettings,
    normalized_phone: &str,
    login_password: &str,
    response: &Value,
    custom_name: &str,
) -> AppResult<AccountCredential> {
    let data = response.get("data").unwrap_or(&Value::Null);
    let access_token = ["access_token", "accessToken", "token"]
        .iter()
        .find_map(|k| data.get(*k).and_then(Value::as_str))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| AppError::Runtime("登录成功但没有返回 Access Token".to_string()))?
        .to_string();

    let label = {
        let extracted = account_label_from_auth("", &access_token);
        if extracted.is_empty() {
            normalized_phone.to_string()
        } else {
            extracted
        }
    };
    let name = if !custom_name.trim().is_empty() {
        custom_name.trim().to_string()
    } else {
        format!("手机号登录-{label}")
    };
    let cookie = format!("ACCESS_TOKEN={access_token}");
    let headers = merge_auth_headers(&BTreeMap::new(), &access_token, &cookie, &settings.user_agent);
    Ok(AccountCredential {
        name,
        cookie,
        access_token,
        user_agent: settings.user_agent.clone(),
        request_headers_json: serde_json::to_string(&headers)?,
        import_method: "phone".to_string(),
        login_phone: normalized_phone.to_string(),
        login_password: login_password.to_string(),
        enabled: true,
        last_checked_at: now_iso_seconds(),
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn phone_login_defaults_to_last_six_digits() {
        let (phone, pwd, body) = build_phone_login_payload("138-0013-8000", None).unwrap();
        assert_eq!(phone, "13800138000");
        assert_eq!(pwd, "138000");
        assert_eq!(body["loginName"], "9qchlnGbOxhfx8VWjQbrSA==");
        assert_eq!(body["password"], "cmB2QaDtXxqsqwP+T3WfKg==");
    }

    #[test]
    fn curl_and_fetch_imports_extract_tokens_and_headers() {
        let curl = r#"curl 'https://qms.stzy.com/matrix/zw-zzw/api/v1/zzw/user/detail' \
          -H 'token: eyJhbGciOiJIUzI1NiJ9.eyJuaWNrTmFtZSI6IuW8oOS4iSIsImV4cCI6NDA3MDkwODgwMH0.sig' \
          -H 'user-agent: CustomUA/1.0'"#;
        let parsed = parse_auth_import(curl).unwrap();
        assert_eq!(parsed.import_method, "network_curl");
        assert!(parsed.cookie.contains("ACCESS_TOKEN=eyJhbGciOiJIUzI1NiJ9"));
        assert_eq!(parsed.user_agent, "CustomUA/1.0");
        assert_eq!(account_label_from_auth("", &parsed.access_token), "张三");

        let fetch_str = r#"fetch("https://qms.stzy.com/matrix/api", {
          "headers": {
            "token": "eyJhbGciOiJIUzI1NiJ9.eyJtb2JpbGUiOiIxMzgwMDEzODAwMCIsImV4cCI6NDA3MDkwODgwMH0.sig"
          },
          "referrer": "https://www.stzy.com/layout/paper-lib"
        });"#;
        let parsed_fetch = parse_auth_import(fetch_str).unwrap();
        assert_eq!(parsed_fetch.import_method, "network_fetch");
        assert_eq!(
            parsed_fetch.request_headers.get("referer").map(String::as_str),
            Some("https://www.stzy.com/layout/paper-lib")
        );
        assert_eq!(account_label_from_auth("", &parsed_fetch.access_token), "13800138000");
    }
}
