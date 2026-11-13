use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use futures_util::StreamExt;
use parking_lot::Mutex;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use serde_json::Value;
use tokio::io::AsyncWriteExt;
use tokio_util::sync::CancellationToken;

use crate::auth::{
    account_from_phone_login_response, account_label_from_auth, build_phone_login_payload,
    format_expiry_error_if_expired, parse_auth_import, token_from_cookie_header,
};
use crate::error::{AppError, AppResult};
use crate::models::{now_iso_seconds, AccountCredential, AppSettings};
use crate::proxy::ProxyPool;
use crate::store::SqliteStore;

#[derive(Clone)]
pub struct StzyHttpClient {
    pub settings: AppSettings,
    pub store: SqliteStore,
    pub proxy_pool: Arc<ProxyPool>,
    pub cancel: CancellationToken,
    clients: Arc<Mutex<HashMap<String, reqwest::Client>>>,
    on_proxy: Arc<dyn Fn(String) + Send + Sync>,
}

impl StzyHttpClient {
    pub fn new(
        settings: AppSettings,
        store: SqliteStore,
        proxy_pool: Option<Arc<ProxyPool>>,
        cancel: Option<CancellationToken>,
        on_proxy: Option<Arc<dyn Fn(String) + Send + Sync>>,
    ) -> Self {
        let pool = proxy_pool.unwrap_or_else(|| ProxyPool::new(settings.clone(), None));
        Self {
            settings,
            store,
            proxy_pool: pool,
            cancel: cancel.unwrap_or_default(),
            clients: Arc::new(Mutex::new(HashMap::new())),
            on_proxy: on_proxy.unwrap_or_else(|| Arc::new(|_| {})),
        }
    }

    fn client_for_proxy(&self, proxy_url: &str) -> AppResult<reqwest::Client> {
        {
            let map = self.clients.lock();
            if let Some(existing) = map.get(proxy_url) {
                return Ok(existing.clone());
            }
        }
        let connect_dur = Duration::from_secs_f64(self.settings.connect_timeout.max(1.0));
        let total_dur =
            Duration::from_secs_f64((self.settings.connect_timeout + self.settings.read_timeout).max(3.0));
        let mut builder = reqwest::Client::builder()
            .connect_timeout(connect_dur)
            .timeout(total_dur)
            .pool_max_idle_per_host(8);
        if proxy_url.is_empty() {
            builder = builder.no_proxy();
        } else {
            let proxy = reqwest::Proxy::all(proxy_url)
                .map_err(|e| AppError::Validation(format!("代理地址格式不合法 ({proxy_url}): {e}")))?;
            builder = builder.proxy(proxy);
        }
        let client = builder.build()?;
        self.clients
            .lock()
            .insert(proxy_url.to_string(), client.clone());
        Ok(client)
    }

    pub fn base_headers(&self) -> BTreeMap<String, String> {
        BTreeMap::from([
            (
                "accept".to_string(),
                "application/json, text/plain, */*".to_string(),
            ),
            ("content-type".to_string(), "application/json".to_string()),
            ("origin".to_string(), self.settings.site_base_url.clone()),
            (
                "referer".to_string(),
                format!("{}/layout/paper-lib", self.settings.site_base_url),
            ),
            ("user-agent".to_string(), self.settings.user_agent.clone()),
            ("x-plat-type".to_string(), "pt_stw".to_string()),
        ])
    }

    pub fn headers_for_account(&self, account: &AccountCredential) -> BTreeMap<String, String> {
        let mut headers = BTreeMap::new();
        for (k, v) in account.request_headers() {
            if k != "host" && k != "content-length" && !v.is_empty() {
                headers.insert(k, v);
            }
        }
        let token = if !account.access_token.is_empty() {
            account.access_token.clone()
        } else {
            token_from_cookie_header(&account.cookie)
        };
        if !token.is_empty() {
            headers.insert("token".to_string(), token);
        }
        if !account.cookie.is_empty() {
            headers.insert("cookie".to_string(), account.cookie.clone());
        }
        if !account.user_agent.is_empty() {
            headers.insert("user-agent".to_string(), account.user_agent.clone());
        }
        headers
    }

    pub async fn default_auth_headers(&self) -> AppResult<BTreeMap<String, String>> {
        let schedulable = self.store.schedulable_accounts()?;
        if !schedulable.is_empty() {
            if let Some(acc) = self.store.next_round_robin_account(|_| true)? {
                if let Some(valid_acc) = self.ensure_account_valid(acc).await {
                    return Ok(self.headers_for_account(&valid_acc));
                }
            }
            for acc in schedulable {
                if let Some(valid_acc) = self.ensure_account_valid(acc).await {
                    return Ok(self.headers_for_account(&valid_acc));
                }
            }
        }
        Ok(BTreeMap::new())
    }

    pub fn enabled_account_names(&self) -> Vec<String> {
        self.store
            .schedulable_accounts()
            .map(|list| list.into_iter().map(|a| a.name).collect())
            .unwrap_or_default()
    }

    pub async fn enabled_valid_accounts(&self) -> AppResult<Vec<AccountCredential>> {
        let candidates = self.store.schedulable_accounts()?;
        let mut out = Vec::new();
        for acc in candidates {
            if let Some(valid) = self.ensure_account_valid(acc).await {
                out.push(valid);
            }
        }
        Ok(out)
    }

    pub async fn ensure_account_valid(
        &self,
        mut account: AccountCredential,
    ) -> Option<AccountCredential> {
        let has_token = !account.access_token.is_empty()
            || !token_from_cookie_header(&account.cookie).is_empty();
        if has_token
            && self
                .probe_auth(
                    &account.cookie,
                    &account.access_token,
                    &account.user_agent,
                    &account.request_headers(),
                )
                .await
                .is_ok()
        {
            return Some(account);
        }
        if self.refresh_account_from_cookie(&mut account, true).await {
            return Some(account);
        }
        if account.login_phone.is_empty() {
            return None;
        }
        let refreshed = self
            .login_with_phone_password(
                &account.login_phone,
                if account.login_password.is_empty() {
                    None
                } else {
                    Some(account.login_password.as_str())
                },
                &account.name,
            )
            .await
            .ok()?;
        let mut merged = refreshed;
        merged.enabled = account.enabled;
        let saved = self.store.upsert_account(merged).ok()?;
        Some(saved)
    }

    pub async fn probe_auth(
        &self,
        cookie_header: &str,
        access_token: &str,
        user_agent: &str,
        request_headers: &BTreeMap<String, String>,
    ) -> AppResult<Value> {
        let probe_acc = AccountCredential {
            name: "probe".to_string(),
            cookie: cookie_header.to_string(),
            access_token: access_token.to_string(),
            user_agent: user_agent.to_string(),
            request_headers_json: serde_json::to_string(request_headers).unwrap_or_default(),
            ..Default::default()
        };
        let headers = self.headers_for_account(&probe_acc);
        if !headers.contains_key("token") {
            return Err(AppError::StzyApi {
                code: "-1".to_string(),
                message: "没有识别到 Token".to_string(),
            });
        }
        let url = self.resolve_url("/zw-zzw/api/v1/zzw/user/detail");
        self.send_with_explicit_headers(reqwest::Method::GET, &url, None, &headers, "")
            .await
    }

    pub async fn refresh_account_from_cookie(
        &self,
        account: &mut AccountCredential,
        persist: bool,
    ) -> bool {
        if account.cookie.is_empty() {
            return false;
        }
        let mut headers = self.headers_for_account(account);
        headers.remove("token");
        headers.insert(
            "accept".to_string(),
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8".to_string(),
        );
        headers.insert("referer".to_string(), self.settings.site_base_url.clone());

        let url = format!("{}/layout/paper-lib", self.settings.site_base_url);
        let Ok((resp, _proxy)) = self
            .send_once(reqwest::Method::GET, &url, None, &headers, "", true)
            .await
        else {
            return false;
        };
        if !resp.status().is_success() {
            return false;
        }
        let refreshed_cookie = merge_response_cookies(&account.cookie, &resp);
        let refreshed_token = token_from_cookie_header(&refreshed_cookie);
        if refreshed_token.is_empty() {
            return false;
        }
        if self
            .probe_auth(
                &refreshed_cookie,
                &refreshed_token,
                &account.user_agent,
                &account.request_headers(),
            )
            .await
            .is_err()
        {
            return false;
        }
        account.cookie = refreshed_cookie;
        account.access_token = refreshed_token;
        let updated_headers = self.headers_for_account(account);
        account.request_headers_json =
            serde_json::to_string(&updated_headers).unwrap_or_default();
        account.last_checked_at = now_iso_seconds();
        if persist {
            let _ = self.store.upsert_account(account.clone());
        }
        true
    }

    pub async fn login_with_phone_password(
        &self,
        phone: &str,
        password: Option<&str>,
        custom_name: &str,
    ) -> AppResult<AccountCredential> {
        let (normalized_phone, login_password, payload) =
            build_phone_login_payload(phone, password)?;
        let empty_headers = BTreeMap::new();
        let login_url = self.resolve_url("/zw-auth/oauth/passwordLogin");
        let response = self
            .send_with_explicit_headers(
                reqwest::Method::POST,
                &login_url,
                Some(&payload),
                &empty_headers,
                "",
            )
            .await?;
        account_from_phone_login_response(
            &self.settings,
            &normalized_phone,
            &login_password,
            &response,
            custom_name,
        )
    }

    pub async fn credential_from_import(
        &self,
        raw_value: &str,
        custom_name: &str,
    ) -> AppResult<AccountCredential> {
        let mut parsed = parse_auth_import(raw_value)?;
        if !parsed.cookie.is_empty() && parsed.access_token.is_empty() {
            let mut probe = AccountCredential {
                name: "probe".to_string(),
                cookie: parsed.cookie.clone(),
                user_agent: parsed.user_agent.clone(),
                request_headers_json: serde_json::to_string(&parsed.request_headers)?,
                ..Default::default()
            };
            if self.refresh_account_from_cookie(&mut probe, false).await {
                parsed.cookie = probe.cookie.clone();
                parsed.access_token = probe.access_token.clone();
                parsed.request_headers = probe.request_headers();
            }
        }
        let token = if !parsed.access_token.is_empty() {
            parsed.access_token.clone()
        } else {
            token_from_cookie_header(&parsed.cookie)
        };
        if token.is_empty() {
            return Err(AppError::Validation(
                "没有识别到 Token，请重新复制网页 Console 脚本输出或 cURL".to_string(),
            ));
        }
        let expired_text = format_expiry_error_if_expired(&token);
        if let Err(err) = self
            .probe_auth(
                &parsed.cookie,
                &parsed.access_token,
                &parsed.user_agent,
                &parsed.request_headers,
            )
            .await
        {
            if let Some(exp_str) = expired_text {
                return Err(AppError::Validation(format!(
                    "Token 已于 {exp_str} 过期，官网用户信息接口也验证失败；请重新登录网页后再复制"
                )));
            }
            return Err(AppError::Validation(format!(
                "官网用户信息接口验证失败：{}",
                err.user_message()
            )));
        }

        let label = if !custom_name.trim().is_empty() {
            custom_name.trim().to_string()
        } else {
            let auto = account_label_from_auth(&parsed.cookie, &parsed.access_token);
            if auto.is_empty() {
                "手动导入账号".to_string()
            } else {
                auto
            }
        };

        Ok(AccountCredential {
            name: label,
            cookie: parsed.cookie,
            access_token: parsed.access_token,
            user_agent: parsed.user_agent,
            request_headers_json: serde_json::to_string(&parsed.request_headers)?,
            import_method: parsed.import_method,
            enabled: true,
            last_checked_at: now_iso_seconds(),
            ..Default::default()
        })
    }

    pub fn resolve_url(&self, path: &str) -> String {
        if path.starts_with("http://") || path.starts_with("https://") {
            path.to_string()
        } else {
            format!("{}{}", self.settings.api_base_url, path)
        }
    }

    async fn send_once(
        &self,
        method: reqwest::Method,
        url: &str,
        json_body: Option<&Value>,
        extra_headers: &BTreeMap<String, String>,
        resource_name: &str,
        mark_proxy_success: bool,
    ) -> AppResult<(reqwest::Response, String)> {
        if self.cancel.is_cancelled() {
            return Err(AppError::RequestStopped);
        }
        let proxy = tokio::select! {
            _ = self.cancel.cancelled() => return Err(AppError::RequestStopped),
            res = self.proxy_pool.acquire_proxy(resource_name) => res?,
        };
        let client = match self.client_for_proxy(&proxy) {
            Ok(c) => c,
            Err(e) => {
                self.proxy_pool.record_failure(&proxy);
                return Err(e);
            }
        };

        let mut merged_headers = self.base_headers();
        for (k, v) in extra_headers {
            merged_headers.insert(k.to_lowercase(), v.clone());
        }
        let header_map = to_header_map(&merged_headers);

        let mut req = client.request(method, url).headers(header_map);
        if let Some(body) = json_body {
            req = req.json(body);
        }

        let send_res = tokio::select! {
            _ = self.cancel.cancelled() => {
                if !proxy.is_empty() {
                    self.proxy_pool.record_success(&proxy);
                }
                return Err(AppError::RequestStopped);
            }
            r = req.send() => r,
        };

        let resp = match send_res {
            Ok(r) => r,
            Err(e) => {
                self.proxy_pool.record_failure(&proxy);
                return Err(AppError::Http(e));
            }
        };

        let status = resp.status().as_u16();
        if matches!(status, 403 | 407 | 429 | 500 | 502 | 503 | 504) {
            self.proxy_pool.record_failure(&proxy);
        } else if mark_proxy_success && !proxy.is_empty() {
            self.proxy_pool.record_success(&proxy);
            (self.on_proxy)(proxy.clone());
        }
        Ok((resp, proxy))
    }

    async fn send_with_retries(
        &self,
        method: reqwest::Method,
        url: &str,
        json_body: Option<&Value>,
        headers: Option<&BTreeMap<String, String>>,
        resource_name: &str,
    ) -> AppResult<Value> {
        let resolved_headers = match headers {
            Some(h) => h.clone(),
            None => self.default_auth_headers().await?,
        };
        self.send_with_explicit_headers(method, url, json_body, &resolved_headers, resource_name)
            .await
    }

    async fn send_with_explicit_headers(
        &self,
        method: reqwest::Method,
        url: &str,
        json_body: Option<&Value>,
        resolved_headers: &BTreeMap<String, String>,
        resource_name: &str,
    ) -> AppResult<Value> {
        let max_attempts = self.settings.max_retries.max(1);
        let mut last_err: Option<AppError> = None;

        for attempt in 0..max_attempts {
            if self.cancel.is_cancelled() {
                return Err(AppError::RequestStopped);
            }
            match self
                .send_once(
                    method.clone(),
                    url,
                    json_body,
                    resolved_headers,
                    resource_name,
                    true,
                )
                .await
            {
                Ok((resp, _)) => {
                    let status = resp.status();
                    if matches!(status.as_u16(), 429 | 500 | 502 | 503 | 504)
                        && attempt + 1 < max_attempts
                    {
                        last_err = Some(AppError::Runtime(format!("HTTP {}", status.as_u16())));
                        self.backoff_sleep(attempt).await?;
                        continue;
                    }
                    let resp = resp.error_for_status()?;
                    let data: Value = resp.json().await?;
                    let code = match data.get("code") {
                        Some(Value::String(s)) => s.clone(),
                        Some(Value::Number(n)) => n.to_string(),
                        _ => String::new(),
                    };
                    if code != "200" && code != "0" {
                        let message = data
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("请求失败")
                            .to_string();
                        return Err(AppError::StzyApi { code, message });
                    }
                    return Ok(data);
                }
                Err(AppError::RequestStopped) => return Err(AppError::RequestStopped),
                Err(err) => {
                    last_err = Some(err);
                    if attempt + 1 < max_attempts {
                        self.backoff_sleep(attempt).await?;
                    }
                }
            }
        }
        Err(last_err.unwrap_or_else(|| AppError::Runtime("请求失败".to_string())))
    }

    async fn backoff_sleep(&self, attempt: usize) -> AppResult<()> {
        let delay_ms = (600u64.saturating_mul(1u64 << attempt.min(4))).min(5000);
        tokio::select! {
            _ = self.cancel.cancelled() => Err(AppError::RequestStopped),
            _ = tokio::time::sleep(Duration::from_millis(delay_ms)) => Ok(()),
        }
    }

    pub async fn post_json(
        &self,
        path: &str,
        payload: &Value,
        headers: Option<&BTreeMap<String, String>>,
        resource_name: &str,
    ) -> AppResult<Value> {
        let url = self.resolve_url(path);
        self.send_with_retries(
            reqwest::Method::POST,
            &url,
            Some(payload),
            headers,
            resource_name,
        )
        .await
    }

    pub async fn get_json(
        &self,
        path: &str,
        headers: Option<&BTreeMap<String, String>>,
        resource_name: &str,
    ) -> AppResult<Value> {
        let url = self.resolve_url(path);
        self.send_with_retries(reqwest::Method::GET, &url, None, headers, resource_name)
            .await
    }

    pub async fn download(
        &self,
        url: &str,
        target: &Path,
        headers: Option<&BTreeMap<String, String>>,
        resource_name: &str,
    ) -> AppResult<u64> {
        let resolved_headers = match headers {
            Some(h) => h.clone(),
            None => self.default_auth_headers().await?,
        };
        let attempts = if self.proxy_pool.proxy_mode() == "off" {
            1
        } else {
            self.settings.proxy_max_failures.max(1) + 1
        };
        if let Some(parent) = target.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let partial = target.with_file_name(format!(
            "{}.download",
            target
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("temp")
        ));

        let mut last_err: Option<AppError> = None;
        for _ in 0..attempts {
            let _ = tokio::fs::remove_file(&partial).await;
            let (resp, proxy) = self
                .send_once(
                    reqwest::Method::GET,
                    url,
                    None,
                    &resolved_headers,
                    resource_name,
                    false,
                )
                .await?;
            let status_u16 = resp.status().as_u16();
            let already_released = matches!(status_u16, 403 | 407 | 429 | 500 | 502 | 503 | 504);

            let content_type = resp
                .headers()
                .get(reqwest::header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("")
                .to_lowercase();

            let stream_res: AppResult<u64> = async {
                let resp = resp.error_for_status()?;
                let mut file = tokio::fs::File::create(&partial).await?;
                let mut written = 0u64;
                let mut stream = resp.bytes_stream();
                while let Some(chunk_res) = tokio::select! {
                    _ = self.cancel.cancelled() => return Err(AppError::RequestStopped),
                    item = stream.next() => item,
                } {
                    let chunk = chunk_res?;
                    file.write_all(&chunk).await?;
                    written += chunk.len() as u64;
                }
                file.flush().await?;
                drop(file);
                validate_downloaded_file(&partial, target, url, &content_type).await?;
                Ok(written)
            }
            .await;

            match stream_res {
                Ok(written) => {
                    tokio::fs::rename(&partial, target).await?;
                    if !already_released && !proxy.is_empty() {
                        self.proxy_pool.record_success(&proxy);
                        (self.on_proxy)(proxy);
                    }
                    return Ok(written);
                }
                Err(AppError::InvalidDownloadContent(msg)) => {
                    if !already_released && !proxy.is_empty() {
                        self.proxy_pool.record_failure(&proxy);
                    }
                    let _ = tokio::fs::remove_file(&partial).await;
                    last_err = Some(AppError::InvalidDownloadContent(msg));
                    continue;
                }
                Err(err) => {
                    if !already_released && !proxy.is_empty() {
                        if matches!(err, AppError::RequestStopped) {
                            self.proxy_pool.record_success(&proxy);
                        } else {
                            self.proxy_pool.record_failure(&proxy);
                        }
                    }
                    let _ = tokio::fs::remove_file(&partial).await;
                    return Err(err);
                }
            }
        }
        Err(last_err
            .unwrap_or_else(|| AppError::InvalidDownloadContent("下载内容异常".to_string())))
    }
}

async fn validate_downloaded_file(
    partial: &Path,
    target: &Path,
    url: &str,
    content_type: &str,
) -> AppResult<()> {
    let meta = tokio::fs::metadata(partial).await?;
    if meta.len() == 0 {
        return Err(AppError::InvalidDownloadContent("下载内容为空".to_string()));
    }
    let head_len = (meta.len() as usize).min(4096);
    let mut file = tokio::fs::File::open(partial).await?;
    let mut head = vec![0u8; head_len];
    use tokio::io::AsyncReadExt;
    let n = file.read(&mut head).await?;
    head.truncate(n);

    let lower_ascii: Vec<u8> = head.iter().map(|b| b.to_ascii_lowercase()).collect();
    if contains_subslice(&lower_ascii, b"<html")
        || contains_subslice(&lower_ascii, b"<!doctype html")
    {
        return Err(AppError::InvalidDownloadContent(
            "下载内容不是试卷文件，可能是代理或登录返回页".to_string(),
        ));
    }

    let suffix = target
        .extension()
        .and_then(|e| e.to_str())
        .map(|s| format!(".{}", s.to_lowercase()))
        .or_else(|| {
            let clean = url.split('?').next().unwrap_or(url);
            Path::new(clean)
                .extension()
                .and_then(|e| e.to_str())
                .map(|s| format!(".{}", s.to_lowercase()))
        })
        .unwrap_or_default();

    if suffix == ".pdf" || content_type.contains("application/pdf") {
        if !head.starts_with(b"%PDF") {
            return Err(AppError::InvalidDownloadContent(
                "PDF 下载内容异常，已尝试切换代理".to_string(),
            ));
        }
    } else if (suffix == ".svg" || content_type.contains("image/svg"))
        && !contains_subslice(&lower_ascii, b"<svg")
    {
        return Err(AppError::InvalidDownloadContent(
            "预览图下载内容异常，已尝试切换代理".to_string(),
        ));
    }
    Ok(())
}

fn contains_subslice(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    haystack.windows(needle.len()).any(|w| w == needle)
}

fn to_header_map(headers: &BTreeMap<String, String>) -> HeaderMap {
    let mut map = HeaderMap::new();
    for (k, v) in headers {
        if let (Ok(name), Ok(val)) = (
            HeaderName::from_bytes(k.as_bytes()),
            HeaderValue::from_str(v),
        ) {
            map.insert(name, val);
        }
    }
    map
}

fn merge_response_cookies(current_cookie: &str, response: &reqwest::Response) -> String {
    let mut cookies = BTreeMap::new();
    for pair in current_cookie.split(';') {
        if let Some((name, val)) = pair.trim().split_once('=') {
            if !name.trim().is_empty() {
                cookies.insert(name.trim().to_string(), val.trim().to_string());
            }
        }
    }
    for cookie in response.cookies() {
        let name = cookie.name().trim();
        let val = cookie.value().trim();
        if !name.is_empty() && !val.is_empty() {
            cookies.insert(name.to_string(), val.to_string());
        }
    }
    cookies
        .into_iter()
        .filter(|(_, v)| !v.is_empty())
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("; ")
}
