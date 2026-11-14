//! Armazenamento cifrado de conversas, memorias e biblioteca.
//!
//! Cada registro e gravado com AES-256-GCM sob uma chave derivada por Argon2id,
//! com nonce aleatorio por escrita e AAD vinculado ao identificador. Nao existe
//! caminho de escrita em texto puro: com o cofre bloqueado qualquer operacao falha.

use std::path::{Path, PathBuf};

use rand_core::{OsRng, RngCore};
use serde::de::DeserializeOwned;
use serde::Serialize;
use zeroize::Zeroize;

use crate::error::{CoreError, CoreResult};
use crate::fsutil::secure_write;
use crate::vault::{EncryptedRecord, MasterKey, SALT_LEN};

const SALT_FILE: &str = "kdf.salt";
const RECORD_EXT: &str = "mrec";

/// Diretorio cifrado de registros.
pub struct EncryptedStore {
    dir: PathBuf,
    key: Option<MasterKey>,
}

impl std::fmt::Debug for EncryptedStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EncryptedStore")
            .field("dir", &self.dir)
            .field("locked", &self.key.is_none())
            .finish()
    }
}

impl EncryptedStore {
    /// Cria o store sobre um diretorio (criado se necessario).
    pub fn open(dir: impl Into<PathBuf>) -> CoreResult<Self> {
        let dir = dir.into();
        std::fs::create_dir_all(&dir)?;
        Ok(Self { dir, key: None })
    }

    /// Diretorio raiz do store.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// Indica se a chave esta carregada.
    pub fn is_unlocked(&self) -> bool {
        self.key.is_some()
    }

    fn salt_path(&self) -> PathBuf {
        self.dir.join(SALT_FILE)
    }

    fn load_or_create_salt(&self) -> CoreResult<[u8; SALT_LEN]> {
        let path = self.salt_path();
        if path.is_file() {
            let raw = std::fs::read(&path)?;
            if raw.len() != SALT_LEN {
                return Err(CoreError::Vault("salt do store corrompido".into()));
            }
            let mut salt = [0u8; SALT_LEN];
            salt.copy_from_slice(&raw);
            return Ok(salt);
        }
        let mut salt = [0u8; SALT_LEN];
        OsRng.fill_bytes(&mut salt);
        secure_write(&path, &salt)?;
        Ok(salt)
    }

    /// Deriva a chave do store a partir da senha mestra.
    pub fn unlock(&mut self, password: &str) -> CoreResult<()> {
        let salt = self.load_or_create_salt()?;
        let key = MasterKey::derive(password, &salt, 64 * 1024, 3, 4)?;
        self.key = Some(key);
        Ok(())
    }

    /// Descarta a chave da memoria.
    pub fn lock(&mut self) {
        self.key = None;
    }

    fn require_key(&self) -> CoreResult<&MasterKey> {
        self.key.as_ref().ok_or(CoreError::VaultLocked)
    }

    fn record_path(&self, id: &str) -> CoreResult<PathBuf> {
        let safe: String = id
            .chars()
            .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.' { c } else { '_' })
            .collect();
        if safe.is_empty() || safe.contains("..") {
            return Err(CoreError::Vault(format!("identificador invalido: {id}")));
        }
        Ok(self.dir.join(format!("{safe}.{RECORD_EXT}")))
    }

    fn aad(id: &str) -> Vec<u8> {
        let mut aad = Vec::with_capacity(11 + id.len());
        aad.extend_from_slice(b"mark-store:");
        aad.extend_from_slice(id.as_bytes());
        aad
    }

    /// Cifra e grava bytes sob um identificador.
    pub fn put_bytes(&self, id: &str, plaintext: &[u8]) -> CoreResult<()> {
        let key = self.require_key()?;
        let rec = EncryptedRecord::seal(key, &Self::aad(id), plaintext)?;
        let path = self.record_path(id)?;
        secure_write(&path, &rec.to_bytes())?;
        Ok(())
    }

    /// Le e decifra bytes de um identificador.
    pub fn get_bytes(&self, id: &str) -> CoreResult<Vec<u8>> {
        let key = self.require_key()?;
        let path = self.record_path(id)?;
        let raw = std::fs::read(&path)
            .map_err(|_| CoreError::NotFound(format!("registro ausente: {id}")))?;
        let rec = EncryptedRecord::from_bytes(&raw)?;
        rec.open(key, &Self::aad(id))
    }

    /// Cifra e grava um valor serializavel em JSON.
    pub fn put_json<T: Serialize>(&self, id: &str, value: &T) -> CoreResult<()> {
        let mut json = serde_json::to_vec(value)?;
        let res = self.put_bytes(id, &json);
        json.zeroize();
        res
    }

    /// Le e desserializa um valor JSON.
    pub fn get_json<T: DeserializeOwned>(&self, id: &str) -> CoreResult<T> {
        let mut raw = self.get_bytes(id)?;
        let value = serde_json::from_slice(&raw).map_err(CoreError::from);
        raw.zeroize();
        value
    }

    /// Anexa uma linha a um registro de conversa (le, decifra, adiciona, cifra).
    pub fn append_line(&self, id: &str, line: &str) -> CoreResult<()> {
        let mut buf = if self.record_path(id)?.is_file() {
            self.get_bytes(id)?
        } else {
            Vec::new()
        };
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
        let res = self.put_bytes(id, &buf);
        buf.zeroize();
        res
    }

    /// Le as linhas decifradas de um registro.
    pub fn read_lines(&self, id: &str) -> CoreResult<Vec<String>> {
        let mut raw = self.get_bytes(id)?;
        let text = String::from_utf8(raw.clone())
            .map_err(|_| CoreError::Vault("registro nao e UTF-8".into()));
        raw.zeroize();
        Ok(text?
            .lines()
            .map(|l| l.to_string())
            .filter(|l| !l.is_empty())
            .collect())
    }

    /// Lista os identificadores existentes.
    pub fn list(&self) -> CoreResult<Vec<String>> {
        let mut out = Vec::new();
        for entry in std::fs::read_dir(&self.dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some(RECORD_EXT) {
                continue;
            }
            if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                out.push(stem.to_string());
            }
        }
        out.sort();
        Ok(out)
    }

    /// Remove um registro.
    pub fn remove(&self, id: &str) -> CoreResult<bool> {
        let path = self.record_path(id)?;
        if path.is_file() {
            std::fs::remove_file(path)?;
            return Ok(true);
        }
        Ok(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> (tempfile::TempDir, EncryptedStore) {
        let tmp = tempfile::tempdir().unwrap();
        let mut s = EncryptedStore::open(tmp.path().join("store")).unwrap();
        s.unlock("senha-forte").unwrap();
        (tmp, s)
    }

    #[test]
    fn roundtrip_json_and_lines() {
        let (_tmp, s) = store();
        s.put_json("conv/2026-01", &vec!["ola", "mundo"]).unwrap();
        let back: Vec<String> = s.get_json("conv/2026-01").unwrap();
        assert_eq!(back, vec!["ola".to_string(), "mundo".to_string()]);

        s.append_line("mem-1", r#"{"k":"fato","v":"rust"}"#).unwrap();
        s.append_line("mem-1", r#"{"k":"fato2","v":"svid"}"#).unwrap();
        let lines = s.read_lines("mem-1").unwrap();
        assert_eq!(lines.len(), 2);
        assert!(lines[1].contains("svid"));
        assert_eq!(s.list().unwrap().len(), 2);
        assert!(s.remove("mem-1").unwrap());
        assert!(!s.remove("mem-1").unwrap());
    }

    #[test]
    fn disk_contains_no_plaintext() {
        let (tmp, s) = store();
        let secret = "sk-segredo-absoluto-123";
        s.put_bytes("api/openai", secret.as_bytes()).unwrap();
        let mut found = false;
        for entry in walkdir::WalkDir::new(tmp.path()) {
            let entry = entry.unwrap();
            if !entry.file_type().is_file() {
                continue;
            }
            let raw = std::fs::read(entry.path()).unwrap();
            if raw.windows(secret.len()).any(|w| w == secret.as_bytes()) {
                found = true;
            }
        }
        assert!(!found, "texto puro encontrado em disco");
    }

    #[test]
    fn locked_store_refuses_all_io() {
        let tmp = tempfile::tempdir().unwrap();
        let mut s = EncryptedStore::open(tmp.path().join("store")).unwrap();
        assert!(s.put_bytes("x", b"dado").is_err());
        assert!(s.get_bytes("x").is_err());
        s.unlock("p").unwrap();
        s.put_bytes("x", b"dado").unwrap();
        s.lock();
        assert!(s.get_bytes("x").is_err());
        assert!(s.append_line("x", "linha").is_err());
    }

    #[test]
    fn wrong_password_cannot_decrypt() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("store");
        let mut s = EncryptedStore::open(&dir).unwrap();
        s.unlock("certa").unwrap();
        s.put_bytes("k", b"segredo").unwrap();
        s.lock();
        let mut s2 = EncryptedStore::open(&dir).unwrap();
        s2.unlock("errada").unwrap();
        assert!(s2.get_bytes("k").is_err());
    }

    #[test]
    fn tampered_record_is_detected() {
        let (tmp, s) = store();
        s.put_bytes("k", b"segredo-sensivel").unwrap();
        let path = tmp.path().join("store").join("k.mrec");
        let mut raw = std::fs::read(&path).unwrap();
        let last = raw.len() - 1;
        raw[last] ^= 0x01;
        std::fs::write(&path, raw).unwrap();
        assert!(s.get_bytes("k").is_err());
    }

    #[test]
    fn rejects_path_traversal_ids() {
        let (_tmp, s) = store();
        assert!(s.put_bytes("../escape", b"x").is_err() || s.record_path("../escape").is_err());
        assert!(s.record_path("a/b/../../x").is_err());
    }
}
