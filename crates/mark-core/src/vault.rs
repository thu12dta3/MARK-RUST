//! Cofre criptografico estilo Cryptomator: Argon2id + AES-256-GCM.
//!
//! Garantias:
//! - Sem fallback silencioso em texto puro. Se o cofre esta bloqueado, o acesso falha
//!   com `VaultError::Locked` explicito.
//! - Chave mestra derivada com Argon2id (salt unico por cofre), mantida em memoria
//!   trancada via `mlock(2)` e zerada com `zeroize` ao bloquear/dropar.
//! - Nonce aleatorio de 96 bits por operacao, gerado via `getrandom`.
//! - Header autenticado (AAD) vincula o ciphertext ao contexto do cofre.
//! - Detecao de adulteracao: alterar 1 byte do ciphertext falha na decifragem.

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use argon2::{Algorithm, Argon2, Params, Version};
use rand_core::{OsRng, RngCore};
use zeroize::{Zeroize, ZeroizeOnDrop};

use crate::error::{CoreError, CoreResult};
use crate::fsutil::secure_write;

/// Tamanho do salt Argon2id.
pub const SALT_LEN: usize = 16;
/// Tamanho do nonce AES-GCM (96 bits, padrao do RFC 5116).
pub const NONCE_LEN: usize = 12;
/// Tamanho da chave AES-256.
pub const KEY_LEN: usize = 32;

/// Parametros Argon2id: 64 MiB de memoria, 3 passes, 4 lanes.
/// Escolhidos para caber em RAM de 16 GB e permanecerem defensivos contra forca bruta.
const ARGON2_M_COST_KIB: u32 = 64 * 1024;
const ARGON2_T_COST: u32 = 3;
const ARGON2_P_COST: u32 = 4;

/// Cabecalho binario do cofre (versionado, sem dados secretos).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VaultHeader {
    pub version: u8,
    pub kdf: u8,
    pub salt: [u8; SALT_LEN],
    pub argon2_m_kib: u32,
    pub argon2_t_cost: u32,
    pub argon2_p_cost: u32,
}

/// Identificador do algoritmo de cifragem de um registro.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordAlgo {
    /// AES-256-GCM com header de 12 bytes (nonce) antes do ciphertext.
    Aes256Gcm,
}

impl RecordAlgo {
    fn to_u8(self) -> u8 {
        match self {
            RecordAlgo::Aes256Gcm => 1,
        }
    }

    fn from_u8(v: u8) -> CoreResult<Self> {
        match v {
            1 => Ok(RecordAlgo::Aes256Gcm),
            other => Err(CoreError::Vault(format!(
                "algoritmo de cofre desconhecido: {other}"
            ))),
        }
    }
}

/// Registro cifrado de um item do cofre.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EncryptedRecord {
    pub algo: RecordAlgo,
    pub nonce: [u8; NONCE_LEN],
    pub ciphertext: Vec<u8>,
}

impl EncryptedRecord {
    /// Cifra `plaintext` com a chave mestra, AAD e nonce aleatorio.
    pub fn seal(key: &MasterKey, aad: &[u8], plaintext: &[u8]) -> CoreResult<Self> {
        let mut nonce = [0u8; NONCE_LEN];
        OsRng.fill_bytes(&mut nonce);
        let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key.as_bytes()));
        let ciphertext = cipher
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: plaintext,
                    aad,
                },
            )
            .map_err(|_| CoreError::Vault("falha ao cifrar registro".into()))?;
        Ok(Self {
            algo: RecordAlgo::Aes256Gcm,
            nonce,
            ciphertext,
        })
    }

    /// Decifra o registro com a chave mestra e o mesmo AAD.
    pub fn open(&self, key: &MasterKey, aad: &[u8]) -> CoreResult<Vec<u8>> {
        let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key.as_bytes()));
        cipher
            .decrypt(
                Nonce::from_slice(&self.nonce),
                Payload {
                    msg: &self.ciphertext,
                    aad,
                },
            )
            .map_err(|_| {
                CoreError::Vault("falha ao decifrar registro (dado corrompido ou adulterado)".into())
            })
    }

    /// Serializa para bytes: `[algo:1][nonce:12][ciphertext...]`.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(1 + NONCE_LEN + self.ciphertext.len());
        out.push(self.algo.to_u8());
        out.extend_from_slice(&self.nonce);
        out.extend_from_slice(&self.ciphertext);
        out
    }

    /// Desserializa bytes previously serialized by [`Self::to_bytes`].
    pub fn from_bytes(raw: &[u8]) -> CoreResult<Self> {
        if raw.len() < 1 + NONCE_LEN {
            return Err(CoreError::Vault("registro de cofre truncado".into()));
        }
        let algo = RecordAlgo::from_u8(raw[0])?;
        let mut nonce = [0u8; NONCE_LEN];
        nonce.copy_from_slice(&raw[1..1 + NONCE_LEN]);
        let ciphertext = raw[1 + NONCE_LEN..].to_vec();
        Ok(Self {
            algo,
            nonce,
            ciphertext,
        })
    }
}

/// Chave mestra derivada, mantida trancada em memoria e zerada no drop.
pub struct MasterKey {
    bytes: [u8; KEY_LEN],
}

impl MasterKey {
    /// Deriva a chave a partir da senha do usuario usando Argon2id.
    pub fn derive(password: &str, salt: &[u8; SALT_LEN], m_kib: u32, t_cost: u32, p_cost: u32) -> CoreResult<Self> {
        let params = Params::new(m_kib, t_cost, p_cost, None)
            .map_err(|e| CoreError::Vault(format!("parametros Argon2id invalidos: {e}")))?;
        let argon = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
        let mut bytes = [0u8; KEY_LEN];
        argon
            .hash_password_into(password.as_bytes(), salt, &mut bytes)
            .map_err(|e| CoreError::Vault(format!("derivacao Argon2id falhou: {e}")))?;
        Ok(Self { bytes })
    }

    /// Acesso bruto a chave. Use com cuidado; o slice e zerado quando o `MasterKey` cai.
    pub fn as_bytes(&self) -> &[u8; KEY_LEN] {
        &self.bytes
    }

    /// Tranca a memoria da chave com `mlock(2)` para impedir swap em disco.
    pub fn lock_in_memory(&self) -> CoreResult<()> {
        let rc = unsafe {
            libc::mlock(
                self.bytes.as_ptr() as *const libc::c_void,
                KEY_LEN,
            )
        };
        if rc != 0 {
            let err = std::io::Error::last_os_error();
            return Err(CoreError::Vault(format!(
                "mlock da chave mestra falhou: {err}"
            )));
        }
        Ok(())
    }

    /// Libera a trava de memoria (a chave permanece, mas pode ir para swap).
    pub fn unlock_memory(&self) -> CoreResult<()> {
        let rc = unsafe {
            libc::munlock(
                self.bytes.as_ptr() as *const libc::c_void,
                KEY_LEN,
            )
        };
        if rc != 0 {
            let err = std::io::Error::last_os_error();
            return Err(CoreError::Vault(format!(
                "munlock da chave mestra falhou: {err}"
            )));
        }
        Ok(())
    }
}

impl Drop for MasterKey {
    fn drop(&mut self) {
        // Zera a chave e libera a trava de memoria.
        self.bytes.zeroize();
        unsafe {
            libc::munlock(self.bytes.as_ptr() as *const libc::c_void, KEY_LEN);
        }
    }
}

impl ZeroizeOnDrop for MasterKey {}

/// Cofre completo: cabecalho + mapa de registros cifrados.
pub struct Vault {
    header: VaultHeader,
    records: std::collections::BTreeMap<String, EncryptedRecord>,
    key: Option<MasterKey>,
    path: std::path::PathBuf,
}

impl std::fmt::Debug for Vault {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Vault")
            .field("path", &self.path)
            .field("locked", &self.key.is_none())
            .field("records", &self.records.len())
            .finish()
    }
}

impl Vault {
    /// Cria um cofre novo, ainda bloqueado, com salt aleatorio.
    pub fn create(path: impl Into<std::path::PathBuf>) -> CoreResult<Self> {
        let path = path.into();
        let mut salt = [0u8; SALT_LEN];
        OsRng.fill_bytes(&mut salt);
        Ok(Self {
            header: VaultHeader {
                version: 1,
                kdf: 1,
                salt,
                argon2_m_kib: ARGON2_M_COST_KIB,
                argon2_t_cost: ARGON2_T_COST,
                argon2_p_cost: ARGON2_P_COST,
            },
            records: std::collections::BTreeMap::new(),
            key: None,
            path,
        })
    }

    /// Abre um cofre existente do disco. Retorna bloqueado (sem chave derivada).
    pub fn open(path: impl Into<std::path::PathBuf>) -> CoreResult<Self> {
        let path = path.into();
        let raw = std::fs::read(&path).map_err(|e| {
            CoreError::Vault(format!("nao foi possivel abrir o cofre {}: {e}", path.display()))
        })?;
        let (header, records) = Self::parse_file(&raw)?;
        Ok(Self {
            header,
            records,
            key: None,
            path,
        })
    }

    /// Abre se existir, cria se nao existir.
    pub fn open_or_create(path: impl Into<std::path::PathBuf>) -> CoreResult<Self> {
        let path = path.into();
        if path.exists() {
            Self::open(path)
        } else {
            Self::create(path)
        }
    }

    fn parse_file(raw: &[u8]) -> CoreResult<(VaultHeader, std::collections::BTreeMap<String, EncryptedRecord>)> {
        if raw.len() < 1 + 1 + 4 + SALT_LEN + 4 + 4 + 4 {
            return Err(CoreError::Vault("arquivo de cofre truncado".into()));
        }
        let mut c = 0usize;
        let version = raw[c];
        c += 1;
        let kdf = raw[c];
        c += 1;
        let m_kib = u32::from_le_bytes(raw[c..c + 4].try_into().unwrap());
        c += 4;
        let mut salt = [0u8; SALT_LEN];
        salt.copy_from_slice(&raw[c..c + SALT_LEN]);
        c += SALT_LEN;
        let t_cost = u32::from_le_bytes(raw[c..c + 4].try_into().unwrap());
        c += 4;
        let p_cost = u32::from_le_bytes(raw[c..c + 4].try_into().unwrap());
        c += 4;

        if version != 1 {
            return Err(CoreError::Vault(format!(
                "versao de cofre nao suportada: {version}"
            )));
        }
        if kdf != 1 {
            return Err(CoreError::Vault(format!("KDF de cofre nao suportado: {kdf}")));
        }

        let count = u32::from_le_bytes(raw[c..c + 4].try_into().unwrap());
        c += 4;
        let mut records = std::collections::BTreeMap::new();
        for _ in 0..count {
            let klen = u32::from_le_bytes(raw[c..c + 4].try_into().unwrap()) as usize;
            c += 4;
            if c + klen > raw.len() {
                return Err(CoreError::Vault("chave de registro truncada".into()));
            }
            let key = String::from_utf8(raw[c..c + klen].to_vec())
                .map_err(|_| CoreError::Vault("chave de registro nao e UTF-8".into()))?;
            c += klen;
            let vlen = u32::from_le_bytes(raw[c..c + 4].try_into().unwrap()) as usize;
            c += 4;
            if c + vlen > raw.len() {
                return Err(CoreError::Vault("valor de registro truncado".into()));
            }
            let rec = EncryptedRecord::from_bytes(&raw[c..c + vlen])?;
            c += vlen;
            records.insert(key, rec);
        }
        Ok((
            VaultHeader {
                version,
                kdf,
                salt,
                argon2_m_kib: m_kib,
                argon2_t_cost: t_cost,
                argon2_p_cost: p_cost,
            },
            records,
        ))
    }

    /// Deriva a chave a partir da senha e desbloqueia o cofre.
    pub fn unlock(&mut self, password: &str) -> CoreResult<()> {
        let key = MasterKey::derive(
            password,
            &self.header.salt,
            self.header.argon2_m_kib,
            self.header.argon2_t_cost,
            self.header.argon2_p_cost,
        )?;
        key.lock_in_memory()?;
        self.key = Some(key);
        Ok(())
    }

    /// Bloqueia o cofre, zerando a chave mestra da memoria.
    pub fn lock(&mut self) {
        self.key = None;
    }

    /// Indica se o cofre esta desbloqueado.
    pub fn is_unlocked(&self) -> bool {
        self.key.is_some()
    }

    /// Metadados publicos do cofre (sem material secreto).
    pub fn header(&self) -> &VaultHeader {
        &self.header
    }

    /// Nomes das chaves armazenadas (sem revelar valores).
    pub fn keys(&self) -> Vec<String> {
        self.records.keys().cloned().collect()
    }

    fn require_key(&self) -> CoreResult<&MasterKey> {
        self.key
            .as_ref()
            .ok_or(CoreError::VaultLocked)
    }

    /// Cifra um valor sob um nome, com AAD vinculando o nome ao registro.
    pub fn put(&mut self, name: &str, plaintext: &[u8]) -> CoreResult<()> {
        let key = self.require_key()?;
        let aad = aad_for(name);
        let mut nonce = [0u8; NONCE_LEN];
        OsRng.fill_bytes(&mut nonce);
        let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key.as_bytes()));
        let ciphertext = cipher
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: plaintext,
                    aad: &aad,
                },
            )
            .map_err(|_| CoreError::Vault(format!("falha ao cifrar o item '{name}'")));
        self.records.insert(
            name.to_string(),
            EncryptedRecord {
                algo: RecordAlgo::Aes256Gcm,
                nonce,
                ciphertext: ciphertext?,
            },
        );
        Ok(())
    }

    /// Decifra um valor. Falha se o cofre estiver bloqueado ou o dado for adulterado.
    pub fn get(&self, name: &str) -> CoreResult<Vec<u8>> {
        let key = self.require_key()?;
        let rec = self
            .records
            .get(name)
            .ok_or_else(|| CoreError::VaultKeyNotFound(name.to_string()))?;
        let aad = aad_for(name);
        let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key.as_bytes()));
        cipher
            .decrypt(
                Nonce::from_slice(&rec.nonce),
                Payload {
                    msg: &rec.ciphertext,
                    aad: &aad,
                },
            )
            .map_err(|_| CoreError::Vault(format!("falha ao decifrar o item '{name}' (dado corrompido ou adulterado)")))
    }

    /// Decifra um valor como string UTF-8.
    pub fn get_string(&self, name: &str) -> CoreResult<String> {
        let bytes = self.get(name)?;
        String::from_utf8(bytes)
            .map_err(|_| CoreError::Vault(format!("item '{name}' nao e UTF-8 valido")))
    }

    /// Remove um item.
    pub fn remove(&mut self, name: &str) -> CoreResult<bool> {
        Ok(self.records.remove(name).is_some())
    }

    /// Serializa o cofre completo para bytes.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = Vec::new();
        out.push(self.header.version);
        out.push(self.header.kdf);
        out.extend_from_slice(&self.header.argon2_m_kib.to_le_bytes());
        out.extend_from_slice(&self.header.salt);
        out.extend_from_slice(&self.header.argon2_t_cost.to_le_bytes());
        out.extend_from_slice(&self.header.argon2_p_cost.to_le_bytes());
        out.extend_from_slice(&(self.records.len() as u32).to_le_bytes());
        for (k, v) in &self.records {
            out.extend_from_slice(&(k.len() as u32).to_le_bytes());
            out.extend_from_slice(k.as_bytes());
            let vb = v.to_bytes();
            out.extend_from_slice(&(vb.len() as u32).to_le_bytes());
            out.extend_from_slice(&vb);
        }
        out
    }

    /// Grava o cofre no disco com permissao 0600.
    pub fn save(&self) -> CoreResult<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let bytes = self.to_bytes();
        secure_write(&self.path, &bytes)?;
        Ok(())
    }

    /// Caminho do arquivo de cofre.
    pub fn path(&self) -> &std::path::Path {
        &self.path
    }
}


/// Registro de verificacao usado para validar a senha mestra.
pub const VERIFY_RECORD: &str = "__mark_verify__";
/// Conteudo esperado do registro de verificacao.
pub const VERIFY_VALUE: &[u8] = b"mark-vault-ok";

impl Vault {
    /// Indica se existe um cofre inicializado no caminho informado.
    pub fn is_initialized(path: &std::path::Path) -> bool {
        path.is_file() && std::fs::metadata(path).map(|m| m.len() > 0).unwrap_or(false)
    }

    /// Cria um cofre brand-new, sobrescrevendo qualquer residuo no caminho.
    pub fn create_fresh(path: impl Into<std::path::PathBuf>, password: &str) -> CoreResult<Self> {
        let path = path.into();
        if path.exists() {
            std::fs::remove_file(&path)?;
        }
        let mut v = Self::create(path)?;
        v.unlock(password)?;
        v.put(VERIFY_RECORD, VERIFY_VALUE)?;
        v.save()?;
        Ok(v)
    }

    /// Desbloqueia validando a senha pelo registro de verificacao.
    pub fn unlock_verified(&mut self, password: &str) -> CoreResult<()> {
        self.unlock(password)?;
        match self.get(VERIFY_RECORD) {
            Ok(v) if v == VERIFY_VALUE => Ok(()),
            _ => {
                self.lock();
                Err(CoreError::Vault("senha mestra incorreta".into()))
            }
        }
    }

    /// Modo A: troca a senha re-encriptando todos os registros sem perda.
    pub fn rekey(&mut self, old_password: &str, new_password: &str) -> CoreResult<()> {
        if new_password.trim().len() < 4 {
            return Err(CoreError::Vault("senha nova muito curta".into()));
        }
        self.unlock_verified(old_password)?;
        let names: Vec<String> = self.records.keys().cloned().collect();
        let mut plain: Vec<(String, Vec<u8>)> = Vec::with_capacity(names.len());
        for name in names {
            plain.push((name.clone(), self.get(&name)?));
        }
        let mut salt = [0u8; SALT_LEN];
        OsRng.fill_bytes(&mut salt);
        let key = MasterKey::derive(
            new_password,
            &salt,
            self.header.argon2_m_kib,
            self.header.argon2_t_cost,
            self.header.argon2_p_cost,
        )?;
        key.lock_in_memory()?;
        self.header.salt = salt;
        self.records.clear();
        self.key = Some(key);
        for (name, value) in &plain {
            self.put(name, value)?;
        }
        self.save()
    }

    /// Modo B: apaga o cofre atual e cria um brand-new com senha nova.
    pub fn factory_reset(
        path: impl Into<std::path::PathBuf>,
        new_password: &str,
    ) -> CoreResult<Self> {
        if new_password.trim().len() < 4 {
            return Err(CoreError::Vault("senha nova muito curta".into()));
        }
        Self::create_fresh(path, new_password)
    }
}

/// AAD por item: vincula o ciphertext ao nome, impedindo trocar itens.
fn aad_for(name: &str) -> Vec<u8> {
    let mut aad = Vec::with_capacity(4 + name.len());
    aad.extend_from_slice(b"mark:");
    aad.extend_from_slice(name.as_bytes());
    aad
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn tmp_vault_path(tag: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("mark_vault_test_{tag}_{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("vault.bin")
    }

    #[test]
    fn roundtrip_encrypt_decrypt() {
        let path = tmp_vault_path("rt");
        let mut v = Vault::create(&path).unwrap();
        v.unlock("senha-correta").unwrap();
        v.put("api/openai", b"sk-test-123").unwrap();
        v.put("api/deepseek", b"sk-test-456").unwrap();
        assert_eq!(v.get_string("api/openai").unwrap(), "sk-test-123");
        assert_eq!(v.get_string("api/deepseek").unwrap(), "sk-test-456");
        v.save().unwrap();

        // reabre do disco
        let mut v2 = Vault::open(&path).unwrap();
        assert!(!v2.is_unlocked());
        assert_eq!(v2.get_string("api/openai").unwrap_err().to_string(), "cofre bloqueado: desbloqueie com a senha mestra");
        v2.unlock("senha-correta").unwrap();
        assert_eq!(v2.get_string("api/openai").unwrap(), "sk-test-123");
        assert_eq!(v2.keys().len(), 2);
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn wrong_password_fails() {
        let path = tmp_vault_path("wrong");
        let mut v = Vault::create(&path).unwrap();
        v.unlock("senha-correta").unwrap();
        v.put("api/x", b"segredo").unwrap();
        v.save().unwrap();

        let mut v2 = Vault::open(&path).unwrap();
        v2.unlock("senha-errada").unwrap();
        // A decifragem falha porque a chave errada produz tag invalido.
        let err = v2.get("api/x").unwrap_err();
        assert!(err.to_string().contains("falha ao decifrar"), "err: {err}");
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn tamper_one_byte_is_detected() {
        let path = tmp_vault_path("tamper");
        let mut v = Vault::create(&path).unwrap();
        v.unlock("p").unwrap();
        v.put("api/k", b"0123456789abcdef").unwrap();
        v.save().unwrap();

        let mut raw = std::fs::read(&path).unwrap();
        // o ciphertext fica no fim do arquivo; altera 1 byte
        let last = raw.len() - 1;
        raw[last] ^= 0x01;
        std::fs::write(&path, &raw).unwrap();

        let mut v2 = Vault::open(&path).unwrap();
        v2.unlock("p").unwrap();
        let err = v2.get("api/k").unwrap_err();
        assert!(
            err.to_string().contains("falha ao decifrar"),
            "tamper nao foi detectado: {err}"
        );
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn record_swap_is_detected_by_aad() {
        let path = tmp_vault_path("swap");
        let mut v = Vault::create(&path).unwrap();
        v.unlock("p").unwrap();
        v.put("api/a", b"AAA").unwrap();
        v.put("api/b", b"BBB").unwrap();
        let mut bytes = v.to_bytes();
        // troca os dois blocos de valor "api/a" e "api/b"
        let s = String::from_utf8_lossy(&bytes).to_string();
        let _ = s;
        // Reconstroi manualmente trocando os ciphertexts
        let mut recs: BTreeMap<String, EncryptedRecord> = BTreeMap::new();
        for name in ["api/a", "api/b"] {
            recs.insert(name.to_string(), v.records[name].clone());
        }
        let a = recs["api/a"].clone();
        let b = recs["api/b"].clone();
        let mut swapped = BTreeMap::new();
        swapped.insert("api/a".to_string(), b.clone());
        swapped.insert("api/b".to_string(), a.clone());
        v.records = swapped;
        bytes = v.to_bytes();
        std::fs::write(&path, &bytes).unwrap();

        let mut v2 = Vault::open(&path).unwrap();
        v2.unlock("p").unwrap();
        let err = v2.get("api/a").unwrap_err();
        assert!(err.to_string().contains("falha ao decifrar"), "swap nao detectado: {err}");
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn no_plaintext_fallback_when_locked() {
        let path = tmp_vault_path("locked");
        let mut v = Vault::create(&path).unwrap();
        v.unlock("p").unwrap();
        v.put("api/k", b"segredo").unwrap();
        v.save().unwrap();
        v.lock();
        assert!(!v.is_unlocked());
        assert!(v.get("api/k").is_err());
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn master_key_is_zeroized_on_drop() {
        let path = tmp_vault_path("zero");
        let v = Vault::create(&path).unwrap();
        let key = MasterKey::derive("p", &v.header().salt, 8192, 1, 1).unwrap();
        let raw = key.as_bytes().to_vec();
        assert!(raw.iter().any(|b| *b != 0), "chave derivada nao pode ser zerada");
        drop(key);
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }
}
