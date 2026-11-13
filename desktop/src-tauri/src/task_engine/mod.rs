pub mod download_service;
pub mod runner;

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use chrono::Local;
use parking_lot::Mutex;
use serde_json::{json, Value};
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::artifacts::{build_filter_display_name, short_task_label, ArtifactService};
use crate::error::{AppError, AppResult};
use crate::models::{
    ensure_directory, expand_tilde, now_iso_seconds, AppSettings, CrawlFilters, CrawlStats,
    ResourceRecord,
};
use crate::store::{SqliteStore, TASK_RESUMABLE};
use crate::task_engine::runner::CrawlRunner;

pub type EventEmitter = Arc<dyn Fn(&str, Value) + Send + Sync>;

#[derive(Clone)]
pub struct TaskManager {
    pub base_settings: AppSettings,
    pub store: SqliteStore,
    pub artifact_service: ArtifactService,
    active_task_sem: Arc<Mutex<Arc<Semaphore>>>,
    download_sem: Arc<Mutex<Arc<Semaphore>>>,
    convert_sem: Arc<Mutex<Arc<Semaphore>>>,
    running_tokens: Arc<Mutex<HashMap<String, CancellationToken>>>,
    emitter: Arc<Mutex<Option<EventEmitter>>>,
}

impl TaskManager {
    pub fn new(
        base_settings: AppSettings,
        store: SqliteStore,
        artifact_service: ArtifactService,
    ) -> Self {
        let rt = store
            .effective_settings(&base_settings)
            .unwrap_or_else(|_| base_settings.clone());
        let mgr = Self {
            base_settings,
            store,
            artifact_service,
            active_task_sem: Arc::new(Mutex::new(Arc::new(Semaphore::new(
                rt.max_active_tasks.max(1),
            )))),
            download_sem: Arc::new(Mutex::new(Arc::new(Semaphore::new(
                rt.max_download_workers.max(1),
            )))),
            convert_sem: Arc::new(Mutex::new(Arc::new(Semaphore::new(
                rt.max_convert_workers.max(1),
            )))),
            running_tokens: Arc::new(Mutex::new(HashMap::new())),
            emitter: Arc::new(Mutex::new(None)),
        };
        let _ = mgr.store.mark_interrupted_running_tasks();
        mgr
    }

    pub fn set_event_emitter(&self, emitter: EventEmitter) {
        *self.emitter.lock() = Some(emitter);
    }

    pub fn enqueue_startup_tasks(&self) {
        if let Ok(queued) = self.store.queued_tasks() {
            for t in queued {
                if let Some(tid) = t.get("id").and_then(Value::as_str) {
                    self.spawn_task(tid.to_string());
                }
            }
        }
    }

    pub fn apply_runtime_limits(&self) {
        let rt = self.runtime_settings();
        *self.download_sem.lock() = Arc::new(Semaphore::new(rt.max_download_workers.max(1)));
        *self.convert_sem.lock() = Arc::new(Semaphore::new(rt.max_convert_workers.max(1)));
        if self.running_tokens.lock().is_empty() {
            *self.active_task_sem.lock() = Arc::new(Semaphore::new(rt.max_active_tasks.max(1)));
        }
    }

    pub fn runtime_settings(&self) -> AppSettings {
        let mut s = self
            .store
            .effective_settings(&self.base_settings)
            .unwrap_or_else(|_| self.base_settings.clone());
        s.data_dir = self.base_settings.data_dir.clone();
        s
    }

    pub fn create_task(
        &self,
        mode: &str,
        filters: Value,
        filter_labels: Value,
        subjects: Option<Vec<Value>>,
        settings_overrides: Value,
        idempotency_key: Option<&str>,
        title: &str,
    ) -> AppResult<Value> {
        let mut rt = self.runtime_settings();
        apply_runtime_overrides(&mut rt, &settings_overrides);
        let norm_subjects = self.normalize_subjects(subjects, &rt);
        if norm_subjects.len() == 1 {
            rt.subject_code = norm_subjects[0]
                .get("code")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            rt.subject_name = norm_subjects[0]
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
        }
        let norm_mode = if mode == "estimate" {
            "estimate"
        } else {
            "crawl"
        };
        let stamp = Local::now().format("%Y%m%d_%H%M%S").to_string();
        let short_id = &Uuid::new_v4().simple().to_string()[..8];
        let task_id = format!("task_{stamp}_{short_id}");
        let task_root = rt.output_dir.join("tasks").join(&task_id);
        ensure_directory(&task_root)?;

        let spec = json!({
            "title": title,
            "mode": norm_mode,
            "filters": filters,
            "filter_labels": if filter_labels.is_object() { filter_labels } else { json!({}) },
            "subjects": norm_subjects,
            "settings": public_settings_snapshot(&rt, &settings_overrides),
        });

        let mut task = self.store.create_task(
            &task_id,
            norm_mode,
            &spec,
            &task_root,
            idempotency_key,
        )?;
        self.attach_task_display(&mut task);
        if let Some(tid) = task.get("id").and_then(Value::as_str) {
            self.spawn_task(tid.to_string());
        }
        Ok(task)
    }

    pub async fn estimate_preview(
        &self,
        filters_val: Value,
        filter_labels: Value,
        subjects: Option<Vec<Value>>,
        settings_overrides: Value,
        title: &str,
    ) -> AppResult<Value> {
        let mut rt = self.runtime_settings();
        apply_runtime_overrides(&mut rt, &settings_overrides);
        let norm_subjects = self.normalize_subjects(subjects, &rt);
        if norm_subjects.len() == 1 {
            rt.subject_code = norm_subjects[0]
                .get("code")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            rt.subject_name = norm_subjects[0]
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
        }
        let spec = json!({
            "title": title,
            "mode": "estimate",
            "filters": filters_val,
            "filter_labels": if filter_labels.is_object() { filter_labels } else { json!({}) },
            "subjects": norm_subjects,
            "settings": public_settings_snapshot(&rt, &settings_overrides),
        });

        let parsed_filters: CrawlFilters =
            serde_json::from_value(filters_val).unwrap_or_default();
        let logs: Arc<Mutex<Vec<Value>>> = Arc::new(Mutex::new(Vec::new()));
        let mut aggregate = CrawlStats {
            task_mode: "estimate".to_string(),
            phase: "running".to_string(),
            running: true,
            ..CrawlStats::default()
        };

        let dl_sem = self.download_sem.lock().clone();
        let cv_sem = self.convert_sem.lock().clone();

        for sub in &norm_subjects {
            let sub_code = sub.get("code").and_then(Value::as_str).unwrap_or("");
            let sub_name = sub
                .get("name")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .unwrap_or(if sub_code.is_empty() { "不限" } else { sub_code });

            let est_id = format!("estimate_preview_{}", &Uuid::new_v4().simple().to_string()[..8]);
            let mut task_settings = rt.clone();
            let est_root = self
                .base_settings
                .data_dir
                .join(".tmp")
                .join("estimates")
                .join(&est_id);
            ensure_directory(&est_root)?;
            task_settings.output_dir = est_root;
            task_settings.subject_code = sub_code.to_string();
            task_settings.subject_name = sub_name.to_string();
            task_settings.task_scope = est_id;

            let logs_ref = logs.clone();
            let runner = CrawlRunner::new(
                task_settings,
                parsed_filters.clone(),
                self.store.clone(),
                CancellationToken::new(),
                dl_sem.clone(),
                cv_sem.clone(),
                HashSet::new(),
                Arc::new(move |msg| {
                    let mut guard = logs_ref.lock();
                    let next_id = guard.len() + 1;
                    guard.push(json!({
                        "id": next_id,
                        "level": "info",
                        "message": msg,
                        "created_at": now_iso_seconds(),
                    }));
                }),
                Arc::new(|_| {}),
                Arc::new(|_| {}),
                Arc::new(|_| {}),
            );
            let res = runner.estimate().await?;
            merge_stats(&mut aggregate, &res);
        }

        aggregate.running = false;
        aggregate.phase = "preview".to_string();
        aggregate.outcome = "estimated".to_string();

        let collected_logs = logs.lock().clone();
        Ok(json!({
            "stats": aggregate,
            "logs": collected_logs,
            "spec": spec,
        }))
    }

    pub fn resume_task(&self, task_id: &str) -> AppResult<Value> {
        let task = self
            .store
            .get_task(task_id)?
            .ok_or_else(|| AppError::NotFound("Task not found".to_string()))?;
        let status = task.get("status").and_then(Value::as_str).unwrap_or("");
        if !TASK_RESUMABLE.contains(&status) {
            return Err(AppError::Conflict(format!("当前状态 {status} 不可恢复")));
        }
        let incomplete = self.store.incomplete_resource_records(task_id)?;
        if !incomplete.is_empty() {
            let _ = self.store.append_log(
                task_id,
                "info",
                &format!(
                    "继续下载：将仅重试未完成资源 {} 份，已完成资源不再重新扫描",
                    incomplete.len()
                ),
            );
        }
        self.store.set_task_status(task_id, "queued", Some(""))?;
        let mut refreshed = self
            .store
            .get_task(task_id)?
            .ok_or_else(|| AppError::NotFound("Task not found".to_string()))?;
        self.attach_task_display(&mut refreshed);
        self.spawn_task(task_id.to_string());
        Ok(refreshed)
    }

    pub fn pause_task(&self, task_id: &str) -> AppResult<Value> {
        let task = self
            .store
            .get_task(task_id)?
            .ok_or_else(|| AppError::NotFound("Task not found".to_string()))?;
        let status = task.get("status").and_then(Value::as_str).unwrap_or("");
        if status == "queued" {
            self.store.set_task_status(task_id, "paused", Some(""))?;
            let mut out = self.store.get_task(task_id)?.unwrap_or(task);
            self.attach_task_display(&mut out);
            return Ok(out);
        }
        if status != "running" {
            return Err(AppError::Conflict(format!("当前状态 {status} 不可暂停")));
        }
        self.store.set_task_status(task_id, "pausing", Some(""))?;
        if let Some(tok) = self.running_tokens.lock().get(task_id) {
            tok.cancel();
        }
        let mut out = self.store.get_task(task_id)?.unwrap_or(task);
        self.attach_task_display(&mut out);
        Ok(out)
    }

    pub fn active_task_count(&self) -> usize {
        if let Ok(tasks) = self.store.list_tasks(false, 200, 0) {
            tasks
                .iter()
                .filter(|t| {
                    matches!(
                        t.get("status").and_then(Value::as_str).unwrap_or(""),
                        "running" | "queued"
                    )
                })
                .count()
        } else {
            self.running_tokens.lock().len()
        }
    }

    pub async fn pause_active_tasks_for_restart(&self) -> usize {
        let mut paused_count = 0usize;
        if let Ok(tasks) = self.store.list_tasks(false, 200, 0) {
            for t in tasks {
                let status = t.get("status").and_then(Value::as_str).unwrap_or("");
                if matches!(status, "running" | "queued") {
                    if let Some(tid) = t.get("id").and_then(Value::as_str) {
                        if self.pause_task(tid).is_ok() {
                            paused_count += 1;
                        }
                    }
                }
            }
        }
        if paused_count > 0 {
            for _ in 0..25 {
                if self.running_tokens.lock().is_empty() {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            }
        }
        paused_count
    }

    pub fn cancel_task(&self, task_id: &str) -> AppResult<Value> {
        let task = self
            .store
            .get_task(task_id)?
            .ok_or_else(|| AppError::NotFound("Task not found".to_string()))?;
        if let Some(tok) = self.running_tokens.lock().get(task_id) {
            tok.cancel();
        }
        self.store.set_task_status(task_id, "cancelled", Some(""))?;
        let mut out = self.store.get_task(task_id)?.unwrap_or(task);
        self.attach_task_display(&mut out);
        Ok(out)
    }

    pub fn archive_task(&self, task_id: &str) -> AppResult<Value> {
        if !self.store.archive_task(task_id, true)? {
            return Err(AppError::NotFound("Task not found".to_string()));
        }
        let mut out = self
            .store
            .get_task(task_id)?
            .unwrap_or_else(|| json!({ "id": task_id, "archived": true }));
        self.attach_task_display(&mut out);
        Ok(out)
    }

    pub fn list_tasks(&self, archived: bool, limit: usize, offset: usize) -> AppResult<Vec<Value>> {
        let mut tasks = self.store.list_tasks(archived, limit, offset)?;
        for t in &mut tasks {
            self.attach_task_display(t);
        }
        Ok(tasks)
    }

    pub fn get_task(&self, task_id: &str) -> AppResult<Value> {
        let mut t = self
            .store
            .get_task(task_id)?
            .ok_or_else(|| AppError::NotFound("Task not found".to_string()))?;
        self.attach_task_display(&mut t);
        Ok(t)
    }

    pub fn resources(
        &self,
        task_id: &str,
        limit: usize,
        offset: usize,
        status: &str,
    ) -> AppResult<Value> {
        Ok(json!({
            "items": self.store.resources(task_id, limit, offset, status)?,
            "total": self.store.resource_count(task_id, status)?,
            "status_counts": self.store.resource_status_counts(task_id)?,
        }))
    }

    pub fn logs(&self, task_id: &str, after: i64, limit: usize, tail: bool) -> AppResult<Vec<Value>> {
        self.store.logs(task_id, after, limit, tail)
    }

    fn spawn_task(&self, task_id: String) {
        {
            let guard = self.running_tokens.lock();
            if guard.contains_key(&task_id) {
                return;
            }
        }
        let mgr = self.clone();
        tauri::async_runtime::spawn(async move {
            mgr.execute_task(task_id).await;
        });
    }

    async fn execute_task(&self, task_id: String) {
        let task_sem = self.active_task_sem.lock().clone();
        let Ok(_task_permit) = task_sem.acquire().await else {
            return;
        };

        let Ok(Some(task)) = self.store.get_task(&task_id) else {
            return;
        };
        let current_status = task.get("status").and_then(Value::as_str).unwrap_or("");
        if matches!(
            current_status,
            "cancelled" | "completed" | "paused" | "pausing"
        ) {
            return;
        }

        let cancel = CancellationToken::new();
        self.running_tokens
            .lock()
            .insert(task_id.clone(), cancel.clone());

        let _ = self.store.set_task_status(&task_id, "running", Some(""));
        self.emit_task_snapshot(&task_id);

        let spec = task.get("spec").cloned().unwrap_or_else(|| json!({}));
        let mode = spec
            .get("mode")
            .or_else(|| task.get("mode"))
            .and_then(Value::as_str)
            .unwrap_or("crawl")
            .to_string();

        let retry_records = if mode == "crawl" {
            self.store
                .incomplete_resource_records(&task_id)
                .unwrap_or_default()
        } else {
            Vec::new()
        };
        let resource_only_resume = !retry_records.is_empty();
        let started_at = Instant::now();
        let mut aggregate = CrawlStats {
            task_mode: mode.clone(),
            phase: "running".to_string(),
            running: true,
            ..CrawlStats::default()
        };

        let exec_res: AppResult<()> = async {
            let filters: CrawlFilters = spec
                .get("filters")
                .cloned()
                .and_then(|v| serde_json::from_value(v).ok())
                .unwrap_or_default();

            let mut rt = self.runtime_settings();
            if let Some(spec_settings) = spec.get("settings") {
                apply_runtime_overrides(&mut rt, spec_settings);
            }
            let subjects: Vec<Value> = spec
                .get("subjects")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_else(|| {
                    vec![json!({
                        "code": rt.subject_code,
                        "name": rt.subject_name,
                    })]
                });

            let dl_sem = self.download_sem.lock().clone();
            let cv_sem = self.convert_sem.lock().clone();

            if resource_only_resume {
                let first_sub = subjects.first().cloned().unwrap_or_else(|| json!({}));
                let sub_code = first_sub.get("code").and_then(Value::as_str).unwrap_or("");
                let sub_name = first_sub
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                    .unwrap_or(if sub_code.is_empty() { "不限" } else { sub_code });

                let runner = self.build_task_runner(
                    &task_id,
                    sub_code,
                    sub_name,
                    &rt,
                    filters,
                    cancel.clone(),
                    dl_sem,
                    cv_sem,
                    aggregate.clone(),
                )?;
                let stats = runner.run_records(retry_records).await?;
                merge_stats(&mut aggregate, &stats);
            } else {
                for sub in &subjects {
                    if let Ok(Some(latest)) = self.store.get_task(&task_id) {
                        let st = latest.get("status").and_then(Value::as_str).unwrap_or("");
                        if matches!(st, "cancelled" | "pausing" | "paused") {
                            aggregate.paused = true;
                            break;
                        }
                    }
                    let sub_code = sub.get("code").and_then(Value::as_str).unwrap_or("");
                    let sub_name = sub
                        .get("name")
                        .and_then(Value::as_str)
                        .filter(|s| !s.is_empty())
                        .unwrap_or(if sub_code.is_empty() { "不限" } else { sub_code });

                    let runner = self.build_task_runner(
                        &task_id,
                        sub_code,
                        sub_name,
                        &rt,
                        filters.clone(),
                        cancel.clone(),
                        dl_sem.clone(),
                        cv_sem.clone(),
                        aggregate.clone(),
                    )?;
                    let res = if mode == "estimate" {
                        runner.estimate().await?
                    } else {
                        runner.run().await?
                    };
                    merge_stats(&mut aggregate, &res);
                    if res.aborted || res.paused {
                        break;
                    }
                }
            }

            let mut stats_payload = self.final_stats(&task_id, &aggregate);
            let final_status = self.final_status(&task_id, &aggregate, &stats_payload);
            let duration_secs = started_at.elapsed().as_secs();
            if let Value::Object(ref mut map) = stats_payload {
                map.insert("duration_seconds".to_string(), json!(duration_secs));
            }
            let err_str = if final_status == "failed" {
                aggregate.error.as_str()
            } else {
                ""
            };
            self.store
                .finalize_task(&task_id, &final_status, err_str, &stats_payload)?;
            Ok(())
        }
        .await;

        if let Err(err) = exec_res {
            let status = if err.requires_login() {
                "auth_expired"
            } else {
                "failed"
            };
            let msg = err.user_message();
            let _ = self.store.set_task_status(&task_id, status, Some(&msg));
            let _ = self.store.append_log(&task_id, "error", &msg);
        }

        self.running_tokens.lock().remove(&task_id);
        self.emit_task_snapshot(&task_id);
    }

    #[allow(clippy::too_many_arguments)]
    fn build_task_runner(
        &self,
        task_id: &str,
        subject_code: &str,
        subject_name: &str,
        base_rt: &AppSettings,
        filters: CrawlFilters,
        cancel: CancellationToken,
        dl_sem: Arc<Semaphore>,
        cv_sem: Arc<Semaphore>,
        prior_aggregate: CrawlStats,
    ) -> AppResult<CrawlRunner> {
        let mut ts = base_rt.clone();
        let task_root = ts.output_dir.join("tasks").join(task_id);
        ensure_directory(&task_root)?;
        ts.output_dir = task_root;
        ts.subject_code = subject_code.to_string();
        ts.subject_name = subject_name.to_string();
        ts.task_scope = task_id.to_string();

        let completed = self.store.completed_resource_ids(task_id)?;

        let store_for_log = self.store.clone();
        let emitter_for_log = self.emitter.clone();
        let tid_log = task_id.to_string();
        let on_log: Arc<dyn Fn(String) + Send + Sync> = Arc::new(move |msg| {
            if let Ok(log_entry) = store_for_log.append_log(&tid_log, "info", &msg) {
                if let Some(ref emit) = *emitter_for_log.lock() {
                    emit("task:log", log_entry);
                }
            }
        });

        let store_for_rec = self.store.clone();
        let art_for_rec = self.artifact_service.clone();
        let tid_rec = task_id.to_string();
        let on_record: Arc<dyn Fn(ResourceRecord) + Send + Sync> = Arc::new(move |rec| {
            let _ = store_for_rec.record_resource(&tid_rec, &rec);
            if !rec.local_dir.is_empty() {
                let p = Path::new(&rec.local_dir);
                if let Err(e) = art_for_rec.register_resource_artifacts(&tid_rec, &rec.resource_id, p) {
                    let _ = store_for_rec.append_log(
                        &tid_rec,
                        "warning",
                        &format!("产物登记失败：{} - {e}", rec.resource_id),
                    );
                }
            }
        });

        let store_for_prog = self.store.clone();
        let emitter_for_prog = self.emitter.clone();
        let tid_prog = task_id.to_string();
        let on_progress: Arc<dyn Fn(CrawlStats) + Send + Sync> = Arc::new(move |st| {
            let mut combined = prior_aggregate.clone();
            merge_stats(&mut combined, &st);
            combined.running = st.running;
            combined.current_resource_name = st.current_resource_name.clone();
            if let Ok(val) = serde_json::to_value(&combined) {
                let _ = store_for_prog.update_task_progress(&tid_prog, Some(&val), None);
                if let Some(ref emit) = *emitter_for_prog.lock() {
                    emit(
                        "task:progress",
                        json!({
                            "task_id": tid_prog,
                            "stats": val,
                        }),
                    );
                }
            }
        });

        let store_for_proxy = self.store.clone();
        let tid_proxy = task_id.to_string();
        let on_proxy: Arc<dyn Fn(String) + Send + Sync> = Arc::new(move |proxy| {
            let _ = store_for_proxy.update_task_progress(&tid_proxy, None, Some(&proxy));
        });

        Ok(CrawlRunner::new(
            ts,
            filters,
            self.store.clone(),
            cancel,
            dl_sem,
            cv_sem,
            completed,
            on_log,
            on_record,
            on_progress,
            on_proxy,
        ))
    }

    fn emit_task_snapshot(&self, task_id: &str) {
        if let Ok(task) = self.get_task(task_id) {
            if let Some(ref emit) = *self.emitter.lock() {
                emit("task:updated", task);
            }
        }
    }

    fn normalize_subjects(&self, subjects: Option<Vec<Value>>, settings: &AppSettings) -> Vec<Value> {
        let entries = subjects.filter(|v| !v.is_empty()).unwrap_or_else(|| {
            vec![json!({
                "code": settings.subject_code,
                "name": settings.subject_name,
            })]
        });
        let subject_names = self.subject_names(&settings.study_phase_code);
        entries
            .into_iter()
            .map(|sub| {
                let code = sub
                    .get("code")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let name = sub
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                    .map(str::to_string)
                    .or_else(|| subject_names.get(&code).cloned())
                    .unwrap_or_else(|| {
                        if code.is_empty() {
                            "不限".to_string()
                        } else {
                            code.clone()
                        }
                    });
                json!({ "code": code, "name": name })
            })
            .collect()
    }

    fn subject_names(&self, phase: &str) -> HashMap<String, String> {
        self.store
            .get_kv("catalog_cache")
            .ok()
            .flatten()
            .and_then(|c| c.get("subjects").cloned())
            .and_then(|s| s.get(phase).cloned())
            .and_then(|m| m.as_object().cloned())
            .map(|obj| {
                obj.into_iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k, s.to_string())))
                    .collect()
            })
            .unwrap_or_default()
    }

    pub fn attach_task_display(&self, task: &mut Value) {
        let tid = task
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let title = task
            .get("title")
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
            .or_else(|| {
                task.get("spec")
                    .and_then(|s| s.get("title"))
                    .and_then(Value::as_str)
            })
            .unwrap_or("")
            .trim()
            .to_string();
        let filter_name = task
            .get("spec")
            .map(|sp| build_filter_display_name(&self.store, sp))
            .unwrap_or_default();
        let display = if !title.is_empty() {
            title.clone()
        } else if !filter_name.is_empty() {
            filter_name
        } else {
            short_task_label(&tid)
        };

        if let Value::Object(ref mut map) = task {
            map.insert("task_title".to_string(), Value::String(title));
            map.insert("task_display_name".to_string(), Value::String(display));
        }

        if task.get("mode").and_then(Value::as_str) == Some("crawl") && !tid.is_empty() {
            if let Ok(counts) = self.store.resource_status_counts(&tid) {
                if !counts.is_empty() {
                    let mut stats = task
                        .get("stats")
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default();
                    let completed = counts.get("completed").copied().unwrap_or(0);
                    let failed = counts.get("failed").copied().unwrap_or(0);
                    let paid = counts.get("paid_unavailable").copied().unwrap_or(0)
                        + counts.get("skipped_paid").copied().unwrap_or(0);
                    let partial = counts.get("partial").copied().unwrap_or(0);
                    let filtered = stats
                        .get("filtered_skipped")
                        .and_then(Value::as_u64)
                        .unwrap_or(0) as usize;
                    let processed = completed + failed + paid + partial + filtered;
                    let prev_proc = stats
                        .get("resources_processed")
                        .and_then(Value::as_u64)
                        .unwrap_or(0) as usize;
                    let prev_comp = stats
                        .get("resources_completed")
                        .and_then(Value::as_u64)
                        .unwrap_or(0) as usize;

                    stats.insert(
                        "resources_processed".to_string(),
                        json!(prev_proc.max(prev_comp).max(processed)),
                    );
                    stats.insert("resources_success".to_string(), json!(completed));
                    stats.insert("resources_completed".to_string(), json!(completed));
                    let prev_failed =
                        stats.get("failed").and_then(Value::as_u64).unwrap_or(0) as usize;
                    stats.insert("failed".to_string(), json!(prev_failed.max(failed)));
                    let prev_paid = stats
                        .get("paid_skipped")
                        .and_then(Value::as_u64)
                        .unwrap_or(0) as usize;
                    stats.insert("paid_skipped".to_string(), json!(prev_paid.max(paid)));
                    let prev_lim = stats
                        .get("preview_limited")
                        .and_then(Value::as_u64)
                        .unwrap_or(0) as usize;
                    stats.insert(
                        "preview_limited".to_string(),
                        json!(prev_lim.max(partial)),
                    );
                    stats.insert("resource_status_counts".to_string(), json!(counts));
                    if let Value::Object(ref mut map) = task {
                        map.insert("stats".to_string(), Value::Object(stats));
                    }
                }
            }
        }
    }

    fn final_stats(&self, task_id: &str, stats: &CrawlStats) -> Value {
        let mut val = serde_json::to_value(stats).unwrap_or_else(|_| json!({}));
        let Ok(counts) = self.store.resource_status_counts(task_id) else {
            return val;
        };
        if counts.is_empty() {
            return val;
        }
        if let Value::Object(ref mut map) = val {
            let completed = counts.get("completed").copied().unwrap_or(0);
            let failed = counts.get("failed").copied().unwrap_or(0);
            let paid = counts.get("paid_unavailable").copied().unwrap_or(0)
                + counts.get("skipped_paid").copied().unwrap_or(0);
            let partial = counts.get("partial").copied().unwrap_or(0);
            let processed = completed + failed + paid + partial + stats.filtered_skipped;
            map.insert(
                "resources_processed".to_string(),
                json!(stats.resources_completed.max(processed)),
            );
            map.insert("resources_success".to_string(), json!(completed));
            map.insert("resources_completed".to_string(), json!(completed));
            map.insert("failed".to_string(), json!(stats.failed.max(failed)));
            map.insert(
                "paid_skipped".to_string(),
                json!(stats.paid_skipped.max(paid)),
            );
            map.insert(
                "preview_limited".to_string(),
                json!(stats.preview_limited.max(partial)),
            );
            map.insert("resource_status_counts".to_string(), json!(counts));
        }
        val
    }

    fn final_status(&self, task_id: &str, stats: &CrawlStats, payload: &Value) -> String {
        if let Ok(Some(t)) = self.store.get_task(task_id) {
            if t.get("status").and_then(Value::as_str) == Some("cancelled") {
                return "cancelled".to_string();
            }
        }
        if stats.aborted {
            return "failed".to_string();
        }
        if stats.paused {
            return "paused".to_string();
        }
        let f = payload.get("failed").and_then(Value::as_u64).unwrap_or(0);
        let p = payload
            .get("paid_skipped")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let l = payload
            .get("preview_limited")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        if f > 0 || p > 0 || l > 0 {
            return "partial_completed".to_string();
        }
        "completed".to_string()
    }
}

fn apply_runtime_overrides(settings: &mut AppSettings, overrides: &Value) {
    let Some(obj) = overrides.as_object() else {
        return;
    };
    if let Some(v) = obj.get("study_phase_code").and_then(Value::as_str) {
        settings.study_phase_code = v.to_string();
    }
    if let Some(v) = obj.get("subject_code").and_then(Value::as_str) {
        settings.subject_code = v.to_string();
    }
    if let Some(v) = obj.get("subject_name").and_then(Value::as_str) {
        settings.subject_name = v.to_string();
    }
    if let Some(v) = obj.get("file_type").and_then(Value::as_str) {
        settings.file_type = v.to_string();
    }
    if let Some(v) = obj.get("max_pages_per_combo").and_then(Value::as_u64) {
        settings.max_pages_per_combo = if v == 0 { None } else { Some(v as usize) };
    }
    if let Some(v) = obj.get("list_delay_seconds").and_then(Value::as_f64) {
        settings.list_delay_seconds = v;
    }
    if let Some(v) = obj.get("image_delay_seconds").and_then(Value::as_f64) {
        settings.image_delay_seconds = v;
    }
    if let Some(v) = obj.get("list_max_retries").and_then(Value::as_u64) {
        settings.list_max_retries = v as usize;
    }
    if let Some(v) = obj.get("combo_failure_limit").and_then(Value::as_u64) {
        settings.combo_failure_limit = v as usize;
    }
    if let Some(v) = obj.get("concurrency").and_then(Value::as_u64) {
        settings.concurrency = v as usize;
    }
    if let Some(v) = obj.get("proxy_mode").and_then(Value::as_str) {
        settings.proxy_mode = v.to_string();
    }
    if let Some(v) = obj.get("proxy_provider").and_then(Value::as_str) {
        settings.proxy_provider = v.to_string();
    }
    if let Some(v) = obj.get("proxy_min_ttl_seconds").and_then(Value::as_f64) {
        settings.proxy_min_ttl_seconds = v;
    }
    if let Some(v) = obj.get("output_dir").and_then(Value::as_str) {
        if !v.trim().is_empty() {
            settings.output_dir = expand_tilde(v);
        }
    }
}

fn public_settings_snapshot(settings: &AppSettings, overrides: &Value) -> Value {
    let mut snap = json!({
        "study_phase_code": settings.study_phase_code,
        "subject_code": settings.subject_code,
        "subject_name": settings.subject_name,
        "file_type": settings.file_type,
        "max_pages_per_combo": settings.max_pages_per_combo,
        "list_delay_seconds": settings.list_delay_seconds,
        "image_delay_seconds": settings.image_delay_seconds,
        "list_max_retries": settings.list_max_retries,
        "combo_failure_limit": settings.combo_failure_limit,
        "concurrency": settings.concurrency,
        "proxy_mode": settings.proxy_mode,
        "proxy_provider": settings.proxy_provider,
        "proxy_min_ttl_seconds": settings.proxy_min_ttl_seconds,
    });
    if let (Some(dst), Some(src)) = (snap.as_object_mut(), overrides.as_object()) {
        for k in [
            "study_phase_code",
            "subject_code",
            "subject_name",
            "file_type",
            "max_pages_per_combo",
            "list_delay_seconds",
            "image_delay_seconds",
            "list_max_retries",
            "combo_failure_limit",
            "concurrency",
            "proxy_mode",
            "proxy_provider",
            "proxy_min_ttl_seconds",
        ] {
            if let Some(v) = src.get(k) {
                dst.insert(k.to_string(), v.clone());
            }
        }
    }
    snap
}

fn merge_stats(base: &mut CrawlStats, res: &CrawlStats) {
    base.total_combos += res.total_combos;
    base.completed_combos += res.completed_combos;
    base.resources_seen += res.resources_seen;
    base.resources_total += res.resources_total;
    base.resources_completed += res.resources_completed;
    base.images_downloaded += res.images_downloaded;
    base.paid_skipped += res.paid_skipped;
    base.filtered_skipped += res.filtered_skipped;
    base.preview_limited += res.preview_limited;
    base.failed += res.failed;
    base.paused = base.paused || res.paused;
    base.aborted = base.aborted || res.aborted;
    if !res.error.is_empty() {
        base.error = res.error.clone();
    }
    base.outcome = res.outcome.clone();
    base.phase = res.phase.clone();
    base.running = false;
}

#[allow(dead_code)]
type _PathRef = PathBuf;
