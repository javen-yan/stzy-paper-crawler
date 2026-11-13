use std::fs;
use std::path::Path;
use std::sync::Arc;

use serde_json::Value;
use tokio::sync::Semaphore;

use crate::converter::office::{humanize_conversion_error, source_kind};
use crate::converter::pdf::pdf_file_looks_valid;
use crate::converter::DocumentConverter;
use crate::crawler::account_scheduler::AccountScheduler;
use crate::crawler::api::StzyCrawlerApi;
use crate::crawler::client::StzyHttpClient;
use crate::error::{AppError, AppResult};
use crate::models::{
    ensure_directory, AppSettings, DownloadResult, ResourceArtifacts, ResourcePathBuilder,
    ResourceRecord, ResourceStatus,
};

const SUPPORTED_SOURCE_SUFFIXES: &[&str] = &[
    ".pdf", ".doc", ".docx", ".zip", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".webp", ".svg",
];

#[derive(Clone)]
pub struct DownloadService {
    pub settings: AppSettings,
    pub client: StzyHttpClient,
    pub api: StzyCrawlerApi,
    pub paths: ResourcePathBuilder,
    pub converter: DocumentConverter,
    pub account_scheduler: AccountScheduler,
    on_log: Arc<dyn Fn(String) + Send + Sync>,
}

impl DownloadService {
    pub fn new(
        settings: AppSettings,
        client: StzyHttpClient,
        api: StzyCrawlerApi,
        convert_semaphore: Option<Arc<Semaphore>>,
        on_log: Option<Arc<dyn Fn(String) + Send + Sync>>,
    ) -> Self {
        let log_cb = on_log.unwrap_or_else(|| Arc::new(|_| {}));
        let paths = ResourcePathBuilder::new(&settings);
        let converter = DocumentConverter::new(
            settings.clone(),
            client.clone(),
            convert_semaphore,
            Some(log_cb.clone()),
        );
        let account_scheduler =
            AccountScheduler::new(client.clone(), api.clone(), Some(log_cb.clone()));
        Self {
            settings,
            client,
            api,
            paths,
            converter,
            account_scheduler,
            on_log: log_cb,
        }
    }

    pub async fn handle_resource(&self, record: &mut ResourceRecord) -> AppResult<DownloadResult> {
        let directory = self.paths.resource_dir(record);
        let dir_str = directory.to_string_lossy().to_string();
        record.local_dir = dir_str.clone();
        ensure_directory(&directory)?;

        let expected_pages = record.page_count;
        let raw_suffix = record
            .raw
            .get("resourceSuffix")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .trim_start_matches('.')
            .to_lowercase();

        if matches!(raw_suffix.as_str(), "doc" | "docx" | "zip" | "rar" | "7z") {
            return self
                .download_other_source(record, &format!(".{raw_suffix}"))
                .await;
        }

        if record.page_count > 10 {
            let saved_count = DocumentConverter::saved_picture_count_from_dir(&directory);
            if expected_pages > 0 && saved_count >= expected_pages {
                (self.on_log)(format!(
                    "资源进度：{} - 已有完整文件 {saved_count}/{expected_pages}，标记完成",
                    record.resource_id
                ));
                return Ok(DownloadResult {
                    status: ResourceStatus::Completed,
                    saved_pages: saved_count,
                    expected_pages,
                    source: "existing".to_string(),
                    local_dir: dir_str,
                    error: String::new(),
                    images_added: 0,
                    paid_unavailable: 0,
                });
            }
            (self.on_log)(format!(
                "资源进度：{} - 页数 {}，下载原文",
                record.resource_id, record.page_count
            ));
            return self.download_full_pdf(record, "pdf", false).await;
        }

        (self.on_log)(format!("资源进度：{} - 获取预览图", record.resource_id));
        let pictures = self
            .api
            .resource_pictures(&record.resource_id, &record.resource_name)
            .await?;
        if !pictures.is_empty() {
            (self.on_log)(format!(
                "资源进度：{} - 预览图 {} 张",
                record.resource_id,
                pictures.len()
            ));
        } else {
            (self.on_log)(format!(
                "资源进度：{} - 未返回预览图，下载原文",
                record.resource_id
            ));
        }

        let images_added = self
            .converter
            .download_preview_images(record, &pictures, &directory)
            .await?;
        let saved_count = DocumentConverter::saved_picture_count_from_dir(&directory);

        if pictures.is_empty() || (record.page_count > 0 && saved_count < record.page_count) {
            (self.on_log)(format!(
                "预览图不完整：{} - 已保存 {saved_count}/{} 页，尝试下载原文补全",
                record.resource_id, record.page_count
            ));
            match self
                .download_full_pdf(record, "preview_fallback_pdf", true)
                .await
            {
                Ok(pdf_res) => {
                    return Ok(DownloadResult {
                        status: pdf_res.status,
                        saved_pages: saved_count.max(pdf_res.saved_pages),
                        expected_pages,
                        source: pdf_res.source,
                        local_dir: dir_str,
                        error: pdf_res.error,
                        images_added: images_added + pdf_res.images_added,
                        paid_unavailable: pdf_res.paid_unavailable,
                    });
                }
                Err(AppError::Cancelled) => return Err(AppError::Cancelled),
                Err(exc) => {
                    return Ok(DownloadResult {
                        status: ResourceStatus::Partial,
                        saved_pages: saved_count,
                        expected_pages,
                        source: "preview".to_string(),
                        local_dir: dir_str,
                        error: format!(
                            "预览接口仅返回 {saved_count}/{} 页，原文补全失败：{exc}",
                            record.page_count
                        ),
                        images_added,
                        paid_unavailable: 0,
                    });
                }
            }
        }

        Ok(Self::result_from_count(
            saved_count,
            expected_pages,
            "preview",
            dir_str,
            images_added,
        ))
    }

    pub async fn download_full_pdf(
        &self,
        record: &mut ResourceRecord,
        source: &str,
        force: bool,
    ) -> AppResult<DownloadResult> {
        let raw_suffix = record
            .raw
            .get("resourceSuffix")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .trim_start_matches('.')
            .to_lowercase();
        if !raw_suffix.is_empty() && raw_suffix != "pdf" {
            return self
                .download_other_source(record, &format!(".{raw_suffix}"))
                .await;
        }

        let directory = self.paths.resource_dir(record);
        let dir_str = directory.to_string_lossy().to_string();
        let artifacts = ResourceArtifacts::new(directory.clone());
        artifacts.prepare_resource_dir()?;

        if force {
            let _ = fs::remove_file(artifacts.temp_pdf());
            let _ = fs::remove_file(artifacts.final_pdf());
        }

        let mut pdf_path = if artifacts.temp_pdf().exists() {
            artifacts.temp_pdf()
        } else {
            artifacts.final_pdf()
        };
        if pdf_path.exists() && !pdf_file_looks_valid(&pdf_path) {
            let _ = fs::remove_file(&pdf_path);
        }

        let pdf_url = if !file_non_empty(&pdf_path) {
            (self.on_log)(format!(
                "资源进度：{} - 获取 PDF 地址",
                record.resource_id
            ));
            let url_res = self.account_scheduler.download_pdf_url(record).await;
            if url_res.status == Some(ResourceStatus::PaidUnavailable) {
                let mut err = if url_res.error.is_empty() {
                    "无账号支持，请补充 VIP 账号后恢复任务".to_string()
                } else {
                    url_res.error
                };
                if !err.contains("无账号支持，请补充 VIP 账号") {
                    err = format!("无账号支持，请补充 VIP 账号后恢复任务（{err}）");
                }
                return Ok(DownloadResult {
                    status: ResourceStatus::PaidUnavailable,
                    saved_pages: 0,
                    expected_pages: record.page_count,
                    source: source.to_string(),
                    local_dir: dir_str,
                    error: err,
                    images_added: 0,
                    paid_unavailable: url_res.paid_unavailable,
                });
            }
            if url_res.url.is_empty() {
                return Err(AppError::Message(if url_res.error.is_empty() {
                    "未获取到 PDF 下载地址".to_string()
                } else {
                    url_res.error
                }));
            }
            pdf_path = artifacts.temp_pdf();
            url_res.url
        } else {
            String::new()
        };

        (self.on_log)(format!(
            "资源进度：{} - PDF 转图片",
            record.resource_id
        ));
        match self
            .converter
            .download_pdf_and_convert(&pdf_url, &pdf_path, &directory)
            .await
        {
            Ok((converted, images_added)) => {
                (self.on_log)(format!(
                    "完成：{} - 已保存 {converted} 页",
                    record.resource_id
                ));
                Ok(Self::result_from_count(
                    converted,
                    record.page_count,
                    source,
                    dir_str,
                    images_added,
                ))
            }
            Err(AppError::Cancelled) => Err(AppError::Cancelled),
            Err(exc) => {
                let saved_count = DocumentConverter::saved_picture_count_from_dir(&directory);
                let expected_pages = record.page_count;
                if expected_pages > 0 && saved_count >= expected_pages {
                    (self.on_log)(format!(
                        "PDF 转图片异常但文件已完整：{} - 已保存 {saved_count}/{expected_pages} 页，标记完成",
                        record.resource_id
                    ));
                    return Ok(DownloadResult {
                        status: ResourceStatus::Completed,
                        saved_pages: saved_count,
                        expected_pages,
                        source: source.to_string(),
                        local_dir: dir_str,
                        error: String::new(),
                        images_added: 0,
                        paid_unavailable: 0,
                    });
                }
                Err(exc)
            }
        }
    }

    pub async fn download_other_source(
        &self,
        record: &mut ResourceRecord,
        suffix: &str,
    ) -> AppResult<DownloadResult> {
        if !SUPPORTED_SOURCE_SUFFIXES.contains(&suffix) {
            return Err(AppError::Message(format!(
                "暂不支持原文格式 {suffix}（支持 Word、ZIP、RAR、7z、PDF 和图片）"
            )));
        }

        let directory = self.paths.resource_dir(record);
        let dir_str = directory.to_string_lossy().to_string();
        ensure_directory(&directory)?;

        let original = directory.join(format!("源文件{suffix}"));
        if original.exists() && source_kind(&original).is_err() {
            let _ = fs::remove_file(&original);
        }

        if !original.exists() {
            (self.on_log)(format!(
                "资源进度：{} - 获取 {suffix} 原文地址",
                record.resource_id
            ));
            let res = self.account_scheduler.download_pdf_url(record).await;
            if res.status == Some(ResourceStatus::PaidUnavailable) {
                let reason = if res.error.is_empty() {
                    "原文不可下载"
                } else {
                    &res.error
                };
                return Ok(DownloadResult {
                    status: ResourceStatus::PaidUnavailable,
                    saved_pages: 0,
                    expected_pages: record.page_count,
                    source: "original".to_string(),
                    local_dir: dir_str,
                    error: format!("无账号支持，请补充 VIP 账号后恢复任务（{reason}）"),
                    images_added: 0,
                    paid_unavailable: res.paid_unavailable,
                });
            }
            if res.url.is_empty() {
                return Err(AppError::Message(if res.error.is_empty() {
                    "未获取到原文下载地址".to_string()
                } else {
                    res.error
                }));
            }

            let temporary = directory.join(format!("源文件{suffix}.download"));
            let dl_res = async {
                self.client
                    .download(&res.url, &temporary, None, &record.resource_name)
                    .await?;
                fs::rename(&temporary, &original)?;
                source_kind(&original)?;
                Ok::<(), AppError>(())
            }
            .await;

            if let Err(err) = dl_res {
                let _ = fs::remove_file(&temporary);
                let _ = fs::remove_file(&original);
                return Err(err);
            }
        }

        let mut expected_pages = record.page_count;
        let mut files_meta: Vec<Value> = Vec::new();
        if source_kind(&original)? == ".zip" {
            match self
                .api
                .resource_detail(&record.resource_id, &record.resource_name)
                .await
            {
                Ok(detail) => {
                    if let Some(arr) = detail.get("fileList").and_then(Value::as_array) {
                        files_meta = arr.iter().filter(|v| v.is_object()).cloned().collect();
                    }
                }
                Err(exc) => {
                    (self.on_log)(format!(
                        "ZIP 子文件目录不可用，按文件名排序：{} - {exc}",
                        record.resource_id
                    ));
                }
            }
            let counts: Vec<usize> = files_meta
                .iter()
                .map(|item| {
                    item.get("totalPage")
                        .and_then(|v| {
                            v.as_u64()
                                .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
                        })
                        .unwrap_or(0) as usize
                })
                .collect();
            expected_pages = if !counts.is_empty() && counts.iter().all(|&c| c > 0) {
                counts.iter().sum()
            } else {
                0
            };
        }

        (self.on_log)(format!(
            "资源进度：{} - 自动处理排版与字体并生成 PDF 和图片",
            record.resource_id
        ));
        match self
            .converter
            .convert_source_and_publish(&original, &directory, expected_pages, &files_meta)
            .await
        {
            Ok((converted, added, self_heal_note)) => {
                if let Value::Object(ref mut map) = record.raw {
                    map.entry("sourcePageNum".to_string())
                        .or_insert_with(|| Value::from(record.page_count));
                }
                record.page_count = converted;
                let mut res = Self::result_from_count(
                    converted,
                    converted,
                    "original_pdf",
                    dir_str,
                    added,
                );
                if res.status == ResourceStatus::Completed && !self_heal_note.is_empty() {
                    res.error = self_heal_note;
                }
                Ok(res)
            }
            Err(AppError::Cancelled) => Err(AppError::Cancelled),
            Err(exc) => Ok(DownloadResult {
                status: ResourceStatus::Partial,
                saved_pages: 0,
                expected_pages,
                source: "original".to_string(),
                local_dir: dir_str,
                error: humanize_conversion_error(&exc.to_string(), suffix),
                images_added: 0,
                paid_unavailable: 0,
            }),
        }
    }

    fn result_from_count(
        saved_count: usize,
        expected_pages: usize,
        source: &str,
        local_dir: String,
        images_added: usize,
    ) -> DownloadResult {
        if saved_count == 0 || (expected_pages > 0 && saved_count < expected_pages) {
            let err = if saved_count > 0 {
                format!("部分完成：已保存 {saved_count}/{expected_pages} 页")
            } else {
                "未生成有效页面".to_string()
            };
            return DownloadResult {
                status: ResourceStatus::Partial,
                saved_pages: saved_count,
                expected_pages,
                source: source.to_string(),
                local_dir,
                error: err,
                images_added,
                paid_unavailable: 0,
            };
        }
        DownloadResult {
            status: ResourceStatus::Completed,
            saved_pages: saved_count,
            expected_pages,
            source: source.to_string(),
            local_dir,
            error: String::new(),
            images_added,
            paid_unavailable: 0,
        }
    }
}

fn file_non_empty(path: &Path) -> bool {
    fs::metadata(path)
        .map(|m| m.is_file() && m.len() > 0)
        .unwrap_or(false)
}
