pub mod artifacts;
pub mod auth;
pub mod commands;
pub mod converter;
pub mod crawler;
pub mod crypto;
pub mod error;
pub mod models;
pub mod protocol;
pub mod proxy;
pub mod store;
pub mod task_engine;
pub mod updater;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{Emitter, Manager};

use crate::artifacts::ArtifactService;
use crate::commands::AppState;
use crate::converter::pdf::register_pdfium_resource_dir;
use crate::models::{ensure_directory, AppSettings};
use crate::store::SqliteStore;
use crate::task_engine::TaskManager;

fn resolve_default_dirs<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> (PathBuf, PathBuf) {
    let data_dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| {
            dirs::data_local_dir()
                .unwrap_or_else(|| PathBuf::from("."))
                .join("com.stzy.desktop")
        });

    let output_dir = app
        .path()
        .download_dir()
        .or_else(|_| app.path().document_dir())
        .unwrap_or_else(|_| {
            dirs::download_dir()
                .or_else(dirs::document_dir)
                .unwrap_or_else(|| data_dir.clone())
        })
        .join("STZY-Papers");

    let _ = ensure_directory(&data_dir);
    let _ = ensure_directory(&output_dir);
    (data_dir, output_dir)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .try_init();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .register_uri_scheme_protocol("stzyfile", protocol::handle_stzyfile_request)
        .setup(|app| {
            let handle = app.handle().clone();
            if let Ok(res_dir) = app.path().resource_dir() {
                register_pdfium_resource_dir(res_dir.clone());
                register_pdfium_resource_dir(res_dir.join("resources"));
            }

            let (data_dir, default_output_dir) = resolve_default_dirs(&handle);
            let mut base_settings = AppSettings::default();
            base_settings.data_dir = data_dir.clone();
            base_settings.output_dir = default_output_dir;

            let store = SqliteStore::open(&data_dir)
                .map_err(|e| format!("初始化本地数据库失败：{e}"))?;
            let artifact_service = ArtifactService::new(store.clone(), base_settings.clone());
            let task_manager =
                TaskManager::new(base_settings.clone(), store.clone(), artifact_service.clone());

            let emit_handle = handle.clone();
            task_manager.set_event_emitter(Arc::new(move |event_name, payload| {
                let _ = emit_handle.emit(event_name, payload);
            }));

            task_manager.enqueue_startup_tasks();

            app.manage(AppState {
                base_settings,
                store,
                artifact_service,
                task_manager,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_runtime_info,
            commands::get_settings,
            commands::update_settings,
            commands::list_accounts,
            commands::save_account,
            commands::import_account,
            commands::phone_login,
            commands::get_auth_script,
            commands::set_account_enabled,
            commands::verify_account,
            commands::delete_account,
            commands::get_catalogs,
            commands::refresh_catalogs,
            commands::get_proxy_status,
            commands::bind_local_proxy_ip,
            commands::get_font_status,
            commands::check_fonts,
            commands::repair_fonts,
            commands::list_tasks,
            commands::create_task,
            commands::estimate_task_preview,
            commands::get_task,
            commands::task_action,
            commands::get_task_logs,
            commands::get_task_resources,
            commands::browse_task_files,
            commands::search_task_files,
            commands::save_browser_file,
            commands::export_task_zip,
            commands::open_local_path,
            commands::open_external_url,
            commands::check_app_update,
            commands::install_app_update,
        ])
        .run(tauri::generate_context!())
        .expect("error while running STZY Desktop application");
}
