use std::fs;
use std::path::Path;
use std::sync::Arc;

use image::{ImageBuffer, Rgb};
use regex::Regex;

use crate::converter::fonts::build_font_database;
use crate::error::{AppError, AppResult};
use crate::models::{ensure_directory, AppSettings};

pub const SVG_FONT_FALLBACKS: &[&str] = &[
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Hiragino Sans GB",
    "Songti SC",
    "STSong",
    "Heiti SC",
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "WenQuanYi Micro Hei",
    "Arial",
    "Helvetica Neue",
];

const KNOWN_SUBSET_PDF_FONTS: &[&str] = &[
    "MicrosoftYaHei",
    "SimHei",
    "SimSun",
    "SymbolMT",
    "Arial-BoldMT",
];

/// Checks whether an SVG embeds broken/subset PDF `@font-face` data URIs.
pub fn svg_needs_font_fallback(svg_path: &Path) -> bool {
    let Ok(content) = fs::read_to_string(svg_path) else {
        return false;
    };
    svg_content_needs_font_fallback(&content)
}

pub fn svg_content_needs_font_fallback(content: &str) -> bool {
    content.contains("<text")
        && content.contains("@font-face")
        && content.contains("data:font/")
        && KNOWN_SUBSET_PDF_FONTS
            .iter()
            .any(|name| content.contains(name))
}

/// Detects the best installed CJK font family from `fontdb`.
pub fn detect_svg_cjk_font_family(settings: &AppSettings) -> String {
    let db = build_font_database(settings);
    for candidate in SVG_FONT_FALLBACKS {
        let found = db.faces().any(|face| {
            face.families
                .iter()
                .any(|(fam, _)| fam.eq_ignore_ascii_case(candidate))
        });
        if found {
            return (*candidate).to_string();
        }
    }
    String::new()
}

/// Prepares SVG markup so `usvg` resolves both subset `@font-face` fonts and Windows-only CJK font
/// names (`SimSun`, `SimHei`, `KaiTi`, `Microsoft YaHei`) cleanly on macOS, Windows, and Linux.
pub fn normalize_svg_for_usvg(raw_svg: &str, preferred_cjk_font: &str) -> String {
    let fallback_stack = if preferred_cjk_font.is_empty() {
        "PingFang SC, Songti SC, Microsoft YaHei, SimSun, Noto Sans CJK SC, sans-serif".to_string()
    } else {
        format!(
            "{preferred_cjk_font}, Songti SC, PingFang SC, Microsoft YaHei, SimSun, Noto Sans CJK SC, sans-serif"
        )
    };

    let mut out = raw_svg.to_string();

    if svg_content_needs_font_fallback(&out) {
        // Strip embedded broken subset @font-face rules and rewrite inline subset font-family attributes
        if let Ok(re_face) = Regex::new(r"(?is)@font-face\s*\{[^}]*data:font/[^}]*\}") {
            out = re_face.replace_all(&out, "").into_owned();
        }
        if let Ok(re_style_ff) = Regex::new(r#"font-family\s*:\s*[^;"\}]+"#) {
            out = re_style_ff
                .replace_all(&out, &format!("font-family: {fallback_stack}"))
                .into_owned();
        }
        if let Ok(re_attr_ff) = Regex::new(r#"font-family="[^"]*""#) {
            out = re_attr_ff
                .replace_all(&out, &format!(r#"font-family="{fallback_stack}""#))
                .into_owned();
        }
        return out;
    }

    // Standard Aspose/Office SVGs declare Windows-specific single families like `font-family="SimSun"`.
    // Expand common CJK/Latin font-family attributes with cross-platform fallbacks while keeping the
    // original font first when installed.
    let replacements: &[(&str, &str)] = &[
        (
            r#"font-family="SimSun""#,
            r#"font-family="SimSun, 宋体, Songti SC, STSong, Noto Serif CJK SC, PingFang SC, serif""#,
        ),
        (
            r#"font-family="宋体""#,
            r#"font-family="宋体, SimSun, Songti SC, STSong, Noto Serif CJK SC, PingFang SC, serif""#,
        ),
        (
            r#"font-family="SimHei""#,
            r#"font-family="SimHei, 黑体, Heiti SC, STHeiti, PingFang SC, Noto Sans CJK SC, sans-serif""#,
        ),
        (
            r#"font-family="KaiTi""#,
            r#"font-family="KaiTi, 楷体, Kaiti SC, STKaiti, Songti SC, Noto Serif CJK SC, serif""#,
        ),
        (
            r#"font-family="FangSong""#,
            r#"font-family="FangSong, 仿宋, STFangsong, Songti SC, Noto Serif CJK SC, serif""#,
        ),
        (
            r#"font-family="Microsoft YaHei""#,
            r#"font-family="Microsoft YaHei, 微软雅黑, PingFang SC, Noto Sans CJK SC, sans-serif""#,
        ),
        (
            r#"font-family="MicrosoftYaHei""#,
            r#"font-family="Microsoft YaHei, 微软雅黑, PingFang SC, Noto Sans CJK SC, sans-serif""#,
        ),
        (
            r#"font-family="Times New Roman""#,
            r#"font-family="Times New Roman, Tinos, Times, Georgia, Songti SC, serif""#,
        ),
        (
            r#"font-family="Calibri""#,
            r#"font-family="Calibri, Carlito, Helvetica Neue, Arial, PingFang SC, sans-serif""#,
        ),
        (
            r#"font-family="Cambria""#,
            r#"font-family="Cambria, Caladea, Times New Roman, Tinos, Songti SC, serif""#,
        ),
    ];

    for (from, to) in replacements {
        if out.contains(from) {
            out = out.replace(from, to);
        }
    }
    out
}

/// Renders an SVG file to a 180-DPI white-flattened RGB PNG file using `resvg`.
pub fn convert_svg_to_png(svg_path: &Path, png_path: &Path, settings: &AppSettings) -> AppResult<()> {
    let raw = fs::read_to_string(svg_path)
        .map_err(|e| AppError::Message(format!("读取 SVG 失败（{}）：{e}", svg_path.display())))?;
    let preferred_cjk = detect_svg_cjk_font_family(settings);
    let normalized = normalize_svg_for_usvg(&raw, &preferred_cjk);

    let db = build_font_database(settings);
    let mut opt = resvg::usvg::Options {
        fontdb: Arc::new(db),
        ..resvg::usvg::Options::default()
    };
    if !preferred_cjk.is_empty() {
        opt.font_family = preferred_cjk;
    }

    let tree = resvg::usvg::Tree::from_str(&normalized, &opt)
        .map_err(|e| AppError::Message(format!("解析 SVG 失败（{}）：{e}", svg_path.display())))?;

    // SVG user units are 96 DPI in CSS/usvg; scale to 180 DPI (180 / 96 = 1.875)
    let scale = 180.0_f32 / 96.0_f32;
    let size = tree.size();
    let width = ((size.width() * scale).ceil() as u32).max(1);
    let height = ((size.height() * scale).ceil() as u32).max(1);

    if (width as u64) * (height as u64) > (settings.preview_max_pixels.max(1_000_000) as u64) {
        return Err(AppError::Message(format!(
            "SVG 尺寸过大（{width}x{height}），超过安全上限"
        )));
    }

    let mut pixmap = resvg::tiny_skia::Pixmap::new(width, height)
        .ok_or_else(|| AppError::Message("无法分配 SVG 渲染画布".to_string()))?;
    pixmap.fill(resvg::tiny_skia::Color::WHITE);

    let transform = resvg::tiny_skia::Transform::from_scale(scale, scale);
    resvg::render(&tree, transform, &mut pixmap.as_mut());

    // Convert premultiplied RGBA8888 ( already over white ) into opaque RGB8 PNG
    let data = pixmap.data();
    let mut rgb = ImageBuffer::<Rgb<u8>, Vec<u8>>::new(width, height);
    for (i, pixel) in rgb.pixels_mut().enumerate() {
        let base = i * 4;
        *pixel = Rgb([data[base], data[base + 1], data[base + 2]]);
    }

    if let Some(parent) = png_path.parent() {
        ensure_directory(parent)?;
    }
    let tmp_path = png_path.with_extension("png.tmp");
    rgb.save_with_format(&tmp_path, image::ImageFormat::Png)
        .map_err(|e| AppError::Message(format!("写入 PNG 失败：{e}")))?;
    fs::rename(&tmp_path, png_path)?;
    Ok(())
}

/// Converts an SVG file to single-page vector PDF bytes via `svg2pdf`.
pub fn convert_svg_to_pdf_bytes(svg_path: &Path, settings: &AppSettings) -> AppResult<Vec<u8>> {
    let raw = fs::read_to_string(svg_path)
        .map_err(|e| AppError::Message(format!("读取 SVG 失败（{}）：{e}", svg_path.display())))?;
    let preferred_cjk = detect_svg_cjk_font_family(settings);
    let normalized = normalize_svg_for_usvg(&raw, &preferred_cjk);

    let mut db = svg2pdf::usvg::fontdb::Database::new();
    db.load_system_fonts();
    if let Ok(dirs) = crate::converter::fonts::font_directories(settings) {
        for dir in dirs {
            if dir.is_dir() {
                db.load_fonts_dir(&dir);
            }
        }
    }

    let mut opt = svg2pdf::usvg::Options {
        fontdb: Arc::new(db),
        ..svg2pdf::usvg::Options::default()
    };
    if !preferred_cjk.is_empty() {
        opt.font_family = preferred_cjk;
    }

    let tree = svg2pdf::usvg::Tree::from_str(&normalized, &opt)
        .map_err(|e| AppError::Message(format!("解析 SVG 转 PDF 失败：{e}")))?;

    svg2pdf::to_pdf(
        &tree,
        svg2pdf::ConversionOptions::default(),
        svg2pdf::PageOptions::default(),
    )
    .map_err(|e| AppError::Message(format!("SVG 转矢量 PDF 失败：{e}")))
}

/// Converts a raster image (`.png`, `.jpg`, `.jpeg`, `.webp`) into a white-flattened RGB PNG.
pub fn convert_image_to_png(image_path: &Path, png_path: &Path) -> AppResult<()> {
    let dyn_img = image::open(image_path)
        .map_err(|e| AppError::Message(format!("解码图片失败（{}）：{e}", image_path.display())))?;
    save_dynamic_image_on_white(&dyn_img, png_path)
}

pub fn save_dynamic_image_on_white(dyn_img: &image::DynamicImage, png_path: &Path) -> AppResult<()> {
    let rgba = dyn_img.to_rgba8();
    let (w, h) = rgba.dimensions();
    let mut rgb = ImageBuffer::<Rgb<u8>, Vec<u8>>::new(w, h);
    for (x, y, px) in rgba.enumerate_pixels() {
        let [r, g, b, a] = px.0;
        if a == 255 {
            rgb.put_pixel(x, y, Rgb([r, g, b]));
        } else if a == 0 {
            rgb.put_pixel(x, y, Rgb([255, 255, 255]));
        } else {
            let alpha = a as u16;
            let inv = 255 - alpha;
            let nr = ((r as u16 * alpha + 255 * inv + 127) / 255) as u8;
            let ng = ((g as u16 * alpha + 255 * inv + 127) / 255) as u8;
            let nb = ((b as u16 * alpha + 255 * inv + 127) / 255) as u8;
            rgb.put_pixel(x, y, Rgb([nr, ng, nb]));
        }
    }
    if let Some(parent) = png_path.parent() {
        ensure_directory(parent)?;
    }
    let tmp_path = png_path.with_extension("png.tmp");
    rgb.save_with_format(&tmp_path, image::ImageFormat::Png)
        .map_err(|e| AppError::Message(format!("写入 PNG 失败：{e}")))?;
    fs::rename(&tmp_path, png_path)?;
    Ok(())
}
