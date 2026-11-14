//! Tipos de erro do nucleo do MARK.

use std::fmt;

pub type CoreResult<T> = Result<T, CoreError>;

#[derive(Debug)]
pub enum CoreError {
    /// Cofre bloqueado: operacao exige senha mestra.
    VaultLocked,
    /// Falha generica do cofre (corrupcao, KDF, permissao).
    Vault(String),
    /// Chave especifica nao existe no cofre.
    VaultKeyNotFound(String),
    /// Erro de IO.
    Io(std::io::Error),
    /// Erro de serializacao (JSON/TOML).
    Serde(String),
    /// Configuracao invalida.
    Config(String),
    /// Caminho ou recurso ausente.
    NotFound(String),
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CoreError::VaultLocked => {
                write!(f, "cofre bloqueado: desbloqueie com a senha mestra")
            }
            CoreError::Vault(m) => write!(f, "erro de cofre: {m}"),
            CoreError::VaultKeyNotFound(k) => write!(f, "chave ausente no cofre: {k}"),
            CoreError::Io(e) => write!(f, "erro de io: {e}"),
            CoreError::Serde(m) => write!(f, "erro de serializacao: {m}"),
            CoreError::Config(m) => write!(f, "configuracao invalida: {m}"),
            CoreError::NotFound(m) => write!(f, "nao encontrado: {m}"),
        }
    }
}

impl std::error::Error for CoreError {}

impl From<std::io::Error> for CoreError {
    fn from(e: std::io::Error) -> Self {
        CoreError::Io(e)
    }
}

impl From<serde_json::Error> for CoreError {
    fn from(e: serde_json::Error) -> Self {
        CoreError::Serde(e.to_string())
    }
}
