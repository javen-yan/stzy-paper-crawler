use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use chrono::Local;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DEFAULT_API_BASE_URL: &str = "https://qms.stzy.com/matrix";
pub const DEFAULT_SITE_BASE_URL: &str = "https://www.stzy.com";
pub const DEFAULT_CDN_BASE_URL: &str = "https://cdn.stzy.com/";
pub const DEFAULT_USER_AGENT: &str =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppSettings {
    pub output_dir: PathBuf,
    pub data_dir: PathBuf,
    pub max_active_tasks: usize,
    pub max_download_workers: usize,
    pub max_convert_workers: usize,
    pub max_export_workers: usize,
    pub preview_max_pages: usize,
    pub preview_max_pixels: usize,
    pub preview_timeout_seconds: u64,
    pub document_timeout_seconds: u64,
    pub task_scope: String,

    pub api_base_url: String,
    pub site_base_url: String,
    pub study_phase_code: String,
    pub subject_code: String,
    pub subject_name: String,
    pub file_type: String,
    pub max_pages_per_combo: Option<usize>,

    pub list_delay_seconds: f64,
    pub image_delay_seconds: f64,
    pub list_max_retries: usize,
    pub combo_failure_limit: usize,
    pub concurrency: usize,
    pub max_retries: usize,
    pub connect_timeout: f64,
    pub read_timeout: f64,

    pub proxy_mode: String,
    pub proxy_provider: String,
    pub proxy_pool: String,
    pub proxy_api_url: String,
    pub proxy_max_failures: usize,
    pub proxy_cooldown_seconds: f64,
    pub proxy_min_ttl_seconds: f64,
    pub shenlong_whitelist_key: String,
    pub shenlong_whitelist_sign: String,
    pub user_agent: String,

    pub word_font_policy: String,
    pub word_font_auto_install: bool,
    pub word_font_dir: String,
    pub soffice_path: String,
}

impl Default for AppSettings {
    fn default() -> Self {
        let data_dir = default_app_data_dir();
        let output_dir = default_output_dir(&data_dir);
        Self {
            output_dir,
            data_dir,
            max_active_tasks: 2,
            max_download_workers: 4,
            max_convert_workers: 2,
            max_export_workers: 1,
            preview_max_pages: 300,
            preview_max_pixels: 24_000_000,
            preview_timeout_seconds: 45,
            document_timeout_seconds: 180,
            task_scope: String::new(),
            api_base_url: DEFAULT_API_BASE_URL.to_string(),
            site_base_url: DEFAULT_SITE_BASE_URL.to_string(),
            study_phase_code: "200".to_string(),
            subject_code: String::new(),
            subject_name: "不限".to_string(),
            file_type: String::new(),
            max_pages_per_combo: None,
            list_delay_seconds: 0.8,
            image_delay_seconds: 0.3,
            list_max_retries: 3,
            combo_failure_limit: 10,
            concurrency: 1,
            max_retries: 3,
            connect_timeout: 6.0,
            read_timeout: 30.0,
            proxy_mode: "off".to_string(),
            proxy_provider: "generic".to_string(),
            proxy_pool: String::new(),
            proxy_api_url: String::new(),
            proxy_max_failures: 3,
            proxy_cooldown_seconds: 300.0,
            proxy_min_ttl_seconds: 30.0,
            shenlong_whitelist_key: String::new(),
            shenlong_whitelist_sign: String::new(),
            user_agent: DEFAULT_USER_AGENT.to_string(),
            word_font_policy: "substitute".to_string(),
            word_font_auto_install: true,
            word_font_dir: String::new(),
            soffice_path: String::new(),
        }
    }
}

pub fn default_app_data_dir() -> PathBuf {
    if let Ok(custom) = std::env::var("STZY_DESKTOP_DATA_DIR") {
        let trimmed = custom.trim();
        if !trimmed.is_empty() {
            return expand_tilde(trimmed);
        }
    }
    dirs::data_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("com.stzy.desktop")
}

pub fn default_output_dir(data_dir: &Path) -> PathBuf {
    dirs::download_dir()
        .map(|d| d.join("STZY-Papers"))
        .unwrap_or_else(|| data_dir.join("output"))
}

pub fn expand_tilde(path: &str) -> PathBuf {
    if let Some(rest) = path.strip_prefix("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(rest);
        }
    }
    PathBuf::from(path)
}

pub fn safe_filename(value: &str, fallback: &str) -> String {
    let illegal = Regex::new(r#"[\\/:*?"<>|\n\r\t]+"#).unwrap();
    let spaces = Regex::new(r"\s+").unwrap();
    let replaced = illegal.replace_all(value, "_");
    let trimmed = replaced.trim_matches(|c| c == ' ' || c == '.' || c == '_');
    let collapsed = spaces.replace_all(trimmed, " ");
    let limited: String = collapsed.chars().take(120).collect();
    if limited.is_empty() {
        fallback.to_string()
    } else {
        limited
    }
}

pub fn ensure_directory(path: &Path) -> std::io::Result<PathBuf> {
    fs::create_dir_all(path)?;
    Ok(path.to_path_buf())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceStatus {
    Pending,
    Downloading,
    Completed,
    Partial,
    SkippedPaid,
    PaidUnavailable,
    Failed,
}

impl ResourceStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Downloading => "downloading",
            Self::Completed => "completed",
            Self::Partial => "partial",
            Self::SkippedPaid => "skipped_paid",
            Self::PaidUnavailable => "paid_unavailable",
            Self::Failed => "failed",
        }
    }

    pub fn from_str_lossy(value: &str) -> Self {
        match value {
            "downloading" => Self::Downloading,
            "completed" => Self::Completed,
            "partial" => Self::Partial,
            "skipped_paid" => Self::SkippedPaid,
            "paid_unavailable" => Self::PaidUnavailable,
            "failed" => Self::Failed,
            _ => Self::Pending,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TagOption {
    pub field: String,
    pub code: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CrawlCombo {
    pub scene: TagOption,
    pub year: TagOption,
    pub rank: TagOption,
    pub province: TagOption,
    pub grade: TagOption,
    pub term: TagOption,
}

impl CrawlCombo {
    pub fn params(&self) -> BTreeMap<String, String> {
        let mut map = BTreeMap::new();
        for (k, v) in [
            ("sceneCode", &self.scene.code),
            ("yearCode", &self.year.code),
            ("rank", &self.rank.code),
            ("provinceCode", &self.province.code),
            ("gradeCode", &self.grade.code),
            ("termCode", &self.term.code),
        ] {
            if !v.is_empty() {
                map.insert(k.to_string(), v.clone());
            }
        }
        map
    }

    pub fn names(&self) -> BTreeMap<String, String> {
        BTreeMap::from([
            ("scene".to_string(), self.scene.name.clone()),
            ("year".to_string(), self.year.name.clone()),
            ("rank".to_string(), self.rank.name.clone()),
            ("province".to_string(), self.province.name.clone()),
            ("grade".to_string(), self.grade.name.clone()),
            ("term".to_string(), self.term.name.clone()),
        ])
    }

    pub fn state_key(&self, subject_code: &str) -> String {
        format!(
            "{}|{}|{}|{}|{}|{}|{}",
            subject_code,
            self.scene.code,
            self.year.code,
            self.rank.code,
            self.province.code,
            self.grade.code,
            self.term.code
        )
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct CrawlFilters {
    pub scenes: Vec<String>,
    pub years: Vec<String>,
    pub ranks: Vec<String>,
    pub provinces: Vec<String>,
    pub grades: Vec<String>,
    pub terms: Vec<String>,
    pub file_type: String,
    pub max_pages_per_combo: Option<usize>,
    pub download_paid: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResourceRecord {
    pub resource_id: String,
    pub resource_name: String,
    #[serde(default)]
    pub subject: String,
    #[serde(default)]
    pub year: String,
    #[serde(default)]
    pub scene: String,
    #[serde(default)]
    pub rank: String,
    #[serde(default)]
    pub province: String,
    #[serde(default)]
    pub grade: String,
    #[serde(default)]
    pub term: String,
    #[serde(default)]
    pub price: f64,
    #[serde(default)]
    pub page_count: usize,
    #[serde(default)]
    pub image_count: usize,
    pub status: ResourceStatus,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub local_dir: String,
    #[serde(default)]
    pub raw: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadResult {
    pub status: ResourceStatus,
    pub saved_pages: usize,
    pub expected_pages: usize,
    pub source: String,
    pub local_dir: String,
    pub error: String,
    pub images_added: usize,
    pub paid_unavailable: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct CrawlStats {
    pub task_mode: String,
    pub phase: String,
    pub outcome: String,
    pub total_combos: usize,
    pub completed_combos: usize,
    pub resources_seen: usize,
    pub resources_total: usize,
    pub resources_completed: usize,
    pub current_resource_name: String,
    pub images_downloaded: usize,
    pub paid_skipped: usize,
    pub filtered_skipped: usize,
    pub preview_limited: usize,
    pub failed: usize,
    pub running: bool,
    pub paused: bool,
    pub aborted: bool,
    pub error: String,
}

impl Default for CrawlStats {
    fn default() -> Self {
        Self {
            task_mode: "idle".to_string(),
            phase: "preview".to_string(),
            outcome: String::new(),
            total_combos: 0,
            completed_combos: 0,
            resources_seen: 0,
            resources_total: 0,
            resources_completed: 0,
            current_resource_name: String::new(),
            images_downloaded: 0,
            paid_skipped: 0,
            filtered_skipped: 0,
            preview_limited: 0,
            failed: 0,
            running: false,
            paused: false,
            aborted: false,
            error: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AccountCredential {
    pub name: String,
    pub cookie: String,
    pub access_token: String,
    pub user_agent: String,
    pub request_headers_json: String,
    pub import_method: String,
    pub login_phone: String,
    pub login_password: String,
    pub enabled: bool,
    pub user_type: Option<i64>,
    pub rank: Option<i64>,
    pub last_price: Option<f64>,
    pub surplus_num: Option<i64>,
    pub fail_count: i64,
    pub last_error: String,
    pub cooldown_until: String,
    pub last_checked_at: String,
}

impl Default for AccountCredential {
    fn default() -> Self {
        Self {
            name: String::new(),
            cookie: String::new(),
            access_token: String::new(),
            user_agent: String::new(),
            request_headers_json: String::new(),
            import_method: String::new(),
            login_phone: String::new(),
            login_password: String::new(),
            enabled: true,
            user_type: None,
            rank: None,
            last_price: None,
            surplus_num: None,
            fail_count: 0,
            last_error: String::new(),
            cooldown_until: String::new(),
            last_checked_at: String::new(),
        }
    }
}

impl AccountCredential {
    pub fn usable(&self) -> bool {
        self.enabled
            && (!self.cookie.is_empty()
                || !self.access_token.is_empty()
                || !self.login_phone.is_empty())
    }

    pub fn request_headers(&self) -> BTreeMap<String, String> {
        let Ok(Value::Object(map)) = serde_json::from_str::<Value>(&self.request_headers_json)
        else {
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

    pub fn in_cooldown(&self) -> bool {
        if self.cooldown_until.is_empty() {
            return false;
        }
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(&self.cooldown_until, "%Y-%m-%dT%H:%M:%S") {
            return dt > Local::now().naive_local();
        }
        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(&self.cooldown_until) {
            return dt.with_timezone(&Local) > Local::now();
        }
        false
    }

    pub fn account_type_label(&self) -> String {
        if self.user_type == Some(3) || self.rank == Some(3) || self.last_price == Some(0.0) {
            return "VIP/高端".to_string();
        }
        if let Some(ut) = self.user_type {
            if ut != 0 {
                return format!("类型{ut}");
            }
        }
        "未知".to_string()
    }

    pub fn health_label(&self) -> String {
        if !self.enabled {
            return "停用".to_string();
        }
        if self.in_cooldown() {
            return "冷却中".to_string();
        }
        if self.fail_count > 0 {
            return format!("失败{}次", self.fail_count);
        }
        "正常".to_string()
    }

    pub fn to_public_json(&self) -> Value {
        let mask = |s: &str| if s.is_empty() { "" } else { "***" };
        serde_json::json!({
            "name": self.name,
            "cookie": mask(&self.cookie),
            "access_token": mask(&self.access_token),
            "user_agent": self.user_agent,
            "request_headers_json": mask(&self.request_headers_json),
            "import_method": self.import_method,
            "login_phone": self.login_phone,
            "login_password": mask(&self.login_password),
            "enabled": self.enabled,
            "user_type": self.user_type,
            "rank": self.rank,
            "last_price": self.last_price,
            "surplus_num": self.surplus_num,
            "fail_count": self.fail_count,
            "last_error": self.last_error,
            "cooldown_until": self.cooldown_until,
            "last_checked_at": self.last_checked_at,
            "usable": self.usable(),
            "in_cooldown": self.in_cooldown(),
            "account_type_label": self.account_type_label(),
            "health_label": self.health_label(),
        })
    }
}

/// Stable on-disk resource path layout identical to Python `ResourcePathBuilder`.
#[derive(Clone)]
pub struct ResourcePathBuilder {
    output_dir: PathBuf,
    subject_code: String,
}

impl ResourcePathBuilder {
    pub fn new(settings: &AppSettings) -> Self {
        Self {
            output_dir: settings.output_dir.clone(),
            subject_code: settings.subject_code.clone(),
        }
    }

    pub fn resource_dir(&self, record: &ResourceRecord) -> PathBuf {
        let subject_fallback = if self.subject_code.is_empty() {
            "unknown"
        } else {
            &self.subject_code
        };
        let id_fallback = if record.resource_id.is_empty() {
            "unknown"
        } else {
            &record.resource_id
        };
        self.output_dir
            .join(safe_filename(&record.subject, subject_fallback))
            .join(safe_filename(&record.grade, "unknown"))
            .join(safe_filename(&Self::term_dir_name(&record.term), "unknown"))
            .join(safe_filename(&Self::province_dir_name(&record.province), "unknown"))
            .join(safe_filename(&record.scene, "unknown"))
            .join(safe_filename(&record.resource_name, id_fallback))
    }

    pub fn term_dir_name(term: &str) -> String {
        if term.ends_with('上') {
            "上学期".to_string()
        } else if term.ends_with('下') {
            "下学期".to_string()
        } else {
            term.to_string()
        }
    }

    pub fn province_dir_name(province: &str) -> String {
        match province {
            "北京" | "天津" | "上海" | "重庆" => format!("{province}市"),
            _ => province.to_string(),
        }
    }
}

/// Owns the on-disk artifact layout for one downloaded resource.
pub struct ResourceArtifacts {
    pub resource_dir: PathBuf,
}

impl ResourceArtifacts {
    pub fn new(resource_dir: PathBuf) -> Self {
        Self { resource_dir }
    }

    pub fn original_dir(&self) -> PathBuf {
        self.resource_dir.join("original")
    }

    pub fn temp_pdf(&self) -> PathBuf {
        self.resource_dir.join("原文.pdf")
    }

    pub fn final_pdf(&self) -> PathBuf {
        let parent = self
            .resource_dir
            .parent()
            .unwrap_or_else(|| Path::new("."));
        let name = self
            .resource_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("resource");
        parent.join(format!("{name}.pdf"))
    }

    pub fn page_png(&self, index: usize) -> PathBuf {
        self.resource_dir.join(format!("练习{index}.png"))
    }

    pub fn prepare_resource_dir(&self) -> std::io::Result<()> {
        fs::create_dir_all(&self.resource_dir)
    }

    pub fn prepare_original_dir(&self) -> std::io::Result<()> {
        fs::create_dir_all(self.original_dir())
    }

    pub fn publish_pdf(&self, source_pdf: &Path) -> std::io::Result<PathBuf> {
        let final_pdf = self.final_pdf();
        if let Some(parent) = final_pdf.parent() {
            fs::create_dir_all(parent)?;
        }
        if source_pdf != final_pdf {
            fs::rename(source_pdf, &final_pdf).or_else(|_: std::io::Error| {
                fs::copy(source_pdf, &final_pdf)?;
                let _ = fs::remove_file(source_pdf);
                Ok::<(), std::io::Error>(())
            })?;
        }
        Ok(final_pdf)
    }

    pub fn cleanup_transient_artifacts(&self) {
        let orig = self.original_dir();
        if orig.exists() {
            let _ = fs::remove_dir_all(orig);
        }
        let temp = self.temp_pdf();
        if temp.exists() {
            let _ = fs::remove_file(temp);
        }
    }
}

pub fn now_iso_seconds() -> String {
    Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}
