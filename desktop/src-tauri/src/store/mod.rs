use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use chrono::{Duration, Local};
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use crate::crypto::CredentialVault;
use crate::error::{AppError, AppResult};
use crate::models::{
    ensure_directory, expand_tilde, now_iso_seconds, AccountCredential, AppSettings, CrawlCombo,
    ResourceRecord, ResourceStatus,
};

pub const TASK_RESUMABLE: &[&str] = &[
    "paused",
    "partial_completed",
    "failed",
    "auth_expired",
    "interrupted",
    "cancelled",
];

const PUBLIC_SETTING_KEYS: &[&str] = &[
    "output_dir",
    "max_active_tasks",
    "max_download_workers",
    "max_convert_workers",
    "max_export_workers",
    "preview_max_pages",
    "preview_max_pixels",
    "preview_timeout_seconds",
    "proxy_mode",
    "proxy_provider",
    "proxy_pool",
    "proxy_api_url",
    "proxy_max_failures",
    "proxy_cooldown_seconds",
    "proxy_min_ttl_seconds",
    "shenlong_whitelist_key",
    "shenlong_whitelist_sign",
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
    "max_retries",
    "connect_timeout",
    "read_timeout",
    "word_font_policy",
    "word_font_auto_install",
    "word_font_dir",
    "soffice_path",
];

const SECRET_SETTING_KEYS: &[&str] = &[
    "proxy_pool",
    "proxy_api_url",
    "shenlong_whitelist_key",
    "shenlong_whitelist_sign",
];

#[derive(Clone)]
pub struct SqliteStore {
    db_path: PathBuf,
    vault: CredentialVault,
    account_state: Arc<Mutex<AccountPoolState>>,
}

struct AccountPoolState {
    next_index: usize,
    auth_locks: HashMap<String, Arc<Mutex<()>>>,
}

impl SqliteStore {
    pub fn open(data_dir: &Path) -> AppResult<Self> {
        ensure_directory(data_dir)?;
        let db_path = data_dir.join("stzy-desktop.db");
        let vault_path = CredentialVault::default_key_path(data_dir);
        let vault = CredentialVault::load_or_create(&vault_path)?;
        let store = Self {
            db_path,
            vault,
            account_state: Arc::new(Mutex::new(AccountPoolState {
                next_index: 0,
                auth_locks: HashMap::new(),
            })),
        };
        store.init_schema()?;
        Ok(store)
    }

    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    fn connect(&self) -> AppResult<Connection> {
        let conn = Connection::open(&self.db_path)?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        conn.busy_timeout(std::time::Duration::from_secs(15))?;
        Ok(conn)
    }

    fn init_schema(&self) -> AppResult<()> {
        let conn = self.connect()?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                name TEXT PRIMARY KEY,
                cookie TEXT NOT NULL DEFAULT '',
                access_token TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                request_headers_json TEXT NOT NULL DEFAULT '',
                import_method TEXT NOT NULL DEFAULT '',
                login_phone TEXT NOT NULL DEFAULT '',
                login_password TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                user_type INTEGER,
                rank INTEGER,
                last_price REAL,
                surplus_num INTEGER,
                fail_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                cooldown_until TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domain_tasks (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT,
                title TEXT NOT NULL DEFAULT '',
                spec_json TEXT NOT NULL DEFAULT '{}',
                stats_json TEXT NOT NULL DEFAULT '{}',
                output_dir TEXT NOT NULL DEFAULT '',
                active_proxy TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_tasks_idempotency
                ON domain_tasks(idempotency_key) WHERE idempotency_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_domain_tasks_status
                ON domain_tasks(status, archived);

            CREATE TABLE IF NOT EXISTS domain_task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_domain_task_logs_task_id
                ON domain_task_logs(task_id, id);

            CREATE TABLE IF NOT EXISTS domain_task_resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                scene TEXT NOT NULL DEFAULT '',
                rank TEXT NOT NULL DEFAULT '',
                province TEXT NOT NULL DEFAULT '',
                grade TEXT NOT NULL DEFAULT '',
                term TEXT NOT NULL DEFAULT '',
                price REAL NOT NULL DEFAULT 0,
                page_count INTEGER NOT NULL DEFAULT 0,
                image_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                local_dir TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, resource_id),
                FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_domain_resources_task_id
                ON domain_task_resources(task_id, id);

            CREATE TABLE IF NOT EXISTS domain_artifacts (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                resource_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                display_name TEXT NOT NULL,
                media_type TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                page_index INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(task_id, path),
                FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_domain_artifacts_task_resource
                ON domain_artifacts(task_id, resource_id, kind);

            CREATE TABLE IF NOT EXISTS combo_states (
                task_id TEXT NOT NULL,
                combo_key TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY(task_id, combo_key),
                FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
            );
            "#,
        )?;
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Key-Value Settings & Catalog Cache
    // -------------------------------------------------------------------------

    pub fn get_kv(&self, key: &str) -> AppResult<Option<Value>> {
        let conn = self.connect()?;
        let raw: Option<String> = conn
            .query_row(
                "SELECT value_json FROM app_kv WHERE key = ?1",
                params![key],
                |row| row.get(0),
            )
            .optional()?;
        match raw {
            Some(s) => Ok(Some(serde_json::from_str(&s)?)),
            None => Ok(None),
        }
    }

    pub fn set_kv(&self, key: &str, value: &Value) -> AppResult<()> {
        let conn = self.connect()?;
        let encoded = serde_json::to_string(value)?;
        let now = now_iso_seconds();
        conn.execute(
            r#"
            INSERT INTO app_kv (key, value_json, updated_at)
            VALUES (?1, ?2, ?3)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            "#,
            params![key, encoded, now],
        )?;
        Ok(())
    }

    pub fn effective_settings(&self, base: &AppSettings) -> AppResult<AppSettings> {
        let mut merged = serde_json::to_value(base)?;
        if let Some(Value::Object(persisted)) = self.get_kv("app_settings")? {
            if let Value::Object(ref mut target) = merged {
                for (k, v) in persisted {
                    if !PUBLIC_SETTING_KEYS.contains(&k.as_str()) {
                        continue;
                    }
                    if SECRET_SETTING_KEYS.contains(&k.as_str()) {
                        if let Some(s) = v.as_str() {
                            if let Ok(decrypted) = self.vault.decrypt(s) {
                                target.insert(k, Value::String(decrypted));
                                continue;
                            }
                        }
                    }
                    target.insert(k, v);
                }
            }
        }
        let mut settings: AppSettings = serde_json::from_value(merged)?;
        settings.output_dir = expand_tilde(&settings.output_dir.to_string_lossy());
        Ok(settings)
    }

    pub fn get_public_settings(&self, base: &AppSettings) -> AppResult<Value> {
        let effective = self.effective_settings(base)?;
        let full = serde_json::to_value(&effective)?;
        let mut out = serde_json::Map::new();
        if let Value::Object(map) = full {
            for &key in PUBLIC_SETTING_KEYS {
                if let Some(mut val) = map.get(key).cloned() {
                    if SECRET_SETTING_KEYS.contains(&key) {
                        let non_empty = val.as_str().map(|s| !s.is_empty()).unwrap_or(false);
                        if non_empty {
                            val = Value::String("***".to_string());
                        }
                    }
                    out.insert(key.to_string(), val);
                }
            }
        }
        Ok(Value::Object(out))
    }

    pub fn update_settings(&self, base: &AppSettings, payload: &Value) -> AppResult<Value> {
        let mut current = match self.get_kv("app_settings")? {
            Some(Value::Object(m)) => m,
            _ => serde_json::Map::new(),
        };
        if let Value::Object(incoming) = payload {
            for (k, v) in incoming {
                if !PUBLIC_SETTING_KEYS.contains(&k.as_str()) {
                    continue;
                }
                if k == "output_dir" {
                    if let Some(raw_dir) = v.as_str() {
                        let expanded = expand_tilde(raw_dir.trim());
                        ensure_directory(&expanded)?;
                        current.insert(
                            k.clone(),
                            Value::String(expanded.to_string_lossy().to_string()),
                        );
                        continue;
                    }
                }
                if SECRET_SETTING_KEYS.contains(&k.as_str()) {
                    if let Some(s) = v.as_str() {
                        if s == "***" {
                            continue;
                        }
                        let encrypted = self.vault.encrypt(s)?;
                        current.insert(k.clone(), Value::String(encrypted));
                        continue;
                    }
                }
                current.insert(k.clone(), v.clone());
            }
        }
        self.set_kv("app_settings", &Value::Object(current))?;
        self.get_public_settings(base)
    }

    // -------------------------------------------------------------------------
    // Accounts Pool
    // -------------------------------------------------------------------------

    pub fn auth_lock(&self, account_name: &str) -> Arc<Mutex<()>> {
        let mut state = self.account_state.lock();
        state
            .auth_locks
            .entry(account_name.to_string())
            .or_insert_with(|| Arc::new(Mutex::new(())))
            .clone()
    }

    pub fn list_accounts(&self) -> AppResult<Vec<AccountCredential>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            r#"
            SELECT
                name, cookie, access_token, user_agent, request_headers_json, import_method,
                login_phone, login_password, enabled, user_type, rank, last_price,
                surplus_num, fail_count, last_error, cooldown_until, last_checked_at
            FROM accounts
            ORDER BY created_at, name
            "#,
        )?;
        let rows = stmt.query_map([], |row| {
            let cookie_enc: String = row.get(1)?;
            let token_enc: String = row.get(2)?;
            let headers_enc: String = row.get(4)?;
            let pwd_enc: String = row.get(7)?;
            let enabled_int: i64 = row.get(8)?;
            Ok((
                row.get::<_, String>(0)?,
                cookie_enc,
                token_enc,
                row.get::<_, String>(3)?,
                headers_enc,
                row.get::<_, String>(5)?,
                row.get::<_, String>(6)?,
                pwd_enc,
                enabled_int != 0,
                row.get::<_, Option<i64>>(9)?,
                row.get::<_, Option<i64>>(10)?,
                row.get::<_, Option<f64>>(11)?,
                row.get::<_, Option<i64>>(12)?,
                row.get::<_, i64>(13)?,
                row.get::<_, String>(14)?,
                row.get::<_, String>(15)?,
                row.get::<_, String>(16)?,
            ))
        })?;

        let mut list = Vec::new();
        for item in rows {
            let (
                name,
                cookie_enc,
                token_enc,
                user_agent,
                headers_enc,
                import_method,
                login_phone,
                pwd_enc,
                enabled,
                user_type,
                rank,
                last_price,
                surplus_num,
                fail_count,
                last_error,
                cooldown_until,
                last_checked_at,
            ) = item?;
            list.push(AccountCredential {
                name,
                cookie: self.vault.decrypt(&cookie_enc).unwrap_or_default(),
                access_token: self.vault.decrypt(&token_enc).unwrap_or_default(),
                user_agent,
                request_headers_json: self.vault.decrypt(&headers_enc).unwrap_or_default(),
                import_method,
                login_phone,
                login_password: self.vault.decrypt(&pwd_enc).unwrap_or_default(),
                enabled,
                user_type,
                rank,
                last_price,
                surplus_num,
                fail_count,
                last_error,
                cooldown_until,
                last_checked_at,
            });
        }
        Ok(list)
    }

    pub fn get_account(&self, name: &str) -> AppResult<Option<AccountCredential>> {
        Ok(self
            .list_accounts()?
            .into_iter()
            .find(|acc| acc.name == name))
    }

    pub fn upsert_account(&self, incoming: AccountCredential) -> AppResult<AccountCredential> {
        let name = incoming.name.trim().to_string();
        if name.is_empty() {
            return Err(AppError::Validation("账号名称不能为空".to_string()));
        }
        let mut incoming = incoming;
        incoming.name = name.clone();

        let merged = if let Some(current) = self.get_account(&name)? {
            merge_account(&current, &incoming)
        } else {
            clean_masked_fields(incoming)
        };

        self.write_account_row(&merged)?;
        Ok(merged)
    }

    fn write_account_row(&self, account: &AccountCredential) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        conn.execute(
            r#"
            INSERT INTO accounts (
                name, cookie, access_token, user_agent, request_headers_json, import_method,
                login_phone, login_password, enabled, user_type, rank, last_price,
                surplus_num, fail_count, last_error, cooldown_until, last_checked_at,
                created_at, updated_at
            )
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?18)
            ON CONFLICT(name) DO UPDATE SET
                cookie = excluded.cookie,
                access_token = excluded.access_token,
                user_agent = excluded.user_agent,
                request_headers_json = excluded.request_headers_json,
                import_method = excluded.import_method,
                login_phone = excluded.login_phone,
                login_password = excluded.login_password,
                enabled = excluded.enabled,
                user_type = excluded.user_type,
                rank = excluded.rank,
                last_price = excluded.last_price,
                surplus_num = excluded.surplus_num,
                fail_count = excluded.fail_count,
                last_error = excluded.last_error,
                cooldown_until = excluded.cooldown_until,
                last_checked_at = excluded.last_checked_at,
                updated_at = excluded.updated_at
            "#,
            params![
                account.name,
                self.vault.encrypt(&account.cookie)?,
                self.vault.encrypt(&account.access_token)?,
                account.user_agent,
                self.vault.encrypt(&account.request_headers_json)?,
                account.import_method,
                account.login_phone,
                self.vault.encrypt(&account.login_password)?,
                if account.enabled { 1 } else { 0 },
                account.user_type,
                account.rank,
                account.last_price,
                account.surplus_num,
                account.fail_count,
                account.last_error,
                account.cooldown_until,
                account.last_checked_at,
                now,
            ],
        )?;
        Ok(())
    }

    pub fn set_account_enabled(&self, name: &str, enabled: bool) -> AppResult<AccountCredential> {
        let mut account = self
            .get_account(name)?
            .ok_or_else(|| AppError::NotFound("Account not found".to_string()))?;
        account.enabled = enabled;
        self.write_account_row(&account)?;
        Ok(account)
    }

    pub fn delete_account(&self, name: &str) -> AppResult<()> {
        let conn = self.connect()?;
        conn.execute("DELETE FROM accounts WHERE name = ?1", params![name])?;
        Ok(())
    }

    pub fn schedulable_accounts(&self) -> AppResult<Vec<AccountCredential>> {
        Ok(self
            .list_accounts()?
            .into_iter()
            .filter(|a| a.usable() && !a.in_cooldown())
            .collect())
    }

    pub fn next_round_robin_account<F>(&self, mut predicate: F) -> AppResult<Option<AccountCredential>>
    where
        F: FnMut(&AccountCredential) -> bool,
    {
        let candidates: Vec<AccountCredential> = self
            .schedulable_accounts()?
            .into_iter()
            .filter(|a| predicate(a))
            .collect();
        if candidates.is_empty() {
            return Ok(None);
        }
        let mut state = self.account_state.lock();
        let idx = state.next_index % candidates.len();
        state.next_index = state.next_index.wrapping_add(1);
        Ok(Some(candidates[idx].clone()))
    }

    pub fn update_account_download_profile(&self, name: &str, info: &Value) -> AppResult<()> {
        let Some(mut account) = self.get_account(name)? else {
            return Ok(());
        };
        account.user_type = info.get("userType").and_then(value_to_i64);
        account.rank = info.get("rank").and_then(value_to_i64);
        account.last_price = info.get("price").and_then(value_to_f64);
        account.surplus_num = info.get("surplusNum").and_then(value_to_i64);
        account.last_checked_at = now_iso_seconds();
        self.write_account_row(&account)
    }

    pub fn mark_account_success(&self, name: &str) -> AppResult<()> {
        let Some(mut account) = self.get_account(name)? else {
            return Ok(());
        };
        account.fail_count = 0;
        account.last_error.clear();
        account.cooldown_until.clear();
        self.write_account_row(&account)
    }

    pub fn mark_account_failure(&self, name: &str, error: &str) -> AppResult<()> {
        let Some(mut account) = self.get_account(name)? else {
            return Ok(());
        };
        account.fail_count += 1;
        account.last_error = error.chars().take(300).collect();
        let cooldown_secs = (20 * account.fail_count).min(300);
        account.cooldown_until = (Local::now() + Duration::seconds(cooldown_secs))
            .format("%Y-%m-%dT%H:%M:%S")
            .to_string();
        self.write_account_row(&account)
    }

    // -------------------------------------------------------------------------
    // Tasks, Logs, Resources & Combo States
    // -------------------------------------------------------------------------

    pub fn mark_interrupted_running_tasks(&self) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        conn.execute(
            r#"
            UPDATE domain_tasks
            SET status = 'interrupted',
                error = CASE WHEN error = '' THEN '客户端上次退出时任务仍在运行，点击恢复可继续下载' ELSE error END,
                updated_at = ?1
            WHERE status IN ('running', 'pausing')
            "#,
            params![now],
        )?;
        Ok(())
    }

    pub fn create_task(
        &self,
        task_id: &str,
        mode: &str,
        spec: &Value,
        output_dir: &Path,
        idempotency_key: Option<&str>,
    ) -> AppResult<Value> {
        let idem = idempotency_key
            .map(str::trim)
            .filter(|s| !s.is_empty());
        if let Some(key) = idem {
            if let Some(existing) = self.find_task_by_idempotency(key)? {
                return Ok(existing);
            }
        }

        let conn = self.connect()?;
        let now = now_iso_seconds();
        let title = spec
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        let spec_json = serde_json::to_string(spec)?;
        conn.execute(
            r#"
            INSERT INTO domain_tasks (
                id, mode, status, archived, idempotency_key, title,
                spec_json, stats_json, output_dir, active_proxy, error,
                created_at, updated_at
            )
            VALUES (?1, ?2, 'queued', 0, ?3, ?4, ?5, '{}', ?6, '', '', ?7, ?7)
            "#,
            params![
                task_id,
                mode,
                idem,
                title,
                spec_json,
                output_dir.to_string_lossy().to_string(),
                now
            ],
        )?;
        self.get_task(task_id)?
            .ok_or_else(|| AppError::NotFound("Task not found".to_string()))
    }

    fn find_task_by_idempotency(&self, key: &str) -> AppResult<Option<Value>> {
        let conn = self.connect()?;
        let id: Option<String> = conn
            .query_row(
                "SELECT id FROM domain_tasks WHERE idempotency_key = ?1",
                params![key],
                |row| row.get(0),
            )
            .optional()?;
        match id {
            Some(tid) => self.get_task(&tid),
            None => Ok(None),
        }
    }

    pub fn get_task(&self, task_id: &str) -> AppResult<Option<Value>> {
        let conn = self.connect()?;
        conn.query_row(
            r#"
            SELECT id, mode, status, archived, title, spec_json, stats_json,
                   output_dir, active_proxy, error, created_at, started_at, ended_at, updated_at
            FROM domain_tasks
            WHERE id = ?1
            "#,
            params![task_id],
            Self::map_task_row,
        )
        .optional()
        .map_err(Into::into)
    }

    pub fn list_tasks(&self, archived: bool, limit: usize, offset: usize) -> AppResult<Vec<Value>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            r#"
            SELECT id, mode, status, archived, title, spec_json, stats_json,
                   output_dir, active_proxy, error, created_at, started_at, ended_at, updated_at
            FROM domain_tasks
            WHERE archived = ?1
            ORDER BY created_at DESC, id DESC
            LIMIT ?2 OFFSET ?3
            "#,
        )?;
        let rows = stmt.query_map(
            params![if archived { 1 } else { 0 }, limit as i64, offset as i64],
            Self::map_task_row,
        )?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row?);
        }
        Ok(out)
    }

    pub fn queued_tasks(&self) -> AppResult<Vec<Value>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            r#"
            SELECT id, mode, status, archived, title, spec_json, stats_json,
                   output_dir, active_proxy, error, created_at, started_at, ended_at, updated_at
            FROM domain_tasks
            WHERE status = 'queued' AND archived = 0
            ORDER BY created_at ASC
            "#,
        )?;
        let rows = stmt.query_map([], Self::map_task_row)?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row?);
        }
        Ok(out)
    }

    fn map_task_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
        let spec_str: String = row.get(5)?;
        let stats_str: String = row.get(6)?;
        let spec: Value = serde_json::from_str(&spec_str).unwrap_or_else(|_| json!({}));
        let stats: Value = serde_json::from_str(&stats_str).unwrap_or_else(|_| json!({}));
        Ok(json!({
            "id": row.get::<_, String>(0)?,
            "mode": row.get::<_, String>(1)?,
            "status": row.get::<_, String>(2)?,
            "archived": row.get::<_, i64>(3)? != 0,
            "title": row.get::<_, String>(4)?,
            "spec": spec,
            "stats": stats,
            "output_dir": row.get::<_, String>(7)?,
            "active_proxy": row.get::<_, String>(8)?,
            "error": row.get::<_, String>(9)?,
            "created_at": row.get::<_, String>(10)?,
            "started_at": row.get::<_, Option<String>>(11)?,
            "ended_at": row.get::<_, Option<String>>(12)?,
            "updated_at": row.get::<_, String>(13)?,
        }))
    }

    pub fn set_task_status(&self, task_id: &str, status: &str, error: Option<&str>) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        if status == "running" {
            conn.execute(
                r#"
                UPDATE domain_tasks
                SET status = ?2,
                    started_at = COALESCE(started_at, ?3),
                    error = COALESCE(?4, error),
                    updated_at = ?3
                WHERE id = ?1
                "#,
                params![task_id, status, now, error],
            )?;
        } else {
            conn.execute(
                r#"
                UPDATE domain_tasks
                SET status = ?2,
                    error = COALESCE(?4, error),
                    updated_at = ?3
                WHERE id = ?1
                "#,
                params![task_id, status, now, error],
            )?;
        }
        Ok(())
    }

    pub fn update_task_progress(
        &self,
        task_id: &str,
        stats: Option<&Value>,
        active_proxy: Option<&str>,
    ) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        let stats_json = stats.map(|s| serde_json::to_string(s).unwrap_or_else(|_| "{}".to_string()));
        conn.execute(
            r#"
            UPDATE domain_tasks
            SET stats_json = COALESCE(?2, stats_json),
                active_proxy = COALESCE(?3, active_proxy),
                updated_at = ?4
            WHERE id = ?1
            "#,
            params![task_id, stats_json, active_proxy, now],
        )?;
        Ok(())
    }

    pub fn finalize_task(
        &self,
        task_id: &str,
        status: &str,
        error: &str,
        stats: &Value,
    ) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        let stats_json = serde_json::to_string(stats)?;
        conn.execute(
            r#"
            UPDATE domain_tasks
            SET status = ?2,
                error = ?3,
                stats_json = ?4,
                active_proxy = '',
                ended_at = ?5,
                updated_at = ?5
            WHERE id = ?1
            "#,
            params![task_id, status, error, stats_json, now],
        )?;
        Ok(())
    }

    pub fn archive_task(&self, task_id: &str, archived: bool) -> AppResult<bool> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        let changed = conn.execute(
            "UPDATE domain_tasks SET archived = ?2, updated_at = ?3 WHERE id = ?1",
            params![task_id, if archived { 1 } else { 0 }, now],
        )?;
        Ok(changed > 0)
    }

    pub fn append_log(&self, task_id: &str, level: &str, message: &str) -> AppResult<Value> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        conn.execute(
            "INSERT INTO domain_task_logs (task_id, level, message, created_at) VALUES (?1, ?2, ?3, ?4)",
            params![task_id, level, message, now],
        )?;
        let id = conn.last_insert_rowid();
        Ok(json!({
            "id": id,
            "task_id": task_id,
            "level": level,
            "message": message,
            "created_at": now,
        }))
    }

    pub fn logs(
        &self,
        task_id: &str,
        after: i64,
        limit: usize,
        tail: bool,
    ) -> AppResult<Vec<Value>> {
        let conn = self.connect()?;
        let mut out = Vec::new();
        if tail && after <= 0 {
            let mut stmt = conn.prepare(
                r#"
                SELECT id, level, message, created_at FROM (
                    SELECT id, level, message, created_at
                    FROM domain_task_logs
                    WHERE task_id = ?1
                    ORDER BY id DESC
                    LIMIT ?2
                ) ORDER BY id ASC
                "#,
            )?;
            let rows = stmt.query_map(params![task_id, limit as i64], |r| {
                Ok(json!({
                    "id": r.get::<_, i64>(0)?,
                    "level": r.get::<_, String>(1)?,
                    "message": r.get::<_, String>(2)?,
                    "created_at": r.get::<_, String>(3)?,
                }))
            })?;
            for row in rows {
                out.push(row?);
            }
        } else {
            let mut stmt = conn.prepare(
                r#"
                SELECT id, level, message, created_at
                FROM domain_task_logs
                WHERE task_id = ?1 AND id > ?2
                ORDER BY id ASC
                LIMIT ?3
                "#,
            )?;
            let rows = stmt.query_map(params![task_id, after, limit as i64], |r| {
                Ok(json!({
                    "id": r.get::<_, i64>(0)?,
                    "level": r.get::<_, String>(1)?,
                    "message": r.get::<_, String>(2)?,
                    "created_at": r.get::<_, String>(3)?,
                }))
            })?;
            for row in rows {
                out.push(row?);
            }
        }
        Ok(out)
    }

    pub fn record_resource(&self, task_id: &str, record: &ResourceRecord) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        let raw_json = serde_json::to_string(&record.raw).unwrap_or_else(|_| "{}".to_string());
        conn.execute(
            r#"
            INSERT INTO domain_task_resources (
                task_id, resource_id, resource_name, subject, year, scene, rank,
                province, grade, term, price, page_count, image_count, status,
                error, local_dir, raw_json, created_at, updated_at
            )
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?18)
            ON CONFLICT(task_id, resource_id) DO UPDATE SET
                resource_name = excluded.resource_name,
                subject = CASE WHEN excluded.subject != '' THEN excluded.subject ELSE domain_task_resources.subject END,
                year = CASE WHEN excluded.year != '' THEN excluded.year ELSE domain_task_resources.year END,
                scene = CASE WHEN excluded.scene != '' THEN excluded.scene ELSE domain_task_resources.scene END,
                rank = CASE WHEN excluded.rank != '' THEN excluded.rank ELSE domain_task_resources.rank END,
                province = CASE WHEN excluded.province != '' THEN excluded.province ELSE domain_task_resources.province END,
                grade = CASE WHEN excluded.grade != '' THEN excluded.grade ELSE domain_task_resources.grade END,
                term = CASE WHEN excluded.term != '' THEN excluded.term ELSE domain_task_resources.term END,
                price = excluded.price,
                page_count = excluded.page_count,
                image_count = excluded.image_count,
                status = excluded.status,
                error = excluded.error,
                local_dir = CASE WHEN excluded.local_dir != '' THEN excluded.local_dir ELSE domain_task_resources.local_dir END,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            "#,
            params![
                task_id,
                record.resource_id,
                record.resource_name,
                record.subject,
                record.year,
                record.scene,
                record.rank,
                record.province,
                record.grade,
                record.term,
                record.price,
                record.page_count as i64,
                record.image_count as i64,
                record.status.as_str(),
                record.error,
                record.local_dir,
                raw_json,
                now,
            ],
        )?;
        Ok(())
    }

    pub fn completed_resource_ids(&self, task_id: &str) -> AppResult<HashSet<String>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT resource_id FROM domain_task_resources WHERE task_id = ?1 AND status = 'completed'",
        )?;
        let rows = stmt.query_map(params![task_id], |r| r.get::<_, String>(0))?;
        let mut set = HashSet::new();
        for row in rows {
            set.insert(row?);
        }
        Ok(set)
    }

    pub fn incomplete_resource_records(&self, task_id: &str) -> AppResult<Vec<ResourceRecord>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            r#"
            SELECT resource_id, resource_name, subject, year, scene, rank, province,
                   grade, term, price, page_count, image_count, status, error, local_dir, raw_json
            FROM domain_task_resources
            WHERE task_id = ?1 AND status != 'completed'
            ORDER BY id ASC
            "#,
        )?;
        let rows = stmt.query_map(params![task_id], |r| {
            let raw_str: String = r.get(15)?;
            let status_str: String = r.get(12)?;
            Ok(ResourceRecord {
                resource_id: r.get(0)?,
                resource_name: r.get(1)?,
                subject: r.get(2)?,
                year: r.get(3)?,
                scene: r.get(4)?,
                rank: r.get(5)?,
                province: r.get(6)?,
                grade: r.get(7)?,
                term: r.get(8)?,
                price: r.get(9)?,
                page_count: r.get::<_, i64>(10)?.max(0) as usize,
                image_count: r.get::<_, i64>(11)?.max(0) as usize,
                status: ResourceStatus::from_str_lossy(&status_str),
                error: r.get(13)?,
                local_dir: r.get(14)?,
                raw: serde_json::from_str(&raw_str).unwrap_or_else(|_| json!({})),
            })
        })?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row?);
        }
        Ok(out)
    }

    pub fn resources(
        &self,
        task_id: &str,
        limit: usize,
        offset: usize,
        status: &str,
    ) -> AppResult<Vec<Value>> {
        let conn = self.connect()?;
        let sql = if status.trim().is_empty() {
            r#"
            SELECT id, resource_id, resource_name, subject, year, scene, rank, province,
                   grade, term, price, page_count, image_count, status, error, local_dir, updated_at
            FROM domain_task_resources
            WHERE task_id = ?1
            ORDER BY id DESC
            LIMIT ?2 OFFSET ?3
            "#
        } else {
            r#"
            SELECT id, resource_id, resource_name, subject, year, scene, rank, province,
                   grade, term, price, page_count, image_count, status, error, local_dir, updated_at
            FROM domain_task_resources
            WHERE task_id = ?1 AND status = ?4
            ORDER BY id DESC
            LIMIT ?2 OFFSET ?3
            "#
        };
        let mut stmt = conn.prepare(sql)?;
        let map_row = |r: &rusqlite::Row<'_>| -> rusqlite::Result<Value> {
            Ok(json!({
                "id": r.get::<_, i64>(0)?.to_string(),
                "resource_id": r.get::<_, String>(1)?,
                "resource_name": r.get::<_, String>(2)?,
                "subject": r.get::<_, String>(3)?,
                "year": r.get::<_, String>(4)?,
                "scene": r.get::<_, String>(5)?,
                "rank": r.get::<_, String>(6)?,
                "province": r.get::<_, String>(7)?,
                "grade": r.get::<_, String>(8)?,
                "term": r.get::<_, String>(9)?,
                "price": r.get::<_, f64>(10)?,
                "page_count": r.get::<_, i64>(11)?,
                "image_count": r.get::<_, i64>(12)?,
                "status": r.get::<_, String>(13)?,
                "error": r.get::<_, String>(14)?,
                "local_dir": r.get::<_, String>(15)?,
                "updated_at": r.get::<_, String>(16)?,
            }))
        };
        let mut out = Vec::new();
        if status.trim().is_empty() {
            let rows = stmt.query_map(params![task_id, limit as i64, offset as i64], map_row)?;
            for row in rows {
                out.push(row?);
            }
        } else {
            let rows = stmt.query_map(
                params![task_id, limit as i64, offset as i64, status.trim()],
                map_row,
            )?;
            for row in rows {
                out.push(row?);
            }
        }
        Ok(out)
    }

    pub fn resource_count(&self, task_id: &str, status: &str) -> AppResult<usize> {
        let conn = self.connect()?;
        let count: i64 = if status.trim().is_empty() {
            conn.query_row(
                "SELECT COUNT(*) FROM domain_task_resources WHERE task_id = ?1",
                params![task_id],
                |r| r.get(0),
            )?
        } else {
            conn.query_row(
                "SELECT COUNT(*) FROM domain_task_resources WHERE task_id = ?1 AND status = ?2",
                params![task_id, status.trim()],
                |r| r.get(0),
            )?
        };
        Ok(count.max(0) as usize)
    }

    pub fn resource_status_counts(&self, task_id: &str) -> AppResult<BTreeMap<String, usize>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT status, COUNT(*) FROM domain_task_resources WHERE task_id = ?1 GROUP BY status",
        )?;
        let rows = stmt.query_map(params![task_id], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?.max(0) as usize))
        })?;
        let mut map = BTreeMap::new();
        for row in rows {
            let (st, cnt) = row?;
            map.insert(st, cnt);
        }
        Ok(map)
    }

    pub fn is_combo_completed(
        &self,
        task_id: &str,
        combo: &CrawlCombo,
        subject_code: &str,
    ) -> AppResult<bool> {
        let conn = self.connect()?;
        let key = combo.state_key(subject_code);
        let exists: Option<i64> = conn
            .query_row(
                "SELECT 1 FROM combo_states WHERE task_id = ?1 AND combo_key = ?2",
                params![task_id, key],
                |r| r.get(0),
            )
            .optional()?;
        Ok(exists.is_some())
    }

    pub fn mark_combo_completed(
        &self,
        task_id: &str,
        combo: &CrawlCombo,
        subject_code: &str,
    ) -> AppResult<()> {
        let conn = self.connect()?;
        let key = combo.state_key(subject_code);
        let now = now_iso_seconds();
        conn.execute(
            r#"
            INSERT INTO combo_states (task_id, combo_key, completed_at)
            VALUES (?1, ?2, ?3)
            ON CONFLICT(task_id, combo_key) DO UPDATE SET completed_at = excluded.completed_at
            "#,
            params![task_id, key, now],
        )?;
        Ok(())
    }

    pub fn upsert_artifact(
        &self,
        id: &str,
        task_id: &str,
        resource_id: &str,
        kind: &str,
        path: &Path,
        display_name: &str,
        media_type: &str,
        size_bytes: u64,
        page_index: Option<usize>,
    ) -> AppResult<()> {
        let conn = self.connect()?;
        let now = now_iso_seconds();
        conn.execute(
            r#"
            INSERT INTO domain_artifacts (
                id, task_id, resource_id, kind, path, display_name,
                media_type, size_bytes, page_index, created_at
            )
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)
            ON CONFLICT(task_id, path) DO UPDATE SET
                id = excluded.id,
                resource_id = excluded.resource_id,
                kind = excluded.kind,
                display_name = excluded.display_name,
                media_type = excluded.media_type,
                size_bytes = excluded.size_bytes,
                page_index = excluded.page_index
            "#,
            params![
                id,
                task_id,
                resource_id,
                kind,
                path.to_string_lossy().to_string(),
                display_name,
                media_type,
                size_bytes as i64,
                page_index.map(|i| i as i64),
                now,
            ],
        )?;
        Ok(())
    }

    pub fn artifact(&self, artifact_id: &str) -> AppResult<Option<Value>> {
        let conn = self.connect()?;
        conn.query_row(
            r#"
            SELECT id, task_id, resource_id, kind, path, display_name,
                   media_type, size_bytes, page_index, created_at
            FROM domain_artifacts
            WHERE id = ?1
            "#,
            params![artifact_id],
            Self::map_artifact_row,
        )
        .optional()
        .map_err(Into::into)
    }

    pub fn artifacts(
        &self,
        task_id: Option<&str>,
        resource_id: Option<&str>,
        kind: Option<&str>,
        limit: usize,
        offset: usize,
    ) -> AppResult<Vec<Value>> {
        let conn = self.connect()?;
        let tid = task_id.unwrap_or("").trim();
        let rid = resource_id.unwrap_or("").trim();
        let knd = kind.unwrap_or("").trim();
        let mut stmt = conn.prepare(
            r#"
            SELECT id, task_id, resource_id, kind, path, display_name,
                   media_type, size_bytes, page_index, created_at
            FROM domain_artifacts
            WHERE (?1 = '' OR task_id = ?1)
              AND (?2 = '' OR resource_id = ?2)
              AND (?3 = '' OR kind = ?3)
            ORDER BY created_at DESC, id DESC
            LIMIT ?4 OFFSET ?5
            "#,
        )?;
        let rows = stmt.query_map(
            params![tid, rid, knd, limit as i64, offset as i64],
            Self::map_artifact_row,
        )?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row?);
        }
        Ok(out)
    }

    fn map_artifact_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
        Ok(json!({
            "id": row.get::<_, String>(0)?,
            "task_id": row.get::<_, String>(1)?,
            "resource_id": row.get::<_, String>(2)?,
            "kind": row.get::<_, String>(3)?,
            "path": row.get::<_, String>(4)?,
            "display_name": row.get::<_, String>(5)?,
            "media_type": row.get::<_, String>(6)?,
            "size_bytes": row.get::<_, i64>(7)?,
            "page_index": row.get::<_, Option<i64>>(8)?,
            "created_at": row.get::<_, String>(9)?,
        }))
    }
}

fn clean_masked_fields(mut account: AccountCredential) -> AccountCredential {
    if account.cookie == "***" {
        account.cookie.clear();
    }
    if account.access_token == "***" {
        account.access_token.clear();
    }
    if account.request_headers_json == "***" {
        account.request_headers_json.clear();
    }
    if account.login_password == "***" {
        account.login_password.clear();
    }
    account
}

fn keep_or_update_secret(current: &str, incoming: &str) -> String {
    if incoming.is_empty() || incoming == "***" {
        current.to_string()
    } else {
        incoming.to_string()
    }
}

fn merge_account(current: &AccountCredential, incoming: &AccountCredential) -> AccountCredential {
    let cookie = keep_or_update_secret(&current.cookie, &incoming.cookie);
    let access_token = keep_or_update_secret(&current.access_token, &incoming.access_token);
    let request_headers_json =
        keep_or_update_secret(&current.request_headers_json, &incoming.request_headers_json);
    let login_password = keep_or_update_secret(&current.login_password, &incoming.login_password);
    let login_phone = if incoming.login_phone.is_empty() {
        current.login_phone.clone()
    } else {
        incoming.login_phone.clone()
    };
    let user_agent = if incoming.user_agent.is_empty() {
        current.user_agent.clone()
    } else {
        incoming.user_agent.clone()
    };

    let credentials_changed = cookie != current.cookie
        || access_token != current.access_token
        || user_agent != current.user_agent
        || request_headers_json != current.request_headers_json
        || login_phone != current.login_phone
        || login_password != current.login_password;

    AccountCredential {
        name: incoming.name.clone(),
        cookie,
        access_token,
        user_agent,
        request_headers_json,
        import_method: if incoming.import_method.is_empty() {
            current.import_method.clone()
        } else {
            incoming.import_method.clone()
        },
        login_phone,
        login_password,
        enabled: incoming.enabled,
        user_type: incoming.user_type.or(current.user_type),
        rank: incoming.rank.or(current.rank),
        last_price: incoming.last_price.or(current.last_price),
        surplus_num: incoming.surplus_num.or(current.surplus_num),
        fail_count: if credentials_changed {
            0
        } else if incoming.fail_count != 0 {
            incoming.fail_count
        } else {
            current.fail_count
        },
        last_error: if credentials_changed {
            String::new()
        } else if !incoming.last_error.is_empty() {
            incoming.last_error.clone()
        } else {
            current.last_error.clone()
        },
        cooldown_until: if credentials_changed {
            String::new()
        } else if !incoming.cooldown_until.is_empty() {
            incoming.cooldown_until.clone()
        } else {
            current.cooldown_until.clone()
        },
        last_checked_at: if !incoming.last_checked_at.is_empty() {
            incoming.last_checked_at.clone()
        } else {
            current.last_checked_at.clone()
        },
    }
}

fn value_to_i64(val: &Value) -> Option<i64> {
    val.as_i64()
        .or_else(|| val.as_f64().map(|f| f as i64))
        .or_else(|| val.as_str().and_then(|s| s.parse::<i64>().ok()))
}

fn value_to_f64(val: &Value) -> Option<f64> {
    val.as_f64()
        .or_else(|| val.as_i64().map(|i| i as f64))
        .or_else(|| val.as_str().and_then(|s| s.parse::<f64>().ok()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_redaction_and_account_encryption_work() {
        let dir = tempfile::tempdir().unwrap();
        let store = SqliteStore::open(dir.path()).unwrap();
        let mut base = AppSettings::default();
        base.data_dir = dir.path().to_path_buf();
        base.output_dir = dir.path().join("out");

        let public = store
            .update_settings(
                &base,
                &json!({
                    "proxy_mode": "fixed",
                    "proxy_pool": "socks5://u:p@127.0.0.1:1080",
                    "max_download_workers": 6
                }),
            )
            .unwrap();
        assert_eq!(public["proxy_pool"], "***");
        assert_eq!(public["max_download_workers"], 6);

        // Sending "***" back does not overwrite stored proxy_pool
        let _ = store
            .update_settings(&base, &json!({ "proxy_pool": "***", "concurrency": 3 }))
            .unwrap();
        let effective = store.effective_settings(&base).unwrap();
        assert_eq!(effective.proxy_pool, "socks5://u:p@127.0.0.1:1080");
        assert_eq!(effective.concurrency, 3);

        // Account roundtrip & secret masking
        let saved = store
            .upsert_account(AccountCredential {
                name: "vip-1".to_string(),
                access_token: "jwt.token.value".to_string(),
                login_phone: "13800138000".to_string(),
                login_password: "secret".to_string(),
                enabled: true,
                ..Default::default()
            })
            .unwrap();
        assert_eq!(saved.access_token, "jwt.token.value");
        assert_eq!(saved.to_public_json()["access_token"], "***");

        // Editing enabled with masked token preserves real token
        let updated = store
            .upsert_account(AccountCredential {
                name: "vip-1".to_string(),
                access_token: "***".to_string(),
                enabled: false,
                ..Default::default()
            })
            .unwrap();
        assert!(!updated.enabled);
        assert_eq!(updated.access_token, "jwt.token.value");
    }
}
