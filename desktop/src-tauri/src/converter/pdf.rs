use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};

use image::{ImageBuffer, Rgb};
use lopdf::{dictionary, Document as LoPdfDocument, Object, ObjectId, Stream, StringFormat};
use parking_lot::Mutex;
use pdfium_render::prelude::*;

use crate::converter::svg::{convert_svg_to_pdf_bytes, save_dynamic_image_on_white};
use crate::error::{AppError, AppResult};
use crate::models::{ensure_directory, replace_file_atomic, AppSettings, ResourceArtifacts};

static PDFIUM_RESOURCE_DIR: OnceLock<PathBuf> = OnceLock::new();

struct SafePdfiumHolder(Pdfium);
// SAFETY: Every access to `SafePdfiumHolder` goes through `SAFE_PDFIUM`'s `parking_lot::Mutex`,
// guaranteeing serialized single-threaded access to the underlying PDFium library bindings.
unsafe impl Send for SafePdfiumHolder {}

static SAFE_PDFIUM: Mutex<Option<Arc<Mutex<SafePdfiumHolder>>>> = Mutex::new(None);

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

#[cfg(target_os = "macos")]
fn try_self_heal_macos_pdfium(source_dylib: &Path) -> Option<Box<dyn PdfiumLibraryBindings>> {
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;

    let cache_root = dirs::data_local_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("com.stzy.desktop")
        .join("runtime-libs");
    let _ = fs::create_dir_all(&cache_root);

    let healed_path = cache_root.join("libpdfium.dylib");
    let src_len = fs::metadata(source_dylib).map(|m| m.len()).unwrap_or(0);
    let need_refresh = match fs::metadata(&healed_path) {
        Ok(meta) => meta.len() != src_len || src_len == 0,
        Err(_) => true,
    };

    if !need_refresh {
        if let Ok(bindings) = Pdfium::bind_to_library(&healed_path) {
            return Some(bindings);
        }
    }

    let tmp_path = cache_root.join(format!("libpdfium.dylib.tmp.{}", std::process::id()));
    fs::copy(source_dylib, &tmp_path).ok()?;
    if let Ok(meta) = fs::metadata(&tmp_path) {
        let mut perms = meta.permissions();
        perms.set_mode(0o755);
        let _ = fs::set_permissions(&tmp_path, perms);
    }

    let _ = Command::new("/usr/bin/xattr").arg("-cr").arg(&tmp_path).output();
    let status = Command::new("/usr/bin/codesign")
        .args(["--force", "--sign", "-"])
        .arg(&tmp_path)
        .status()
        .ok()?;
    if !status.success() {
        let _ = fs::remove_file(&tmp_path);
        return None;
    }

    let _ = fs::rename(&tmp_path, &healed_path);
    Pdfium::bind_to_library(&healed_path).ok()
}

fn bind_pdfium_once() -> Result<Arc<Mutex<SafePdfiumHolder>>, String> {
    if let Ok(explicit) = std::env::var("STZY_PDFIUM_PATH") {
        let p = PathBuf::from(explicit.trim());
        if p.is_file() {
            if let Ok(bindings) = Pdfium::bind_to_library(&p) {
                return Ok(Arc::new(Mutex::new(SafePdfiumHolder(Pdfium::new(bindings)))));
            }
        }
    }
    let mut candidate_errors = Vec::new();
    for dir in candidate_pdfium_dirs() {
        let lib_path = dir.join(platform_pdfium_filename());
        if lib_path.exists() {
            match Pdfium::bind_to_library(&lib_path) {
                Ok(bindings) => {
                    return Ok(Arc::new(Mutex::new(SafePdfiumHolder(Pdfium::new(bindings)))))
                }
                Err(err) => {
                    #[cfg(target_os = "macos")]
                    if let Some(healed_bindings) = try_self_heal_macos_pdfium(&lib_path) {
                        tracing::info!(
                            "已自动修复 macOS Pdfium 动态库签名并成功加载: {}",
                            lib_path.display()
                        );
                        return Ok(Arc::new(Mutex::new(SafePdfiumHolder(Pdfium::new(
                            healed_bindings,
                        )))));
                    }
                    candidate_errors.push(format!("{}: {err}", lib_path.display()));
                }
            }
        }
    }
    match Pdfium::bind_to_system_library() {
        Ok(bindings) => Ok(Arc::new(Mutex::new(SafePdfiumHolder(Pdfium::new(bindings))))),
        Err(err) => {
            tracing::error!(
                "Pdfium 动态库加载失败: candidates=[{}], system={err}",
                candidate_errors.join(" | ")
            );
            let hint = if candidate_errors
                .iter()
                .any(|e| e.contains("no cdhash") || e.contains("code signature"))
            {
                "PDF 渲染组件签名校验未通过，请在软件内点击「检查更新」升级至最新版或重新安装"
            } else {
                "PDF 渲染组件加载失败，请确认安装包完整后重试"
            };
            Err(hint.to_string())
        }
    }
}

fn with_pdfium<T, F>(f: F) -> AppResult<T>
where
    F: FnOnce(&Pdfium) -> AppResult<T>,
{
    let holder = {
        let mut slot = SAFE_PDFIUM.lock();
        if let Some(existing) = slot.as_ref() {
            existing.clone()
        } else {
            let initialized = bind_pdfium_once().map_err(AppError::Message)?;
            *slot = Some(initialized.clone());
            initialized
        }
    };
    let guard = holder.lock();
    f(&guard.0)
}

pub fn pdf_file_looks_valid(path: &Path) -> bool {
    use std::io::Read;
    let Ok(mut file) = fs::File::open(path) else {
        return false;
    };
    let mut head = [0u8; 8];
    let Ok(n) = file.read(&mut head) else {
        return false;
    };
    n >= 5 && head[..n].starts_with(b"%PDF")
}

#[derive(Debug, Clone)]
pub struct PdfInspection {
    pub page_count: usize,
    pub extracted_text: String,
}

/// Opens a PDF via Pdfium, ensures it is unencrypted and non-empty, and returns page count + text.
pub fn inspect_pdf(pdf_path: &Path, extract_text: bool) -> AppResult<PdfInspection> {
    let pdf_bytes = fs::read(pdf_path)
        .map_err(|e| AppError::Message(format!("读取 PDF 文件失败：{e}")))?;
    with_pdfium(|pdfium| {
        let doc = pdfium
            .load_pdf_from_byte_slice(&pdf_bytes, None)
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
    append_pdf_to_pngs(pdf_path, directory, 1, settings)
}

/// Renders all pages of `pdf_path` into `练习{start_index}.png ..` inside `directory` at 180 DPI,
/// returning the number of pages rendered from this PDF.
pub fn append_pdf_to_pngs(
    pdf_path: &Path,
    directory: &Path,
    start_index: usize,
    settings: &AppSettings,
) -> AppResult<usize> {
    if !pdf_file_looks_valid(pdf_path) {
        return Ok(0);
    }
    ensure_directory(directory)?;
    let artifacts = ResourceArtifacts::new(directory.to_path_buf());
    let base_idx = start_index.max(1);
    let max_pages = settings.preview_max_pages.max(1);
    let max_pixels = settings.preview_max_pixels.max(1_000_000);

    let pdf_bytes = fs::read(pdf_path)
        .map_err(|e| AppError::Message(format!("读取 PDF 文件失败：{e}")))?;
    let total = with_pdfium(|pdfium| {
        let doc = pdfium
            .load_pdf_from_byte_slice(&pdf_bytes, None)
            .map_err(|e| AppError::Message(format!("读取 PDF 失败：{e}")))?;
        Ok(doc.pages().len() as usize)
    })?;
    if total == 0 {
        return Ok(0);
    }
    if base_idx.saturating_add(total).saturating_sub(1) > max_pages {
        return Err(AppError::Message(format!(
            "累计渲染页数超过安全上限（{max_pages}）"
        )));
    }

    // Stream rendering in small 4-page batches so 150-300 page bundles never hold gigabytes
    // of uncompressed RGBA bitmaps in RAM simultaneously, while avoiding long holds on SAFE_PDFIUM.
    const BATCH_SIZE: usize = 4;
    let mut start = 0usize;
    while start < total {
        let end = (start + BATCH_SIZE).min(total);
        let batch_images: Vec<(usize, image::DynamicImage)> = with_pdfium(|pdfium| {
            let doc = pdfium
                .load_pdf_from_byte_slice(&pdf_bytes, None)
                .map_err(|e| AppError::Message(format!("读取 PDF 失败：{e}")))?;
            let mut batch = Vec::with_capacity(end - start);
            for idx in start..end {
                let page = doc
                    .pages()
                    .get(idx as u16)
                    .map_err(|e| AppError::Message(format!("访问第 {} 页失败：{e}", idx + 1)))?;
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
                batch.push((base_idx + idx, bitmap.as_image()));
            }
            Ok(batch)
        })?;

        for (page_no, dyn_img) in batch_images {
            let target = artifacts.page_png(page_no);
            save_dynamic_image_on_white(&dyn_img, &target)?;
        }
        start = end;
    }
    Ok(total)
}

fn append_raster_page_to_doc(
    doc: &mut LoPdfDocument,
    pages_id: ObjectId,
    image_path: &Path,
) -> AppResult<ObjectId> {
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

    let mut jpeg_bytes = Vec::with_capacity((width as usize) * (height as usize) / 4);
    let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg_bytes, 92);
    encoder
        .encode(&rgb_raw, width, height, image::ExtendedColorType::Rgb8)
        .map_err(|e| AppError::Message(format!("编码打印页图像失败：{e}")))?;

    let img_stream = Stream::new(
        dictionary! {
            "Type" => "XObject",
            "Subtype" => "Image",
            "Width" => width as i64,
            "Height" => height as i64,
            "ColorSpace" => "DeviceRGB",
            "BitsPerComponent" => 8_i64,
            "Filter" => "DCTDecode",
        },
        jpeg_bytes,
    );
    let img_id = doc.add_object(img_stream);

    // Normalize page dimensions to standard A4 width (595.28pt) when high-DPI screenshots are used,
    // while keeping full raster pixel resolution inside the embedded XObject image.
    let (pt_w, pt_h) = if width > 900 {
        let target_w = 595.28_f64;
        let target_h = (target_w * (height as f64) / (width as f64)).max(1.0);
        (target_w, target_h)
    } else {
        (width as f64, height as f64)
    };

    let content_ops = format!("q {:.2} 0 0 {:.2} 0 0 cm /Im0 Do Q\n", pt_w, pt_h).into_bytes();
    let content_id = doc.add_object(Stream::new(dictionary! {}, content_ops));

    let resources_id = doc.add_object(dictionary! {
        "XObject" => dictionary! {
            "Im0" => img_id,
        },
    });

    Ok(doc.add_object(dictionary! {
        "Type" => "Page",
        "Parent" => pages_id,
        "MediaBox" => vec![0.into(), 0.into(), (pt_w as f32).into(), (pt_h as f32).into()],
        "Contents" => content_id,
        "Resources" => resources_id,
    }))
}

/// Builds a single-page PDF byte buffer from a raster image (`.png`, `.jpg`, `.jpeg`, `.webp`).
pub fn image_to_single_pdf_bytes(image_path: &Path) -> AppResult<Vec<u8>> {
    let mut doc = LoPdfDocument::with_version("1.5");
    let pages_id = doc.new_object_id();
    let page_id = append_raster_page_to_doc(&mut doc, pages_id, image_path)?;
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

/// Directly packs a sequence of raster page images into one compact, A4 print-ready PDF.
pub fn images_to_print_pdf(image_paths: &[PathBuf], pdf_path: &Path) -> AppResult<()> {
    if image_paths.is_empty() {
        return Ok(());
    }
    if let Some(parent) = pdf_path.parent() {
        ensure_directory(parent)?;
    }
    let mut doc = LoPdfDocument::with_version("1.5");
    let pages_id = doc.new_object_id();
    let mut kids: Vec<Object> = Vec::with_capacity(image_paths.len());
    for img_path in image_paths {
        let page_id = append_raster_page_to_doc(&mut doc, pages_id, img_path)?;
        kids.push(page_id.into());
    }
    let count = kids.len() as i64;
    doc.objects.insert(
        pages_id,
        Object::Dictionary(dictionary! {
            "Type" => "Pages",
            "Kids" => kids,
            "Count" => count,
        }),
    );
    let catalog_id = doc.add_object(dictionary! {
        "Type" => "Catalog",
        "Pages" => pages_id,
    });
    doc.trailer.set("Root", catalog_id);

    let tmp = pdf_path.with_file_name(format!(
        ".{}.tmp",
        pdf_path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("merged.pdf")
    ));
    if let Err(e) = doc.save(&tmp) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::Message(format!("写入打印 PDF 失败：{e}")));
    }
    if let Err(e) = replace_file_atomic(&tmp, pdf_path) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::Io(e));
    }
    Ok(())
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
    let has_svg = originals.iter().any(|p| {
        p.extension()
            .and_then(|s| s.to_str())
            .map(|s| s.eq_ignore_ascii_case("svg"))
            .unwrap_or(false)
    });
    if !has_svg {
        return images_to_print_pdf(originals, pdf_path);
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

    let tmp = pdf_path.with_file_name(format!(
        ".{}.tmp",
        pdf_path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("merged.pdf")
    ));
    if let Err(e) = fs::write(&tmp, &merged_bytes) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::Io(e));
    }
    if let Err(e) = replace_file_atomic(&tmp, pdf_path) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::Io(e));
    }
    Ok(())
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
    let tmp = pdf_path.with_file_name(format!(
        ".{}.outline.tmp",
        pdf_path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("merged.pdf")
    ));
    if let Err(e) = doc.save(&tmp) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::Message(format!("保存 PDF 书签失败：{e}")));
    }
    if let Err(e) = replace_file_atomic(&tmp, pdf_path) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::Io(e));
    }
    Ok(())
}

// Keep unused-import lint clean for ImageBuffer/Rgb if referenced across helpers
#[allow(dead_code)]
type _RgbBuf = ImageBuffer<Rgb<u8>, Vec<u8>>;
