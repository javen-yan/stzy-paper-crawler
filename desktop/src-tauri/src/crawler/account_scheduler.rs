use std::collections::BTreeMap;
use std::sync::Arc;

use serde_json::{json, Value};

use crate::crawler::api::StzyCrawlerApi;
use crate::crawler::client::StzyHttpClient;
use crate::models::{AccountCredential, ResourceRecord, ResourceStatus};

#[derive(Debug, Clone)]
pub struct DownloadUrlResult {
    pub url: String,
    pub status: Option<ResourceStatus>,
    pub error: String,
    pub paid_unavailable: usize,
}

#[derive(Debug, Clone)]
struct DownloadAttempt {
    name: String,
    headers: BTreeMap<String, String>,
    account: Option<AccountCredential>,
    diagnosis: Value,
}

#[derive(Clone)]
pub struct AccountScheduler {
    client: StzyHttpClient,
    api: StzyCrawlerApi,
    on_log: Arc<dyn Fn(String) + Send + Sync>,
}

impl AccountScheduler {
    pub fn new(
        client: StzyHttpClient,
        api: StzyCrawlerApi,
        on_log: Option<Arc<dyn Fn(String) + Send + Sync>>,
    ) -> Self {
        Self {
            client,
            api,
            on_log: on_log.unwrap_or_else(|| Arc::new(|_| {})),
        }
    }

    pub async fn download_pdf_url(&self, record: &ResourceRecord) -> DownloadUrlResult {
        let mut attempts = self.scheduled_attempts(record).await;
        if attempts.is_empty() {
            let default_headers = self
                .client
                .default_auth_headers()
                .await
                .unwrap_or_default();
            attempts.push(DownloadAttempt {
                name: "当前登录".to_string(),
                headers: default_headers,
                account: None,
                diagnosis: json!({}),
            });
        }

        let mut last_error = "没有可用账号".to_string();
        let mut diagnostics = Vec::new();

        for attempt in attempts {
            match self
                .api
                .download_resource_url(&record.resource_id, &attempt.headers, &record.resource_name)
                .await
            {
                Ok(url) if !url.is_empty() => {
                    if let Some(ref acc) = attempt.account {
                        let _ = self.client.store.mark_account_success(&acc.name);
                    }
                    (self.on_log)(format!(
                        "账号 {} 下载成功：{}",
                        attempt.name, record.resource_id
                    ));
                    return DownloadUrlResult {
                        url,
                        status: None,
                        error: String::new(),
                        paid_unavailable: 0,
                    };
                }
                Ok(_) => {
                    last_error = "接口未返回 PDF 地址".to_string();
                }
                Err(err) => {
                    last_error = Self::user_facing_error(&err.user_message());
                }
            }

            let diag = if attempt
                .diagnosis
                .as_object()
                .map(|m| !m.is_empty())
                .unwrap_or(false)
            {
                attempt.diagnosis.clone()
            } else {
                self.download_diagnosis(&record.resource_id, &attempt.headers, &record.resource_name)
                    .await
            };
            if diag.as_object().map(|m| !m.is_empty()).unwrap_or(false) {
                let diag_text = Self::format_download_diagnosis(&diag);
                if !diag_text.is_empty() && !last_error.contains(&diag_text) {
                    last_error = format!("{last_error}；{diag_text}");
                }
                diagnostics.push(diag);
            }
            if let Some(ref acc) = attempt.account {
                let _ = self.client.store.mark_account_failure(&acc.name, &last_error);
            }
            (self.on_log)(format!(
                "账号 {} 下载失败，尝试下一个账号：{last_error}",
                attempt.name
            ));
        }

        let has_zero_price_account = diagnostics
            .iter()
            .any(|d| d.get("price").and_then(val_f64) == Some(0.0));
        if record.price > 0.0 && !has_zero_price_account {
            return DownloadUrlResult {
                url: String::new(),
                status: Some(ResourceStatus::PaidUnavailable),
                error: Self::final_error(&last_error),
                paid_unavailable: 1,
            };
        }

        DownloadUrlResult {
            url: String::new(),
            status: None,
            error: Self::final_error(&last_error),
            paid_unavailable: 0,
        }
    }

    async fn scheduled_attempts(&self, record: &ResourceRecord) -> Vec<DownloadAttempt> {
        let accounts = self.client.enabled_valid_accounts().await.unwrap_or_default();
        let mut indexed = Vec::with_capacity(accounts.len());
        for (idx, acc) in accounts.into_iter().enumerate() {
            let headers = self.client.headers_for_account(&acc);
            let mut diagnosis = json!({});
            if record.price > 0.0 {
                diagnosis = self
                    .download_diagnosis(&record.resource_id, &headers, &record.resource_name)
                    .await;
                if diagnosis.get("check_error").is_none()
                    && diagnosis.as_object().map(|m| !m.is_empty()).unwrap_or(false)
                {
                    let _ = self
                        .client
                        .store
                        .update_account_download_profile(&acc.name, &diagnosis);
                }
            }
            indexed.push((
                DownloadAttempt {
                    name: acc.name.clone(),
                    headers,
                    account: Some(acc),
                    diagnosis,
                },
                idx,
            ));
        }

        indexed.sort_by(|(a, ia), (b, ib)| {
            account_schedule_key(a.account.as_ref(), &a.diagnosis, *ia)
                .partial_cmp(&account_schedule_key(b.account.as_ref(), &b.diagnosis, *ib))
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let sorted: Vec<DownloadAttempt> = indexed.into_iter().map(|(a, _)| a).collect();
        if record.price > 0.0 && !sorted.is_empty() {
            let order = sorted
                .iter()
                .map(|a| {
                    if a.diagnosis
                        .as_object()
                        .map(|m| !m.is_empty())
                        .unwrap_or(false)
                    {
                        format!("{}({})", a.name, Self::format_download_diagnosis(&a.diagnosis))
                    } else {
                        a.name.clone()
                    }
                })
                .collect::<Vec<_>>()
                .join(" -> ");
            (self.on_log)(format!("付费资源账号调度：{order}"));
        }
        sorted
    }

    async fn download_diagnosis(
        &self,
        resource_id: &str,
        headers: &BTreeMap<String, String>,
        resource_name: &str,
    ) -> Value {
        match self
            .api
            .check_download_info(resource_id, headers, resource_name)
            .await
        {
            Ok(info) => {
                let mut out = serde_json::Map::new();
                for key in [
                    "price",
                    "economizePrice",
                    "surplusNum",
                    "dayLimit",
                    "weekLimit",
                    "rank",
                    "userType",
                ] {
                    if let Some(v) = info.get(key) {
                        out.insert(key.to_string(), v.clone());
                    }
                }
                Value::Object(out)
            }
            Err(err) => json!({ "check_error": err.user_message() }),
        }
    }

    pub fn format_download_diagnosis(info: &Value) -> String {
        if let Some(err) = info.get("check_error").and_then(Value::as_str) {
            return Self::user_facing_error(err);
        }
        let mut parts = Vec::new();
        if let Some(p) = info.get("price") {
            parts.push(format!("实付 {}", val_display(p)));
        }
        if let Some(s) = info.get("surplusNum") {
            parts.push(format!("剩余额度 {}", val_display(s)));
        }
        if let Some(u) = info.get("userType") {
            parts.push(format!("用户类型 {}", val_display(u)));
        }
        if let Some(r) = info.get("rank") {
            parts.push(format!("资源等级 {}", val_display(r)));
        }
        if parts.is_empty() {
            "无下载资格明细".to_string()
        } else {
            parts.join("，")
        }
    }

    pub fn user_facing_error(message: &str) -> String {
        if message.contains("暂未登录")
            || message.contains("token已经过期")
            || message.contains("请登录")
        {
            "登录态已失效".to_string()
        } else if message.contains("额度不足") || message.contains('豆') {
            "账号额度不足".to_string()
        } else if message.contains("无权限") {
            "账号无下载权限".to_string()
        } else {
            message.to_string()
        }
    }

    pub fn final_error(last_error: &str) -> String {
        let compact = Self::user_facing_error(last_error);
        if compact == "登录态已失效" {
            "登录态已失效，请重新登录或换一个可用账号".to_string()
        } else if compact.contains("账号额度不足") || compact.contains("账号无下载权限") {
            format!("无账号支持，请补充 VIP 账号后恢复任务（{compact}）")
        } else {
            format!("所有账号均不可用或额度不足：{compact}")
        }
    }
}

pub fn account_schedule_key(
    account: Option<&AccountCredential>,
    diagnosis: &Value,
    index: usize,
) -> (i64, f64, i64, i64, usize) {
    let effective_price = diagnosis.get("price").and_then(val_f64);
    let surplus_num = diagnosis
        .get("surplusNum")
        .and_then(val_i64)
        .unwrap_or(-1);
    let user_type = diagnosis
        .get("userType")
        .and_then(val_i64)
        .or_else(|| account.and_then(|a| a.user_type));
    let rank = diagnosis
        .get("rank")
        .and_then(val_i64)
        .or_else(|| account.and_then(|a| a.rank));
    let vip_score = if user_type == Some(3) || rank == Some(3) || effective_price == Some(0.0) {
        1
    } else {
        0
    };
    let fail_count = account.map(|a| a.fail_count).unwrap_or(0);
    let price_score = effective_price.unwrap_or(9999.0);
    (-vip_score, price_score, -surplus_num, fail_count, index)
}

fn val_f64(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_i64().map(|i| i as f64))
        .or_else(|| v.as_str().and_then(|s| s.parse::<f64>().ok()))
}

fn val_i64(v: &Value) -> Option<i64> {
    v.as_i64()
        .or_else(|| v.as_f64().map(|f| f as i64))
        .or_else(|| v.as_str().and_then(|s| s.parse::<i64>().ok()))
}

fn val_display(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vip_zero_price_high_surplus_account_ranks_first() {
        let normal = AccountCredential {
            name: "normal".to_string(),
            user_type: Some(1),
            ..Default::default()
        };
        let vip = AccountCredential {
            name: "vip".to_string(),
            user_type: Some(3),
            ..Default::default()
        };
        let k_normal = account_schedule_key(
            Some(&normal),
            &json!({"price": 5.0, "surplusNum": 0, "userType": 1}),
            0,
        );
        let k_vip = account_schedule_key(
            Some(&vip),
            &json!({"price": 0.0, "surplusNum": 20, "userType": 3}),
            1,
        );
        assert!(k_vip < k_normal);
    }
}
