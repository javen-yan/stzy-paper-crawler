use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use serde_json::{json, Value};
use tauri::{AppHandle, State};
use tauri_plugin_opener::OpenerExt;

use crate::artifacts::ArtifactService;
use crate::auth::COOKIE_TOKEN_CONSOLE_SCRIPT;
use crate::converter::fonts::{font_status, repair_fonts as run_repair_fonts};
use crate::converter::office::detect_office_engine;
use crate::crawler::client::StzyHttpClient;
use crate::crawler::tags::{current_catalogs, refresh_catalogs as run_refresh_catalogs};
use crate::error::{AppError, AppResult};
use crate::models::{expand_tilde, now_iso_seconds, AccountCredential, AppSettings};
use crate::proxy::{bind_shenlong_local_ip, build_proxy_status};
use crate::store::SqliteStore;
use crate::task_engine::TaskManager;

#[derive(Clone)]
pub struct AppState {
    pub base_settings: AppSettings,
    pub store: SqliteStore,
    pub artifact_service: ArtifactService,
    pub task_manager: TaskManager,
}

impl AppState {
    pub fn effective_settings(&self) -> AppResult<AppSettings> {
        let mut s = self.store.effective_settings(&self.base_settings)?;
        s.data_dir = self.base_settings.data_dir.clone();
        Ok(s)
    }

    pub fn office_label(&self, settings: &AppSettings) -> String {
        detect_office_engine(settings)
            .map(|e| e.display_label())
            .unwrap_or_default()
    }
}

// -----------------------------------------------------------------------------
// Runtime & Settings Commands
// -----------------------------------------------------------------------------

#[tauri::command]
pub fn get_runtime_info(state: State<'_, AppState>) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    let has_office = detect_office_engine(&eff).is_some();
    Ok(json!({
        "mode": "gui",
        "host": "local",
        "port": 0,
        "public_base_url": "",
        "capabilities": {
            "local_file_actions": true,
            "native_desktop": true,
            "local_directory_picker": true,
            "open_local_path": true,
            "native_save_dialog": true,
            "office_converter_detected": has_office,
            "bundled_pdfium": true,
            "rust_fontdb": true,
        },
        "preview": {
            "max_pages": eff.preview_max_pages,
            "max_pixels": eff.preview_max_pixels,
            "timeout_seconds": eff.preview_timeout_seconds,
        }
    }))
}

#[tauri::command]
pub fn get_settings(state: State<'_, AppState>) -> AppResult<Value> {
    state.store.get_public_settings(&state.base_settings)
}

#[tauri::command]
pub fn update_settings(state: State<'_, AppState>, payload: Value) -> AppResult<Value> {
    let updated = state.store.update_settings(&state.base_settings, &payload)?;
    state.task_manager.apply_runtime_limits();
    Ok(updated)
}

// -----------------------------------------------------------------------------
// Accounts Pool & Auth Import Commands
// -----------------------------------------------------------------------------

#[tauri::command]
pub fn list_accounts(state: State<'_, AppState>) -> AppResult<Value> {
    let items: Vec<Value> = state
        .store
        .list_accounts()?
        .into_iter()
        .map(|a| a.to_public_json())
        .collect();
    Ok(json!({ "items": items }))
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct SaveAccountPayload {
    pub name: String,
    pub cookie: String,
    pub access_token: String,
    pub user_agent: String,
    pub request_headers_json: String,
    pub login_phone: String,
    pub login_password: String,
    pub enabled: bool,
}

impl Default for SaveAccountPayload {
    fn default() -> Self {
        Self {
            name: String::new(),
            cookie: String::new(),
            access_token: String::new(),
            user_agent: String::new(),
            request_headers_json: String::new(),
            login_phone: String::new(),
            login_password: String::new(),
            enabled: true,
        }
    }
}

#[tauri::command]
pub fn save_account(state: State<'_, AppState>, payload: SaveAccountPayload) -> AppResult<Value> {
    let saved = state.store.upsert_account(AccountCredential {
        name: payload.name,
        cookie: payload.cookie,
        access_token: payload.access_token,
        user_agent: payload.user_agent,
        request_headers_json: payload.request_headers_json,
        login_phone: payload.login_phone,
        login_password: payload.login_password,
        enabled: payload.enabled,
        import_method: "manual".to_string(),
        ..Default::default()
    })?;
    Ok(saved.to_public_json())
}

#[derive(Debug, Deserialize)]
pub struct ImportAccountPayload {
    pub raw: String,
    #[serde(default)]
    pub name: String,
}

#[tauri::command]
pub async fn import_account(
    state: State<'_, AppState>,
    payload: ImportAccountPayload,
) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    let client = StzyHttpClient::new(eff, state.store.clone(), None, None, None);
    let credential = client
        .credential_from_import(&payload.raw, &payload.name)
        .await?;
    let saved = state.store.upsert_account(credential)?;
    Ok(saved.to_public_json())
}

#[derive(Debug, Deserialize)]
pub struct PhoneLoginPayload {
    pub phone: String,
    pub password: Option<String>,
    #[serde(default)]
    pub name: String,
}

#[tauri::command]
pub async fn phone_login(
    state: State<'_, AppState>,
    payload: PhoneLoginPayload,
) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    let client = StzyHttpClient::new(eff, state.store.clone(), None, None, None);
    let credential = client
        .login_with_phone_password(&payload.phone, payload.password.as_deref(), &payload.name)
        .await?;
    let saved = state.store.upsert_account(credential)?;
    Ok(saved.to_public_json())
}

#[tauri::command]
pub fn get_auth_script() -> AppResult<Value> {
    Ok(json!({ "script": COOKIE_TOKEN_CONSOLE_SCRIPT }))
}

#[tauri::command]
pub fn set_account_enabled(
    state: State<'_, AppState>,
    name: String,
    enabled: bool,
) -> AppResult<Value> {
    let updated = state.store.set_account_enabled(&name, enabled)?;
    Ok(updated.to_public_json())
}

#[tauri::command]
pub async fn verify_account(state: State<'_, AppState>, name: String) -> AppResult<Value> {
    let account = state
        .store
        .get_account(&name)?
        .ok_or_else(|| AppError::NotFound("Account not found".to_string()))?;
    let eff = state.effective_settings()?;
    let client = StzyHttpClient::new(eff, state.store.clone(), None, None, None);

    if let Some(mut valid) = client.ensure_account_valid(account.clone()).await {
        valid.fail_count = 0;
        valid.last_error.clear();
        valid.cooldown_until.clear();
        valid.last_checked_at = now_iso_seconds();
        let saved = state.store.upsert_account(valid)?;
        return Ok(saved.to_public_json());
    }

    state
        .store
        .mark_account_failure(&name, "凭证已失效且无法自动刷新")?;
    Err(AppError::Validation(format!(
        "账号 {name} 校验未通过，请重新登录或导入最新凭证"
    )))
}

#[tauri::command]
pub fn delete_account(state: State<'_, AppState>, name: String) -> AppResult<Value> {
    state.store.delete_account(&name)?;
    Ok(json!({ "ok": true }))
}

// -----------------------------------------------------------------------------
// Catalogs, Proxy & Fonts Commands
// -----------------------------------------------------------------------------

#[tauri::command]
pub fn get_catalogs(state: State<'_, AppState>) -> AppResult<Value> {
    current_catalogs(&state.store)
}

#[tauri::command]
pub async fn refresh_catalogs(state: State<'_, AppState>) -> AppResult<Value> {
    run_refresh_catalogs(&state.base_settings, &state.store).await
}

#[tauri::command]
pub async fn get_proxy_status(state: State<'_, AppState>) -> AppResult<Value> {
    build_proxy_status(&state.base_settings, &state.store).await
}

#[tauri::command]
pub async fn bind_local_proxy_ip(state: State<'_, AppState>) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    bind_shenlong_local_ip(&eff).await
}

#[tauri::command]
pub async fn get_font_status(state: State<'_, AppState>) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    let office = state.office_label(&eff);
    tokio::task::spawn_blocking(move || font_status(&eff, None, &office))
        .await
        .map_err(|e| AppError::Runtime(format!("字体状态检测线程异常：{e}")))?
}

#[tauri::command]
pub async fn check_fonts(state: State<'_, AppState>, fonts: Vec<String>) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    let office = state.office_label(&eff);
    let set: BTreeSet<String> = fonts
        .into_iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    tokio::task::spawn_blocking(move || {
        let opt = if set.is_empty() { None } else { Some(&set) };
        font_status(&eff, opt, &office)
    })
    .await
    .map_err(|e| AppError::Runtime(format!("字体检测线程异常：{e}")))?
}

#[tauri::command]
pub async fn repair_fonts(state: State<'_, AppState>, fonts: Vec<String>) -> AppResult<Value> {
    let eff = state.effective_settings()?;
    let office = state.office_label(&eff);
    let set: BTreeSet<String> = fonts
        .into_iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    tokio::task::spawn_blocking(move || {
        let opt = if set.is_empty() { None } else { Some(&set) };
        run_repair_fonts(&eff, opt, &office)
    })
    .await
    .map_err(|e| AppError::Runtime(format!("字体补齐线程异常：{e}")))?
}

// -----------------------------------------------------------------------------
// Crawl Tasks & Real-Time Estimation Commands
// -----------------------------------------------------------------------------

#[tauri::command]
pub fn list_tasks(
    state: State<'_, AppState>,
    archived: Option<bool>,
    limit: Option<usize>,
    offset: Option<usize>,
) -> AppResult<Value> {
    let items = state.task_manager.list_tasks(
        archived.unwrap_or(false),
        limit.unwrap_or(100).clamp(1, 500),
        offset.unwrap_or(0),
    )?;
    Ok(json!({ "items": items }))
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct TaskCreatePayload {
    pub title: String,
    pub mode: String,
    pub filters: Value,
    pub filter_labels: Value,
    pub subjects: Option<Vec<Value>>,
    pub settings: Value,
    pub idempotency_key: Option<String>,
}

impl Default for TaskCreatePayload {
    fn default() -> Self {
        Self {
            title: String::new(),
            mode: "crawl".to_string(),
            filters: json!({}),
            filter_labels: json!({}),
            subjects: None,
            settings: json!({}),
            idempotency_key: None,
        }
    }
}

#[tauri::command]
pub fn create_task(state: State<'_, AppState>, payload: TaskCreatePayload) -> AppResult<Value> {
    state.task_manager.create_task(
        &payload.mode,
        payload.filters,
        payload.filter_labels,
        payload.subjects,
        payload.settings,
        payload.idempotency_key.as_deref(),
        &payload.title,
    )
}

#[tauri::command]
pub async fn estimate_task_preview(
    state: State<'_, AppState>,
    payload: TaskCreatePayload,
) -> AppResult<Value> {
    state
        .task_manager
        .estimate_preview(
            payload.filters,
            payload.filter_labels,
            payload.subjects,
            payload.settings,
            &payload.title,
        )
        .await
}

#[tauri::command(rename_all = "snake_case")]
pub fn get_task(state: State<'_, AppState>, task_id: String) -> AppResult<Value> {
    state.task_manager.get_task(&task_id)
}

#[tauri::command(rename_all = "snake_case")]
pub fn task_action(
    state: State<'_, AppState>,
    task_id: String,
    action: String,
) -> AppResult<Value> {
    match action.as_str() {
        "pause" => state.task_manager.pause_task(&task_id),
        "resume" => state.task_manager.resume_task(&task_id),
        "cancel" => state.task_manager.cancel_task(&task_id),
        "archive" => state.task_manager.archive_task(&task_id),
        other => Err(AppError::Validation(format!("未知任务动作：{other}"))),
    }
}

#[tauri::command(rename_all = "snake_case")]
pub fn get_task_logs(
    state: State<'_, AppState>,
    task_id: String,
    after: Option<i64>,
    limit: Option<usize>,
    tail: Option<bool>,
) -> AppResult<Value> {
    let cursor_in = after.unwrap_or(0);
    let items = state.task_manager.logs(
        &task_id,
        cursor_in,
        limit.unwrap_or(300).clamp(1, 2000),
        tail.unwrap_or(false),
    )?;
    let next_cursor = items
        .last()
        .and_then(|v| v.get("id"))
        .and_then(Value::as_i64)
        .unwrap_or(cursor_in);
    Ok(json!({
        "items": items,
        "next_cursor": next_cursor,
    }))
}

#[tauri::command(rename_all = "snake_case")]
pub fn get_task_resources(
    state: State<'_, AppState>,
    task_id: String,
    limit: Option<usize>,
    offset: Option<usize>,
    status: Option<String>,
) -> AppResult<Value> {
    state.task_manager.resources(
        &task_id,
        limit.unwrap_or(100).clamp(1, 500),
        offset.unwrap_or(0),
        status.as_deref().unwrap_or(""),
    )
}

// -----------------------------------------------------------------------------
// File Browser, Native Save-As & Native ZIP Export Commands
// -----------------------------------------------------------------------------

#[tauri::command(rename_all = "snake_case")]
pub fn browse_task_files(
    state: State<'_, AppState>,
    task_id: Option<String>,
    path: Option<String>,
) -> AppResult<Value> {
    state
        .artifact_service
        .browser_list(task_id.as_deref(), path.as_deref())
}

#[tauri::command(rename_all = "snake_case")]
pub fn search_task_files(
    state: State<'_, AppState>,
    task_id: Option<String>,
    path: Option<String>,
    filter: Option<String>,
    deep: Option<bool>,
) -> AppResult<Value> {
    state.artifact_service.browser_search(
        task_id.as_deref(),
        path.as_deref(),
        filter.as_deref().unwrap_or(""),
        deep.unwrap_or(true),
    )
}

#[tauri::command(rename_all = "snake_case")]
pub async fn save_browser_file(
    state: State<'_, AppState>,
    path: String,
    task_id: Option<String>,
    destination: String,
) -> AppResult<Value> {
    let art = state.artifact_service.clone();
    let dest = expand_tilde(destination.trim());
    tokio::task::spawn_blocking(move || art.save_browser_file_to(&path, task_id.as_deref(), &dest))
        .await
        .map_err(|e| AppError::Runtime(format!("文件保存线程异常：{e}")))?
}

#[tauri::command(rename_all = "snake_case")]
pub async fn export_task_zip(
    state: State<'_, AppState>,
    task_id: String,
    file_paths: Option<Vec<String>>,
    destination: String,
) -> AppResult<Value> {
    let art = state.artifact_service.clone();
    let dest = expand_tilde(destination.trim());
    let selected = file_paths.unwrap_or_default();
    tokio::task::spawn_blocking(move || art.export_zip_to_path(&task_id, &selected, &dest))
        .await
        .map_err(|e| AppError::Runtime(format!("ZIP 导出线程异常：{e}")))?
}

#[tauri::command(rename_all = "snake_case")]
pub fn open_local_path(
    app: AppHandle,
    state: State<'_, AppState>,
    path: String,
    task_id: Option<String>,
    reveal: Option<bool>,
) -> AppResult<Value> {
    let trimmed = path.trim();
    let target: PathBuf = if let Some(ref tid) = task_id.as_ref().filter(|s| !s.trim().is_empty())
    {
        if Path::new(trimmed).is_absolute() {
            expand_tilde(trimmed)
        } else {
            state
                .artifact_service
                .browser_file_path(Some(trimmed), Some(tid.as_str()), true)?
        }
    } else {
        expand_tilde(trimmed)
    };

    if !target.exists() {
        return Err(AppError::NotFound(format!(
            "本地路径不存在：{}",
            target.display()
        )));
    }

    if reveal.unwrap_or(false) && target.is_file() {
        app.opener()
            .reveal_item_in_dir(&target)
            .map_err(|e| AppError::Message(format!("在系统文件管理器中显示失败：{e}")))?;
    } else {
        let open_str = target.to_string_lossy().to_string();
        app.opener()
            .open_path(open_str, None::<&str>)
            .map_err(|e| AppError::Message(format!("打开本地路径失败：{e}")))?;
    }

    Ok(json!({ "ok": true, "path": target.to_string_lossy().to_string() }))
}
