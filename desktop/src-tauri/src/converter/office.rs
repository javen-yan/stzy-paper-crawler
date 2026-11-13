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
    ensure_word_fonts, font_directories, write_fontconfig_xml, FontResolutionPlan,
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
            "下载结果是 HTML 页面，不是原文文件".to_string(),
        ));
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
            "无法识别原文格式（支持 PDF、Word、ZIP、RAR、7z 和图片）".to_string(),
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
            "未检测到本地 Word 转 PDF 引擎（Windows 支持 Microsoft Word / WPS / LibreOffice；macOS 请安装 LibreOffice），原件已完整保留"
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

    let plan: FontResolutionPlan = match engine {
        OfficeEngine::LibreOffice(ref soffice) => {
            let profile = work.join("profile");
            fs::create_dir_all(profile.join("user"))?;
            fs::write(
                profile.join("user/registrymodifications.xcu"),
                r#"<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>"#,
            )?;

            let mut inspection_docx = local_source.clone();
            if kind == ".doc" {
                let rem = deadline.saturating_duration_since(Instant::now());
                libreoffice_convert(
                    soffice,
                    work,
                    &profile,
                    &local_source,
                    "docx:Office Open XML Text",
                    settings,
                    &BTreeMap::new(),
                    rem,
                )?;
                inspection_docx = work.join("source.docx");
                if !inspection_docx.exists() {
                    return Err(AppError::Message(
                        "无法检查 DOC 字体，文件可能已加密或损坏".to_string(),
                    ));
                }
            }

            let (declared_fonts, source_text) = docx_content(&inspection_docx)?;
            let mut resolved = ensure_word_fonts(&declared_fonts, settings)?;
            if !resolved.missing.is_empty() {
                return Err(AppError::Message(format!(
                    "缺少原文字体：{}；请安装有授权的字体或在设置中指定字体目录，原件已保留",
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
                    "LibreOffice 未生成 PDF，原件已保留".to_string(),
                ));
            }
            verify_word_pdf_output(&output_pdf, &source_text, expected_pages, &mut resolved)?;
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
                    docx_content(inspect_target)?
                } else {
                    (BTreeSet::new(), String::new())
                };
                let mut resolved = ensure_word_fonts(&declared_fonts, settings)?;
                if !resolved.missing.is_empty() {
                    return Err(AppError::Message(format!(
                        "缺少原文字体：{}；原件已保留",
                        resolved.missing.join("、")
                    )));
                }
                verify_word_pdf_output(&output_pdf, &source_text, expected_pages, &mut resolved)?;
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

fn verify_word_pdf_output(
    output_pdf: &Path,
    source_text: &str,
    expected_pages: usize,
    plan: &mut FontResolutionPlan,
) -> AppResult<()> {
    let inspection = inspect_pdf(output_pdf, true)?;
    plan.page_check = page_check(expected_pages, inspection.page_count, plan.visual_review, "")?;

    let src_chars = count_non_whitespace_chars(source_text);
    let rendered_chars = count_non_whitespace_chars(&inspection.extracted_text);
    for (ch, needed) in src_chars {
        let got = rendered_chars.get(&ch).copied().unwrap_or(0);
        if got < needed {
            return Err(AppError::Message(
                "Word 转换文字覆盖校验失败，可能缺字或对象未正确渲染；未发布 PDF".to_string(),
            ));
        }
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

/// Safely validates and unpacks a `.zip` bundle in site `fileList` order (falling back to natural sort).
pub fn unpack_zip(
    source: &Path,
    directory: &Path,
    file_order: &[String],
) -> AppResult<Vec<(String, PathBuf)>> {
    let zf = File::open(source)?;
    let mut archive = ZipArchive::new(zf)
        .map_err(|e| AppError::Message(format!("打开 ZIP 失败：{e}")))?;

    let count = archive.len();
    if count > MAX_ZIP_MEMBERS {
        return Err(AppError::Message(
            "ZIP 超过 500 个条目或解压后 512 MiB 限制".to_string(),
        ));
    }

    let mut total_bytes: u64 = 0;
    let mut raw_entries: Vec<(usize, String, bool)> = Vec::with_capacity(count);
    for idx in 0..count {
        let entry = archive
            .by_index_raw(idx)
            .map_err(|e| AppError::Message(format!("读取 ZIP 条目失败：{e}")))?;
        total_bytes = total_bytes.saturating_add(entry.size());
        if total_bytes > MAX_EXPANDED_BYTES {
            return Err(AppError::Message(
                "ZIP 超过 500 个条目或解压后 512 MiB 限制".to_string(),
            ));
        }
        let raw_name = entry.name().replace('\\', "/");
        if entry.encrypted() {
            return Err(AppError::Message("ZIP 已加密，原包已保留".to_string()));
        }
        if let Some(mode) = entry.unix_mode() {
            if (mode & 0o170000) == 0o120000 {
                return Err(AppError::Message(
                    "ZIP 包含不安全路径或符号链接".to_string(),
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

    let mut extracted = Vec::new();
    for (idx, norm_name, is_dir) in raw_entries {
        if norm_name.starts_with('/')
            || norm_name.contains(':')
            || norm_name.split('/').any(|p| p == "..")
        {
            return Err(AppError::Message(
                "ZIP 包含不安全路径或符号链接".to_string(),
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
        if filename.starts_with('.') || filename.starts_with("~$") {
            continue;
        }
        let suffix = Path::new(filename)
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| format!(".{}", s.to_lowercase()))
            .unwrap_or_default();
        if !matches!(
            suffix.as_str(),
            ".pdf" | ".doc" | ".docx" | ".png" | ".jpg" | ".jpeg" | ".webp"
        ) {
            return Err(AppError::Message(format!(
                "ZIP 中的 {norm_name} 暂不支持转换，未跳过或标记完成"
            )));
        }

        let clean_rel = parts.join("/");
        let target = directory.join(format!("{:04}{suffix}", extracted.len()));
        let mut entry = archive
            .by_index(idx)
            .map_err(|e| AppError::Message(format!("解压 {clean_rel} 失败：{e}")))?;
        let mut out_file = File::create(&target)?;
        std::io::copy(&mut entry, &mut out_file)?;
        out_file.flush()?;
        extracted.push((clean_rel, target));
    }

    if extracted.is_empty() {
        return Err(AppError::Message("ZIP 中没有可转换文档".to_string()));
    }
    Ok(extracted)
}

/// Converts any supported source file (`.pdf`, `.doc`, `.docx`, `.zip`, raster image) to a verified
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
        policy: crate::converter::fonts::normalized_policy(settings),
        ..FontResolutionPlan::default()
    };
    let mut parts_tolerated = false;

    match kind {
        ".pdf" => {
            fs::copy(source, target)?;
        }
        ".doc" | ".docx" => {
            font_plan = word_to_pdf(source, target, timeout_secs, expected_pages, settings)?;
        }
        ".zip" => {
            let temp_dir = tempfile::Builder::new().prefix("stzy-zip-").tempdir()?;
            let work = temp_dir.path();
            let file_order: Vec<String> = files_metadata
                .iter()
                .filter_map(|item| item.get("fileName").and_then(Value::as_str))
                .map(str::to_string)
                .collect();
            let members = unpack_zip(source, work, &file_order)?;
            let deadline = Instant::now() + Duration::from_secs_f64(timeout_secs.max(5.0));

            let mut converted_member_pdfs: Vec<(String, PathBuf)> = Vec::with_capacity(members.len());
            let mut member_reports: Vec<(String, Value)> = Vec::with_capacity(members.len());

            for (name, member_path) in members {
                let member_kind = source_kind(&member_path)?;
                if matches!(member_kind, ".zip" | ".rar" | ".7z") {
                    return Err(AppError::Message(
                        "暂不支持嵌套压缩包转换，原包已保留".to_string(),
                    ));
                }
                let rem = deadline.saturating_duration_since(Instant::now());
                if rem.is_zero() {
                    return Err(AppError::Message("ZIP 转换超时，原包已保留".to_string()));
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
                .map_err(|e| AppError::Message(format!("ZIP 成员 {name} 转换失败：{e}")))?;

                let m_insp = inspect_pdf(&member_pdf, false)?;
                let m_visual = m_rep
                    .get("fonts")
                    .and_then(|f| f.get("visual_review"))
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
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
                        m_visual,
                        &format!("{name} "),
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
        ".png" | ".jpg" | ".jpeg" | ".webp" => {
            convert_originals_to_pdf(&[source.to_path_buf()], target, settings)?;
        }
        other => {
            return Err(AppError::Message(format!(
                "暂不支持 {other} 转 PDF，原件已保留"
            )));
        }
    }

    let final_insp = inspect_pdf(target, false)?;
    let final_check = page_check(
        expected_pages,
        final_insp.page_count,
        font_plan.visual_review || parts_tolerated,
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
        "fonts": font_plan.to_report_json(),
        "page_check": final_check,
        "layout": layout,
    }))
}
