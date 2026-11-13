use std::collections::BTreeMap;

use serde_json::{json, Value};
use url::Url;

use crate::crawler::client::StzyHttpClient;
use crate::crypto::{stzy_decrypt_text, stzy_encrypt_json};
use crate::error::AppResult;
use crate::models::{
    CrawlCombo, CrawlFilters, ResourceRecord, ResourceStatus, DEFAULT_CDN_BASE_URL,
};

#[derive(Clone)]
pub struct StzyCrawlerApi {
    pub client: StzyHttpClient,
}

impl StzyCrawlerApi {
    pub fn new(client: StzyHttpClient) -> Self {
        Self { client }
    }

    pub async fn list_resources(
        &self,
        combo: &CrawlCombo,
        filters: &CrawlFilters,
        page_num: usize,
    ) -> AppResult<Value> {
        let mut params = json!({
            "sort": 0,
            "answerFlag": 2,
            "explainsFlag": 2,
            "audio": 2,
            "studyPhaseCode": self.client.settings.study_phase_code,
            "cityCode": "",
            "areaCode": "",
            "organizationCode": "",
            "area": "",
            "keyWord": "",
            "filterQuestionFlag": false,
            "searchScope": 0,
            "searchType": 1,
            "source": 1,
            "treeIds": [],
            "fileType": filters.file_type,
        });
        if let Value::Object(ref mut map) = params {
            if !self.client.settings.subject_code.is_empty() {
                map.insert(
                    "subjectCode".to_string(),
                    Value::String(self.client.settings.subject_code.clone()),
                );
            }
            for (k, v) in combo.params() {
                map.insert(k, Value::String(v));
            }
        }
        let payload = json!({
            "pageNum": page_num,
            "pageSize": 10,
            "params": params,
        });
        let resp = self
            .client
            .post_json(
                "/zw-search/api/v1/homeEs/resource/textbookQuery",
                &payload,
                None,
                "",
            )
            .await?;
        Ok(resp.get("data").cloned().unwrap_or_else(|| json!({})))
    }

    pub async fn resource_detail(&self, resource_id: &str, resource_name: &str) -> AppResult<Value> {
        let resp = self
            .client
            .get_json(
                &format!("/zw-resource/api/v1/tkResource/detail/{resource_id}"),
                None,
                resource_name,
            )
            .await?;
        Ok(resp.get("data").cloned().unwrap_or_else(|| json!({})))
    }

    pub async fn resource_pictures(
        &self,
        resource_id: &str,
        resource_name: &str,
    ) -> AppResult<Vec<String>> {
        let resp = self
            .client
            .get_json(
                &format!("/zw-resource/api/v1/tkResource/resourcePicList/{resource_id}"),
                None,
                resource_name,
            )
            .await?;
        let arr = resp
            .get("data")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        Ok(arr
            .into_iter()
            .filter_map(|v| v.as_str().map(str::trim).filter(|s| !s.is_empty()).map(ToString::to_string))
            .collect())
    }

    pub async fn check_download_info(
        &self,
        resource_id: &str,
        headers: &BTreeMap<String, String>,
        resource_name: &str,
    ) -> AppResult<Value> {
        let resp = self
            .client
            .get_json(
                &format!("/zw-resource/api/v1/tkResource/checkDownloadNum/{resource_id}"),
                Some(headers),
                resource_name,
            )
            .await?;
        Ok(resp.get("data").cloned().unwrap_or_else(|| json!({})))
    }

    pub async fn download_resource_url(
        &self,
        resource_id: &str,
        headers: &BTreeMap<String, String>,
        resource_name: &str,
    ) -> AppResult<String> {
        let encrypted_dto = stzy_encrypt_json(&json!({ "id": resource_id }))?;
        let resp = self
            .client
            .post_json(
                "/zw-resource/api/v1/tkResource/download",
                &json!({ "resourceDownloadDto": encrypted_dto }),
                Some(headers),
                resource_name,
            )
            .await?;
        let encrypted_url = resp
            .get("data")
            .and_then(|d| d.get("resUrl"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if encrypted_url.is_empty() {
            return Ok(String::new());
        }
        let resource_path = stzy_decrypt_text(encrypted_url)?.trim().to_string();
        if resource_path.starts_with("http://") || resource_path.starts_with("https://") {
            return Ok(resource_path);
        }
        let base = Url::parse(DEFAULT_CDN_BASE_URL).unwrap();
        Ok(base
            .join(&resource_path)
            .map(|u| u.to_string())
            .unwrap_or_else(|_| format!("{DEFAULT_CDN_BASE_URL}{}", resource_path.trim_start_matches('/'))))
    }
}

pub fn build_record(item: &Value, combo: &CrawlCombo, subject_name: &str) -> ResourceRecord {
    let names = combo.names();
    let str_field = |key: &str| -> Option<String> {
        item.get(key).and_then(|v| match v {
            Value::String(s) if !s.trim().is_empty() => Some(s.trim().to_string()),
            Value::Number(n) => Some(n.to_string()),
            _ => None,
        })
    };
    let price = item
        .get("price")
        .and_then(|v| {
            v.as_f64()
                .or_else(|| v.as_i64().map(|i| i as f64))
                .or_else(|| v.as_str().and_then(|s| s.parse::<f64>().ok()))
        })
        .unwrap_or(0.0);
    let page_count = item
        .get("pageNum")
        .and_then(|v| {
            v.as_u64()
                .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
        })
        .unwrap_or(0) as usize;

    let resource_id = str_field("resourceId")
        .or_else(|| str_field("id"))
        .unwrap_or_default();
    let resource_name = str_field("resourceName").unwrap_or_default();

    ResourceRecord {
        resource_id,
        resource_name,
        subject: subject_name.to_string(),
        year: str_field("yearCode").unwrap_or_else(|| names["year"].clone()),
        scene: str_field("sceneName").unwrap_or_else(|| names["scene"].clone()),
        rank: str_field("rankName").unwrap_or_else(|| names["rank"].clone()),
        province: str_field("provinceName").unwrap_or_else(|| names["province"].clone()),
        grade: str_field("gradeName").unwrap_or_else(|| names["grade"].clone()),
        term: str_field("termName").unwrap_or_else(|| names["term"].clone()),
        price,
        page_count,
        image_count: 0,
        status: ResourceStatus::Pending,
        error: String::new(),
        local_dir: String::new(),
        raw: item.clone(),
    }
}
