use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use quick_xml::events::Event;
use quick_xml::Reader;
use regex::Regex;
use serde_json::{json, Value};
use url::Url;
use zip::ZipArchive;

use crate::converter::fonts::{
    default_common_substitutions, ensure_word_fonts, font_directories, normalized_policy,
    write_fontconfig_xml, FontResolutionPlan,
};
use crate::converter::pdf::{
    convert_originals_to_pdf, count_non_whitespace_chars, inspect_pdf, merge_pdf_files_with_toc,
};
use crate::error::{AppError, AppResult};
use crate::models::AppSettings;

pub const MAX_ZIP_MEMBERS: usize = 500;
pub const MAX_EXPANDED_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OfficeEngine {
    LibreOffice(PathBuf),
    MsWordCom,
    WpsCom,
}

impl OfficeEngine {
    pub fn display_label(&self) -> String {
        match self {
            OfficeEngine::LibreOffice(p) => format!("LibreOffice ({})", p.display()),
            OfficeEngine::MsWordCom => "Microsoft Word (COM)".to_string(),
            OfficeEngine::WpsCom => "WPS Office (COM)".to_string(),
        }
    }
}

/// Auto-detects the best local Office-to-PDF engine without bundling heavy runtimes.
pub fn detect_office_engine(settings: &AppSettings) -> Option<OfficeEngine> {
    let explicit = std::env::var("STZY_SOFFICE_PATH")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| settings.soffice_path.clone());
    if !explicit.trim().is_empty() {
        let p = crate::models::expand_tilde(explicit.trim());
        if p.is_file() {
            return Some(OfficeEngine::LibreOffice(p));
        }
        if let Some(found) = which_binary(explicit.trim()) {
            return Some(OfficeEngine::LibreOffice(found));
        }
    }

    #[cfg(target_os = "windows")]
    {
        if windows_progid_exists("Word.Application") {
            return Some(OfficeEngine::MsWordCom);
        }
        if windows_progid_exists("KWPS.Application") || windows_progid_exists("WPS.Application") {
            return Some(OfficeEngine::WpsCom);
        }
        let win_candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ];
        for cand in win_candidates {
            let p = PathBuf::from(cand);
            if p.is_file() {
                return Some(OfficeEngine::LibreOffice(p));
            }
        }
    }

    for bin in ["soffice", "libreoffice"] {
        if let Some(found) = which_binary(bin) {
            return Some(OfficeEngine::LibreOffice(found));
        }
    }

    #[cfg(target_os = "macos")]
    {
        let mac_app = PathBuf::from("/Applications/LibreOffice.app/Contents/MacOS/soffice");
        if mac_app.is_file() {
            return Some(OfficeEngine::LibreOffice(mac_app));
        }
    }

    None
}

fn which_binary(name: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        let full = dir.join(name);
        if full.is_file() {
            return Some(full);
        }
        #[cfg(target_os = "windows")]
        {
            let exe = dir.join(format!("{name}.exe"));
            if exe.is_file() {
                return Some(exe);
            }
        }
    }
    None
}

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg(target_os = "windows")]
fn windows_progid_exists(prog_id: &str) -> bool {
    use std::os::windows::process::CommandExt;
    Command::new("reg")
        .creation_flags(CREATE_NO_WINDOW)
        .args(["query", &format!(r"HKCR\{prog_id}")])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Detects the true source document type from magic bytes and ZIP structure.
pub fn source_kind(path: &Path) -> AppResult<&'static str> {
    let mut file = File::open(path)
        .map_err(|e| AppError::Message(format!("读取源文件失败（{}）：{e}", path.display())))?;
    let mut head = [0u8; 4096];
    let n = file.read(&mut head)?;
    let slice = &head[..n];

    if slice.starts_with(b"%PDF") {
        return Ok(".pdf");
    }
    if slice.starts_with(&[0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]) {
        return Ok(".doc");
    }
    if slice.starts_with(b"Rar!\x1a\x07") {
        return Ok(".rar");
    }
    if slice.starts_with(&[b'7', b'z', 0xBC, 0xAF, 0x27, 0x1C]) {
        return Ok(".7z");
    }

    // Check if valid ZIP / DOCX
    if slice.starts_with(b"PK\x03\x04") || slice.starts_with(b"PK\x05\x06") {
        let zf = File::open(path)?;
        if let Ok(archive) = ZipArchive::new(zf) {
            let names: HashSet<&str> = archive.file_names().collect();
            if names.contains("[Content_Types].xml") && names.contains("word/document.xml") {
                return Ok(".docx");
            }
            return Ok(".zip");
        }
    }

    let lowered = String::from_utf8_lossy(slice).to_lowercase();
    if lowered.contains("<html") || lowered.contains("<!doctype html") {
        return Err(AppError::Message(
            "下载结果是网页而非试卷原文，可能是链接已失效".to_string(),
        ));
    }
    if slice.starts_with(b"{\\rtf")
        || lowered.contains("progid=\"word.document\"")
        || lowered.contains("<w:worddocument")
    {
        return Ok(".doc");
    }
    if slice.starts_with(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]) {
        return Ok(".png");
    }
    if slice.starts_with(&[0xFF, 0xD8, 0xFF]) {
        return Ok(".jpg");
    }
    if slice.len() >= 12 && &slice[..4] == b"RIFF" && &slice[8..12] == b"WEBP" {
        return Ok(".webp");
    }
    if lowered.contains("<svg") {
        return Ok(".svg");
    }

    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();
    match ext.as_str() {
        "png" => Ok(".png"),
        "jpg" => Ok(".jpg"),
        "jpeg" => Ok(".jpeg"),
        "webp" => Ok(".webp"),
        "svg" => Ok(".svg"),
        _ => Err(AppError::Message(
            "无法识别该文件格式（目前支持 PDF、Word、ZIP 和图片）".to_string(),
        )),
    }
}

/// Pure Rust `.docx` XML inspector: extracts all declared `w:rFonts` + `theme1.xml` typefaces
/// and concatenates body text (`w:t`) for post-conversion character coverage verification.
pub fn docx_content(path: &Path) -> AppResult<(BTreeSet<String>, String)> {
    let file = File::open(path)?;
    let mut archive = ZipArchive::new(file)
        .map_err(|e| AppError::Message(format!("打开 DOCX 压缩结构失败：{e}")))?;

    let mut total_uncompressed: u64 = 0;
    for i in 0..archive.len() {
        let entry = archive
            .by_index_raw(i)
            .map_err(|e| AppError::Message(format!("读取 DOCX 目录项失败：{e}")))?;
        total_uncompressed = total_uncompressed.saturating_add(entry.size());
    }
    if total_uncompressed > MAX_EXPANDED_BYTES {
        return Err(AppError::Message(
            "Word 解压体积超过 512 MiB，原件已保留".to_string(),
        ));
    }

    let mut fonts = BTreeSet::new();
    let mut body_text = String::new();

    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| AppError::Message(format!("读取 DOCX XML 失败：{e}")))?;
        let name = entry.name().to_string();
        if name == "word/theme/theme1.xml" {
            let mut xml = String::new();
            let _ = entry.read_to_string(&mut xml);
            extract_theme_fonts(&xml, &mut fonts);
            continue;
        }
        if !name.starts_with("word/") || !name.ends_with(".xml") {
            continue;
        }
        let mut xml = String::new();
        let _ = entry.read_to_string(&mut xml);
        let is_document = name == "word/document.xml";
        extract_word_xml_fonts_and_text(&xml, is_document, &mut fonts, &mut body_text);
    }

    Ok((fonts, body_text))
}

fn local_tag_name(raw: &[u8]) -> &[u8] {
    match raw.iter().rposition(|&b| b == b':') {
        Some(pos) => &raw[pos + 1..],
        None => raw,
    }
}

fn extract_word_xml_fonts_and_text(
    xml: &str,
    collect_text: bool,
    fonts: &mut BTreeSet<String>,
    body_text: &mut String,
) {
    let mut reader = Reader::from_str(xml);
    let mut in_wt = false;

    loop {
        match reader.read_event() {
            Ok(Event::Start(ref e)) => {
                let qname = e.name();
                let local = local_tag_name(qname.as_ref());
                if local == b"rFonts" {
                    collect_rfonts_attrs(e, fonts);
                } else if collect_text && local == b"t" {
                    in_wt = true;
                }
            }
            Ok(Event::Empty(ref e)) => {
                let qname = e.name();
                let local = local_tag_name(qname.as_ref());
                if local == b"rFonts" {
                    collect_rfonts_attrs(e, fonts);
                }
            }
            Ok(Event::Text(ref t)) if in_wt => {
                if let Ok(decoded) = t.unescape() {
                    body_text.push_str(&decoded);
                }
            }
            Ok(Event::End(ref e)) => {
                if collect_text && local_tag_name(e.name().as_ref()) == b"t" {
                    in_wt = false;
                }
            }
            Ok(Event::Eof) | Err(_) => break,
            _ => {}
        }
    }
}

fn collect_rfonts_attrs(e: &quick_xml::events::BytesStart<'_>, fonts: &mut BTreeSet<String>) {
    for attr in e.attributes().flatten() {
        let key = local_tag_name(attr.key.as_ref());
        if matches!(key, b"ascii" | b"hAnsi" | b"eastAsia" | b"cs") {
            if let Ok(val) = attr.unescape_value() {
                let trimmed = val.trim();
                if !trimmed.is_empty() {
                    fonts.insert(trimmed.to_string());
                }
            }
        }
    }
}

fn extract_theme_fonts(xml: &str, fonts: &mut BTreeSet<String>) {
    let mut reader = Reader::from_str(xml);
    loop {
        match reader.read_event() {
            Ok(Event::Start(ref e)) | Ok(Event::Empty(ref e)) => {
                let qname = e.name();
                let local = local_tag_name(qname.as_ref());
                let mut is_target = matches!(local, b"latin" | b"ea" | b"cs");
                let mut typeface = String::new();
                for attr in e.attributes().flatten() {
                    let k = local_tag_name(attr.key.as_ref());
                    if k == b"script" {
                        if let Ok(v) = attr.unescape_value() {
                            if v.trim() == "Hans" {
                                is_target = true;
                            }
                        }
                    } else if k == b"typeface" {
                        if let Ok(v) = attr.unescape_value() {
                            typeface = v.trim().to_string();
                        }
                    }
                }
                if is_target && !typeface.is_empty() {
                    fonts.insert(typeface);
                }
            }
            Ok(Event::Eof) | Err(_) => break,
            _ => {}
        }
    }
}

pub fn page_check(expected: usize, actual: usize, tolerant: bool, label: &str) -> AppResult<Value> {
    if expected == 0 || actual == expected {
        return Ok(json!({
            "expected": expected,
            "actual": actual,
            "tolerated": false,
            "note": "",
        }));
    }
    let note = format!("{label}页数与站点预览不一致：{actual}/{expected}");
    if !tolerant {
        return Err(AppError::Message(format!(
            "{note}，需核对字体和排版；未发布 PDF"
        )));
    }
    Ok(json!({
        "expected": expected,
        "actual": actual,
        "tolerated": true,
        "note": format!("{note}；使用了替代字体，按实际页数发布"),
    }))
}

fn run_command_with_timeout(mut cmd: Command, timeout: Duration) -> AppResult<std::process::Output> {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());
    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::Message(format!("启动外部转换进程失败：{e}")))?;
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => {
                return child
                    .wait_with_output()
                    .map_err(|e| AppError::Message(format!("读取转换输出失败：{e}")));
            }
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(AppError::Message("Word 转换超时，原件已保留".to_string()));
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => return Err(AppError::Message(format!("等待转换进程失败：{e}"))),
        }
    }
}

fn libreoffice_convert(
    soffice: &Path,
    work_dir: &Path,
    profile_dir: &Path,
    input_path: &Path,
    format_spec: &str,
    settings: &AppSettings,
    aliases: &BTreeMap<String, String>,
    timeout: Duration,
) -> AppResult<()> {
    let dirs = font_directories(settings)?;
    let font_conf = write_fontconfig_xml(work_dir, &dirs, aliases)?;
    let profile_uri = Url::from_directory_path(profile_dir)
        .or_else(|_| Url::from_file_path(profile_dir))
        .map(|u| u.to_string())
        .unwrap_or_else(|_| format!("file://{}", profile_dir.display()));

    let mut cmd = Command::new(soffice);
    cmd.arg(format!("-env:UserInstallation={}", profile_uri.trim_end_matches('/')))
        .arg("--headless")
        .arg("--norestore")
        .arg("--convert-to")
        .arg(format_spec)
        .arg("--outdir")
        .arg(work_dir)
        .arg(input_path)
        .env("FONTCONFIG_FILE", &font_conf);

    if !dirs.is_empty() {
        let joined = std::env::join_paths(&dirs)
            .map(|os| os.to_string_lossy().to_string())
            .unwrap_or_default();
        if !joined.is_empty() {
            cmd.env("SAL_FONTPATH", joined);
        }
    }

    let output = run_command_with_timeout(cmd, timeout)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(AppError::Message(format!(
            "LibreOffice 转换失败（{}），原件已保留",
            stderr.trim()
        )));
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn windows_com_convert_to_pdf(
    prog_id: &str,
    source_path: &Path,
    pdf_path: &Path,
    to_docx_first: Option<&Path>,
    timeout: Duration,
) -> AppResult<()> {
    let src = source_path.to_string_lossy().replace('\'', "''");
    let dst = pdf_path.to_string_lossy().replace('\'', "''");
    let docx_step = if let Some(docx_out) = to_docx_first {
        let dx = docx_out.to_string_lossy().replace('\'', "''");
        format!("$doc.SaveAs([ref]'{dx}', [ref]16); ")
    } else {
        String::new()
    };

    let script = format!(
        "$ErrorActionPreference = 'Stop'; \
         $app = New-Object -ComObject '{prog_id}'; \
         try {{ \
           $app.Visible = $false; \
           $app.DisplayAlerts = 0; \
           $doc = $app.Documents.Open('{src}', $false, $true); \
           try {{ \
             {docx_step}\
             $doc.ExportAsFixedFormat('{dst}', 17); \
           }} finally {{ \
             $doc.Close($false); \
           }} \
         }} finally {{ \
           $app.Quit(); \
         }}"
    );

    let mut cmd = Command::new("powershell");
    cmd.args(["-NoProfile", "-NonInteractive", "-Command", &script]);
    let out = run_command_with_timeout(cmd, timeout)?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(AppError::Message(format!(
            "Windows Office COM 转换失败（{}），原件已保留",
            err.trim()
        )));
    }
    Ok(())
}

pub fn word_to_pdf(
    source: &Path,
    target: &Path,
    timeout_secs: f64,
    expected_pages: usize,
    settings: &AppSettings,
) -> AppResult<FontResolutionPlan> {
    let Some(engine) = detect_office_engine(settings) else {
        return Err(AppError::Message(
            "未安装 LibreOffice 转换核心，已保存原 Word 文件；安装 LibreOffice 后点击「继续任务」即可生成 PDF"
                .to_string(),
        ));
    };

    let temp_dir = tempfile::Builder::new()
        .prefix("stzy-office-")
        .tempdir()?;
    let work = temp_dir.path();
    let kind = source_kind(source)?;
    let local_source = work.join(format!("source{kind}"));
    fs::copy(source, &local_source)?;

    let deadline = Instant::now() + Duration::from_secs_f64(timeout_secs.max(5.0));
    let output_pdf = work.join("source.pdf");
    let strict_mode = normalized_policy(settings) == "strict";

    let plan: FontResolutionPlan = match engine {
        OfficeEngine::LibreOffice(ref soffice) => {
            let profile = work.join("profile");
            fs::create_dir_all(profile.join("user"))?;
            fs::write(
                profile.join("user/registrymodifications.xcu"),
                r#"<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>"#,
            )?;

            let mut inspection_docx = local_source.clone();
            let mut can_inspect_docx = kind == ".docx";
            if kind == ".doc" {
                let rem = deadline.saturating_duration_since(Instant::now());
                if libreoffice_convert(
                    soffice,
                    work,
                    &profile,
                    &local_source,
                    "docx:Office Open XML Text",
                    settings,
                    &BTreeMap::new(),
                    rem,
                )
                .is_ok()
                {
                    let candidate = work.join("source.docx");
                    if candidate.exists() {
                        inspection_docx = candidate;
                        can_inspect_docx = true;
                    }
                }
            }

            let (declared_fonts, source_text, mut resolved) = if can_inspect_docx {
                match docx_content(&inspection_docx) {
                    Ok((fonts, text)) => {
                        let plan = ensure_word_fonts(&fonts, settings)?;
                        (fonts, text, plan)
                    }
                    Err(_) => (
                        BTreeSet::new(),
                        String::new(),
                        FontResolutionPlan {
                            substituted: default_common_substitutions(settings),
                            policy: normalized_policy(settings),
                            visual_review: true,
                            ..FontResolutionPlan::default()
                        },
                    ),
                }
            } else {
                (
                    BTreeSet::new(),
                    String::new(),
                    FontResolutionPlan {
                        substituted: default_common_substitutions(settings),
                        policy: normalized_policy(settings),
                        visual_review: true,
                        ..FontResolutionPlan::default()
                    },
                )
            };

            let _ = declared_fonts;
            if strict_mode && !resolved.missing.is_empty() {
                return Err(AppError::Message(format!(
                    "缺少原文字体：{}；原件已保留",
                    resolved.missing.join("、")
                )));
            }

            let rem = deadline.saturating_duration_since(Instant::now());
            libreoffice_convert(
                soffice,
                work,
                &profile,
                &local_source,
                "pdf:writer_pdf_Export",
                settings,
                &resolved.substituted,
                rem,
            )?;

            if !output_pdf.exists() {
                return Err(AppError::Message(
                    "文档转换失败（可能受密码保护或格式损坏），原文件已保存".to_string(),
                ));
            }
            verify_word_pdf_output(
                &output_pdf,
                &source_text,
                expected_pages,
                strict_mode,
                &mut resolved,
            )?;
            resolved
        }
        OfficeEngine::MsWordCom | OfficeEngine::WpsCom => {
            #[cfg(target_os = "windows")]
            {
                let prog_id = if matches!(engine, OfficeEngine::MsWordCom) {
                    "Word.Application"
                } else if windows_progid_exists("KWPS.Application") {
                    "KWPS.Application"
                } else {
                    "WPS.Application"
                };
                let docx_temp = if kind == ".doc" {
                    Some(work.join("source_inspected.docx"))
                } else {
                    None
                };
                let rem = deadline.saturating_duration_since(Instant::now());
                windows_com_convert_to_pdf(
                    prog_id,
                    &local_source,
                    &output_pdf,
                    docx_temp.as_deref(),
                    rem,
                )?;
                let inspect_target = docx_temp.as_deref().unwrap_or(&local_source);
                let (declared_fonts, source_text) = if inspect_target.exists() {
                    docx_content(inspect_target).unwrap_or_default()
                } else {
                    (BTreeSet::new(), String::new())
                };
                let mut resolved = ensure_word_fonts(&declared_fonts, settings)?;
                if strict_mode && !resolved.missing.is_empty() {
                    return Err(AppError::Message(format!(
                        "缺少原文字体：{}；原件已保留",
                        resolved.missing.join("、")
                    )));
                }
                verify_word_pdf_output(
                    &output_pdf,
                    &source_text,
                    expected_pages,
                    strict_mode,
                    &mut resolved,
                )?;
                resolved
            }
            #[cfg(not(target_os = "windows"))]
            {
                return Err(AppError::Message("当前系统不支持 Windows COM 转换".to_string()));
            }
        }
    };

    fs::copy(&output_pdf, target)?;
    Ok(plan)
}

fn should_ignore_coverage_char(ch: char) -> bool {
    if ch.is_whitespace() || ch.is_control() {
        return true;
    }
    // Ignore Private Use Area (Word Wingdings/Symbol bullets), zero-width/variation selectors,
    // replacement chars, and decorative list markers that render as vector shapes in PDF.
    matches!(
        ch,
        '\u{00AD}'
            | '\u{200B}'..='\u{200F}'
            | '\u{2028}'..='\u{202F}'
            | '\u{2060}'..='\u{206F}'
            | '\u{FE00}'..='\u{FE0F}'
            | '\u{FEFF}'
            | '\u{E000}'..='\u{F8FF}'
            | '\u{FFF9}'..='\u{FFFD}'
            | '•'
            | '·'
            | '▪'
            | '▫'
            | '■'
            | '□'
            | '▲'
            | '△'
            | '◆'
            | '◇'
            | '○'
            | '●'
            | '★'
            | '☆'
            | '✓'
            | '✔'
            | '✗'
            | '✘'
    )
}

fn compute_text_coverage(source_text: &str, extracted_text: &str) -> (usize, usize, Vec<char>) {
    let raw_src = count_non_whitespace_chars(source_text);
    let rendered = count_non_whitespace_chars(extracted_text);

    let mut total_needed = 0usize;
    let mut total_matched = 0usize;
    let mut missing_samples = Vec::new();

    for (ch, needed) in raw_src {
        if should_ignore_coverage_char(ch) {
            continue;
        }
        total_needed = total_needed.saturating_add(needed);
        let got = rendered.get(&ch).copied().unwrap_or(0);
        total_matched = total_matched.saturating_add(got.min(needed));
        if got < needed && missing_samples.len() < 5 {
            missing_samples.push(ch);
        }
    }
    (total_matched, total_needed, missing_samples)
}

fn verify_word_pdf_output(
    output_pdf: &Path,
    source_text: &str,
    expected_pages: usize,
    strict_mode: bool,
    plan: &mut FontResolutionPlan,
) -> AppResult<()> {
    let inspection = inspect_pdf(output_pdf, true)?;
    if inspection.page_count == 0 {
        return Err(AppError::Message(
            "转换后的 PDF 没有有效页面，原文件已保存".to_string(),
        ));
    }

    // In beginner-friendly mode, always tolerate minor page-count variance vs site preview
    plan.page_check = page_check(
        expected_pages,
        inspection.page_count,
        !strict_mode || plan.visual_review,
        "",
    )?;

    if source_text.trim().is_empty() {
        return Ok(());
    }

    let (matched, needed, missing_samples) =
        compute_text_coverage(source_text, &inspection.extracted_text);
    if needed == 0 {
        return Ok(());
    }

    if strict_mode && matched < needed {
        return Err(AppError::Message(
            "Word 转换文字覆盖校验失败，可能缺字或对象未正确渲染；未发布 PDF".to_string(),
        ));
    }

    let coverage = (matched as f64) / (needed as f64);
    if needed >= 25 && coverage < 0.45 {
        let sample_str: String = missing_samples.into_iter().collect();
        return Err(AppError::Message(format!(
            "文档内大量特殊公式或嵌入对象未能转为文字（识别率 {:.0}%，缺失示例：{sample_str}），已保留原 Word 文件",
            coverage * 100.0
        )));
    }

    if needed >= 15 && coverage < 0.92 {
        plan.warnings.push(
            "含少量特殊公式或符号，已生成 PDF 并保留原 Word 文件供核对".to_string(),
        );
    }

    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
enum NaturalPart {
    Num(u64),
    Text(String),
}

fn natural_key(name: &str) -> Vec<NaturalPart> {
    let Ok(re) = Regex::new(r"(\d+|\D+)") else {
        return vec![NaturalPart::Text(name.to_lowercase())];
    };
    re.find_iter(name)
        .map(|m| {
            let s = m.as_str();
            if let Ok(n) = s.parse::<u64>() {
                NaturalPart::Num(n)
            } else {
                NaturalPart::Text(s.to_lowercase())
            }
        })
        .collect()
}

#[derive(Debug, Default)]
pub struct UnpackedZipBundle {
    pub documents: Vec<(String, PathBuf)>,
    pub companion_audios: Vec<(String, PathBuf)>,
    pub skipped_files: Vec<String>,
}

/// Safely validates and unpacks a `.zip` bundle in site `fileList` order (falling back to natural sort),
/// preserving companion listening audio files (`.mp3`, `.wav`, etc.) and skipping harmless readme files.
pub fn unpack_zip_bundle(
    source: &Path,
    directory: &Path,
    file_order: &[String],
) -> AppResult<UnpackedZipBundle> {
    let zf = File::open(source)?;
    let mut archive = ZipArchive::new(zf)
        .map_err(|e| AppError::Message(format!("压缩包损坏无法打开（{e}），原文件已保留")))?;

    let count = archive.len();
    if count > MAX_ZIP_MEMBERS {
        return Err(AppError::Message(
            "压缩包内文件过多（超过 500 个），已保留原压缩包".to_string(),
        ));
    }

    let mut total_bytes: u64 = 0;
    let mut raw_entries: Vec<(usize, String, bool)> = Vec::with_capacity(count);
    for idx in 0..count {
        let entry = archive
            .by_index_raw(idx)
            .map_err(|e| AppError::Message(format!("读取压缩包目录失败（{e}），原文件已保留")))?;
        total_bytes = total_bytes.saturating_add(entry.size());
        if total_bytes > MAX_EXPANDED_BYTES {
            return Err(AppError::Message(
                "压缩包解压体积超过 512 MB 安全上限，已保留原压缩包".to_string(),
            ));
        }
        let raw_name = entry.name().replace('\\', "/");
        if entry.encrypted() {
            return Err(AppError::Message(
                "压缩包设有密码保护无法自动转换，已保留原压缩包".to_string(),
            ));
        }
        if let Some(mode) = entry.unix_mode() {
            if (mode & 0o170000) == 0o120000 {
                return Err(AppError::Message(
                    "压缩包包含不安全的符号链接路径，已跳过转换".to_string(),
                ));
            }
        }
        raw_entries.push((idx, raw_name, entry.is_dir()));
    }

    let mut order_map = BTreeMap::new();
    for (pos, name) in file_order.iter().enumerate() {
        order_map.entry(name.clone()).or_insert(pos);
    }

    raw_entries.sort_by(|a, b| {
        let base_a = a.1.rsplit('/').next().unwrap_or(&a.1);
        let base_b = b.1.rsplit('/').next().unwrap_or(&b.1);
        let rank_a = order_map
            .get(&a.1)
            .or_else(|| order_map.get(base_a))
            .copied()
            .unwrap_or(file_order.len());
        let rank_b = order_map
            .get(&b.1)
            .or_else(|| order_map.get(base_b))
            .copied()
            .unwrap_or(file_order.len());
        rank_a
            .cmp(&rank_b)
            .then_with(|| natural_key(&a.1).cmp(&natural_key(&b.1)))
    });

    let mut bundle = UnpackedZipBundle::default();
    let mut unsupported_exts = BTreeSet::new();

    for (idx, norm_name, is_dir) in raw_entries {
        if norm_name.starts_with('/')
            || norm_name.contains(':')
            || norm_name.split('/').any(|p| p == "..")
        {
            return Err(AppError::Message(
                "压缩包包含不安全路径，已跳过转换".to_string(),
            ));
        }
        if is_dir || norm_name.ends_with('/') {
            continue;
        }
        let parts: Vec<&str> = norm_name.split('/').filter(|p| !p.is_empty()).collect();
        if parts.is_empty() || parts.contains(&"__MACOSX") {
            continue;
        }
        let filename = *parts.last().unwrap();
        if filename.starts_with('.')
            || filename.starts_with("~$")
            || filename.eq_ignore_ascii_case("thumbs.db")
            || filename.eq_ignore_ascii_case("desktop.ini")
        {
            continue;
        }
        let suffix = Path::new(filename)
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| format!(".{}", s.to_lowercase()))
            .unwrap_or_default();

        let clean_rel = parts.join("/");

        if matches!(
            suffix.as_str(),
            ".pdf" | ".doc" | ".docx" | ".png" | ".jpg" | ".jpeg" | ".webp" | ".svg"
        ) {
            let target = directory.join(format!("{:04}{suffix}", bundle.documents.len()));
            let mut entry = archive
                .by_index(idx)
                .map_err(|e| AppError::Message(format!("解压 {clean_rel} 失败：{e}")))?;
            let mut out_file = File::create(&target)?;
            std::io::copy(&mut entry, &mut out_file)?;
            out_file.flush()?;
            bundle.documents.push((clean_rel, target));
        } else if matches!(
            suffix.as_str(),
            ".mp3" | ".wav" | ".m4a" | ".wma" | ".aac" | ".ogg" | ".flac"
        ) {
            let safe_audio_name = filename.replace(['/', '\\', ':', '*', '?', '"', '<', '>', '|'], "_");
            let target = directory.join(format!(
                "audio_{:02}_{safe_audio_name}",
                bundle.companion_audios.len() + 1
            ));
            if let Ok(mut entry) = archive.by_index(idx) {
                if let Ok(mut out_file) = File::create(&target) {
                    if std::io::copy(&mut entry, &mut out_file).is_ok() {
                        let _ = out_file.flush();
                        bundle.companion_audios.push((safe_audio_name, target));
                    }
                }
            }
        } else {
            if !suffix.is_empty() {
                unsupported_exts.insert(suffix);
            }
            bundle.skipped_files.push(clean_rel);
        }
    }

    if bundle.documents.is_empty() {
        if !bundle.companion_audios.is_empty() {
            return Err(AppError::Message(
                "压缩包内仅包含听力音频，无 Word/PDF 试卷文档，已保留原压缩包".to_string(),
            ));
        }
        if !unsupported_exts.is_empty() {
            let exts: Vec<String> = unsupported_exts.into_iter().collect();
            return Err(AppError::Message(format!(
                "压缩包内仅含不支持自动转 PDF 的格式（{}），已保留原压缩包",
                exts.join("、")
            )));
        }
        return Err(AppError::Message(
            "压缩包内没有可转换的文档或图片，已保留原压缩包".to_string(),
        ));
    }

    Ok(bundle)
}

pub fn unpack_zip(
    source: &Path,
    directory: &Path,
    file_order: &[String],
) -> AppResult<Vec<(String, PathBuf)>> {
    Ok(unpack_zip_bundle(source, directory, file_order)?.documents)
}

/// Converts raw conversion errors into concise, beginner-friendly Chinese explanations.
pub fn humanize_conversion_error(raw: &str, suffix: &str) -> String {
    let lower_suffix = suffix.trim().to_lowercase();
    if lower_suffix == ".rar" || raw.contains(".rar") {
        return "暂不支持 RAR 压缩包自动转 PDF，已保存原压缩包（点击右侧「打开」可直接解压查看）"
            .to_string();
    }
    if lower_suffix == ".7z" || raw.contains(".7z") {
        return "暂不支持 7z 压缩包自动转 PDF，已保存原压缩包（点击右侧「打开」可直接解压查看）"
            .to_string();
    }
    if raw.contains("未检测到本地 Word 转 PDF 引擎") || raw.contains("未安装 LibreOffice") {
        return "未安装 LibreOffice 转换核心，已保存原文件；安装后继续任务即可补全 PDF".to_string();
    }
    if raw.contains("加密") || raw.contains("密码") || raw.to_lowercase().contains("password") {
        return "文件设有密码保护无法自动转换，已保存原文件".to_string();
    }
    if raw.contains("超时") || raw.to_lowercase().contains("timed out") {
        return "文档排版较复杂导致转换超时，已保存原文件".to_string();
    }
    if raw.contains("嵌套压缩包") {
        return "压缩包内含有多层嵌套压缩包无法自动转换，已保存原压缩包".to_string();
    }
    let cleaned = raw
        .trim_start_matches("原件已保存，PDF 尚未通过校验：")
        .trim();
    if cleaned.contains("已保留") || cleaned.contains("已保存") {
        cleaned.to_string()
    } else {
        format!("{cleaned}（已为您保留原文件）")
    }
}

/// Converts any supported source file (`.pdf`, `.doc`, `.docx`, `.zip`, `.svg`, raster image) to a verified
/// target PDF and returns the structured conversion report matching `conversion-report.json`.
pub fn source_to_pdf(
    source: &Path,
    target: &Path,
    timeout_secs: f64,
    expected_pages: usize,
    files_metadata: &[Value],
    settings: &AppSettings,
) -> AppResult<Value> {
    let kind = source_kind(source)?;
    let mut parts_report: Vec<Value> = Vec::new();
    let mut font_plan = FontResolutionPlan {
        policy: normalized_policy(settings),
        ..FontResolutionPlan::default()
    };
    let mut parts_tolerated = false;
    let mut self_heal_notes: Vec<String> = Vec::new();
    let mut exported_companions: Vec<String> = Vec::new();

    match kind {
        ".pdf" => {
            fs::copy(source, target)?;
        }
        ".doc" | ".docx" => {
            font_plan = word_to_pdf(source, target, timeout_secs, expected_pages, settings)?;
            let note = font_plan.summary_note();
            if !note.is_empty() {
                self_heal_notes.push(note);
            }
        }
        ".zip" => {
            let temp_dir = tempfile::Builder::new().prefix("stzy-zip-").tempdir()?;
            let work = temp_dir.path();
            let file_order: Vec<String> = files_metadata
                .iter()
                .filter_map(|item| item.get("fileName").and_then(Value::as_str))
                .map(str::to_string)
                .collect();
            let bundle = unpack_zip_bundle(source, work, &file_order)?;
            let deadline = Instant::now() + Duration::from_secs_f64(timeout_secs.max(5.0));

            if let Some(out_dir) = target.parent() {
                for (audio_name, audio_tmp) in &bundle.companion_audios {
                    let dst = out_dir.join(format!("companion_{audio_name}"));
                    if fs::copy(audio_tmp, &dst).is_ok() {
                        exported_companions.push(audio_name.clone());
                    }
                }
            }
            if !bundle.companion_audios.is_empty() {
                self_heal_notes.push(format!(
                    "已保留配套音频 {} 个",
                    bundle.companion_audios.len()
                ));
            }

            let mut converted_member_pdfs: Vec<(String, PathBuf)> =
                Vec::with_capacity(bundle.documents.len());
            let mut member_reports: Vec<(String, Value)> =
                Vec::with_capacity(bundle.documents.len());
            let mut zip_installed_fonts = BTreeSet::new();
            let mut zip_substituted_fonts = BTreeMap::new();

            for (name, member_path) in bundle.documents {
                let member_kind = source_kind(&member_path)?;
                if matches!(member_kind, ".zip" | ".rar" | ".7z") {
                    return Err(AppError::Message(
                        "暂不支持嵌套压缩包转换，原压缩包已保留".to_string(),
                    ));
                }
                let rem = deadline.saturating_duration_since(Instant::now());
                if rem.is_zero() {
                    return Err(AppError::Message("压缩包转换超时，原压缩包已保留".to_string()));
                }
                let base_name = name.rsplit('/').next().unwrap_or(&name);
                let expected_member_pages = files_metadata
                    .iter()
                    .find(|f| {
                        f.get("fileName")
                            .and_then(Value::as_str)
                            .map(|fnm| fnm == name || fnm == base_name)
                            .unwrap_or(false)
                    })
                    .and_then(|f| f.get("totalPage"))
                    .and_then(|v| {
                        v.as_u64()
                            .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
                    })
                    .unwrap_or(0) as usize;

                let stem = member_path
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("part");
                let member_pdf = work.join(format!("{stem}-converted.pdf"));
                let m_rep = source_to_pdf(
                    &member_path,
                    &member_pdf,
                    rem.as_secs_f64(),
                    expected_member_pages,
                    &[],
                    settings,
                )
                .map_err(|e| AppError::Message(format!("压缩包内《{base_name}》转换失败：{e}")))?;

                if let Some(f_obj) = m_rep.get("fonts") {
                    if let Some(inst) = f_obj.get("installed").and_then(Value::as_array) {
                        for item in inst.iter().filter_map(Value::as_str) {
                            zip_installed_fonts.insert(item.to_string());
                        }
                    }
                    if let Some(sub) = f_obj.get("substituted").and_then(Value::as_object) {
                        for (k, v) in sub {
                            if let Some(vs) = v.as_str() {
                                zip_substituted_fonts.insert(k.clone(), vs.to_string());
                            }
                        }
                    }
                }

                let m_insp = inspect_pdf(&member_pdf, false)?;
                let m_check = if m_rep
                    .get("page_check")
                    .and_then(Value::as_object)
                    .map(|o| !o.is_empty())
                    .unwrap_or(false)
                {
                    m_rep.get("page_check").cloned().unwrap_or_else(|| json!({}))
                } else {
                    page_check(
                        expected_member_pages,
                        m_insp.page_count,
                        normalized_policy(settings) != "strict",
                        &format!("{base_name} "),
                    )?
                };
                if m_check
                    .get("tolerated")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                {
                    parts_tolerated = true;
                }

                converted_member_pdfs.push((name.clone(), member_pdf));
                member_reports.push((name, m_rep));
            }

            font_plan.installed = zip_installed_fonts.into_iter().collect();
            font_plan.substituted = zip_substituted_fonts;
            let zip_font_note = font_plan.summary_note();
            if !zip_font_note.is_empty() {
                self_heal_notes.push(zip_font_note);
            }

            let merged_toc = merge_pdf_files_with_toc(&converted_member_pdfs, target)?;
            for ((name, first_page, pages), (_, m_rep)) in
                merged_toc.into_iter().zip(member_reports.into_iter())
            {
                parts_report.push(json!({
                    "name": name,
                    "pages": pages,
                    "first_page": first_page,
                    "source_kind": m_rep.get("source_kind").cloned().unwrap_or(json!("")),
                    "layout": m_rep.get("layout").cloned().unwrap_or(json!("")),
                    "fonts": m_rep.get("fonts").cloned().unwrap_or(json!({})),
                    "page_check": m_rep.get("page_check").cloned().unwrap_or(json!({})),
                }));
            }
        }
        ".png" | ".jpg" | ".jpeg" | ".webp" | ".svg" => {
            convert_originals_to_pdf(&[source.to_path_buf()], target, settings)?;
        }
        other => {
            return Err(AppError::Message(humanize_conversion_error(
                &format!("暂不支持 {other} 转 PDF"),
                other,
            )));
        }
    }

    let final_insp = inspect_pdf(target, false)?;
    let final_check = page_check(
        expected_pages,
        final_insp.page_count,
        normalized_policy(settings) != "strict" || font_plan.visual_review || parts_tolerated,
        "",
    )?;

    let all_source_pdf = matches!(kind, ".pdf" | ".zip")
        && parts_report.iter().all(|p| {
            p.get("layout")
                .and_then(Value::as_str)
                .map(|l| l == "source_pdf_pages")
                .unwrap_or(false)
        });
    let layout = if all_source_pdf {
        "source_pdf_pages"
    } else {
        "converted_requires_visual_review"
    };

    Ok(json!({
        "source_kind": kind,
        "pages": final_insp.page_count,
        "files": parts_report,
        "companions": exported_companions,
        "fonts": font_plan.to_report_json(),
        "page_check": final_check,
        "self_heal_note": self_heal_notes.join("；"),
        "layout": layout,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn text_coverage_ignores_pua_wingdings_and_bullets() {
        let src = "一、选择题（共10题）\u{F0FE}\u{F06C} • 第一题：已知集合 A={1,2}";
        let rendered = "一、选择题（共10题） 第一题：已知集合 A={1,2}";
        let (matched, needed, missing) = compute_text_coverage(src, rendered);
        assert_eq!(matched, needed);
        assert!(missing.is_empty());
    }

    #[test]
    fn humanize_error_explains_rar_and_passwords_clearly() {
        let rar_msg = humanize_conversion_error("暂不支持 .rar 转 PDF", ".rar");
        assert!(rar_msg.contains("暂不支持 RAR 压缩包自动转 PDF"));
        let enc_msg = humanize_conversion_error("ZIP 已加密，原包已保留", ".zip");
        assert!(enc_msg.contains("密码保护"));
    }
}
