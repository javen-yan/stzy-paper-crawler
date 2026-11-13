use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use tauri_plugin_updater::UpdaterExt;

use crate::commands::AppState;
use crate::error::{AppError, AppResult};

const DEFAULT_RELEASE_URL: &str = "https://github.com/javen-yan/stzy-paper-crawler/releases/latest";

fn emit_progress(app: &AppHandle, phase: &str, downloaded: u64, total: Option<u64>, percent: f64) {
    let _ = app.emit(
        "updater:progress",
        json!({
            "phase": phase,
            "downloaded": downloaded,
            "total": total,
            "percent": (percent * 10.0).round() / 10.0,
        }),
    );
}

pub async fn check_for_app_update(app: &AppHandle, state: &AppState) -> AppResult<Value> {
    let current_version = app.package_info().version.to_string();
    let running_tasks = state.task_manager.active_task_count();

    let updater = app
        .updater_builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|e| AppError::Runtime(format!("初始化更新组件失败：{e}")))?;

    let maybe_update = updater.check().await.map_err(|e| {
        AppError::Message(format!(
            "连接更新源失败：{e}（可稍后重试，或点击网页下载最新安装包）"
        ))
    })?;

    if let Some(update) = maybe_update {
        let tag_version = update.version.trim_start_matches('v');
        let release_url = format!(
            "https://github.com/javen-yan/stzy-paper-crawler/releases/tag/v{}",
            tag_version
        );
        let pub_date = update
            .date
            .map(|d| format!("{:04}-{:02}-{:02}", d.year(), d.month() as u8, d.day()))
            .unwrap_or_default();

        Ok(json!({
            "current_version": current_version,
            "available": true,
            "version": update.version,
            "date": pub_date,
            "body": update.body.unwrap_or_default(),
            "release_url": release_url,
            "running_tasks": running_tasks,
        }))
    } else {
        Ok(json!({
            "current_version": current_version,
            "available": false,
            "release_url": DEFAULT_RELEASE_URL,
            "running_tasks": running_tasks,
        }))
    }
}

pub async fn download_and_install_app_update(app: &AppHandle, state: &AppState) -> AppResult<Value> {
    let updater = app
        .updater_builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| AppError::Runtime(format!("初始化更新组件失败：{e}")))?;

    let update = updater
        .check()
        .await
        .map_err(|e| AppError::Message(format!("获取更新清单失败：{e}")))?
        .ok_or_else(|| AppError::Conflict("当前已是最新版本，无需升级".to_string()))?;

    let mut downloaded_bytes: u64 = 0;
    emit_progress(app, "downloading", 0, None, 0.0);

    let package_bytes = update
        .download(
            |chunk_length, content_length| {
                downloaded_bytes = downloaded_bytes.saturating_add(chunk_length as u64);
                let pct = content_length
                    .filter(|&total| total > 0)
                    .map(|total| ((downloaded_bytes as f64 / total as f64) * 100.0).min(100.0))
                    .unwrap_or(0.0);
                emit_progress(app, "downloading", downloaded_bytes, content_length, pct);
            },
            || {},
        )
        .await
        .map_err(|e| {
            AppError::Message(format!(
                "下载或校验更新包失败：{e}（可能是网络波动，可重试或前往网页手动下载）"
            ))
        })?;

    emit_progress(
        app,
        "pausing_tasks",
        downloaded_bytes,
        Some(downloaded_bytes),
        100.0,
    );
    let _ = state.task_manager.pause_active_tasks_for_restart().await;

    emit_progress(
        app,
        "installing",
        downloaded_bytes,
        Some(downloaded_bytes),
        100.0,
    );
    update
        .install(package_bytes)
        .map_err(|e| AppError::Runtime(format!("写入新版本安装包失败：{e}")))?;

    emit_progress(
        app,
        "restarting",
        downloaded_bytes,
        Some(downloaded_bytes),
        100.0,
    );
    tokio::time::sleep(Duration::from_millis(350)).await;
    crate::tray::mark_exiting();
    app.restart();
}
