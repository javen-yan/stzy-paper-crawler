use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use regex::Regex;
use serde_json::{json, Value};
use url::Url;
use zip::ZipArchive;

use crate::converter::fonts::{
    default_common_substitutions, font_directories, write_fontconfig_xml,
    write_libreoffice_registry_xcu,
};
use crate::converter::pdf::{
    append_pdf_to_pngs, attach_pdf_outlines, convert_originals_to_pdf,
};
use crate::converter::svg::{convert_image_to_png, convert_svg_to_png};
use crate::error::{AppError, AppResult};
use crate::models::{ensure_directory, AppSettings, ResourceArtifacts};

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

/// Auto-detects all available local Office-to-PDF engines in priority order so Windows can
/// seamlessly fall back (e.g. Word COM -> WPS COM -> LibreOffice) if one engine fails.
pub fn detect_office_engines(settings: &AppSettings) -> Vec<OfficeEngine> {
    let mut engines = Vec::new();
    let mut push_unique = |eng: OfficeEngine| {
        if !engines.contains(&eng) {
            engines.push(eng);
        }
    };

    let explicit = std::env::var("STZY_SOFFICE_PATH")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| settings.soffice_path.clone());
    if !explicit.trim().is_empty() {
        let p = crate::models::expand_tilde(explicit.trim());
        if p.is_file() {
            push_unique(OfficeEngine::LibreOffice(p));
        } else if let Some(found) = which_binary(explicit.trim()) {
            push_unique(OfficeEngine::LibreOffice(found));
        }
    }

    #[cfg(target_os = "windows")]
    {
        if windows_progid_exists("Word.Application") {
            push_unique(OfficeEngine::MsWordCom);
        }
        if windows_progid_exists("KWPS.Application") || windows_progid_exists("WPS.Application") {
            push_unique(OfficeEngine::WpsCom);
        }
        let win_candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ];
        for cand in win_candidates {
            let p = PathBuf::from(cand);
            if p.is_file() {
                push_unique(OfficeEngine::LibreOffice(p));
            }
        }
    }

    for bin in ["soffice", "libreoffice"] {
        if let Some(found) = which_binary(bin) {
            push_unique(OfficeEngine::LibreOffice(found));
        }
    }

    #[cfg(target_os = "macos")]
    {
        let mac_app = PathBuf::from("/Applications/LibreOffice.app/Contents/MacOS/soffice");
        if mac_app.is_file() {
            push_unique(OfficeEngine::LibreOffice(mac_app));
        }
    }

    engines
}

/// Auto-detects the best local Office-to-PDF engine (Windows prefers native Word / WPS COM first;
/// macOS & Linux use LibreOffice headless).
pub fn detect_office_engine(settings: &AppSettings) -> Option<OfficeEngine> {
    detect_office_engines(settings).into_iter().next()
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

    if slice.starts_with(b"PK\x03\x04") || slice.starts_with(b"PK\x05\x06") {
        let zf = File::open(path)?;
        match ZipArchive::new(zf) {
            Ok(archive) => {
                let names: HashSet<&str> = archive.file_names().collect();
                if names.contains("[Content_Types].xml") {
                    if names.contains("word/document.xml") {
                        return Ok(".docx");
                    }
                    if names.contains("xl/workbook.xml") {
                        return Ok(".xlsx");
                    }
                    if names.contains("ppt/presentation.xml") {
                        return Ok(".pptx");
                    }
                }
                return Ok(".zip");
            }
            Err(e) => {
                return Err(AppError::Message(format!(
                    "压缩包或文档结构已损坏（{e}），原文件已保留"
                )));
            }
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

fn kill_process_tree(child: &mut std::process::Child) {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let pid = child.id();
        let _ = Command::new("taskkill")
            .creation_flags(CREATE_NO_WINDOW)
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .output();
    }
    #[cfg(unix)]
    {
        let pid = child.id();
        if pid > 0 {
            let _ = Command::new("kill")
                .args(["-9", &format!("-{pid}")])
                .output();
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn run_command_with_timeout(
    mut cmd: Command,
    timeout: Duration,
) -> AppResult<std::process::Output> {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());
    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::Message(format!("启动外部转换进程失败：{e}")))?;

    // Drain stdout/stderr concurrently to avoid deadlocking on Windows' 4 KB pipe buffer,
    // using bounded recv_timeout so inherited child handles can never hang wait/timeout cleanup.
    let stdout_pipe = child.stdout.take();
    let stderr_pipe = child.stderr.take();
    let (stdout_tx, stdout_rx) = std::sync::mpsc::sync_channel(1);
    let (stderr_tx, stderr_rx) = std::sync::mpsc::sync_channel(1);
    std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut pipe) = stdout_pipe {
            let _ = pipe.read_to_end(&mut buf);
        }
        let _ = stdout_tx.send(buf);
    });
    std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut pipe) = stderr_pipe {
            let _ = pipe.read_to_end(&mut buf);
        }
        let _ = stderr_tx.send(buf);
    });

    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let stdout = stdout_rx
                    .recv_timeout(Duration::from_secs(2))
                    .unwrap_or_default();
                let stderr = stderr_rx
                    .recv_timeout(Duration::from_secs(2))
                    .unwrap_or_default();
                return Ok(std::process::Output {
                    status,
                    stdout,
                    stderr,
                });
            }
            Ok(None) => {
                if Instant::now() >= deadline {
                    kill_process_tree(&mut child);
                    return Err(AppError::Message("Word 转换超时，原件已保留".to_string()));
                }
                std::thread::sleep(Duration::from_millis(80));
            }
            Err(e) => {
                kill_process_tree(&mut child);
                return Err(AppError::Message(format!("等待转换进程失败：{e}")));
            }
        }
    }
}

fn stage_profile_fonts(profile_dir: &Path, font_dirs: &[PathBuf]) {
    let user_fonts = profile_dir.join("user").join("fonts");
    if fs::create_dir_all(&user_fonts).is_err() {
        return;
    }
    for dir in font_dirs {
        let Ok(entries) = fs::read_dir(dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let src = entry.path();
            let Some(ext) = src.extension().and_then(|e| e.to_str()) else {
                continue;
            };
            if !matches!(
                ext.to_ascii_lowercase().as_str(),
                "ttf" | "otf" | "ttc" | "otc"
            ) {
                continue;
            }
            let Some(name) = src.file_name() else {
                continue;
            };
            let dst = user_fonts.join(name);
            if dst.exists() {
                continue;
            }
            if fs::hard_link(&src, &dst).is_err() {
                let _ = fs::copy(&src, &dst);
            }
        }
    }
}

#[cfg(target_os = "windows")]
static WINDOWS_COM_LOCK: parking_lot::Mutex<()> = parking_lot::Mutex::new(());

#[cfg(target_os = "windows")]
fn encode_powershell_utf16le_base64(script: &str) -> String {
    use base64::Engine;
    let utf16: Vec<u8> = script
        .encode_utf16()
        .flat_map(|u| u.to_le_bytes())
        .collect();
    base64::engine::general_purpose::STANDARD.encode(utf16)
}

#[cfg(target_os = "windows")]
fn windows_com_convert_to_pdf(
    prog_id: &str,
    source_path: &Path,
    pdf_path: &Path,
    timeout: Duration,
) -> AppResult<()> {
    // Word / WPS COM servers share Normal.dotm and single-instance state; serialize access
    // so concurrent convert workers never corrupt or kill each other's COM session.
    let _com_guard = WINDOWS_COM_LOCK.lock();

    let src = source_path.to_string_lossy().replace('\'', "''");
    let dst = pdf_path.to_string_lossy().replace('\'', "''");

    let script = format!(
        "$ErrorActionPreference = 'Stop'\n\
         [Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n\
         $app = $null\n\
         $doc = $null\n\
         try {{\n\
           $app = New-Object -ComObject '{prog_id}'\n\
           $app.Visible = $false\n\
           try {{ $app.DisplayAlerts = 0 }} catch {{}}\n\
           try {{\n\
             $doc = $app.Documents.Open('{src}', $false, $true, $false, '__STZY_NO_PASSWORD__')\n\
           }} catch {{\n\
             if ($_.Exception.Message -match '参数|argument|parameter|mismatch') {{\n\
               $doc = $app.Documents.Open('{src}', $false, $true, $false)\n\
             }} else {{\n\
               throw\n\
             }}\n\
           }}\n\
           try {{\n\
             $doc.ExportAsFixedFormat('{dst}', 17)\n\
           }} catch {{\n\
             $doc.SaveAs2('{dst}', 17)\n\
           }}\n\
         }} finally {{\n\
           if ($doc -ne $null) {{\n\
             try {{ $doc.Close($false) }} catch {{}}\n\
             try {{ [void][System.Runtime.Interopservices.Marshal]::ReleaseComObject($doc) }} catch {{}}\n\
           }}\n\
           if ($app -ne $null) {{\n\
             try {{ $app.Quit() }} catch {{}}\n\
             try {{ [void][System.Runtime.Interopservices.Marshal]::ReleaseComObject($app) }} catch {{}}\n\
           }}\n\
         }}"
    );

    let encoded = encode_powershell_utf16le_base64(&script);
    let mut cmd = Command::new("powershell");
    cmd.args([
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        &encoded,
    ]);
    let out = run_command_with_timeout(cmd, timeout)?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let msg = if err.trim().is_empty() {
            String::from_utf8_lossy(&out.stdout).trim().to_string()
        } else {
            err.trim().to_string()
        };
        return Err(AppError::Message(format!(
            "Windows Office COM 转换失败（{msg}），原件已保留"
        )));
    }
    Ok(())
}

/// Thin single-pass adapter that delegates `.doc` / `.docx` visual rendering to the best installed
/// local Office engine (WPS / Word COM with automatic fallback to LibreOffice on Windows;
/// LibreOffice with full system + bundled fonts on macOS/Linux).
fn convert_word_to_temp_pdf(
    source: &Path,
    target_pdf: &Path,
    timeout_secs: f64,
    settings: &AppSettings,
) -> AppResult<()> {
    let engines = detect_office_engines(settings);
    if engines.is_empty() {
        return Err(AppError::Message(
            "未安装 LibreOffice 转换核心，已保存原 Word 文件；安装 LibreOffice 后点击「继续任务」即可生成 PDF"
                .to_string(),
        ));
    }

    let kind = source_kind(source)?;
    let timeout = Duration::from_secs_f64(timeout_secs.max(10.0));
    let mut last_err: Option<AppError> = None;

    for engine in engines {
        let temp_dir = tempfile::Builder::new()
            .prefix("stzy-office-")
            .tempdir()?;
        let work = temp_dir.path();
        let local_source = work.join(format!("source{kind}"));
        fs::copy(source, &local_source)?;
        let output_pdf = work.join("source.pdf");

        let attempt_res: AppResult<()> = match engine {
            OfficeEngine::LibreOffice(ref soffice) => {
                let profile = work.join("profile");
                let dirs = font_directories(settings)?;
                let aliases = default_common_substitutions(settings);
                write_libreoffice_registry_xcu(&profile, &aliases)?;
                stage_profile_fonts(&profile, &dirs);
                let font_conf = write_fontconfig_xml(work, &dirs, &aliases)?;
                let profile_uri = Url::from_directory_path(&profile)
                    .or_else(|_| Url::from_file_path(&profile))
                    .map(|u| u.to_string())
                    .unwrap_or_else(|_| format!("file://{}", profile.display()));

                let mut cmd = Command::new(soffice);
                cmd.arg(format!(
                    "-env:UserInstallation={}",
                    profile_uri.trim_end_matches('/')
                ))
                .arg("--headless")
                .arg("--norestore")
                .arg("--convert-to")
                .arg("pdf:writer_pdf_Export")
                .arg("--outdir")
                .arg(work)
                .arg(&local_source)
                .env("FONTCONFIG_FILE", &font_conf);

                let output = run_command_with_timeout(cmd, timeout)?;
                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    Err(AppError::Message(format!(
                        "LibreOffice 转换失败（{}），原件已保留",
                        stderr.trim()
                    )))
                } else {
                    Ok(())
                }
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
                    windows_com_convert_to_pdf(prog_id, &local_source, &output_pdf, timeout)
                }
                #[cfg(not(target_os = "windows"))]
                {
                    Err(AppError::Message("当前系统不支持 Windows COM 转换".to_string()))
                }
            }
        };

        match attempt_res {
            Ok(()) if output_pdf.exists() => {
                fs::copy(&output_pdf, target_pdf)?;
                return Ok(());
            }
            Ok(()) => {
                last_err = Some(AppError::Message(
                    "文档转换失败（可能受密码保护或格式损坏），原文件已保存".to_string(),
                ));
            }
            Err(err) => {
                last_err = Some(err);
            }
        }
    }

    Err(last_err.unwrap_or_else(|| {
        AppError::Message("文档转换失败（可能受密码保护或格式损坏），原文件已保存".to_string())
    }))
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

fn decode_zip_entry_name(raw_bytes: &[u8]) -> String {
    if let Ok(utf8) = std::str::from_utf8(raw_bytes) {
        return utf8.replace('\\', "/");
    }
    let (decoded, _) = encoding_rs::GB18030.decode_without_bom_handling(raw_bytes);
    decoded.into_owned().replace('\\', "/")
}

/// Classifies a ZIP sub-document filename so exam papers ALWAYS appear first, followed by
/// answer sheets, listening scripts, and answer keys / explanations:
/// `0` = 正卷 / 试题 / 原卷版 / 学生版
/// `1` = 答题卡 / 答题纸 / 答题卷
/// `2` = 听力文本 / 听力原文 / 听力材料 / 录音稿
/// `3` = 参考答案 / 答案 / 解析 / 教师版 / 评分标准
fn zip_member_role_rank(filename: &str) -> u8 {
    let stem = Path::new(filename)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(filename)
        .to_lowercase();

    if stem.contains("原卷") || stem.contains("学生版") || stem.contains("空白卷") {
        return 0;
    }

    if stem.contains("答题卡") || stem.contains("答题纸") || stem.contains("答题卷") {
        return 1;
    }

    if stem.contains("听力文本")
        || stem.contains("听力原文")
        || stem.contains("听力材料")
        || stem.contains("听力稿")
        || stem.contains("录音稿")
        || stem.contains("录音原文")
    {
        return 2;
    }

    // Check explicit edition tags (`含解析版` / `含答案版` / `答案版` / `解析版`) BEFORE stripping `含答案`
    for answer_edition in [
        "含参考答案版",
        "含答案解析版",
        "含答案及解析版",
        "含解析版",
        "含答案版",
        "带解析版",
        "带答案版",
        "附解析版",
        "附答案版",
        "有答案版",
        "答案版",
        "解析版",
    ] {
        if stem.contains(answer_edition) {
            return 3;
        }
    }

    let mut cleaned = stem;
    for combined_tag in [
        "含参考答案",
        "附参考答案",
        "带参考答案",
        "含部分解析",
        "含答案及解析",
        "含答案解析",
        "含答案",
        "附答案",
        "带答案",
        "有答案",
        "含解析",
        "附解析",
        "带解析",
    ] {
        cleaned = cleaned.replace(combined_tag, "");
    }

    if cleaned.contains("答案")
        || cleaned.contains("解析")
        || cleaned.contains("教师版")
        || cleaned.contains("评分标准")
        || cleaned.contains("评分细则")
        || cleaned.contains("answer")
    {
        return 3;
    }

    0
}

fn zip_entry_effective_role(full_rel_path: &str) -> u8 {
    let base = full_rel_path.rsplit('/').next().unwrap_or(full_rel_path);
    let leaf_role = zip_member_role_rank(base);
    if leaf_role != 0 {
        return leaf_role;
    }
    let lower_base = base.to_lowercase();
    if lower_base.contains("原卷")
        || lower_base.contains("学生版")
        || lower_base.contains("空白卷")
    {
        return 0;
    }
    for dir_seg in full_rel_path.rsplit('/').skip(1) {
        let dir_role = zip_member_role_rank(dir_seg);
        if dir_role != 0 {
            return dir_role;
        }
    }
    0
}

/// Safely validates and unpacks a `.zip` bundle in paper-first pedagogical order
/// (`正卷` -> `答题卡` -> `听力文本` -> `参考答案/解析`, breaking ties by site `fileList` & natural sort),
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
        let raw_name = decode_zip_entry_name(entry.name_raw());
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
        let role_a = zip_entry_effective_role(&a.1);
        let role_b = zip_entry_effective_role(&b.1);
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
        role_a
            .cmp(&role_b)
            .then_with(|| rank_a.cmp(&rank_b))
            .then_with(|| natural_key(&a.1).cmp(&natural_key(&b.1)))
    });

    let mut bundle = UnpackedZipBundle::default();
    let mut unsupported_exts = BTreeSet::new();
    let mut actual_extracted_bytes: u64 = 0;
    let mut used_audio_names = HashSet::new();

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
            let entry = archive
                .by_index(idx)
                .map_err(|e| AppError::Message(format!("解压 {clean_rel} 失败：{e}")))?;
            let remaining = MAX_EXPANDED_BYTES.saturating_sub(actual_extracted_bytes);
            let mut bounded = entry.take(remaining.saturating_add(1));
            let mut out_file = File::create(&target)?;
            let written = std::io::copy(&mut bounded, &mut out_file)?;
            out_file.flush()?;
            actual_extracted_bytes = actual_extracted_bytes.saturating_add(written);
            if actual_extracted_bytes > MAX_EXPANDED_BYTES {
                return Err(AppError::Message(
                    "压缩包实际解压体积超过 512 MB 安全上限，已保留原压缩包".to_string(),
                ));
            }
            bundle.documents.push((clean_rel, target));
        } else if matches!(
            suffix.as_str(),
            ".mp3" | ".wav" | ".m4a" | ".wma" | ".aac" | ".ogg" | ".flac"
        ) {
            let stem_raw = Path::new(filename)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("audio");
            let clean_stem: String = crate::models::safe_filename(stem_raw, "audio")
                .chars()
                .take(48)
                .collect();
            let mut safe_audio_name = format!("{clean_stem}{suffix}");
            let mut dup_idx = 2usize;
            while used_audio_names.contains(&safe_audio_name.to_lowercase()) {
                safe_audio_name = format!("{clean_stem}_{dup_idx}{suffix}");
                dup_idx += 1;
            }
            used_audio_names.insert(safe_audio_name.to_lowercase());

            let target = directory.join(format!(
                "audio_{:02}_{safe_audio_name}",
                bundle.companion_audios.len() + 1
            ));
            if let Ok(entry) = archive.by_index(idx) {
                let remaining = MAX_EXPANDED_BYTES.saturating_sub(actual_extracted_bytes);
                let mut bounded = entry.take(remaining.saturating_add(1));
                if let Ok(mut out_file) = File::create(&target) {
                    if let Ok(written) = std::io::copy(&mut bounded, &mut out_file) {
                        actual_extracted_bytes = actual_extracted_bytes.saturating_add(written);
                        if actual_extracted_bytes <= MAX_EXPANDED_BYTES {
                            let _ = out_file.flush();
                            bundle.companion_audios.push((safe_audio_name, target));
                        } else {
                            let _ = fs::remove_file(&target);
                        }
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

/// Renders one leaf source file (`.pdf`, `.doc`, `.docx`, `.svg`, or raster image) directly into
/// `练习{start_index}.png ..` inside `page_dir`, returning the number of pages rendered.
fn render_leaf_source_to_pngs(
    source: &Path,
    page_dir: &Path,
    start_index: usize,
    timeout_secs: f64,
    settings: &AppSettings,
) -> AppResult<usize> {
    ensure_directory(page_dir)?;
    let artifacts = ResourceArtifacts::new(page_dir.to_path_buf());
    let kind = source_kind(source)?;

    match kind {
        ".pdf" => {
            let count = append_pdf_to_pngs(source, page_dir, start_index, settings)?;
            if count == 0 {
                return Err(AppError::Message("PDF 没有可渲染的有效页面".to_string()));
            }
            Ok(count)
        }
        ".doc" | ".docx" => {
            let temp_dir = tempfile::Builder::new().prefix("stzy-word-").tempdir()?;
            let temp_pdf = temp_dir.path().join("word.pdf");
            convert_word_to_temp_pdf(source, &temp_pdf, timeout_secs, settings)?;
            let count = append_pdf_to_pngs(&temp_pdf, page_dir, start_index, settings)?;
            if count == 0 {
                return Err(AppError::Message("文档转换后没有可渲染的有效页面".to_string()));
            }
            Ok(count)
        }
        ".svg" => {
            convert_svg_to_png(source, &artifacts.page_png(start_index.max(1)), settings)?;
            Ok(1)
        }
        ".png" | ".jpg" | ".jpeg" | ".webp" => {
            convert_image_to_png(source, &artifacts.page_png(start_index.max(1)))?;
            Ok(1)
        }
        other => Err(AppError::Message(humanize_conversion_error(
            &format!("暂不支持 {other} 转换"),
            other,
        ))),
    }
}

/// Unified image-first print pipeline:
/// 1. Renders any supported source (`.pdf`, `.doc`, `.docx`, `.zip`, `.svg`, image) into a continuous
///    sequence of print-ready 180-DPI images `练习1.png .. 练习N.png` inside `page_dir`.
/// 2. Stitches those exact page images into a standard A4 print-ready `target_pdf` (attaching PDF
///    Outlines bookmarks when unpacking multi-file `.zip` archives).
pub fn render_source_to_pages_and_pdf(
    source: &Path,
    page_dir: &Path,
    target_pdf: &Path,
    timeout_secs: f64,
    files_metadata: &[Value],
    settings: &AppSettings,
) -> AppResult<(usize, Value)> {
    ensure_directory(page_dir)?;
    let kind = source_kind(source)?;
    let mut parts_report: Vec<Value> = Vec::new();
    let mut toc_pairs: Vec<(String, usize)> = Vec::new();
    let mut self_heal_notes: Vec<String> = Vec::new();
    let mut exported_companions: Vec<String> = Vec::new();

    let total_pages = if kind == ".zip" {
        let temp_dir = tempfile::Builder::new().prefix("stzy-zip-").tempdir()?;
        let work = temp_dir.path();
        let file_order: Vec<String> = files_metadata
            .iter()
            .filter_map(|item| item.get("fileName").and_then(Value::as_str))
            .map(str::to_string)
            .collect();
        let bundle = unpack_zip_bundle(source, work, &file_order)?;
        let doc_count = bundle.documents.len();
        let zip_total_timeout =
            (timeout_secs.max(30.0) * (doc_count.max(1) as f64)).clamp(90.0, 900.0);
        let deadline = Instant::now() + Duration::from_secs_f64(zip_total_timeout);

        for (audio_name, audio_tmp) in &bundle.companion_audios {
            let dst = page_dir.join(format!("companion_{audio_name}"));
            if fs::copy(audio_tmp, &dst).is_ok() {
                exported_companions.push(audio_name.clone());
            }
        }
        if !bundle.companion_audios.is_empty() {
            self_heal_notes.push(format!(
                "已保留配套音频 {} 个",
                bundle.companion_audios.len()
            ));
        }

        let mut next_page_index = 1usize;
        let mut skipped_members: Vec<String> = Vec::new();
        let mut last_member_err = String::new();

        for (name, member_path) in bundle.documents {
            let base_name = name.rsplit('/').next().unwrap_or(&name).to_string();
            let Ok(member_kind) = source_kind(&member_path) else {
                skipped_members.push(base_name);
                continue;
            };
            if matches!(member_kind, ".zip" | ".rar" | ".7z") {
                skipped_members.push(base_name);
                continue;
            }
            let rem = deadline.saturating_duration_since(Instant::now());
            if rem.is_zero() {
                last_member_err = "压缩包渲染超时".to_string();
                break;
            }
            let per_doc_timeout = rem.as_secs_f64().min(timeout_secs.max(45.0));
            let first_page = next_page_index;

            match render_leaf_source_to_pngs(
                &member_path,
                page_dir,
                first_page,
                per_doc_timeout,
                settings,
            ) {
                Ok(pages) => {
                    next_page_index += pages;
                    toc_pairs.push((name.clone(), first_page));
                    parts_report.push(json!({
                        "name": name,
                        "pages": pages,
                        "first_page": first_page,
                        "source_kind": member_kind,
                        "layout": "rendered_print_pages",
                    }));
                }
                Err(e) => {
                    last_member_err = format!("《{base_name}》渲染失败：{e}");
                    skipped_members.push(base_name);
                }
            }
        }

        let rendered_total = next_page_index.saturating_sub(1);
        if rendered_total == 0 {
            let reason = if !last_member_err.is_empty() {
                format!("{last_member_err}，原压缩包已保留")
            } else {
                "压缩包内无成功渲染的子文档，原压缩包已保留".to_string()
            };
            return Err(AppError::Message(reason));
        }
        if !skipped_members.is_empty() {
            self_heal_notes.push(format!(
                "已跳过 {} 个无法转换的附加文件，完整原文件见源文件.zip",
                skipped_members.len()
            ));
        }
        rendered_total
    } else {
        render_leaf_source_to_pngs(source, page_dir, 1, timeout_secs, settings)?
    };

    let artifacts = ResourceArtifacts::new(page_dir.to_path_buf());
    let png_paths: Vec<PathBuf> = (1..=total_pages).map(|i| artifacts.page_png(i)).collect();
    convert_originals_to_pdf(&png_paths, target_pdf, settings)?;

    if !toc_pairs.is_empty() {
        if let Err(err) = attach_pdf_outlines(target_pdf, &toc_pairs) {
            tracing::warn!("Failed attaching PDF outlines to print PDF: {err}");
        }
    }

    let report = json!({
        "source_kind": kind,
        "pages": total_pages,
        "files": parts_report,
        "companions": exported_companions,
        "self_heal_note": self_heal_notes.join("；"),
        "layout": "rendered_print_pages",
    });
    Ok((total_pages, report))
}

/// Convenience wrapper producing `target` PDF via the unified image-first print pipeline.
pub fn source_to_pdf(
    source: &Path,
    target: &Path,
    timeout_secs: f64,
    _expected_pages: usize,
    files_metadata: &[Value],
    settings: &AppSettings,
) -> AppResult<Value> {
    let temp_pages = tempfile::Builder::new().prefix("stzy-pages-").tempdir()?;
    let (_count, report) = render_source_to_pages_and_pdf(
        source,
        temp_pages.path(),
        target,
        timeout_secs,
        files_metadata,
        settings,
    )?;
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn humanize_error_explains_rar_and_passwords_clearly() {
        let rar_msg = humanize_conversion_error("暂不支持 .rar 转 PDF", ".rar");
        assert!(rar_msg.contains("暂不支持 RAR 压缩包自动转 PDF"));
        let enc_msg = humanize_conversion_error("ZIP 已加密，原包已保留", ".zip");
        assert!(enc_msg.contains("密码保护"));
    }

    #[test]
    fn zip_member_role_orders_paper_before_card_script_and_answer_key() {
        assert_eq!(zip_member_role_rank("七历史七历史转.pdf"), 0);
        assert_eq!(
            zip_member_role_rank("湖北孝感市孝昌县七年级历史试题word版含答案历史.pdf"),
            0
        );
        assert_eq!(zip_member_role_rank("2026期中数学试卷（原卷版）.docx"), 0);
        assert_eq!(zip_member_role_rank("26-27道法期中答题卡.pdf"), 1);
        assert_eq!(zip_member_role_rank("八年级英语期中听力原文.docx"), 2);
        assert_eq!(
            zip_member_role_rank("七历史26秋期中监测七年级历史参考答案.pdf"),
            3
        );
        assert_eq!(zip_member_role_rank("2026期中数学试卷（解析版）.docx"), 3);
        assert_eq!(zip_member_role_rank("2026期中数学试卷（含解析版）.docx"), 3);
        assert_eq!(zip_member_role_rank("2026期中数学试卷（含答案版）.docx"), 3);
        assert_eq!(zip_entry_effective_role("试题/数学.pdf"), 0);
        assert_eq!(zip_entry_effective_role("答题卡/数学.pdf"), 1);
        assert_eq!(zip_entry_effective_role("答案/数学.pdf"), 3);

        let gbk_bytes = encoding_rs::GB18030
            .encode("七历史26秋期中监测七年级历史参考答案.pdf")
            .0;
        assert_eq!(
            decode_zip_entry_name(&gbk_bytes),
            "七历史26秋期中监测七年级历史参考答案.pdf"
        );
    }
}
