use std::fs;
use std::path::{Path, PathBuf};

use aes::cipher::{block_padding::Pkcs7, BlockDecryptMut, BlockEncryptMut, KeyIvInit};
use aes::Aes128;
use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::engine::general_purpose::{STANDARD as BASE64_STD, URL_SAFE as BASE64_URL_SAFE};
use base64::Engine;
use rand::RngCore;
use serde::Serialize;

use crate::error::{AppError, AppResult};

type Aes128CbcEnc = cbc::Encryptor<Aes128>;
type Aes128CbcDec = cbc::Decryptor<Aes128>;

pub const STZY_AES_KEY: &[u8; 16] = b"abADefg234cdegsd";
pub const VAULT_PREFIX: &str = "enc:v1:";

/// Encrypts a UTF-8 string using STZY's AES-128-CBC (key == iv) + PKCS7 + standard Base64.
pub fn stzy_encrypt_text(value: &str) -> String {
    let encrypted =
        Aes128CbcEnc::new(STZY_AES_KEY.into(), STZY_AES_KEY.into()).encrypt_padded_vec_mut::<Pkcs7>(value.as_bytes());
    BASE64_STD.encode(encrypted)
}

/// Serializes JSON compactly (no spaces, matching Python `separators=(",", ":")`) and encrypts it.
pub fn stzy_encrypt_json<T: Serialize>(data: &T) -> AppResult<String> {
    let payload = serde_json::to_string(data)?;
    Ok(stzy_encrypt_text(&payload))
}

/// Decrypts a STZY Base64 AES-128-CBC string back to UTF-8.
pub fn stzy_decrypt_text(value: &str) -> AppResult<String> {
    let raw = BASE64_STD
        .decode(value.trim())
        .map_err(|e| AppError::Validation(format!("密文 Base64 解码失败: {e}")))?;
    let decrypted = Aes128CbcDec::new(STZY_AES_KEY.into(), STZY_AES_KEY.into())
        .decrypt_padded_vec_mut::<Pkcs7>(&raw)
        .map_err(|e| AppError::Validation(format!("AES-128-CBC 解密失败: {e}")))?;
    String::from_utf8(decrypted)
        .map_err(|e| AppError::Validation(format!("解密内容不是合法 UTF-8: {e}")))
}

/// Local AES-256-GCM vault compatible with `enc:v1:<urlsafe_b64(nonce12 + tag16 + ciphertext)>`.
#[derive(Clone)]
pub struct CredentialVault {
    key: [u8; 32],
}

impl CredentialVault {
    pub fn load_or_create(key_path: &Path) -> AppResult<Self> {
        if let Ok(env_key) = std::env::var("STZY_SECRET_KEY") {
            let trimmed = env_key.trim();
            if !trimmed.is_empty() {
                let decoded = BASE64_URL_SAFE
                    .decode(trimmed)
                    .map_err(|e| AppError::Validation(format!("STZY_SECRET_KEY 解码失败: {e}")))?;
                if decoded.len() != 32 {
                    return Err(AppError::Validation(
                        "STZY_SECRET_KEY must decode to 32 bytes".to_string(),
                    ));
                }
                let mut key = [0u8; 32];
                key.copy_from_slice(&decoded);
                return Ok(Self { key });
            }
        }

        if key_path.exists() {
            if let Ok(text) = fs::read_to_string(key_path) {
                if let Ok(decoded) = BASE64_URL_SAFE.decode(text.trim()) {
                    if decoded.len() == 32 {
                        let mut key = [0u8; 32];
                        key.copy_from_slice(&decoded);
                        return Ok(Self { key });
                    }
                }
            }
        }

        if let Some(parent) = key_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut key = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut key);
        let encoded = BASE64_URL_SAFE.encode(key);
        fs::write(key_path, encoded)?;
        set_owner_only_permissions(key_path);
        Ok(Self { key })
    }

    pub fn default_key_path(data_dir: &Path) -> PathBuf {
        data_dir.join(".stzy-credentials.key")
    }

    /// Encrypts plaintext into `enc:v1:<urlsafe_b64(nonce[12] + tag[16] + ciphertext)>`.
    pub fn encrypt(&self, value: &str) -> AppResult<String> {
        if value.is_empty() || value.starts_with(VAULT_PREFIX) {
            return Ok(value.to_string());
        }
        let cipher = Aes256Gcm::new_from_slice(&self.key)
            .map_err(|e| AppError::Runtime(format!("初始化凭据加密器失败: {e}")))?;
        let mut nonce_bytes = [0u8; 12];
        rand::thread_rng().fill_bytes(&mut nonce_bytes);
        let nonce = Nonce::from_slice(&nonce_bytes);
        // `aes-gcm` appends the 16-byte authentication tag at the end of ciphertext.
        // Python's `CredentialVault` packs `nonce(12) + tag(16) + ciphertext`.
        let ct_and_tag = cipher
            .encrypt(nonce, value.as_bytes())
            .map_err(|e| AppError::Runtime(format!("凭据加密失败: {e}")))?;
        let split_at = ct_and_tag.len().saturating_sub(16);
        let (ciphertext, tag) = ct_and_tag.split_at(split_at);

        let mut packed = Vec::with_capacity(12 + 16 + ciphertext.len());
        packed.extend_from_slice(&nonce_bytes);
        packed.extend_from_slice(tag);
        packed.extend_from_slice(ciphertext);
        Ok(format!("{VAULT_PREFIX}{}", BASE64_URL_SAFE.encode(packed)))
    }

    pub fn decrypt(&self, value: &str) -> AppResult<String> {
        if value.is_empty() || !value.starts_with(VAULT_PREFIX) {
            return Ok(value.to_string());
        }
        let encoded = &value[VAULT_PREFIX.len()..];
        let packed = BASE64_URL_SAFE
            .decode(encoded.trim())
            .map_err(|e| AppError::Runtime(format!("凭据密文 Base64 解码失败: {e}")))?;
        if packed.len() < 28 {
            return Err(AppError::Runtime("凭据密文长度不合法".to_string()));
        }
        let nonce = Nonce::from_slice(&packed[..12]);
        let tag = &packed[12..28];
        let ciphertext = &packed[28..];

        let mut ct_and_tag = Vec::with_capacity(ciphertext.len() + 16);
        ct_and_tag.extend_from_slice(ciphertext);
        ct_and_tag.extend_from_slice(tag);

        let cipher = Aes256Gcm::new_from_slice(&self.key)
            .map_err(|e| AppError::Runtime(format!("初始化凭据解密器失败: {e}")))?;
        let plaintext = cipher
            .decrypt(nonce, ct_and_tag.as_ref())
            .map_err(|_| AppError::Runtime("凭据解密校验失败（密钥不匹配或数据已损坏）".to_string()))?;
        String::from_utf8(plaintext)
            .map_err(|e| AppError::Runtime(format!("凭据明文 UTF-8 解码失败: {e}")))
    }
}

#[cfg(unix)]
fn set_owner_only_permissions(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn set_owner_only_permissions(_path: &Path) {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn stzy_aes_cbc_matches_python_reference_vectors() {
        assert_eq!(stzy_encrypt_text("13800138000"), "9qchlnGbOxhfx8VWjQbrSA==");
        assert_eq!(stzy_encrypt_text("138000"), "cmB2QaDtXxqsqwP+T3WfKg==");
        assert_eq!(
            stzy_encrypt_json(&json!({"id": "773614591691493376"})).unwrap(),
            "9DVmGgmg6rpuU3hPxk2KFsdy/KWcvgEaMIt8H3TRU5U="
        );

        assert_eq!(
            stzy_decrypt_text("9qchlnGbOxhfx8VWjQbrSA==").unwrap(),
            "13800138000"
        );
        assert_eq!(
            stzy_decrypt_text("9DVmGgmg6rpuU3hPxk2KFsdy/KWcvgEaMIt8H3TRU5U=").unwrap(),
            r#"{"id":"773614591691493376"}"#
        );
    }

    #[test]
    fn credential_vault_roundtrip_and_idempotent() {
        let dir = tempfile::tempdir().unwrap();
        let key_path = CredentialVault::default_key_path(dir.path());
        let vault = CredentialVault::load_or_create(&key_path).unwrap();

        let secret = "ACCESS_TOKEN=eyJhbGciOiJIUzI1NiJ9.payload.sig; sid=12345";
        let encrypted = vault.encrypt(secret).unwrap();
        assert!(encrypted.starts_with(VAULT_PREFIX));
        assert_ne!(encrypted, secret);

        // Encrypting an already encrypted value is a no-op
        assert_eq!(vault.encrypt(&encrypted).unwrap(), encrypted);

        // Reloading from disk key decrypts identically
        let reloaded = CredentialVault::load_or_create(&key_path).unwrap();
        assert_eq!(reloaded.decrypt(&encrypted).unwrap(), secret);
        assert_eq!(reloaded.decrypt("plain_legacy_value").unwrap(), "plain_legacy_value");
    }
}
