//! Nucleo do MARK Desktop: paths, cofre criptografico, configuracao e catalogo de modelos.
//!
//! Este crate nao depende da GUI e nao depende do motor de inferencia, o que
//! permite testar criptografia e config isoladamente.

pub mod config;
pub mod error;
pub mod fsutil;
pub mod models;
pub mod paths;
pub mod vault;

pub use config::{
    AppConfig, ApprovalMode, InferenceConfig, ReasoningLevel, Role, RoleConfig, SpeculativeDecoding,
};
pub use error::{CoreError, CoreResult};
pub use models::{Backend, FitLevel, HardwareProfile, ModelEntry};
pub use vault::{EncryptedRecord, MasterKey, Vault, VaultHeader};
