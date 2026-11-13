use std::collections::{BTreeSet, HashMap};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::UNIX_EPOCH;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use walkdir::WalkDir;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

use crate::error::{AppError, AppResult};
use crate::models::{expand_tilde, safe_filename};
use crate::store::SqliteStore;

const IMAGE_SUFFIXES: &[&str] = &[".png", ".jpg", ".jpeg", ".webp"];
const BLOCKED_INLINE_SUFFIXES: &[&str] = &[".svg", ".html", ".htm"];

fn clean_canonical_path(path: &Path) -> PathBuf {
    let resolved = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    #[cfg(target_os = "windows")]
    {
        let raw = resolved.to_string_lossy();
        if let Some(stripped) = raw.strip_prefix(r"\\?\") {
            return PathBuf::from(stripped);
        }
    }
    resolved
}

#[derive(Clone)]
pub struct ArtifactService {
    pub store: SqliteStore,
    pub base_settings: crate::models::AppSettings,
}

impl ArtifactService {
    pub fn new(store: SqliteStore, base_settings: crate::models::AppSettings) -> Self {
        Self {
            store,
            base_settings,
        }
    }

    pub fn current_output_root(&self) -> PathBuf {
        self.store
            .effective_settings(&self.base_settings)
            .map(|s| expand_tilde(&s.output_dir.to_string_lossy()))
            .unwrap_or_else(|_| self.base_settings.output_dir.clone())
    }

    pub fn register_resource_artifacts(
        &self,
        task_id: &str,
        resource_id: &str,
        directory: &Path,
    ) -> AppResult<()> {
        let mut candidates = BTreeSet::new();
        if directory.exists() {
            if let Ok(entries) = fs::read_dir(directory) {
                for entry in entries.flatten() {
                    let p = entry.path();
                    if p.is_file() {
                        if let Some(name) = p.file_name().and_then(|s| s.to_str()) {
                            if !name.starts_with('.') {
                                candidates.insert(p);
                            }
                        }
                    }
                }
            }
            if let (Some(parent), Some(dir_name)) =
                (directory.parent(), directory.file_name().and_then(|s| s.to_str()))
            {
                let sibling_pdf = parent.join(format!("{dir_name}.pdf"));
                if sibling_pdf.is_file() {
                    candidates.insert(sibling_pdf);
                }
            }
        }

        for path in candidates {
            let _ = self.register_file(task_id, resource_id, &path, None);
        }
        Ok(())
    }

    pub fn register_file(
        &self,
        task_id: &str,
        resource_id: &str,
        path: &Path,
        page_index: Option<i64>,
    ) -> AppResult<Value> {
        let canonical = clean_canonical_path(path);
        if canonical.is_symlink() {
            return Err(AppError::Validation("不允许登记符号链接文件".to_string()));
        }
        let suffix = canonical
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| format!(".{}", s.to_lowercase()))
            .unwrap_or_default();

        let mut media_type = mime_guess::from_path(&canonical)
            .first_raw()
            .unwrap_or("application/octet-stream")
            .to_string();

        let kind = if IMAGE_SUFFIXES.contains(&suffix.as_str()) {
            "image"
        } else if suffix == ".pdf" {
            "pdf"
        } else if BLOCKED_INLINE_SUFFIXES.contains(&suffix.as_str()) {
            media_type = "application/octet-stream".to_string();
            "attachment"
        } else {
            "attachment"
        };

        let size_bytes = fs::metadata(&canonical).map(|m| m.len()).unwrap_or(0);
        let display_name = canonical
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("file")
            .to_string();

        let art_id = artifact_id(task_id, &canonical);
        self.store.upsert_artifact(
            &art_id,
            task_id,
            resource_id,
            kind,
            &canonical,
            &display_name,
            &media_type,
            size_bytes,
            page_index.and_then(|v| usize::try_from(v).ok()),
        )?;
        Ok(json!({
            "id": art_id,
            "task_id": task_id,
            "resource_id": resource_id,
            "kind": kind,
            "path": canonical.to_string_lossy().to_string(),
            "display_name": display_name,
            "media_type": media_type,
            "size_bytes": size_bytes,
            "page_index": page_index,
        }))
    }

    pub fn list_artifacts(
        &self,
        task_id: Option<&str>,
        resource_id: Option<&str>,
        kind: Option<&str>,
        limit: usize,
        offset: usize,
    ) -> AppResult<Vec<Value>> {
        let mut items = self
            .store
            .artifacts(task_id, resource_id, kind, limit, offset)?;
        let mut task_cache: HashMap<String, Option<Value>> = HashMap::new();
        let output_root = self.current_output_root();

        for item in &mut items {
            let tid = item
                .get("task_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let task_val = task_cache
                .entry(tid.clone())
                .or_insert_with(|| {
                    if tid.is_empty() {
                        None
                    } else {
                        self.store.get_task(&tid).ok().flatten()
                    }
                })
                .clone();
            self.attach_task_display(item, task_val.as_ref());
            self.attach_path_display(item, &output_root);
        }
        Ok(items)
    }

    pub fn browser_root(&self, task_id: Option<&str>) -> AppResult<PathBuf> {
        let out_root = self.current_output_root();
        match task_id.filter(|s| !s.trim().is_empty()) {
            Some(tid) => {
                let task = self
                    .store
                    .get_task(tid)?
                    .ok_or_else(|| AppError::NotFound("Task not found".to_string()))?;
                let raw_dir = task
                    .get("output_dir")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .trim();
                if raw_dir.is_empty() {
                    Ok(out_root.join("tasks").join(tid))
                } else {
                    let p = expand_tilde(raw_dir);
                    if p.is_absolute() {
                        Ok(p)
                    } else {
                        Ok(out_root.join(p))
                    }
                }
            }
            None => Ok(out_root.join("tasks")),
        }
    }

    pub fn browser_file_path(
        &self,
        path: Option<&str>,
        task_id: Option<&str>,
        allow_dir: bool,
    ) -> AppResult<PathBuf> {
        let root = self.browser_root(task_id)?;
        let rel = normalize_relative_browser_path(path)?;
        let candidate = if rel.as_os_str().is_empty() {
            root.clone()
        } else {
            root.join(&rel)
        };
        safe_browser_path(&candidate, &root, true)?;
        if !allow_dir && candidate.exists() && !candidate.is_file() {
            return Err(AppError::NotFound("File not found".to_string()));
        }
        Ok(candidate)
    }

    pub fn browser_list(&self, task_id: Option<&str>, path: Option<&str>) -> AppResult<Value> {
        let root = self.browser_root(task_id)?;
        let current_dir = self.browser_file_path(path, task_id, true)?;
        let mut children = Vec::new();
        if current_dir.exists() {
            if !current_dir.is_dir() {
                return Err(AppError::Validation("Path is not a directory".to_string()));
            }
            for entry in fs::read_dir(&current_dir)?.flatten() {
                let child = entry.path();
                if is_visible_path(&child, &root) {
                    if let Ok(item) = browser_fs_entry(&child, &root) {
                        children.push(item);
                    }
                }
            }
        }
        sort_browser_entries(&mut children);
        Ok(json!({
            "current_path": relative_posix(&current_dir, &root),
            "items": children,
        }))
    }

    pub fn browser_search(
        &self,
        task_id: Option<&str>,
        path: Option<&str>,
        filter_text: &str,
        deep: bool,
    ) -> AppResult<Value> {
        let root = self.browser_root(task_id)?;
        let current_dir = self.browser_file_path(path, task_id, true)?;
        if !current_dir.exists() {
            return Ok(json!({ "items": [] }));
        }
        if !current_dir.is_dir() {
            return Err(AppError::Validation("Path is not a directory".to_string()));
        }

        let needle = filter_text.trim().to_lowercase();
        let max_depth = if deep { 16 } else { 1 };
        let mut matched = Vec::new();

        for entry in WalkDir::new(&current_dir)
            .min_depth(1)
            .max_depth(max_depth)
            .follow_links(false)
            .into_iter()
            .flatten()
        {
            let p = entry.path();
            if !p.is_file() || !is_visible_path(p, &root) {
                continue;
            }
            let Ok(item) = browser_fs_entry(p, &root) else {
                continue;
            };
            let name_s = item.get("name").and_then(Value::as_str).unwrap_or("");
            let rel_s = item
                .get("relative_path")
                .and_then(Value::as_str)
                .unwrap_or("");
            let haystack = format!("{name_s} {rel_s}").to_lowercase();
            if needle.is_empty() || haystack.contains(&needle) {
                matched.push(item);
            }
        }

        sort_browser_entries(&mut matched);
        Ok(json!({ "items": matched }))
    }

    pub fn resolve_browser_file(
        &self,
        path: &str,
        task_id: Option<&str>,
    ) -> AppResult<(PathBuf, String)> {
        let file_path = self.browser_file_path(Some(path), task_id, false)?;
        if !file_path.is_file() {
            return Err(AppError::NotFound("File not found".to_string()));
        }
        let suffix = file_path
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| format!(".{}", s.to_lowercase()))
            .unwrap_or_default();
        let mime = if BLOCKED_INLINE_SUFFIXES.contains(&suffix.as_str()) {
            "application/octet-stream".to_string()
        } else {
            mime_guess::from_path(&file_path)
                .first_raw()
                .unwrap_or("application/octet-stream")
                .to_string()
        };
        Ok((file_path, mime))
    }

    pub fn resolve_artifact_file(&self, artifact_id_val: &str) -> AppResult<(PathBuf, String)> {
        let art = self
            .store
            .artifact(artifact_id_val)?
            .ok_or_else(|| AppError::NotFound("Artifact not found".to_string()))?;
        let raw_path = art
            .get("path")
            .and_then(Value::as_str)
            .unwrap_or("");
        let p = PathBuf::from(raw_path);
        if !p.is_file() || p.is_symlink() {
            return Err(AppError::NotFound("Artifact file not found on disk".to_string()));
        }
        let suffix = p
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| format!(".{}", s.to_lowercase()))
            .unwrap_or_default();
        let mime = if BLOCKED_INLINE_SUFFIXES.contains(&suffix.as_str()) {
            "application/octet-stream".to_string()
        } else {
            art.get("media_type")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| {
                    mime_guess::from_path(&p)
                        .first_raw()
                        .unwrap_or("application/octet-stream")
                        .to_string()
                })
        };
        Ok((p, mime))
    }

    /// Copies a browsable file to a user-chosen destination path (Save-As dialog result).
    pub fn save_browser_file_to(
        &self,
        path: &str,
        task_id: Option<&str>,
        destination: &Path,
    ) -> AppResult<Value> {
        let (src, _) = self.resolve_browser_file(path, task_id)?;
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)?;
        }
        let bytes = fs::copy(&src, destination)?;
        Ok(json!({
            "saved": true,
            "destination": destination.to_string_lossy().to_string(),
            "size_bytes": bytes,
        }))
    }

    /// Exports all or selected files of `task_id` directly to `destination_zip` chosen via native dialog.
    pub fn export_zip_to_path(
        &self,
        task_id: &str,
        selected_paths: &[String],
        destination_zip: &Path,
    ) -> AppResult<Value> {
        let root = self.browser_root(Some(task_id))?;
        let mut files = Vec::new();
        if !selected_paths.is_empty() {
            for rel in selected_paths {
                if rel.trim().is_empty() {
                    continue;
                }
                if let Ok(p) = self.browser_file_path(Some(rel), Some(task_id), false) {
                    if p.is_file() {
                        files.push(p);
                    }
                }
            }
        } else if root.exists() {
            for entry in WalkDir::new(&root)
                .min_depth(1)
                .follow_links(false)
                .into_iter()
                .flatten()
            {
                let p = entry.path();
                if p.is_file() && is_visible_path(p, &root) {
                    files.push(p.to_path_buf());
                }
            }
        }

        if files.is_empty() {
            return Err(AppError::Validation("没有可打包的文件".to_string()));
        }

        if let Some(parent) = destination_zip.parent() {
            fs::create_dir_all(parent)?;
        }

        let tmp_zip = destination_zip.with_extension("zip.tmp");
        let out_file = File::create(&tmp_zip)?;
        let mut writer = ZipWriter::new(out_file);
        let options = SimpleFileOptions::default()
            .compression_method(CompressionMethod::Deflated);

        let mut included = Vec::new();
        let mut missing = Vec::new();
        let mut buf = vec![0u8; 64 * 1024];

        for file_path in files {
            let rel = relative_posix(&file_path, &root);
            if !file_path.exists() {
                missing.push(json!({ "path": rel, "reason": "文件不存在" }));
                continue;
            }
            let arc_parts: Vec<String> = rel
                .split('/')
                .filter(|s| !s.is_empty())
                .map(|part| safe_filename(part, "未命名"))
                .collect();
            let arcname = if arc_parts.is_empty() {
                "未命名".to_string()
            } else {
                arc_parts.join("/")
            };

            writer
                .start_file(&arcname, options)
                .map_err(|e| AppError::Message(format!("写入 ZIP 条目失败：{e}")))?;
            let mut src = File::open(&file_path)?;
            loop {
                let n = src.read(&mut buf)?;
                if n == 0 {
                    break;
                }
                writer.write_all(&buf[..n])?;
            }
            included.push(json!({ "path": rel, "name": arcname }));
        }

        if included.is_empty() {
            let _ = fs::remove_file(&tmp_zip);
            return Err(AppError::Validation("没有可用文件可打包".to_string()));
        }

        let manifest = json!({
            "included": included,
            "missing": missing,
        });
        writer
            .start_file("manifest.json", options)
            .map_err(|e| AppError::Message(format!("写入 manifest.json 失败：{e}")))?;
        writer.write_all(serde_json::to_string_pretty(&manifest)?.as_bytes())?;
        writer
            .finish()
            .map_err(|e| AppError::Message(format!("完成 ZIP 归档失败：{e}")))?;

        fs::rename(&tmp_zip, destination_zip)?;
        let size_bytes = fs::metadata(destination_zip).map(|m| m.len()).unwrap_or(0);
        let display_name = destination_zip
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("export.zip")
            .to_string();

        Ok(json!({
            "id": format!("exp_{}", uuid::Uuid::new_v4().simple()),
            "task_id": task_id,
            "status": "completed",
            "display_name": display_name,
            "file_path": destination_zip.to_string_lossy().to_string(),
            "size_bytes": size_bytes,
            "included_count": included.len(),
        }))
    }

    pub fn task_display_name(&self, task_id: &str) -> String {
        let mut item = json!({ "task_id": task_id });
        let task = self.store.get_task(task_id).ok().flatten();
        self.attach_task_display(&mut item, task.as_ref());
        item.get("task_display_name")
            .and_then(Value::as_str)
            .unwrap_or_else(|| "筛选任务")
            .to_string()
    }

    pub fn attach_task_display(&self, item: &mut Value, task: Option<&Value>) {
        let tid = item
            .get("task_id")
            .or_else(|| item.get("id"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let mut title = String::new();
        if let Some(t) = task {
            title = t
                .get("title")
                .and_then(Value::as_str)
                .filter(|s| !s.trim().is_empty())
                .or_else(|| {
                    t.get("spec")
                        .and_then(|sp| sp.get("title"))
                        .and_then(Value::as_str)
                })
                .unwrap_or("")
                .trim()
                .to_string();
        }
        let filter_name = task
            .and_then(|t| t.get("spec"))
            .map(|spec| build_filter_display_name(&self.store, spec))
            .unwrap_or_default();
        let display = if !title.is_empty() {
            title.clone()
        } else if !filter_name.is_empty() {
            filter_name
        } else {
            short_task_label(&tid)
        };
        if let Value::Object(ref mut map) = item {
            map.insert("task_title".to_string(), Value::String(title));
            map.insert("task_display_name".to_string(), Value::String(display));
        }
    }

    fn attach_path_display(&self, item: &mut Value, output_root: &Path) {
        let tid = item
            .get("task_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let raw_path = item
            .get("path")
            .and_then(Value::as_str)
            .unwrap_or("");
        let p = Path::new(raw_path);
        let rel_parts: Vec<String> = p
            .strip_prefix(output_root)
            .map(|rel| {
                rel.components()
                    .filter_map(|c| match c {
                        Component::Normal(s) => Some(s.to_string_lossy().to_string()),
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default();

        let inside_task: &[String] = if !tid.is_empty()
            && rel_parts.len() >= 2
            && rel_parts[0] == "tasks"
            && rel_parts[1] == tid
        {
            &rel_parts[2..]
        } else {
            &rel_parts
        };

        let dir_parts = if inside_task.len() > 1 {
            &inside_task[..inside_task.len() - 1]
        } else {
            &[]
        };
        let resource_dir_name = if dir_parts.len() >= 6 {
            dir_parts.last().cloned().unwrap_or_default()
        } else {
            String::new()
        };
        let hierarchy_parts: Vec<String> = if !resource_dir_name.is_empty() && !dir_parts.is_empty()
        {
            dir_parts[..dir_parts.len() - 1].to_vec()
        } else {
            dir_parts.to_vec()
        };
        let hierarchy_path = if hierarchy_parts.is_empty() {
            "未分类".to_string()
        } else {
            hierarchy_parts.join("/")
        };
        let kind_label = match item.get("kind").and_then(Value::as_str).unwrap_or("") {
            "image" => "图片",
            "pdf" => "PDF",
            "attachment" => "附件",
            other if !other.is_empty() => other,
            _ => "文件",
        }
        .to_string();

        if let Value::Object(ref mut map) = item {
            map.insert(
                "relative_path".to_string(),
                Value::String(inside_task.join("/")),
            );
            map.insert(
                "directory_path".to_string(),
                Value::String(dir_parts.join("/")),
            );
            map.insert("hierarchy_parts".to_string(), json!(hierarchy_parts));
            map.insert("hierarchy_path".to_string(), Value::String(hierarchy_path));
            map.insert(
                "resource_dir_name".to_string(),
                Value::String(resource_dir_name),
            );
            map.insert("kind_label".to_string(), Value::String(kind_label));
        }
    }
}

pub fn build_filter_display_name(store: &SqliteStore, spec: &Value) -> String {
    let Some(spec_obj) = spec.as_object() else {
        return String::new();
    };
    let settings = spec_obj.get("settings").and_then(Value::as_object);
    let filters = spec_obj.get("filters").and_then(Value::as_object);
    let filter_labels = spec_obj.get("filter_labels").and_then(Value::as_object);
    let phase = settings
        .and_then(|s| s.get("study_phase_code"))
        .and_then(Value::as_str)
        .unwrap_or("");
    let catalog_cache = store.get_kv("catalog_cache").ok().flatten();

    let mut parts: Vec<String> = Vec::new();
    let phase_label = catalog_cache
        .as_ref()
        .and_then(|c| c.get("study_phases"))
        .and_then(|p| p.get(phase))
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| match phase {
            "200" => "初中".to_string(),
            "300" => "高中".to_string(),
            other => other.to_string(),
        });
    if !phase_label.is_empty() {
        parts.push(phase_label);
    }

    let subject_map: HashMap<String, String> = catalog_cache
        .as_ref()
        .and_then(|c| c.get("subjects"))
        .and_then(|s| s.get(phase))
        .and_then(Value::as_object)
        .map(|obj| {
            obj.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                .collect()
        })
        .unwrap_or_default();

    if let Some(subjects) = spec_obj.get("subjects").and_then(Value::as_array) {
        let mut labels = Vec::new();
        for sub in subjects {
            let code = sub.get("code").and_then(Value::as_str).unwrap_or("");
            let name = sub
                .get("name")
                .and_then(Value::as_str)
                .filter(|s| !s.trim().is_empty())
                .map(str::to_string)
                .or_else(|| subject_map.get(code).cloned())
                .unwrap_or_default();
            if !name.is_empty() && name != "不限" {
                labels.push(name);
            } else if !code.is_empty() && !code.chars().all(|c| c.is_ascii_digit()) {
                labels.push(code.to_string());
            }
        }
        if !labels.is_empty() {
            let head: Vec<&str> = labels.iter().take(2).map(String::as_str).collect();
            let suffix = if labels.len() > 2 { "等" } else { "" };
            parts.push(format!("{}{suffix}", head.join("、")));
        }
    }

    let fields = [
        ("provinces", "provinceCode"),
        ("grades", "gradeCode"),
        ("terms", "termCode"),
        ("years", "yearCode"),
        ("scenes", "sceneCode"),
        ("ranks", "rank"),
    ];
    for (fkey, cat_field) in fields {
        let values = extract_string_list(filters.and_then(|f| f.get(fkey)));
        if values.is_empty() {
            continue;
        }
        let mut labels = extract_string_list(filter_labels.and_then(|fl| fl.get(fkey)));
        if labels.is_empty() {
            labels = lookup_catalog_labels(catalog_cache.as_ref(), phase, cat_field, &values);
        }
        if !labels.is_empty() {
            let head: Vec<&str> = labels.iter().take(2).map(String::as_str).collect();
            let suffix = if labels.len() > 2 { "等" } else { "" };
            parts.push(format!("{}{suffix}", head.join("、")));
        }
    }

    if let Some(ft) = settings
        .and_then(|s| s.get("file_type"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        parts.push(ft.to_string());
    }

    let mut deduped = Vec::new();
    for p in parts {
        if !p.is_empty() && !deduped.contains(&p) {
            deduped.push(p);
        }
    }
    deduped.join(" / ")
}

fn extract_string_list(val: Option<&Value>) -> Vec<String> {
    match val {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(arr)) => arr
            .iter()
            .filter_map(|v| match v {
                Value::String(s) if !s.is_empty() => Some(s.clone()),
                Value::Number(n) => Some(n.to_string()),
                _ => None,
            })
            .collect(),
        Some(Value::String(s)) if !s.is_empty() => vec![s.clone()],
        Some(other) => {
            let s = other.to_string();
            if s.is_empty() {
                Vec::new()
            } else {
                vec![s]
            }
        }
    }
}

fn lookup_catalog_labels(
    cache: Option<&Value>,
    phase: &str,
    field: &str,
    values: &[String],
) -> Vec<String> {
    let Some(options) = cache
        .and_then(|c| c.get("catalogs"))
        .and_then(|cat| cat.get(phase))
        .and_then(|ph| ph.get(field))
        .and_then(Value::as_array)
    else {
        return Vec::new();
    };
    let mut by_code = HashMap::new();
    for opt in options {
        let code = opt.get("code").and_then(Value::as_str).unwrap_or("");
        let name = opt.get("name").and_then(Value::as_str).unwrap_or("");
        if !code.is_empty() && !name.is_empty() {
            by_code.insert(code.to_string(), name.to_string());
        }
    }
    let resolved: Vec<String> = values
        .iter()
        .filter_map(|v| by_code.get(v).cloned())
        .collect();
    if resolved.len() == values.len() {
        resolved
    } else {
        Vec::new()
    }
}

pub fn short_task_label(task_id: &str) -> String {
    if task_id.is_empty() {
        return "未关联任务".to_string();
    }
    let chars: Vec<char> = task_id.chars().collect();
    let suffix: String = if chars.len() > 8 {
        chars[chars.len() - 8..].iter().collect()
    } else {
        task_id.to_string()
    };
    format!("筛选任务 {suffix}")
}

fn artifact_id(task_id: &str, path: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(format!("{task_id}:{}", path.display()).as_bytes());
    let hex = format!("{:x}", hasher.finalize());
    format!("art_{}", &hex[..24])
}

fn normalize_relative_browser_path(path: Option<&str>) -> AppResult<PathBuf> {
    let raw = path.unwrap_or("").trim().replace('\\', "/");
    if raw.is_empty() {
        return Ok(PathBuf::new());
    }
    if raw.starts_with('/') || raw.contains(':') {
        return Err(AppError::Validation("Absolute paths are not browsable".to_string()));
    }
    let mut out = PathBuf::new();
    for part in raw.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            return Err(AppError::Validation(
                "Parent path traversal is not allowed".to_string(),
            ));
        }
        if part.starts_with('.') {
            return Err(AppError::Validation(
                "Hidden files are not browsable".to_string(),
            ));
        }
        out.push(part);
    }
    Ok(out)
}

fn safe_browser_path(candidate: &Path, root: &Path, allow_missing: bool) -> AppResult<()> {
    let rel = candidate
        .strip_prefix(root)
        .map_err(|_| AppError::Validation("Path escapes the file browser root".to_string()))?;
    let mut cur = root.to_path_buf();
    for comp in rel.components() {
        match comp {
            Component::Normal(os) => {
                let s = os.to_string_lossy();
                if s.starts_with('.') {
                    return Err(AppError::Validation(
                        "Hidden files are not browsable".to_string(),
                    ));
                }
                cur.push(os);
                if cur.exists() && cur.is_symlink() {
                    return Err(AppError::Validation(
                        "Symbolic links are not browsable".to_string(),
                    ));
                }
            }
            Component::CurDir => {}
            _ => {
                return Err(AppError::Validation(
                    "Path escapes the file browser root".to_string(),
                ))
            }
        }
    }
    if !allow_missing && !candidate.exists() {
        return Err(AppError::NotFound("File not found".to_string()));
    }
    Ok(())
}

fn is_visible_path(path: &Path, root: &Path) -> bool {
    safe_browser_path(path, root, false).is_ok()
}

fn relative_posix(path: &Path, root: &Path) -> String {
    let Ok(rel) = path.strip_prefix(root) else {
        return String::new();
    };
    let parts: Vec<String> = rel
        .components()
        .filter_map(|c| match c {
            Component::Normal(s) => Some(s.to_string_lossy().to_string()),
            _ => None,
        })
        .collect();
    parts.join("/")
}

fn browser_fs_entry(path: &Path, root: &Path) -> AppResult<Value> {
    let meta = fs::metadata(path)?;
    let is_dir = meta.is_dir();
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string();
    let ext = if is_dir {
        String::new()
    } else {
        path.extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_lowercase()
    };
    let rel = relative_posix(path, root);
    let parent_rel = path
        .parent()
        .map(|p| relative_posix(p, root))
        .unwrap_or_default();
    let modified_ms = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    let media_type = if is_dir {
        Value::Null
    } else {
        Value::String(
            mime_guess::from_path(path)
                .first_raw()
                .unwrap_or("application/octet-stream")
                .to_string(),
        )
    };
    let size_val = if is_dir {
        Value::Null
    } else {
        json!(meta.len())
    };

    Ok(json!({
        "name": name,
        "extension": ext,
        "relative_path": rel,
        "parent_path": parent_rel,
        "item_type": if is_dir { "folder" } else { "file" },
        "size_bytes": size_val,
        "modified_at": modified_ms,
        "media_type": media_type,
    }))
}

fn sort_browser_entries(items: &mut [Value]) {
    items.sort_by(|a, b| {
        let rank_a = if a.get("item_type").and_then(Value::as_str) == Some("folder") {
            0
        } else {
            1
        };
        let rank_b = if b.get("item_type").and_then(Value::as_str) == Some("folder") {
            0
        } else {
            1
        };
        let name_a = a
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_lowercase();
        let name_b = b
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_lowercase();
        rank_a.cmp(&rank_b).then_with(|| name_a.cmp(&name_b))
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::AppSettings;

    #[test]
    fn browser_path_security_and_zip_export_work() {
        let dir = tempfile::tempdir().unwrap();
        let store = SqliteStore::open(&dir.path().join("data")).unwrap();
        let mut base = AppSettings::default();
        base.data_dir = dir.path().join("data");
        base.output_dir = dir.path().join("out");

        let task_dir = base.output_dir.join("tasks").join("task_1");
        let paper_dir = task_dir.join("北京/高一/数学/期中试卷");
        fs::create_dir_all(&paper_dir).unwrap();
        fs::write(paper_dir.join("第001页.png"), b"png-bytes").unwrap();
        fs::write(task_dir.join("北京/高一/数学/期中试卷.pdf"), b"%PDF-1.4\n%%EOF").unwrap();

        let _ = store
            .create_task("task_1", "crawl", &json!({"title": "北京高一数学"}), &task_dir, None)
            .unwrap();

        let svc = ArtifactService::new(store, base);
        assert!(svc.browser_file_path(Some("../secret"), Some("task_1"), false).is_err());
        assert!(svc.browser_file_path(Some("/etc/passwd"), Some("task_1"), false).is_err());

        let found = svc
            .browser_search(Some("task_1"), Some(""), "期中", true)
            .unwrap();
        assert_eq!(found["items"].as_array().unwrap().len(), 2);

        let zip_out = dir.path().join("exported.zip");
        let exp = svc.export_zip_to_path("task_1", &[], &zip_out).unwrap();
        assert_eq!(exp["status"], "completed");
        assert_eq!(exp["included_count"], 2);
        assert!(zip_out.is_file());
    }
}
