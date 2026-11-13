use std::sync::atomic::{AtomicBool, Ordering};

use serde_json::json;
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Window};
use tauri_plugin_opener::OpenerExt;

use crate::commands::AppState;
use crate::models::ensure_directory;

const TRAY_ID: &str = "main-tray";
static EXITING: AtomicBool = AtomicBool::new(false);

pub struct TrayMenuState {
    pub status_item: MenuItem<tauri::Wry>,
    pub pause_all_item: MenuItem<tauri::Wry>,
    pub resume_all_item: MenuItem<tauri::Wry>,
}

pub fn is_exiting() -> bool {
    EXITING.load(Ordering::SeqCst)
}

pub fn mark_exiting() {
    EXITING.store(true, Ordering::SeqCst);
}

pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

pub fn hide_window_to_tray(window: &Window) {
    if window.is_fullscreen().unwrap_or(false) {
        let _ = window.set_fullscreen(false);
    }
    let _ = window.hide();
}

fn load_tray_icon(app: &AppHandle) -> Option<Image<'static>> {
    #[cfg(target_os = "macos")]
    let bytes: &[u8] = include_bytes!("../icons/tray-macos.png");
    #[cfg(not(target_os = "macos"))]
    let bytes: &[u8] = include_bytes!("../icons/32x32.png");

    if let Ok(decoded) = image::load_from_memory(bytes) {
        let rgba = decoded.to_rgba8();
        let (width, height) = rgba.dimensions();
        return Some(Image::new_owned(rgba.into_raw(), width, height));
    }

    app.default_window_icon().map(|ic| ic.clone().to_owned())
}

pub fn refresh_tray_state(app: &AppHandle) {
    let Some(app_state) = app.try_state::<AppState>() else {
        return;
    };
    let (active_count, resumable_count) = app_state.task_manager.tray_task_summary();

    if let Some(menu_state) = app.try_state::<TrayMenuState>() {
        let status_label = if active_count > 0 && resumable_count > 0 {
            format!("状态：下载中（{active_count} 进行中 · {resumable_count} 已暂停）")
        } else if active_count > 0 {
            format!("状态：正在后台下载（{active_count} 个任务运行中）")
        } else if resumable_count > 0 {
            format!("状态：后台待命（{resumable_count} 个暂停任务可继续）")
        } else {
            "状态：后台待命（无运行中任务）".to_string()
        };
        let _ = menu_state.status_item.set_text(status_label);

        let pause_label = if active_count > 0 {
            format!("暂停全部下载任务 ({active_count})")
        } else {
            "暂停全部下载任务".to_string()
        };
        let _ = menu_state.pause_all_item.set_text(pause_label);
        let _ = menu_state.pause_all_item.set_enabled(active_count > 0);

        let resume_label = if resumable_count > 0 {
            format!("继续已暂停任务 ({resumable_count})")
        } else {
            "继续已暂停任务".to_string()
        };
        let _ = menu_state.resume_all_item.set_text(resume_label);
        let _ = menu_state.resume_all_item.set_enabled(resumable_count > 0);
    }

    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let tooltip = if active_count > 0 {
            format!("PaperDesk · 正在后台下载 ({active_count} 个任务)")
        } else {
            "PaperDesk · 试卷下载器".to_string()
        };
        let _ = tray.set_tooltip(Some(&tooltip));
    }
}

pub fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let status_item = MenuItem::with_id(
        app,
        "status_summary",
        "状态：后台待命（无运行中任务）",
        false,
        None::<&str>,
    )?;
    let sep_status = PredefinedMenuItem::separator(app)?;

    let show_main_item = MenuItem::with_id(app, "show_main", "显示主窗口", true, None::<&str>)?;
    let new_task_item = MenuItem::with_id(app, "new_task", "新建下载任务…", true, None::<&str>)?;
    let open_dir_item =
        MenuItem::with_id(app, "open_output_dir", "打开下载文件夹", true, None::<&str>)?;
    let sep_tasks = PredefinedMenuItem::separator(app)?;

    let pause_all_item =
        MenuItem::with_id(app, "pause_all", "暂停全部下载任务", false, None::<&str>)?;
    let resume_all_item =
        MenuItem::with_id(app, "resume_all", "继续已暂停任务", false, None::<&str>)?;
    let sep_nav = PredefinedMenuItem::separator(app)?;

    let nav_files_item = MenuItem::with_id(app, "nav_files", "浏览本地文件", true, None::<&str>)?;
    let nav_accounts_item =
        MenuItem::with_id(app, "nav_accounts", "账号管理", true, None::<&str>)?;
    let nav_settings_item =
        MenuItem::with_id(app, "nav_settings", "系统设置", true, None::<&str>)?;
    let check_update_item =
        MenuItem::with_id(app, "check_update", "检查软件更新…", true, None::<&str>)?;
    let sep_quit = PredefinedMenuItem::separator(app)?;

    let quit_item = MenuItem::with_id(app, "quit", "退出 PaperDesk", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &status_item,
            &sep_status,
            &show_main_item,
            &new_task_item,
            &open_dir_item,
            &sep_tasks,
            &pause_all_item,
            &resume_all_item,
            &sep_nav,
            &nav_files_item,
            &nav_accounts_item,
            &nav_settings_item,
            &check_update_item,
            &sep_quit,
            &quit_item,
        ],
    )?;

    app.manage(TrayMenuState {
        status_item,
        pause_all_item,
        resume_all_item,
    });

    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip("PaperDesk · 试卷下载器")
        .show_menu_on_left_click(cfg!(target_os = "macos"))
        .icon_as_template(cfg!(target_os = "macos"))
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show_main" => {
                show_main_window(app);
            }
            "new_task" => {
                show_main_window(app);
                let _ = app.emit("tray:action", json!({ "action": "new_task" }));
            }
            "open_output_dir" => {
                if let Some(state) = app.try_state::<AppState>() {
                    let root = state.artifact_service.current_output_root();
                    let _ = ensure_directory(&root);
                    let _ = app
                        .opener()
                        .open_path(root.to_string_lossy().to_string(), None::<&str>);
                }
            }
            "pause_all" => {
                if let Some(state) = app.try_state::<AppState>() {
                    let count = state.task_manager.pause_all_active_tasks();
                    refresh_tray_state(app);
                    if count > 0 {
                        let _ = app.emit(
                            "tray:action",
                            json!({
                                "action": "tasks_changed",
                                "toast": format!("已在后台暂停 {count} 个下载任务"),
                            }),
                        );
                    }
                }
            }
            "resume_all" => {
                if let Some(state) = app.try_state::<AppState>() {
                    let count = state.task_manager.resume_all_paused_tasks();
                    refresh_tray_state(app);
                    if count > 0 {
                        let _ = app.emit(
                            "tray:action",
                            json!({
                                "action": "tasks_changed",
                                "toast": format!("已在后台继续 {count} 个下载任务"),
                            }),
                        );
                    }
                }
            }
            "nav_files" => {
                show_main_window(app);
                let _ = app.emit(
                    "tray:action",
                    json!({ "action": "navigate", "path": "/files" }),
                );
            }
            "nav_accounts" => {
                show_main_window(app);
                let _ = app.emit(
                    "tray:action",
                    json!({ "action": "navigate", "path": "/accounts" }),
                );
            }
            "nav_settings" => {
                show_main_window(app);
                let _ = app.emit(
                    "tray:action",
                    json!({ "action": "navigate", "path": "/settings" }),
                );
            }
            "check_update" => {
                show_main_window(app);
                let _ = app.emit("tray:action", json!({ "action": "check_update" }));
            }
            "quit" => {
                mark_exiting();
                let app_clone = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Some(state) = app_clone.try_state::<AppState>() {
                        let _ = state.task_manager.pause_active_tasks_for_restart().await;
                    }
                    app_clone.exit(0);
                });
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            let app = tray.app_handle();
            match event {
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } => {
                    refresh_tray_state(app);
                    #[cfg(not(target_os = "macos"))]
                    {
                        show_main_window(app);
                    }
                }
                TrayIconEvent::Click {
                    button: MouseButton::Right,
                    button_state: MouseButtonState::Up,
                    ..
                } => {
                    refresh_tray_state(app);
                }
                TrayIconEvent::DoubleClick {
                    button: MouseButton::Left,
                    ..
                } => {
                    show_main_window(app);
                }
                _ => {}
            }
        });

    if let Some(icon) = load_tray_icon(app) {
        builder = builder.icon(icon);
    }

    let _tray = builder.build(app)?;
    Ok(())
}
