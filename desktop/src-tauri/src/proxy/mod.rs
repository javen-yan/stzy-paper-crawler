use std::collections::{HashMap, HashSet};
use std::sync::{Arc, LazyLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use chrono::{DateTime, NaiveDate, NaiveDateTime};
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::Notify;
use url::Url;

use crate::error::{AppError, AppResult};
use crate::models::AppSettings;
use crate::store::SqliteStore;

pub const SHENLONG_API_BASE: &str = "http://api.shenlongip.com";
pub const PUBLIC_IP_ENDPOINTS: &[&str] = &[
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "http://myip.ipip.net",
];

pub static PROXY_RUNTIME: LazyLock<ProxyRuntimeRegistry> = LazyLock::new(ProxyRuntimeRegistry::new);

pub fn now_unix_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// Returns a log-safe proxy label without credentials (`scheme://host:port`).
pub fn display_proxy_url(proxy: &str) -> String {
    let Ok(parsed) = Url::parse(proxy) else {
        return proxy.to_string();
    };
    let Some(host) = parsed.host_str() else {
        return proxy.to_string();
    };
    match parsed.port() {
        Some(port) => format!("{}://{}:{}", parsed.scheme(), host, port),
        None => format!("{}://{}", parsed.scheme(), host),
    }
}

pub fn normalize_proxy_url(raw: &str) -> String {
    let item = raw.trim();
    if item.is_empty() || item.starts_with('#') {
        return String::new();
    }
    if item.contains("://") {
        item.to_string()
    } else {
        format!("http://{item}")
    }
}

pub fn parse_proxy_pool(value: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for line in value.lines() {
        let normalized = normalize_proxy_url(line);
        if !normalized.is_empty() && seen.insert(normalized.clone()) {
            out.push(normalized);
        }
    }
    out
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ProxyLeaseInfo {
    pub task_id: String,
    pub resource_name: String,
    pub leased_at: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyRuntimeItem {
    pub proxy: String,
    pub address: String,
    pub source: String,
    pub status: String,
    pub lease_task_id: String,
    pub lease_resource_name: String,
    pub leased_at: f64,
    pub cooldown_until: f64,
    pub failure_count: usize,
}

pub struct ProxyRuntimeRegistry {
    items: Mutex<HashMap<String, ProxyRuntimeItem>>,
}

impl ProxyRuntimeRegistry {
    pub fn new() -> Self {
        Self {
            items: Mutex::new(HashMap::new()),
        }
    }

    pub fn lease(&self, proxy: &str, source: &str, lease: &ProxyLeaseInfo) {
        if proxy.is_empty() {
            return;
        }
        let mut items = self.items.lock();
        let entry = items
            .entry(proxy.to_string())
            .or_insert_with(|| ProxyRuntimeItem {
                proxy: proxy.to_string(),
                address: display_proxy_url(proxy),
                source: source.to_string(),
                status: "使用中".to_string(),
                lease_task_id: String::new(),
                lease_resource_name: String::new(),
                leased_at: 0.0,
                cooldown_until: 0.0,
                failure_count: 0,
            });
        entry.source = source.to_string();
        entry.status = "使用中".to_string();
        entry.lease_task_id = lease.task_id.clone();
        entry.lease_resource_name = lease.resource_name.clone();
        entry.leased_at = lease.leased_at;
    }

    pub fn release(&self, proxy: &str, failure_count: usize, cooldown_until: f64) {
        if proxy.is_empty() {
            return;
        }
        let now = now_unix_secs();
        let mut items = self.items.lock();
        if let Some(entry) = items.get_mut(proxy) {
            entry.failure_count = failure_count;
            entry.cooldown_until = cooldown_until;
            entry.lease_task_id.clear();
            entry.lease_resource_name.clear();
            entry.leased_at = 0.0;
            entry.status = if cooldown_until > now {
                "冷却中".to_string()
            } else {
                "空闲".to_string()
            };
        }
    }

    pub fn sync_known(
        &self,
        source: &str,
        known: &[String],
        leases: &HashMap<String, ProxyLeaseInfo>,
        failures: &HashMap<String, usize>,
        cooldowns: &HashMap<String, f64>,
    ) {
        let now = now_unix_secs();
        let known_set: HashSet<&String> = known.iter().collect();
        let mut items = self.items.lock();
        items.retain(|proxy, item| {
            if item.source != source || known_set.contains(proxy) {
                return true;
            }
            let is_leased = !item.lease_task_id.is_empty() || item.leased_at > 0.0;
            is_leased || item.cooldown_until > now
        });

        for proxy in known {
            let entry = items
                .entry(proxy.clone())
                .or_insert_with(|| ProxyRuntimeItem {
                    proxy: proxy.clone(),
                    address: display_proxy_url(proxy),
                    source: source.to_string(),
                    status: "空闲".to_string(),
                    lease_task_id: String::new(),
                    lease_resource_name: String::new(),
                    leased_at: 0.0,
                    cooldown_until: 0.0,
                    failure_count: 0,
                });
            entry.source = source.to_string();
            entry.failure_count = *failures.get(proxy).unwrap_or(&0);
            entry.cooldown_until = *cooldowns.get(proxy).unwrap_or(&0.0);
            if let Some(lease) = leases.get(proxy) {
                entry.status = "使用中".to_string();
                entry.lease_task_id = lease.task_id.clone();
                entry.lease_resource_name = lease.resource_name.clone();
                entry.leased_at = lease.leased_at;
            } else if entry.cooldown_until > now {
                entry.status = "冷却中".to_string();
                entry.lease_task_id.clear();
                entry.lease_resource_name.clear();
                entry.leased_at = 0.0;
            } else {
                entry.status = "空闲".to_string();
                entry.lease_task_id.clear();
                entry.lease_resource_name.clear();
                entry.leased_at = 0.0;
            }
        }
    }

    pub fn snapshot(&self) -> Vec<ProxyRuntimeItem> {
        self.items.lock().values().cloned().collect()
    }
}

#[derive(Debug, Clone)]
pub struct ProxyEndpoint {
    pub url: String,
    pub expires_at: Option<String>,
}

pub fn extract_public_ipv4(text: &str) -> Option<String> {
    let re = Regex::new(r"\b(?:\d{1,3}\.){3}\d{1,3}\b").unwrap();
    re.find(text).map(|m| m.as_str().to_string())
}

fn build_direct_client(connect_secs: f64, read_secs: f64) -> AppResult<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(Duration::from_secs_f64(connect_secs.max(1.0)))
        .timeout(Duration::from_secs_f64((connect_secs + read_secs).max(2.0)))
        .build()?)
}

pub async fn detect_public_ip_status(connect_secs: f64, read_secs: f64) -> Value {
    let client = match build_direct_client(connect_secs, read_secs) {
        Ok(c) => c,
        Err(e) => {
            return json!({
                "ok": false,
                "ip": "",
                "source": "",
                "error": e.to_string(),
                "attempts": []
            });
        }
    };
    let mut attempts = Vec::new();
    let mut last_error = "无法获取本机公网 IP".to_string();
    for &endpoint in PUBLIC_IP_ENDPOINTS {
        match client.get(endpoint).send().await {
            Ok(resp) => match resp.text().await {
                Ok(body) => {
                    let ip = serde_json::from_str::<Value>(&body)
                        .ok()
                        .and_then(|v| {
                            v.get("ip")
                                .or_else(|| v.get("origin"))
                                .and_then(Value::as_str)
                                .and_then(extract_public_ipv4)
                        })
                        .or_else(|| extract_public_ipv4(&body));
                    if let Some(found) = ip {
                        attempts.push(json!({ "endpoint": endpoint, "ok": true, "ip": found }));
                        return json!({
                            "ok": true,
                            "ip": found,
                            "source": endpoint,
                            "error": "",
                            "attempts": attempts,
                        });
                    }
                    last_error = "响应中未解析到 IPv4".to_string();
                    attempts.push(json!({ "endpoint": endpoint, "ok": false, "error": last_error }));
                }
                Err(err) => {
                    last_error = err.to_string();
                    attempts.push(json!({ "endpoint": endpoint, "ok": false, "error": last_error }));
                }
            },
            Err(err) => {
                last_error = err.to_string();
                attempts.push(json!({ "endpoint": endpoint, "ok": false, "error": last_error }));
            }
        }
    }
    json!({
        "ok": false,
        "ip": "",
        "source": "",
        "error": last_error,
        "attempts": attempts,
    })
}

pub fn extract_shenlong_credentials(settings: &AppSettings) -> (String, String) {
    let mut key = settings.shenlong_whitelist_key.trim().to_string();
    let mut sign = settings.shenlong_whitelist_sign.trim().to_string();
    if (key.is_empty() || sign.is_empty()) && !settings.proxy_api_url.is_empty() {
        if let Ok(parsed) = Url::parse(&settings.proxy_api_url) {
            for (k, v) in parsed.query_pairs() {
                if k == "key" && key.is_empty() {
                    key = v.trim().to_string();
                } else if k == "sign" && sign.is_empty() {
                    sign = v.trim().to_string();
                }
            }
        }
    }
    (key, sign)
}

pub async fn bind_shenlong_local_ip(settings: &AppSettings) -> AppResult<Value> {
    if settings.proxy_provider.trim().to_lowercase() != "shenlong" {
        return Err(AppError::Validation("当前代理服务商不是神龙HTTP".to_string()));
    }
    let (key, sign) = extract_shenlong_credentials(settings);
    if key.is_empty() || sign.is_empty() {
        return Err(AppError::Validation("请填写白名单账号和签名".to_string()));
    }
    let ip_status = detect_public_ip_status(settings.connect_timeout, settings.read_timeout).await;
    let ip = ip_status
        .get("ip")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if ip.is_empty() {
        let err = ip_status
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("无法获取本机公网 IP");
        return Err(AppError::Validation(err.to_string()));
    }

    let client = build_direct_client(settings.connect_timeout, settings.read_timeout)?;
    let fetch_url = Url::parse_with_params(
        &format!("{SHENLONG_API_BASE}/white/fetch"),
        &[("key", key.as_str()), ("sign", sign.as_str()), ("ip", ip.as_str())],
    )
    .map_err(|e| AppError::Validation(e.to_string()))?;

    let fetch_payload: Value = client
        .get(fetch_url)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await
        .map_err(|_| AppError::Validation("神龙接口返回异常".to_string()))?;

    let fetch_code = value_code_string(&fetch_payload);
    if fetch_code != "200" {
        let msg = fetch_payload
            .get("msg")
            .and_then(Value::as_str)
            .unwrap_or("神龙接口请求失败");
        return Err(AppError::Validation(msg.to_string()));
    }
    let already_bound = fetch_payload
        .get("data")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(Value::as_str)
                .any(|item| item.trim() == ip)
        })
        .unwrap_or(false);
    if already_bound {
        return Ok(json!({
            "ip": ip,
            "added": false,
            "message": format!("本机 IP 已绑定：{ip}"),
        }));
    }

    let add_url = Url::parse_with_params(
        &format!("{SHENLONG_API_BASE}/white/add"),
        &[("key", key.as_str()), ("sign", sign.as_str()), ("ip", ip.as_str())],
    )
    .map_err(|e| AppError::Validation(e.to_string()))?;
    let add_payload: Value = client
        .get(add_url)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await
        .map_err(|_| AppError::Validation("神龙接口返回异常".to_string()))?;
    let add_code = value_code_string(&add_payload);
    if add_code != "200" && add_code != "1007" {
        let msg = add_payload
            .get("msg")
            .and_then(Value::as_str)
            .unwrap_or("白名单绑定失败");
        return Err(AppError::Validation(msg.to_string()));
    }
    Ok(json!({
        "ip": ip,
        "added": true,
        "message": format!("本机 IP 已绑定：{ip}"),
    }))
}

fn value_code_string(payload: &Value) -> String {
    match payload.get("code") {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        _ => String::new(),
    }
}

pub fn proxies_from_api_response(body: &str) -> Vec<ProxyEndpoint> {
    if let Ok(json_val) = serde_json::from_str::<Value>(body) {
        return proxies_from_json(&json_val);
    }
    body.lines()
        .map(normalize_proxy_url)
        .filter(|s| !s.is_empty())
        .map(|url| ProxyEndpoint {
            url,
            expires_at: None,
        })
        .collect()
}

pub fn proxies_from_json(data: &Value) -> Vec<ProxyEndpoint> {
    if let Value::Object(map) = data {
        if let Some(inner) = map.get("data") {
            let list = proxies_from_ip_port(inner);
            if !list.is_empty() {
                return list;
            }
        }
        let direct = proxies_from_ip_port(data);
        if !direct.is_empty() {
            return direct;
        }
        for key in ["proxy", "https", "http", "data"] {
            if let Some(Value::String(s)) = map.get(key) {
                let norm = normalize_proxy_url(s);
                if !norm.is_empty() {
                    return vec![ProxyEndpoint {
                        url: norm,
                        expires_at: None,
                    }];
                }
            }
        }
        return Vec::new();
    }
    if let Value::String(s) = data {
        let norm = normalize_proxy_url(s);
        if !norm.is_empty() {
            return vec![ProxyEndpoint {
                url: norm,
                expires_at: None,
            }];
        }
    }
    Vec::new()
}

fn proxies_from_ip_port(payload: &Value) -> Vec<ProxyEndpoint> {
    match payload {
        Value::Array(items) => items.iter().flat_map(proxies_from_ip_port).collect(),
        Value::Object(map) => {
            let host = map
                .get("ip")
                .or_else(|| map.get("host"))
                .and_then(value_as_trimmed_string)
                .unwrap_or_default();
            let port = map
                .get("port")
                .and_then(value_as_trimmed_string)
                .unwrap_or_default();
            if host.is_empty() || port.is_empty() {
                return Vec::new();
            }
            let protocol = map
                .get("protocol")
                .or_else(|| map.get("type"))
                .and_then(value_as_trimmed_string)
                .unwrap_or_else(|| "http".to_string())
                .to_lowercase();
            let scheme = match protocol.as_str() {
                "1" | "http" | "https" => "http",
                "2" | "socks5" | "socks" => "socks5",
                other => other.split("://").next().unwrap_or("http"),
            };
            let url = normalize_proxy_url(&format!("{scheme}://{host}:{port}"));
            if url.is_empty() {
                return Vec::new();
            }
            let expires_at = map
                .get("expire")
                .or_else(|| map.get("expires_at"))
                .and_then(value_as_trimmed_string)
                .filter(|s| !s.is_empty());
            vec![ProxyEndpoint { url, expires_at }]
        }
        _ => Vec::new(),
    }
}

fn value_as_trimmed_string(v: &Value) -> Option<String> {
    match v {
        Value::String(s) => Some(s.trim().to_string()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

pub fn url_with_count(api_url: &str, count: Option<usize>) -> String {
    let Some(c) = count.filter(|&c| c > 0) else {
        return api_url.to_string();
    };
    let Ok(mut parsed) = Url::parse(api_url) else {
        return api_url.to_string();
    };
    let mut pairs: Vec<(String, String)> = parsed
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    let mut found = false;
    for (k, v) in &mut pairs {
        if k == "count" {
            *v = c.to_string();
            found = true;
        }
    }
    if !found {
        pairs.push(("count".to_string(), c.to_string()));
    }
    {
        let mut qp = parsed.query_pairs_mut();
        qp.clear();
        for (k, v) in pairs {
            qp.append_pair(&k, &v);
        }
    }
    parsed.to_string()
}

pub fn parse_proxy_expires_at(raw: Option<&str>) -> f64 {
    let Some(text) = raw.map(str::trim).filter(|s| !s.is_empty()) else {
        return 0.0;
    };
    if text.chars().all(|c| c.is_ascii_digit()) {
        if let Ok(num) = text.parse::<f64>() {
            return if num > 10_000_000_000.0 {
                num / 1000.0
            } else {
                num
            };
        }
    }
    let normalized = text.replace('/', "-");
    if let Ok(dt) = DateTime::parse_from_rfc3339(&normalized) {
        return dt.timestamp() as f64;
    }
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"] {
        if let Ok(ndt) = NaiveDateTime::parse_from_str(&normalized, fmt) {
            if let Some(local_dt) = ndt.and_local_timezone(chrono::Local).single() {
                return local_dt.timestamp() as f64;
            }
        }
    }
    if let Ok(nd) = NaiveDate::parse_from_str(&normalized, "%Y-%m-%d") {
        if let Some(ndt) = nd.and_hms_opt(0, 0, 0) {
            if let Some(local_dt) = ndt.and_local_timezone(chrono::Local).single() {
                return local_dt.timestamp() as f64;
            }
        }
    }
    0.0
}

struct ProxyPoolInner {
    fixed_urls: Vec<String>,
    api_urls: Vec<String>,
    api_expiries: HashMap<String, f64>,
    failures: HashMap<String, usize>,
    cooldowns: HashMap<String, f64>,
    leases: HashMap<String, ProxyLeaseInfo>,
    cursor: usize,
    refilling: bool,
}

/// Async-friendly strict-lease proxy pool for one crawl task.
pub struct ProxyPool {
    settings: AppSettings,
    mode: String,
    source_label: String,
    inner: Mutex<ProxyPoolInner>,
    notify: Notify,
    on_event: Arc<dyn Fn(String) + Send + Sync>,
}

impl ProxyPool {
    pub fn new(
        settings: AppSettings,
        on_event: Option<Arc<dyn Fn(String) + Send + Sync>>,
    ) -> Arc<Self> {
        let raw_mode = settings.proxy_mode.trim().to_lowercase();
        let mode = match raw_mode.as_str() {
            "fixed" | "api" => raw_mode,
            _ => "off".to_string(),
        };
        let provider = settings.proxy_provider.trim().to_lowercase();
        let source_label = match mode.as_str() {
            "fixed" => "固定代理池".to_string(),
            "api" if provider == "shenlong" => "神龙 HTTP".to_string(),
            "api" => "通用接口".to_string(),
            _ => "直连".to_string(),
        };
        let fixed_urls = if mode == "fixed" {
            parse_proxy_pool(&settings.proxy_pool)
        } else {
            Vec::new()
        };
        let emitter = on_event.unwrap_or_else(|| Arc::new(|_| {}));
        if mode == "fixed" && !fixed_urls.is_empty() {
            emitter(format!("固定代理池：{} 个", fixed_urls.len()));
        } else if mode == "api" {
            emitter(format!("代理服务商：{source_label}"));
        }

        let pool = Arc::new(Self {
            settings,
            mode: mode.clone(),
            source_label: source_label.clone(),
            inner: Mutex::new(ProxyPoolInner {
                fixed_urls: fixed_urls.clone(),
                api_urls: Vec::new(),
                api_expiries: HashMap::new(),
                failures: HashMap::new(),
                cooldowns: HashMap::new(),
                leases: HashMap::new(),
                cursor: 0,
                refilling: false,
            }),
            notify: Notify::new(),
            on_event: emitter,
        });
        if mode == "fixed" {
            PROXY_RUNTIME.sync_known(
                &source_label,
                &fixed_urls,
                &HashMap::new(),
                &HashMap::new(),
                &HashMap::new(),
            );
        }
        pool
    }

    pub fn proxy_mode(&self) -> &str {
        &self.mode
    }

    pub fn target_size(&self) -> usize {
        match self.mode.as_str() {
            "api" => self.settings.concurrency.clamp(1, 20),
            "fixed" => self.inner.lock().fixed_urls.len(),
            _ => 0,
        }
    }

    pub async fn available_capacity(&self) -> usize {
        if self.mode == "off" {
            return self.settings.max_download_workers.max(1);
        }
        if self.mode == "api" {
            self.ensure_api_refilled().await;
        }
        let now = now_unix_secs();
        let min_ttl = self.min_ttl_secs();
        let inner = self.inner.lock();
        let urls = if self.mode == "api" {
            &inner.api_urls
        } else {
            &inner.fixed_urls
        };
        urls.iter()
            .filter(|p| is_proxy_usable(p, &inner, now, min_ttl) && !inner.leases.contains_key(*p))
            .count()
    }

    pub async fn acquire_proxy(&self, resource_name: &str) -> AppResult<String> {
        if self.mode == "off" {
            return Ok(String::new());
        }
        let timeout_secs = self.settings.read_timeout.clamp(1.0, 60.0);
        let deadline = tokio::time::Instant::now() + Duration::from_secs_f64(timeout_secs);

        loop {
            if self.mode == "api" {
                self.ensure_api_refilled().await;
            }
            if let Some(leased) = self.try_lease_one(resource_name) {
                return Ok(leased);
            }

            let now_inst = tokio::time::Instant::now();
            if now_inst >= deadline {
                return Err(AppError::ProxyUnavailable(
                    "代理池可用 IP 不足，请增加代理数量或降低下载并发".to_string(),
                ));
            }
            let wait_for = (deadline - now_inst).min(Duration::from_millis(250));
            let _ = tokio::time::timeout(wait_for, self.notify.notified()).await;
        }
    }

    fn try_lease_one(&self, resource_name: &str) -> Option<String> {
        let now = now_unix_secs();
        let min_ttl = self.min_ttl_secs();
        let mut inner = self.inner.lock();
        if self.mode == "api" {
            let expired = prune_expired_inner(&mut inner, now, min_ttl);
            if expired > 0 {
                (self.on_event)(format!("代理已到期，主动换下：{expired} 个"));
            }
        }
        let urls = if self.mode == "api" {
            inner.api_urls.clone()
        } else {
            inner.fixed_urls.clone()
        };
        if urls.is_empty() {
            return None;
        }
        let len = urls.len();
        let start = inner.cursor % len;
        for offset in 0..len {
            let idx = (start + offset) % len;
            let candidate = &urls[idx];
            if is_proxy_usable(candidate, &inner, now, min_ttl)
                && !inner.leases.contains_key(candidate)
            {
                inner.cursor = (idx + 1) % len;
                let lease = ProxyLeaseInfo {
                    task_id: self.settings.task_scope.clone(),
                    resource_name: resource_name.to_string(),
                    leased_at: now,
                };
                inner.leases.insert(candidate.clone(), lease.clone());
                PROXY_RUNTIME.lease(candidate, &self.source_label, &lease);
                return Some(candidate.clone());
            }
        }
        None
    }

    pub fn record_success(&self, proxy: &str) {
        if proxy.is_empty() {
            return;
        }
        let now = now_unix_secs();
        let had_failure;
        {
            let mut inner = self.inner.lock();
            if inner.cooldowns.get(proxy).copied().unwrap_or(0.0) > now {
                inner.leases.remove(proxy);
                return;
            }
            had_failure = inner.failures.remove(proxy).is_some();
            inner.cooldowns.remove(proxy);
            inner.leases.remove(proxy);
            PROXY_RUNTIME.release(proxy, 0, 0.0);
        }
        self.notify.notify_waiters();
        if had_failure {
            (self.on_event)(format!("代理恢复：{}", display_proxy_url(proxy)));
        }
    }

    pub fn record_failure(&self, proxy: &str) {
        if proxy.is_empty() {
            return;
        }
        let now = now_unix_secs();
        let max_failures = self.settings.proxy_max_failures.max(1);
        let mut switched = false;
        let current_failures;
        {
            let mut inner = self.inner.lock();
            let count = inner.failures.get(proxy).copied().unwrap_or(0) + 1;
            current_failures = count;
            if count >= max_failures {
                let until = now + self.settings.proxy_cooldown_seconds.max(1.0);
                inner.cooldowns.insert(proxy.to_string(), until);
                inner.failures.insert(proxy.to_string(), 0);
                if self.mode == "api" {
                    inner.api_urls.retain(|u| u != proxy);
                    inner.api_expiries.remove(proxy);
                }
                switched = true;
            } else {
                inner.failures.insert(proxy.to_string(), count);
            }
            inner.leases.remove(proxy);
            let f_cnt = inner.failures.get(proxy).copied().unwrap_or(0);
            let cd = inner.cooldowns.get(proxy).copied().unwrap_or(0.0);
            PROXY_RUNTIME.release(proxy, f_cnt, cd);
        }
        (self.on_event)(format!(
            "代理请求失败：{}（{current_failures}/{max_failures}）",
            display_proxy_url(proxy)
        ));
        if switched {
            (self.on_event)(format!("代理不可用，已换下一个：{}", display_proxy_url(proxy)));
        }
        self.notify.notify_waiters();
    }

    async fn ensure_api_refilled(&self) {
        if self.mode != "api" || self.settings.proxy_api_url.trim().is_empty() {
            return;
        }
        let missing = {
            let now = now_unix_secs();
            let min_ttl = self.min_ttl_secs();
            let mut inner = self.inner.lock();
            let expired = prune_expired_inner(&mut inner, now, min_ttl);
            if expired > 0 {
                (self.on_event)(format!("代理已到期，主动换下：{expired} 个"));
            }
            let target = self.settings.concurrency.clamp(1, 20);
            let available = inner
                .api_urls
                .iter()
                .filter(|p| is_proxy_usable(p, &inner, now, min_ttl))
                .count();
            if available >= target || inner.refilling {
                0
            } else {
                inner.refilling = true;
                target - available
            }
        };
        if missing == 0 {
            return;
        }

        (self.on_event)(format!("提取接口补充代理：需要 {missing} 个"));
        let fetched = self.fetch_from_api(missing).await;
        let now = now_unix_secs();
        let min_ttl = self.min_ttl_secs();
        let target = self.settings.concurrency.clamp(1, 20);
        let (added_count, avail_after) = {
            let mut inner = self.inner.lock();
            inner.refilling = false;
            let mut added = 0usize;
            for ep in fetched {
                if inner.api_urls.contains(&ep.url) || inner.cooldowns.contains_key(&ep.url) {
                    continue;
                }
                let exp = parse_proxy_expires_at(ep.expires_at.as_deref());
                if exp > 0.0 && exp <= now + min_ttl {
                    continue;
                }
                if exp > 0.0 {
                    inner.api_expiries.insert(ep.url.clone(), exp);
                }
                inner.api_urls.push(ep.url);
                added += 1;
            }
            let avail = inner
                .api_urls
                .iter()
                .filter(|p| is_proxy_usable(p, &inner, now, min_ttl))
                .count();
            PROXY_RUNTIME.sync_known(
                &self.source_label,
                &inner.api_urls,
                &inner.leases,
                &inner.failures,
                &inner.cooldowns,
            );
            (added, avail)
        };

        if added_count > 0 {
            (self.on_event)(format!(
                "提取接口返回代理：{added_count} 个，可用 {avail_after}/{target}"
            ));
        } else {
            (self.on_event)("提取接口暂时没有返回可用代理".to_string());
        }
        self.notify.notify_waiters();
    }

    async fn fetch_from_api(&self, count: usize) -> Vec<ProxyEndpoint> {
        let Ok(client) = build_direct_client(self.settings.connect_timeout, self.settings.read_timeout)
        else {
            return Vec::new();
        };
        let url = url_with_count(self.settings.proxy_api_url.trim(), Some(count));
        let Ok(resp) = client.get(&url).send().await else {
            return Vec::new();
        };
        if !resp.status().is_success() {
            return Vec::new();
        }
        let Ok(text) = resp.text().await else {
            return Vec::new();
        };
        proxies_from_api_response(&text)
    }

    fn min_ttl_secs(&self) -> f64 {
        self.settings.proxy_min_ttl_seconds.max(0.0)
    }
}

fn is_proxy_usable(proxy: &str, inner: &ProxyPoolInner, now: f64, min_ttl: f64) -> bool {
    if proxy.is_empty() {
        return false;
    }
    if inner.cooldowns.get(proxy).copied().unwrap_or(0.0) > now {
        return false;
    }
    if let Some(&exp) = inner.api_expiries.get(proxy) {
        if exp > 0.0 && exp <= now + min_ttl {
            return false;
        }
    }
    true
}

fn prune_expired_inner(inner: &mut ProxyPoolInner, now: f64, min_ttl: f64) -> usize {
    if inner.api_expiries.is_empty() {
        return 0;
    }
    let expired: Vec<String> = inner
        .api_urls
        .iter()
        .filter(|p| {
            inner
                .api_expiries
                .get(*p)
                .map(|&exp| exp > 0.0 && exp <= now + min_ttl)
                .unwrap_or(false)
        })
        .cloned()
        .collect();
    if expired.is_empty() {
        return 0;
    }
    let expired_set: HashSet<&String> = expired.iter().collect();
    inner.api_urls.retain(|p| !expired_set.contains(p));
    for p in &expired {
        inner.api_expiries.remove(p);
        inner.failures.remove(p);
        inner.cooldowns.remove(p);
        if !inner.leases.contains_key(p) {
            PROXY_RUNTIME.release(p, 0, 0.0);
        }
    }
    expired.len()
}

/// Builds the full `/proxy/status` diagnostics payload expected by `ProxyStatusPopover.vue`.
pub async fn build_proxy_status(base_settings: &AppSettings, store: &SqliteStore) -> AppResult<Value> {
    let effective = store.effective_settings(base_settings)?;
    let proxy_mode = match effective.proxy_mode.trim().to_lowercase().as_str() {
        "fixed" => "fixed",
        "api" => "api",
        _ => "off",
    };
    let proxy_provider = match effective.proxy_provider.trim().to_lowercase().as_str() {
        "shenlong" => "shenlong",
        _ => "generic",
    };
    let fixed_proxies = if proxy_mode == "fixed" {
        parse_proxy_pool(&effective.proxy_pool)
    } else {
        Vec::new()
    };
    let target_proxy_count = if proxy_mode == "api" {
        effective.concurrency.clamp(1, 20)
    } else {
        fixed_proxies.len()
    };

    let tasks = store.list_tasks(false, 500, 0)?;
    let running_tasks: Vec<&Value> = tasks
        .iter()
        .filter(|t| t.get("status").and_then(Value::as_str) == Some("running"))
        .collect();
    let active_proxies: Vec<String> = running_tasks
        .iter()
        .filter_map(|t| t.get("active_proxy").and_then(Value::as_str))
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .collect();

    let mut runtime_map: HashMap<String, ProxyRuntimeItem> = PROXY_RUNTIME
        .snapshot()
        .into_iter()
        .map(|i| (i.proxy.clone(), i))
        .collect();

    let running_task_list: Vec<Value> = running_tasks
        .iter()
        .map(|t| {
            let id = t.get("id").and_then(Value::as_str).unwrap_or("");
            let title = t
                .get("title")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .unwrap_or(id);
            json!({
                "id": id,
                "title": title,
                "mode": t.get("mode").and_then(Value::as_str).unwrap_or(""),
                "active_proxy": t.get("active_proxy").and_then(Value::as_str).unwrap_or(""),
            })
        })
        .collect();

    let mut items = Vec::new();
    for (idx, proxy) in fixed_proxies.iter().enumerate() {
        let running_cnt = active_proxies.iter().filter(|&p| p == proxy).count();
        let rt = runtime_map.get(proxy);
        let status = rt
            .map(|r| r.status.clone())
            .unwrap_or_else(|| if running_cnt > 0 { "使用中" } else { "空闲" }.to_string());
        items.push(json!({
            "id": format!("fixed-{}", idx + 1),
            "source": "固定代理池",
            "address": display_proxy_url(proxy),
            "status": status,
            "running_count": running_cnt,
            "lease_task_id": rt.map(|r| r.lease_task_id.as_str()).unwrap_or(""),
            "lease_resource_name": rt.map(|r| r.lease_resource_name.as_str()).unwrap_or(""),
            "cooldown_until": rt.map(|r| r.cooldown_until).unwrap_or(0.0),
            "failure_count": rt.map(|r| r.failure_count).unwrap_or(0),
        }));
    }

    for ap in &active_proxies {
        runtime_map
            .entry(ap.clone())
            .or_insert_with(|| ProxyRuntimeItem {
                proxy: ap.clone(),
                address: display_proxy_url(ap),
                source: "运行中".to_string(),
                status: "使用中".to_string(),
                lease_task_id: String::new(),
                lease_resource_name: String::new(),
                leased_at: 0.0,
                cooldown_until: 0.0,
                failure_count: 0,
            });
    }

    let fixed_set: HashSet<&String> = fixed_proxies.iter().collect();
    for (idx, (proxy, rt)) in runtime_map.iter().enumerate() {
        if fixed_set.contains(proxy) {
            continue;
        }
        let running_cnt = active_proxies.iter().filter(|&p| p == proxy).count();
        items.push(json!({
            "id": format!("active-{}", idx + 1),
            "source": rt.source,
            "address": rt.address,
            "status": rt.status,
            "running_count": running_cnt,
            "lease_task_id": rt.lease_task_id,
            "lease_resource_name": rt.lease_resource_name,
            "cooldown_until": rt.cooldown_until,
            "failure_count": rt.failure_count,
        }));
    }

    let leased_proxy_count = items
        .iter()
        .filter(|i| i.get("status").and_then(Value::as_str) == Some("使用中"))
        .count();
    let cooldown_proxy_count = items
        .iter()
        .filter(|i| i.get("status").and_then(Value::as_str) == Some("冷却中"))
        .count();
    let available_proxy_count = items
        .iter()
        .filter(|i| i.get("status").and_then(Value::as_str) == Some("空闲"))
        .count();

    let configured_workers = effective.max_download_workers.max(1);
    let effective_download_workers = if proxy_mode != "off" {
        let cap = if available_proxy_count > 0 {
            available_proxy_count
        } else if target_proxy_count > 0 {
            target_proxy_count
        } else {
            1
        };
        configured_workers.min(cap).max(1)
    } else {
        configured_workers
    };

    let public_ip = detect_public_ip_status(effective.connect_timeout, effective.read_timeout).await;
    let my_ip = public_ip
        .get("ip")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    Ok(json!({
        "my_ip": my_ip,
        "my_ip_status": public_ip,
        "proxy_mode": proxy_mode,
        "proxy_provider": proxy_provider,
        "proxy_api_configured": !effective.proxy_api_url.trim().is_empty(),
        "pool_size": fixed_proxies.len(),
        "target_proxy_count": target_proxy_count,
        "available_proxy_count": available_proxy_count,
        "leased_proxy_count": leased_proxy_count,
        "cooldown_proxy_count": cooldown_proxy_count,
        "running_task_count": running_tasks.len(),
        "running_proxy_count": active_proxies.len(),
        "running_tasks": running_task_list,
        "effective_download_workers": effective_download_workers,
        "items": items,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shenlong_json_and_credentials_parsing() {
        let payload = r#"{"code":200,"data":[{"ip":"1.2.3.4","port":8080,"expire":"2099-01-01 12:00:00"}]}"#;
        let eps = proxies_from_api_response(payload);
        assert_eq!(eps.len(), 1);
        assert_eq!(eps[0].url, "http://1.2.3.4:8080");
        assert_eq!(eps[0].expires_at.as_deref(), Some("2099-01-01 12:00:00"));

        let mut settings = AppSettings::default();
        settings.proxy_api_url =
            "http://api.shenlongip.com/ip?key=my_key&pattern=json&count=1&sign=my_sign".to_string();
        let (k, s) = extract_shenlong_credentials(&settings);
        assert_eq!(k, "my_key");
        assert_eq!(s, "my_sign");
        assert_eq!(
            display_proxy_url("socks5://user:secret@10.0.0.1:1080"),
            "socks5://10.0.0.1:1080"
        );
    }

    #[tokio::test]
    async fn strict_proxy_lease_prevents_double_checkout() {
        let mut settings = AppSettings::default();
        settings.proxy_mode = "fixed".to_string();
        settings.proxy_pool = "http://127.0.0.1:8001\n127.0.0.1:8002".to_string();
        settings.read_timeout = 0.3;
        settings.proxy_max_failures = 2;
        settings.proxy_cooldown_seconds = 60.0;

        let pool = ProxyPool::new(settings, None);
        let p1 = pool.acquire_proxy("res-1").await.unwrap();
        let p2 = pool.acquire_proxy("res-2").await.unwrap();
        assert_ne!(p1, p2);

        // Third concurrent acquire must time out since both proxies are leased
        let err = pool.acquire_proxy("res-3").await.unwrap_err();
        assert!(matches!(err, AppError::ProxyUnavailable(_)));

        // Releasing p1 allows acquiring again
        pool.record_success(&p1);
        let p3 = pool.acquire_proxy("res-3").await.unwrap();
        assert_eq!(p3, p1);

        // Two consecutive failures put p2 into cooldown
        pool.record_failure(&p2);
        let p2_retry = pool.acquire_proxy("res-4").await.unwrap();
        assert_eq!(p2_retry, p2);
        pool.record_failure(&p2_retry);
        assert_eq!(pool.available_capacity().await, 0);
    }
}
