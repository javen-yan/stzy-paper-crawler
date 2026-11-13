use std::fs::File;
use std::io::{Read, Seek, SeekFrom};

use tauri::http::{header, Request, Response, StatusCode};
use tauri::{Manager, Runtime, UriSchemeContext};
use url::Url;

use crate::commands::AppState;

/// Handles custom `stzyfile://` (macOS/Linux) / `http://stzyfile.localhost/` (Windows) requests
/// for inline image and PDF preview inside the WebView without running an external HTTP server.
pub fn handle_stzyfile_request<R: Runtime>(
    ctx: UriSchemeContext<'_, R>,
    request: Request<Vec<u8>>,
) -> Response<Vec<u8>> {
    if request.method() == tauri::http::Method::OPTIONS {
        return Response::builder()
            .status(StatusCode::NO_CONTENT)
            .header(header::ACCESS_CONTROL_ALLOW_ORIGIN, "*")
            .header(header::ACCESS_CONTROL_ALLOW_METHODS, "GET, HEAD, OPTIONS")
            .header(header::ACCESS_CONTROL_ALLOW_HEADERS, "Range, Content-Type")
            .body(Vec::new())
            .unwrap_or_default();
    }

    let Some(state) = ctx.app_handle().try_state::<AppState>() else {
        return plain_error(StatusCode::SERVICE_UNAVAILABLE, "Application state not ready");
    };

    let uri_str = request.uri().to_string();
    let parsed = Url::parse(&uri_str).or_else(|_| {
        let path_and_q = request
            .uri()
            .path_and_query()
            .map(|pq| pq.as_str())
            .unwrap_or("/");
        Url::parse(&format!("stzyfile://localhost{path_and_q}"))
    });
    let Ok(url) = parsed else {
        return plain_error(StatusCode::BAD_REQUEST, "Invalid preview URI");
    };

    let route = url.path().trim_matches('/');
    let mut query_path = String::new();
    let mut query_task_id = String::new();
    let mut query_artifact_id = String::new();
    for (k, v) in url.query_pairs() {
        match k.as_ref() {
            "path" => query_path = v.into_owned(),
            "task_id" => query_task_id = v.into_owned(),
            "id" => query_artifact_id = v.into_owned(),
            _ => {}
        }
    }

    let resolved = match route {
        "browser" => state.artifact_service.resolve_browser_file(
            &query_path,
            if query_task_id.is_empty() {
                None
            } else {
                Some(query_task_id.as_str())
            },
        ),
        "artifact" => state
            .artifact_service
            .resolve_artifact_file(&query_artifact_id),
        _ => {
            return plain_error(StatusCode::NOT_FOUND, "Unknown stzyfile endpoint");
        }
    };

    let (file_path, mime_type) = match resolved {
        Ok(pair) => pair,
        Err(err) => {
            let status = StatusCode::from_u16(err.status_code()).unwrap_or(StatusCode::NOT_FOUND);
            return plain_error(status, &err.user_message());
        }
    };

    let mut file = match File::open(&file_path) {
        Ok(f) => f,
        Err(_) => return plain_error(StatusCode::NOT_FOUND, "File not found"),
    };
    let total_len = match file.metadata() {
        Ok(m) => m.len(),
        Err(_) => return plain_error(StatusCode::INTERNAL_SERVER_ERROR, "Metadata read failed"),
    };

    let disposition = if mime_type == "application/octet-stream" {
        "attachment"
    } else {
        "inline"
    };

    // Support HTTP Range requests so WebView built-in PDF viewers stream smoothly
    if let Some(range_hdr) = request
        .headers()
        .get(header::RANGE)
        .and_then(|v| v.to_str().ok())
    {
        if let Some((start, end)) = parse_byte_range(range_hdr, total_len) {
            let chunk_len = (end - start + 1) as usize;
            let mut buf = vec![0u8; chunk_len];
            if file.seek(SeekFrom::Start(start)).is_ok() && file.read_exact(&mut buf).is_ok() {
                return Response::builder()
                    .status(StatusCode::PARTIAL_CONTENT)
                    .header(header::CONTENT_TYPE, &mime_type)
                    .header(header::ACCEPT_RANGES, "bytes")
                    .header(
                        header::CONTENT_RANGE,
                        format!("bytes {start}-{end}/{total_len}"),
                    )
                    .header(header::CONTENT_LENGTH, chunk_len.to_string())
                    .header(header::CONTENT_DISPOSITION, disposition)
                    .header(header::ACCESS_CONTROL_ALLOW_ORIGIN, "*")
                    .header("X-Content-Type-Options", "nosniff")
                    .body(buf)
                    .unwrap_or_default();
            }
        }
    }

    let mut buf = Vec::with_capacity(total_len as usize);
    if file.read_to_end(&mut buf).is_err() {
        return plain_error(StatusCode::INTERNAL_SERVER_ERROR, "Failed to read file");
    }

    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, &mime_type)
        .header(header::ACCEPT_RANGES, "bytes")
        .header(header::CONTENT_LENGTH, buf.len().to_string())
        .header(header::CONTENT_DISPOSITION, disposition)
        .header(header::ACCESS_CONTROL_ALLOW_ORIGIN, "*")
        .header("X-Content-Type-Options", "nosniff")
        .body(buf)
        .unwrap_or_default()
}

fn parse_byte_range(header_val: &str, total_len: u64) -> Option<(u64, u64)> {
    if total_len == 0 {
        return None;
    }
    let spec = header_val.trim().strip_prefix("bytes=")?;
    let first_range = spec.split(',').next()?.trim();
    let (start_s, end_s) = first_range.split_once('-')?;
    if start_s.is_empty() {
        let suffix_len: u64 = end_s.parse().ok()?;
        if suffix_len == 0 {
            return None;
        }
        let start = total_len.saturating_sub(suffix_len);
        Some((start, total_len - 1))
    } else {
        let start: u64 = start_s.parse().ok()?;
        if start >= total_len {
            return None;
        }
        let end = if end_s.is_empty() {
            total_len - 1
        } else {
            end_s.parse::<u64>().ok()?.min(total_len - 1)
        };
        if start > end {
            return None;
        }
        Some((start, end))
    }
}

fn plain_error(status: StatusCode, msg: &str) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .header(header::ACCESS_CONTROL_ALLOW_ORIGIN, "*")
        .body(msg.as_bytes().to_vec())
        .unwrap_or_default()
}
