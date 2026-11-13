use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("{0}")]
    Validation(String),

    #[error("{0}")]
    NotFound(String),

    #[error("{0}")]
    Conflict(String),

    #[error("STZY API error {code}: {message}")]
    StzyApi { code: String, message: String },

    #[error("任务已停止")]
    RequestStopped,

    #[error("任务已停止")]
    Cancelled,

    #[error("{0}")]
    InvalidDownloadContent(String),

    #[error("{0}")]
    ProxyUnavailable(String),

    #[error("{0}")]
    Runtime(String),

    #[error("{0}")]
    Message(String),

    #[error(transparent)]
    Io(#[from] std::io::Error),

    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),

    #[error(transparent)]
    Json(#[from] serde_json::Error),

    #[error(transparent)]
    Http(#[from] reqwest::Error),
}

impl AppError {
    pub fn requires_login(&self) -> bool {
        match self {
            Self::StzyApi { code, message } => code == "-1" || message.contains("登录"),
            _ => false,
        }
    }

    pub fn status_code(&self) -> u16 {
        match self {
            Self::Validation(_) => 400,
            Self::NotFound(_) => 404,
            Self::Conflict(_) => 409,
            Self::StzyApi { .. } if self.requires_login() => 401,
            _ => 500,
        }
    }

    pub fn user_message(&self) -> String {
        match self {
            Self::StzyApi { message, .. } => message.clone(),
            other => other.to_string(),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct CommandErrorPayload {
    pub detail: String,
    pub status: u16,
}

impl Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        CommandErrorPayload {
            detail: self.user_message(),
            status: self.status_code(),
        }
        .serialize(serializer)
    }
}

pub type AppResult<T> = Result<T, AppError>;
