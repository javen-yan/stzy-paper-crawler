pub mod fonts;
pub mod office;
pub mod pdf;
pub mod svg;

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use serde_json::Value;
use tokio::sync::Semaphore;

use crate::converter::office::render_source_to_pages_and_pdf;
use crate::converter::pdf::{convert_originals_to_pdf, convert_pdf_to_pngs, pdf_file_looks_valid};
use crate::converter::svg::{
    convert_image_to_png, convert_svg_to_png, detect_svg_cjk_font_family, svg_needs_font_fallback,
};
use crate::crawler::client::StzyHttpClient;
use crate::error::{AppError, AppResult};
use crate::models::{AppSettings, ResourceArtifacts, ResourceRecord};

#[derive(Clone)]
pub struct DocumentConverter {
    pub settings: AppSettings,
    pub client: StzyHttpClient,
    pub convert_semaphore: Arc<Semaphore>,
    on_log: Arc<dyn Fn(String) + Send + Sync>,
}

impl DocumentConverter {
    pub fn new(
        settings: AppSettings,
        client: StzyHttpClient,
        convert_semaphore: Option<Arc<Semaphore>>,
        on_log: Option<Arc<dyn Fn(String) + Send + Sync>>,
    ) -> Self {
        let sem = convert_semaphore.unwrap_or_else(|| {
            Arc::new(Semaphore::new(settings.max_convert_workers.max(1)))
        });
        Self {
            settings,
            client,
            convert_semaphore: sem,
            on_log: on_log.unwrap_or_else(|| Arc::new(|_| {})),
        }
    }

    pub async fn download_preview_images(
        &self,
        record: &ResourceRecord,
        pictures: &[String],
        directory: &Path,
    ) -> AppResult<usize> {
        let artifacts = ResourceArtifacts::new(directory.to_path_buf());
        artifacts.prepare_resource_dir()?;
        artifacts.prepare_original_dir()?;

        let mut images_added = 0usize;
        let mut rendered_pngs: Vec<PathBuf> = Vec::with_capacity(pictures.len());
        let total = pictures.len();

        for (i, url) in pictures.iter().enumerate() {
            if self.client.cancel.is_cancelled() {
                return Err(AppError::Cancelled);
            }
            let index = i + 1;
            let clean_url = url.split('?').next().unwrap_or(url);
            let suffix = Path::new(clean_url)
                .extension()
                .and_then(|s| s.to_str())
                .map(|s| format!(".{s}"))
                .unwrap_or_else(|| ".svg".to_string());

            let original = artifacts.original_dir().join(format!("练习{index}{suffix}"));
            let target = artifacts.page_png(index);
            let had_target = file_non_empty(&target);

            if original.exists() && !Self::original_file_looks_valid(&original, url) {
                let _ = fs::remove_file(&original);
            }
            if !file_non_empty(&original) {
                (self.on_log)(format!(
                    "预览图下载：{} - {index}/{total}",
                    record.resource_id
                ));
                self.client
                    .download(url, &original, None, &record.resource_name)
                    .await?;
            }

            self.convert_original_to_png(&original, &target, &record.resource_id, index, total)
                .await?;
            rendered_pngs.push(target.clone());
            if !had_target && file_non_empty(&target) {
                images_added += 1;
            }
            (self.on_log)(format!(
                "预览图完成：{} - {index}/{total}",
                record.resource_id
            ));
            self.sleep_jitter(self.settings.image_delay_seconds).await?;
        }

        if !rendered_pngs.is_empty() {
            (self.on_log)(format!("资源进度：{} - 由截图合成 PDF", record.resource_id));
            let _permit = self
                .convert_semaphore
                .acquire()
                .await
                .map_err(|_| AppError::Cancelled)?;
            let temp_pdf = artifacts.temp_pdf();
            let settings_clone = self.settings.clone();
            let pngs_clone = rendered_pngs.clone();
            tokio::task::spawn_blocking(move || {
                convert_originals_to_pdf(&pngs_clone, &temp_pdf, &settings_clone)
            })
            .await
            .map_err(|e| AppError::Message(format!("PDF 合成线程异常：{e}")))??;

            artifacts.publish_pdf(&artifacts.temp_pdf())?;
            artifacts.cleanup_transient_artifacts();
        }

        Ok(images_added)
    }

    pub async fn download_pdf_and_convert(
        &self,
        pdf_url: &str,
        pdf_path: &Path,
        directory: &Path,
    ) -> AppResult<(usize, usize)> {
        let artifacts = ResourceArtifacts::new(directory.to_path_buf());
        artifacts.prepare_resource_dir()?;

        let mut source_pdf = pdf_path.to_path_buf();
        if source_pdf.exists() && !pdf_file_looks_valid(&source_pdf) {
            let _ = fs::remove_file(&source_pdf);
        }
        if !file_non_empty(&source_pdf) {
            let tmp_pdf = artifacts.temp_pdf();
            self.client.download(pdf_url, &tmp_pdf, None, "").await?;
            source_pdf = tmp_pdf;
        }

        let existing_count = Self::saved_picture_count_from_dir(directory);
        let converted = self.run_pdf_to_pngs(&source_pdf, directory).await?;
        artifacts.publish_pdf(&source_pdf)?;
        artifacts.cleanup_transient_artifacts();
        Ok((converted, converted.saturating_sub(existing_count)))
    }

    pub async fn convert_source_and_publish(
        &self,
        original: &Path,
        directory: &Path,
        _expected_pages: usize,
        files_metadata: &[Value],
    ) -> AppResult<(usize, usize, String)> {
        let existing = Self::saved_picture_count_from_dir(directory);
        let artifacts = ResourceArtifacts::new(directory.to_path_buf());

        let _permit = self
            .convert_semaphore
            .acquire()
            .await
            .map_err(|_| AppError::Cancelled)?;

        let orig_buf = original.to_path_buf();
        let dir_buf = directory.to_path_buf();
        let settings_clone = self.settings.clone();
        let files_clone = files_metadata.to_vec();

        let (count, report) = tokio::task::spawn_blocking(move || -> AppResult<(usize, Value)> {
            let staging_dir = tempfile::Builder::new()
                .prefix(".convert-")
                .tempdir_in(&dir_buf)?;
            let staging = staging_dir.path();
            let converted_pdf = staging.join("converted.pdf");
            let (rendered_count, report) = render_source_to_pages_and_pdf(
                &orig_buf,
                staging,
                &converted_pdf,
                settings_clone.document_timeout_seconds as f64,
                &files_clone,
                &settings_clone,
            )?;
            if rendered_count == 0 {
                return Err(AppError::Message(
                    "页面图片生成异常，已保留原文件".to_string(),
                ));
            }

            let report_path = staging.join(".conversion-report.json");
            let pretty = serde_json::to_string_pretty(&report)?;
            fs::write(&report_path, pretty)?;

            artifacts.publish_pdf(&converted_pdf)?;

            // Atomically swap 练习*.png pages & publish any companion audio files
            if let Ok(entries) = fs::read_dir(&dir_buf) {
                for entry in entries.flatten() {
                    let p = entry.path();
                    if is_practice_png(&p) {
                        let _ = fs::remove_file(&p);
                    }
                }
            }
            if let Ok(entries) = fs::read_dir(staging) {
                for entry in entries.flatten() {
                    let p = entry.path();
                    if is_practice_png(&p) {
                        if let Some(name) = p.file_name() {
                            fs::rename(&p, dir_buf.join(name))?;
                        }
                    } else if let Some(name_str) = p.file_name().and_then(|s| s.to_str()) {
                        if let Some(clean_audio) = name_str.strip_prefix("companion_") {
                            let _ = fs::rename(&p, dir_buf.join(clean_audio));
                        }
                    }
                }
            }
            let _ = fs::remove_file(dir_buf.join("conversion-report.json"));
            fs::rename(&report_path, dir_buf.join(".conversion-report.json"))?;
            Ok((rendered_count, report))
        })
        .await
        .map_err(|e| AppError::Message(format!("源文件转换线程异常：{e}")))??;

        let self_heal_note = report
            .get("self_heal_note")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        Ok((count, count.saturating_sub(existing), self_heal_note))
    }

    async fn convert_original_to_png(
        &self,
        original: &Path,
        target: &Path,
        resource_id: &str,
        page_index: usize,
        page_total: usize,
    ) -> AppResult<()> {
        if file_non_empty(target) {
            return Ok(());
        }
        let is_svg = original
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| s.eq_ignore_ascii_case("svg"))
            .unwrap_or(false);

        if is_svg && svg_needs_font_fallback(original) {
            let progress = if page_index > 0 && page_total > 0 {
                format!(" - {page_index}/{page_total}")
            } else {
                String::new()
            };
            let prefix = if !resource_id.is_empty() {
                format!("{resource_id}{progress}，")
            } else {
                String::new()
            };
            let fam = detect_svg_cjk_font_family(&self.settings);
            let fam_label = if fam.is_empty() {
                "系统默认字体"
            } else {
                &fam
            };
            let fname = original
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("page.svg");
            (self.on_log)(format!(
                "使用内置转换器处理复杂 SVG：{prefix}{fname}，字体回退 {fam_label}"
            ));
        }

        let _permit = self
            .convert_semaphore
            .acquire()
            .await
            .map_err(|_| AppError::Cancelled)?;

        let orig_buf = original.to_path_buf();
        let target_buf = target.to_path_buf();
        let settings_clone = self.settings.clone();
        tokio::task::spawn_blocking(move || {
            if is_svg {
                convert_svg_to_png(&orig_buf, &target_buf, &settings_clone)
            } else {
                convert_image_to_png(&orig_buf, &target_buf)
            }
        })
        .await
        .map_err(|e| AppError::Message(format!("图片转换线程异常：{e}")))?
    }

    pub async fn run_pdf_to_pngs(&self, pdf_path: &Path, directory: &Path) -> AppResult<usize> {
        if !file_non_empty(pdf_path) {
            return Ok(0);
        }
        let _permit = self
            .convert_semaphore
            .acquire()
            .await
            .map_err(|_| AppError::Cancelled)?;

        let pdf_buf = pdf_path.to_path_buf();
        let dir_buf = directory.to_path_buf();
        let settings_clone = self.settings.clone();
        tokio::task::spawn_blocking(move || {
            convert_pdf_to_pngs(&pdf_buf, &dir_buf, &settings_clone)
        })
        .await
        .map_err(|e| AppError::Message(format!("PDF 渲染线程异常：{e}")))?
    }

    pub fn saved_picture_count_from_dir(directory: &Path) -> usize {
        let Ok(entries) = fs::read_dir(directory) else {
            return 0;
        };
        entries
            .flatten()
            .map(|e| e.path())
            .filter(|p| is_practice_png(p) && file_non_empty(p))
            .count()
    }

    pub fn original_file_looks_valid(path: &Path, url: &str) -> bool {
        if !file_non_empty(path) {
            return false;
        }
        let Ok(bytes) = fs::read(path) else {
            return false;
        };
        let head_len = bytes.len().min(4096);
        let head_str = String::from_utf8_lossy(&bytes[..head_len]).to_lowercase();
        if head_str.contains("<html") || head_str.contains("<!doctype html") {
            return false;
        }
        let suffix = path
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| s.to_lowercase())
            .unwrap_or_else(|| {
                let clean = url.split('?').next().unwrap_or(url);
                Path::new(clean)
                    .extension()
                    .and_then(|s| s.to_str())
                    .unwrap_or("")
                    .to_lowercase()
            });
        match suffix.as_str() {
            "pdf" => bytes.starts_with(b"%PDF"),
            "svg" => head_str.contains("<svg"),
            _ => true,
        }
    }

    async fn sleep_jitter(&self, base_secs: f64) -> AppResult<()> {
        let jitter: f64 = rand::thread_rng().gen_range(0.0..0.2);
        let delay = base_secs.max(0.0) + jitter;
        if delay <= 0.001 {
            return Ok(());
        }
        tokio::select! {
            _ = self.client.cancel.cancelled() => Err(AppError::Cancelled),
            _ = tokio::time::sleep(Duration::from_secs_f64(delay)) => Ok(()),
        }
    }
}

fn file_non_empty(path: &Path) -> bool {
    fs::metadata(path)
        .map(|m| m.is_file() && m.len() > 0)
        .unwrap_or(false)
}

fn is_practice_png(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|s| s.to_str()) else {
        return false;
    };
    name.starts_with("练习") && name.ends_with(".png")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::converter::office::{detect_office_engine, source_kind};
    use crate::converter::pdf::inspect_pdf;
    use tempfile::tempdir;

    #[test]
    fn renders_subset_font_svg_and_real_site_svg_fixture() {
        let dir = tempdir().unwrap();
        let mut settings = AppSettings::default();
        settings.data_dir = dir.path().join("data");
        settings.output_dir = dir.path().join("out");

        // 1. Subset @font-face SVG fallback test
        let subset_svg = dir.path().join("subset.svg");
        fs::write(
            &subset_svg,
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80">
                <style>
                  @font-face {
                    font-family: 'HLEOCO+MicrosoftYaHei';
                    src: url("data:font/truetype;base64,AAEAAA==");
                  }
                </style>
                <rect width="240" height="80" fill="white"/>
                <text x="16" y="48" font-size="24" style="font-family:'HLEOCO+MicrosoftYaHei';">宣城市联考</text>
            </svg>"#,
        )
        .unwrap();
        assert!(svg_needs_font_fallback(&subset_svg));

        let subset_png = dir.path().join("subset.png");
        convert_svg_to_png(&subset_svg, &subset_png, &settings).unwrap();
        assert!(file_non_empty(&subset_png));

        // 2. Real STZY Aspose SVG fixture (if present in workspace)
        let repo_svg = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../output/format-validation/server-font-test/site-page1.svg");
        if repo_svg.exists() {
            let site_png = dir.path().join("site1.png");
            convert_svg_to_png(&repo_svg, &site_png, &settings).unwrap();
            assert!(file_non_empty(&site_png));

            let site_pdf = dir.path().join("site1.pdf");
            convert_originals_to_pdf(&[repo_svg], &site_pdf, &settings).unwrap();
            let insp = inspect_pdf(&site_pdf, false).unwrap();
            assert_eq!(insp.page_count, 1);

            let png_dir = dir.path().join("pdf_pages");
            let count = convert_pdf_to_pngs(&site_pdf, &png_dir, &settings).unwrap();
            assert_eq!(count, 1);
            assert!(file_non_empty(&png_dir.join("练习1.png")));
        }
    }

    #[test]
    fn unified_pipeline_renders_zip_and_docx_fixtures() {
        let dir = tempdir().unwrap();
        let mut settings = AppSettings::default();
        settings.data_dir = dir.path().join("data");
        settings.output_dir = dir.path().join("out");

        // 1. Real ZIP sample (3 PDFs -> 13 continuous print PNGs + print PDF with TOC bookmarks, paper first!)
        let repo_zip = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../output/format-validation/originals/zip-sample-773614591691493376.zip");
        if repo_zip.exists() {
            assert_eq!(source_kind(&repo_zip).unwrap(), ".zip");
            let zip_pages_dir = dir.path().join("zip_pages");
            let merged_pdf = dir.path().join("merged.pdf");
            let (count, report) = render_source_to_pages_and_pdf(
                &repo_zip,
                &zip_pages_dir,
                &merged_pdf,
                60.0,
                &[],
                &settings,
            )
            .unwrap();
            assert_eq!(count, 13);
            assert_eq!(report["pages"].as_u64().unwrap(), 13);
            assert_eq!(report["layout"].as_str().unwrap(), "rendered_print_pages");
            let files = report["files"].as_array().unwrap();
            assert_eq!(files.len(), 3);
            assert_eq!(files[0]["name"].as_str().unwrap(), "26-27道法期中试卷.pdf");
            assert_eq!(files[1]["name"].as_str().unwrap(), "26-27道法期中答题卡.pdf");
            assert_eq!(files[2]["name"].as_str().unwrap(), "26-27道法期中答案.pdf");
            assert!(file_non_empty(&zip_pages_dir.join("练习1.png")));
            assert!(file_non_empty(&zip_pages_dir.join("练习13.png")));

            let lo = lopdf::Document::load(&merged_pdf).unwrap();
            let catalog = lo.catalog().unwrap();
            assert!(catalog.has(b"Outlines"));
        }

        // 2. Real DOCX fixture -> single-pass print pages + print PDF (when local Office engine exists)
        let repo_docx = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../output/format-validation/originals/word-sample-773569953530155008.docx");
        if repo_docx.exists() {
            assert_eq!(source_kind(&repo_docx).unwrap(), ".docx");
            if detect_office_engine(&settings).is_some() {
                let word_pages_dir = dir.path().join("word_pages");
                let word_pdf = dir.path().join("word.pdf");
                let (count, _) = render_source_to_pages_and_pdf(
                    &repo_docx,
                    &word_pages_dir,
                    &word_pdf,
                    60.0,
                    &[],
                    &settings,
                )
                .unwrap();
                assert_eq!(count, 11);
                assert!(file_non_empty(&word_pages_dir.join("练习1.png")));
                assert!(file_non_empty(&word_pages_dir.join("练习11.png")));
                assert!(file_non_empty(&word_pdf));
            }
        }
    }
}
