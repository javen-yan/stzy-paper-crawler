use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use image::{ImageBuffer, Rgb};
use lopdf::{dictionary, Document as LoPdfDocument, Object, ObjectId, Stream, StringFormat};
use parking_lot::Mutex;
use pdfium_render::prelude::*;

use crate::converter::svg::{convert_svg_to_pdf_bytes, save_dynamic_image_on_white};
use crate::error::{AppError, AppResult};
use crate::models::{ensure_directory, AppSettings, ResourceArtifacts};

static PDFIUM_RESOURCE_DIR: OnceLock<PathBuf> = OnceLock::new();

struct SafePdfiumHolder(Pdfium);
// SAFETY: Every access to `SafePdfiumHolder` goes through `PDFIUM_INSTANCE`'s `parking_lot::Mutex`,
// guaranteeing serialized single-threaded access to the underlying PDFium library bindings.
unsafe impl Send for SafePdfiumHolder {}

static SAFE_PDFIUM: OnceLock<Result<Mutex<SafePdfiumHolder>, String>> = OnceLock::new();

/// Optionally registers the Tauri app's resolved resource directory at startup so bundled
/// `libpdfium.dylib` / `pdfium.dll` / `libpdfium.so` is found first in packaged builds.
pub fn register_pdfium_resource_dir(dir: PathBuf) {
    let _ = PDFIUM_RESOURCE_DIR.set(dir);
}

fn candidate_pdfium_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(explicit) = std::env::var("STZY_PDFIUM_PATH") {
        let p = PathBuf::from(explicit.trim());
        if p.is_file() {
            if let Some(parent) = p.parent() {
                dirs.push(parent.to_path_buf());
            }
        } else if p.is_dir() {
            dirs.push(p);
        }
    }
    if let Some(reg) = PDFIUM_RESOURCE_DIR.get() {
        dirs.push(reg.clone());
        dirs.push(reg.join("resources"));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            dirs.push(exe_dir.to_path_buf());
            dirs.push(exe_dir.join("resources"));
            if let Some(macos_contents) = exe_dir.parent() {
                dirs.push(macos_contents.join("Resources"));
                dirs.push(macos_contents.join("Resources").join("resources"));
            }
        }
    }
    let manifest_res = Path::new(env!("CARGO_MANIFEST_DIR")).join("resources");
    dirs.push(manifest_res);
    dirs
}

fn platform_pdfium_filename() -> &'static str {
    #[cfg(target_os = "macos")]
    {
        "libpdfium.dylib"
    }
    #[cfg(target_os = "windows")]
    {
        "pdfium.dll"
    }
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    {
        "libpdfium.so"
    }
}

fn bind_pdfium_once() -> Result<Mutex<SafePdfiumHolder>, String> {
    if let Ok(explicit) = std::env::var("STZY_PDFIUM_PATH") {
        let p = PathBuf::from(explicit.trim());
        if p.is_file() {
            if let Ok(bindings) = Pdfium::bind_to_library(&p) {
                return Ok(Mutex::new(SafePdfiumHolder(Pdfium::new(bindings))));
            }
        }
    }
    let mut candidate_errors = Vec::new();
    for dir in candidate_pdfium_dirs() {
        let lib_path = dir.join(platform_pdfium_filename());
        if lib_path.exists() {
            match Pdfium::bind_to_library(&lib_path) {
                Ok(bindings) => return Ok(Mutex::new(SafePdfiumHolder(Pdfium::new(bindings)))),
                Err(err) => {
                    candidate_errors.push(format!("{}: {err}", lib_path.display()));
                }
            }
        }
    }
    match Pdfium::bind_to_system_library() {
        Ok(bindings) => Ok(Mutex::new(SafePdfiumHolder(Pdfium::new(bindings)))),
        Err(err) => Err(format!(
            "未能加载 Pdfium 动态库（候选错误：{}；系统库：{err}）",
            candidate_errors.join(" | ")
        )),
    }
}

fn with_pdfium<T, F>(f: F) -> AppResult<T>
where
    F: FnOnce(&Pdfium) -> AppResult<T>,
{
    let res = SAFE_PDFIUM.get_or_init(bind_pdfium_once);
    match res {
        Ok(mutex) => {
            let guard = mutex.lock();
            f(&guard.0)
        }
        Err(msg) => Err(AppError::Message(msg.clone())),
    }
}

pub fn pdf_file_looks_valid(path: &Path) -> bool {
    let Ok(meta) = fs::metadata(path) else {
        return false;
    };
    if !meta.is_file() || meta.len() < 5 {
        return false;
    }
    let Ok(bytes) = fs::read(path) else {
        return false;
    };
    bytes.starts_with(b"%PDF")
}

#[derive(Debug, Clone)]
pub struct PdfInspection {
    pub page_count: usize,
    pub extracted_text: String,
}

/// Opens a PDF via Pdfium, ensures it is unencrypted and non-empty, and returns page count + text.
pub fn inspect_pdf(pdf_path: &Path, extract_text: bool) -> AppResult<PdfInspection> {
    with_pdfium(|pdfium| {
        let doc = pdfium
            .load_pdf_from_file(pdf_path, None)
            .map_err(|e| AppError::Message(format!("打开 PDF 失败（可能已加密或损坏）：{e}")))?;
        let count = doc.pages().len() as usize;
        if count == 0 {
            return Err(AppError::Message("PDF 页数为 0".to_string()));
        }
        let mut full_text = String::new();
        if extract_text {
            for page in doc.pages().iter() {
                if let Ok(page_text) = page.text() {
                    full_text.push_str(&page_text.all());
                }
            }
        }
        Ok(PdfInspection {
            page_count: count,
            extracted_text: full_text,
        })
    })
}

/// Renders all pages of `pdf_path` into `练习1.png .. 练习N.png` inside `directory` at 180 DPI.
pub fn convert_pdf_to_pngs(
    pdf_path: &Path,
    directory: &Path,
    settings: &AppSettings,
) -> AppResult<usize> {
    if !pdf_file_looks_valid(pdf_path) {
        return Ok(0);
    }
    ensure_directory(directory)?;
    let artifacts = ResourceArtifacts::new(directory.to_path_buf());
    let max_pages = settings.preview_max_pages.max(1);
    let max_pixels = settings.preview_max_pixels.max(1_000_000);

    // Render pages to DynamicImages while holding the Pdfium lock, then encode PNGs outside or inline.
    let rendered_images: Vec<(usize, image::DynamicImage)> = with_pdfium(|pdfium| {
        let doc = pdfium
            .load_pdf_from_file(pdf_path, None)
            .map_err(|e| AppError::Message(format!("读取 PDF 失败：{e}")))?;
        let total = doc.pages().len() as usize;
        if total > max_pages {
            return Err(AppError::Message(format!(
                "PDF 页数（{total}）超过安全上限（{max_pages}）"
            )));
        }
        let mut out = Vec::with_capacity(total);
        for (idx, page) in doc.pages().iter().enumerate() {
            let pt_w = page.width().value.max(1.0);
            let pt_h = page.height().value.max(1.0);
            let px_w = ((pt_w * 180.0 / 72.0).round() as i32).max(1);
            let px_h = ((pt_h * 180.0 / 72.0).round() as i32).max(1);
            if (px_w as u64) * (px_h as u64) > (max_pixels as u64) {
                return Err(AppError::Message(format!(
                    "第 {} 页渲染像素（{px_w}x{px_h}）超过安全上限",
                    idx + 1
                )));
            }
            let config = PdfRenderConfig::new()
                .set_target_width(px_w)
                .set_maximum_height(px_h + 4)
                .render_form_data(true)
                .render_annotations(true);
            let bitmap = page
                .render_with_config(&config)
                .map_err(|e| AppError::Message(format!("渲染第 {} 页失败：{e}", idx + 1)))?;
            out.push((idx + 1, bitmap.as_image()));
        }
        Ok(out)
    })?;

    let count = rendered_images.len();
    for (page_no, dyn_img) in &rendered_images {
        let target = artifacts.page_png(*page_no);
        save_dynamic_image_on_white(dyn_img, &target)?;
    }
    Ok(count)
}

/// Builds a single-page PDF byte buffer from a raster image (`.png`, `.jpg`, `.jpeg`, `.webp`).
pub fn image_to_single_pdf_bytes(image_path: &Path) -> AppResult<Vec<u8>> {
    let dyn_img = image::open(image_path)
        .map_err(|e| AppError::Message(format!("读取图片失败（{}）：{e}", image_path.display())))?;
    let rgba = dyn_img.to_rgba8();
    let (width, height) = rgba.dimensions();
    if width == 0 || height == 0 {
        return Err(AppError::Message("图片尺寸无效".to_string()));
    }

    let mut rgb_raw = Vec::with_capacity((width as usize) * (height as usize) * 3);
    for px in rgba.pixels() {
        let [r, g, b, a] = px.0;
        if a == 255 {
            rgb_raw.extend_from_slice(&[r, g, b]);
        } else if a == 0 {
            rgb_raw.extend_from_slice(&[255, 255, 255]);
        } else {
            let alpha = a as u16;
            let inv = 255 - alpha;
            rgb_raw.push(((r as u16 * alpha + 255 * inv + 127) / 255) as u8);
            rgb_raw.push(((g as u16 * alpha + 255 * inv + 127) / 255) as u8);
            rgb_raw.push(((b as u16 * alpha + 255 * inv + 127) / 255) as u8);
        }
    }

    let mut doc = LoPdfDocument::with_version("1.5");
    let pages_id = doc.new_object_id();

    let mut img_stream = Stream::new(
        dictionary! {
            "Type" => "XObject",
            "Subtype" => "Image",
            "Width" => width as i64,
            "Height" => height as i64,
            "ColorSpace" => "DeviceRGB",
            "BitsPerComponent" => 8_i64,
        },
        rgb_raw,
    );
    let _ = img_stream.compress();
    let img_id = doc.add_object(img_stream);

    let content_ops = format!("q {} 0 0 {} 0 0 cm /Im0 Do Q\n", width, height).into_bytes();
    let content_id = doc.add_object(Stream::new(dictionary! {}, content_ops));

    let resources_id = doc.add_object(dictionary! {
        "XObject" => dictionary! {
            "Im0" => img_id,
        },
    });

    let page_id = doc.add_object(dictionary! {
        "Type" => "Page",
        "Parent" => pages_id,
        "MediaBox" => vec![0.into(), 0.into(), (width as i64).into(), (height as i64).into()],
        "Contents" => content_id,
        "Resources" => resources_id,
    });

    doc.objects.insert(
        pages_id,
        Object::Dictionary(dictionary! {
            "Type" => "Pages",
            "Kids" => vec![page_id.into()],
            "Count" => 1_i64,
        }),
    );

    let catalog_id = doc.add_object(dictionary! {
        "Type" => "Catalog",
        "Pages" => pages_id,
    });
    doc.trailer.set("Root", catalog_id);

    let mut out = Vec::new();
    doc.save_to(&mut out)
        .map_err(|e| AppError::Message(format!("生成单页图片 PDF 失败：{e}")))?;
    Ok(out)
}

/// Combines preview original files (`.svg` vector pages + `.png`/`.jpg`/`.webp` raster pages)
/// into a single sibling PDF file.
pub fn convert_originals_to_pdf(
    originals: &[PathBuf],
    pdf_path: &Path,
    settings: &AppSettings,
) -> AppResult<()> {
    if originals.is_empty() {
        return Ok(());
    }
    if let Some(parent) = pdf_path.parent() {
        ensure_directory(parent)?;
    }

    let mut page_pdf_blobs: Vec<Vec<u8>> = Vec::with_capacity(originals.len());
    for orig in originals {
        let ext = orig
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_lowercase();
        if ext == "svg" {
            page_pdf_blobs.push(convert_svg_to_pdf_bytes(orig, settings)?);
        } else {
            page_pdf_blobs.push(image_to_single_pdf_bytes(orig)?);
        }
    }

    let merged_bytes = with_pdfium(|pdfium| {
        let mut merged = pdfium
            .create_new_pdf()
            .map_err(|e| AppError::Message(format!("创建合并 PDF 失败：{e}")))?;
        for blob in &page_pdf_blobs {
            let part = pdfium
                .load_pdf_from_byte_slice(blob, None)
                .map_err(|e| AppError::Message(format!("加载单页 PDF 失败：{e}")))?;
            merged
                .pages_mut()
                .append(&part)
                .map_err(|e| AppError::Message(format!("拼接 PDF 页面失败：{e}")))?;
        }
        merged
            .save_to_bytes()
            .map_err(|e| AppError::Message(format!("序列化 PDF 失败：{e}")))
    })?;

    let tmp = pdf_path.with_extension("pdf.tmp");
    fs::write(&tmp, &merged_bytes)?;
    fs::rename(&tmp, pdf_path)?;
    Ok(())
}

/// Losslessly appends multiple PDF files into `target_pdf` and writes top-level Chinese/UTF-16BE
/// bookmarks (`Outlines`) corresponding to `(title, 1-based start page)`.
pub fn merge_pdf_files_with_toc(
    member_pdfs: &[(String, PathBuf)],
    target_pdf: &Path,
) -> AppResult<Vec<(String, usize, usize)>> {
    if member_pdfs.is_empty() {
        return Err(AppError::Message("没有可合并的 PDF 成员".to_string()));
    }
    if let Some(parent) = target_pdf.parent() {
        ensure_directory(parent)?;
    }

    let mut toc_entries: Vec<(String, usize, usize)> = Vec::with_capacity(member_pdfs.len());
    let merged_bytes = with_pdfium(|pdfium| {
        let mut merged = pdfium
            .create_new_pdf()
            .map_err(|e| AppError::Message(format!("创建目标 PDF 失败：{e}")))?;
        for (name, path) in member_pdfs {
            let doc = pdfium
                .load_pdf_from_file(path, None)
                .map_err(|e| AppError::Message(format!("{name} 是加密或损坏的 PDF：{e}")))?;
            let count = doc.pages().len() as usize;
            if count == 0 {
                return Err(AppError::Message(format!("{name} 是空 PDF")));
            }
            let first_page = (merged.pages().len() as usize) + 1;
            merged
                .pages_mut()
                .append(&doc)
                .map_err(|e| AppError::Message(format!("合并 {name} 失败：{e}")))?;
            toc_entries.push((name.clone(), first_page, count));
        }
        merged
            .save_to_bytes()
            .map_err(|e| AppError::Message(format!("保存合并 PDF 失败：{e}")))
    })?;

    let tmp = target_pdf.with_extension("pdf.tmp");
    fs::write(&tmp, &merged_bytes)?;

    // Attach top-level Outlines (TOC bookmarks) using lopdf
    let toc_pairs: Vec<(String, usize)> = toc_entries
        .iter()
        .map(|(title, first, _)| (title.clone(), *first))
        .collect();
    if let Err(err) = attach_pdf_outlines(&tmp, &toc_pairs) {
        tracing::warn!("Failed attaching PDF outlines (merged pages remain intact): {err}");
    }

    fs::rename(&tmp, target_pdf)?;
    Ok(toc_entries)
}

fn encode_pdf_utf16be(text: &str) -> Vec<u8> {
    let mut bytes = vec![0xFE, 0xFF];
    for unit in text.encode_utf16() {
        bytes.extend_from_slice(&unit.to_be_bytes());
    }
    bytes
}

pub fn attach_pdf_outlines(pdf_path: &Path, toc: &[(String, usize)]) -> AppResult<()> {
    if toc.is_empty() {
        return Ok(());
    }
    let mut doc = LoPdfDocument::load(pdf_path)
        .map_err(|e| AppError::Message(format!("加载 PDF 写入书签失败：{e}")))?;
    let pages_map = doc.get_pages();
    let outlines_id = doc.new_object_id();

    let mut valid_items: Vec<(String, ObjectId, ObjectId)> = Vec::new();
    for (title, page_no) in toc {
        if let Some(&page_obj_id) = pages_map.get(&(*page_no as u32)) {
            let item_id = doc.new_object_id();
            valid_items.push((title.clone(), page_obj_id, item_id));
        }
    }
    if valid_items.is_empty() {
        return Ok(());
    }

    let total = valid_items.len();
    for i in 0..total {
        let (ref title, page_obj_id, item_id) = valid_items[i];
        let mut dict = dictionary! {
            "Title" => Object::String(encode_pdf_utf16be(title), StringFormat::Hexadecimal),
            "Parent" => outlines_id,
            "Dest" => vec![Object::Reference(page_obj_id), Object::Name(b"Fit".to_vec())],
        };
        if i > 0 {
            dict.set("Prev", valid_items[i - 1].2);
        }
        if i + 1 < total {
            dict.set("Next", valid_items[i + 1].2);
        }
        doc.objects.insert(item_id, Object::Dictionary(dict));
    }

    let first_id = valid_items[0].2;
    let last_id = valid_items[total - 1].2;
    doc.objects.insert(
        outlines_id,
        Object::Dictionary(dictionary! {
            "Type" => "Outlines",
            "First" => first_id,
            "Last" => last_id,
            "Count" => total as i64,
        }),
    );

    if let Ok(catalog) = doc.catalog_mut() {
        catalog.set("Outlines", outlines_id);
    }
    doc.save(pdf_path)
        .map_err(|e| AppError::Message(format!("保存 PDF 书签失败：{e}")))?;
    Ok(())
}

/// Counts non-whitespace Unicode characters for Word text-coverage verification.
pub fn count_non_whitespace_chars(text: &str) -> HashMap<char, usize> {
    let mut counts = HashMap::new();
    for ch in text.chars() {
        if !ch.is_whitespace() {
            *counts.entry(ch).or_insert(0) += 1;
        }
    }
    counts
}

// Keep unused-import lint clean for ImageBuffer/Rgb if referenced across helpers
#[allow(dead_code)]
type _RgbBuf = ImageBuffer<Rgb<u8>, Vec<u8>>;
