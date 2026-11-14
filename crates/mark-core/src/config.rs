//! Configuracao persistente do MARK Desktop (TOML).
//!
//! Regras:
//! - Nenhum controle de UI pode existir sem um campo correspondente aqui E
//!   um consumidor real no backend. Este modulo define o contrato.
//! - Teto de contexto e o teto REAL do motor carregado, nunca um valor generico.
//! - Sem caminho hardcoded: tudo vem de `crate::paths`.

use serde::{Deserialize, Serialize};

use crate::error::{CoreError, CoreResult};
use crate::fsutil::secure_write;
use crate::paths;

/// Nivel de raciocinio realmente aplicado ao motor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ReasoningLevel {
    Instant,
    Medium,
    High,
}

impl ReasoningLevel {
    /// Rotulo exibido na UI.
    pub fn label(self) -> &'static str {
        match self {
            ReasoningLevel::Instant => "Instantaneo",
            ReasoningLevel::Medium => "Medio",
            ReasoningLevel::High => "Profundo",
        }
    }

    /// Identificador estavel persistido.
    pub fn as_str(self) -> &'static str {
        match self {
            ReasoningLevel::Instant => "instant",
            ReasoningLevel::Medium => "medium",
            ReasoningLevel::High => "high",
        }
    }

    /// Numero de passes do motor 1-bit. Este valor e REALMENTE enviado ao backend.
    pub fn core_loops(self) -> u32 {
        match self {
            ReasoningLevel::Instant => 1,
            ReasoningLevel::Medium => 2,
            ReasoningLevel::High => 3,
        }
    }

    /// Converte a partir do texto persistido, com fallback seguro.
    pub fn from_str_lossy(s: &str) -> Self {
        match s.trim().to_ascii_lowercase().as_str() {
            "instant" | "instantaneo" | "rapido" | "low" => ReasoningLevel::Instant,
            "high" | "profundo" | "deep" => ReasoningLevel::High,
            _ => ReasoningLevel::Medium,
        }
    }
}

/// Papel do agente. Cada papel aponta para um modelo real.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    General,
    Engineer,
    Professor,
    Vision,
}

impl Role {
    /// Todos os papeis suportados.
    pub const ALL: [Role; 4] = [Role::General, Role::Engineer, Role::Professor, Role::Vision];

    /// Identificador estavel persistido.
    pub fn as_str(self) -> &'static str {
        match self {
            Role::General => "general",
            Role::Engineer => "engineer",
            Role::Professor => "professor",
            Role::Vision => "vision",
        }
    }

    /// Rotulo exibido na UI.
    pub fn label(self) -> &'static str {
        match self {
            Role::General => "Geral",
            Role::Engineer => "Engenheiro",
            Role::Professor => "Professor",
            Role::Vision => "Vision",
        }
    }

    /// Converte a partir do texto persistido.
    pub fn from_str_lossy(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "general" | "geral" => Some(Role::General),
            "engineer" | "engenheiro" => Some(Role::Engineer),
            "professor" => Some(Role::Professor),
            "vision" | "multimodal" => Some(Role::Vision),
            _ => None,
        }
    }
}

/// Politica de seguranca do Modo Engineer (espelha o codex).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ApprovalMode {
    /// Sugere mudancas; nunca executa comando.
    Suggest,
    /// Edita arquivos automaticamente; comandos de shell exigem aprovacao.
    AutoEdit,
    /// Executa tudo dentro do sandbox bwrap.
    FullAuto,
}

impl ApprovalMode {
    /// Rotulo exibido na UI.
    pub fn label(self) -> &'static str {
        match self {
            ApprovalMode::Suggest => "Sugestao",
            ApprovalMode::AutoEdit => "Auto-Edit",
            ApprovalMode::FullAuto => "Full-Auto",
        }
    }

    /// Descricao curta do que este modo permite.
    pub fn description(self) -> &'static str {
        match self {
            ApprovalMode::Suggest => "Sugere edicoes e comandos; nada e executado",
            ApprovalMode::AutoEdit => "Edita arquivos; comandos de shell pedem aprovacao",
            ApprovalMode::FullAuto => "Executa tudo isolado em sandbox bwrap",
        }
    }
}

/// Configuracao de inferencia local.
///
/// Cada campo aqui TEM consumidor no motor. Campos sem consumidor nao existem.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InferenceConfig {
    /// Janela de contexto em tokens. teto definido pelo modelo carregado.
    pub num_ctx: u32,
    /// Camadas descarregadas para a GPU.
    pub num_gpu: u32,
    /// Threads do pool de CPU.
    pub num_thread: u32,
    /// Tamanho do lote de avaliacao.
    pub num_batch: u32,
    /// Tamanho do lote fisico (ubatch).
    pub physical_batch_size: u32,
    /// Numero maximo de previsoes concorrentes.
    pub max_concurrent_predictions: u32,
    /// Mantem o modelo residente em memoria entre requisicoes.
    pub keep_model_in_memory: bool,
    /// Usa mapeamento de memoria para os pesos.
    pub use_mmap: bool,
    /// Descarrega o cache KV para a memoria da GPU.
    pub offload_kv_cache: bool,
    /// Ativa Flash Attention quando o backend suportar.
    pub flash_attn: bool,
    /// Semente deterministica; `None` = semente aleatoria do motor.
    pub seed: Option<u64>,
    /// Frequencia base do RoPE; `None` = valor do modelo.
    pub rope_freq_base: Option<f64>,
    /// Escala de frequencia do RoPE; `None` = valor do modelo.
    pub rope_freq_scale: Option<f64>,
    /// Modo de decodificacao especulativa.
    pub speculative_decoding: SpeculativeDecoding,
    /// Template de chat a forcar; `None` = template do tokenizador.
    pub chat_template: Option<String>,
    /// Mensagem de orcamento de raciocinio anexada ao system prompt.
    pub reasoning_budget_message: String,
}

impl Default for InferenceConfig {
    fn default() -> Self {
        Self {
            num_ctx: 32768,
            num_gpu: 16,
            num_thread: 4,
            num_batch: 2048,
            physical_batch_size: 512,
            max_concurrent_predictions: 1,
            keep_model_in_memory: true,
            use_mmap: true,
            offload_kv_cache: true,
            flash_attn: true,
            seed: None,
            rope_freq_base: None,
            rope_freq_scale: None,
            speculative_decoding: SpeculativeDecoding::Off,
            chat_template: None,
            reasoning_budget_message: String::new(),
        }
    }
}

/// Modos de decodificacao especulativa suportados de fato pelo motor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum SpeculativeDecoding {
    Off,
    /// Rascunho local barato seguido de verificacao.
    DraftModel,
    /// Reutilizacao do contexto como rascunho (ngram/lookup).
    PromptLookup,
}

impl SpeculativeDecoding {
    /// Rotulo exibido na UI.
    pub fn label(self) -> &'static str {
        match self {
            SpeculativeDecoding::Off => "Desligado",
            SpeculativeDecoding::DraftModel => "Modelo Rascunho",
            SpeculativeDecoding::PromptLookup => "Prompt Lookup",
        }
    }

    /// Todos os modos, na ordem exibida.
    pub const ALL: [SpeculativeDecoding; 3] = [
        SpeculativeDecoding::Off,
        SpeculativeDecoding::DraftModel,
        SpeculativeDecoding::PromptLookup,
    ];
}

/// Configuracao de um papel (modelo primario e fallback).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoleConfig {
    pub primary_model: String,
    pub secondary_model: String,
}

impl Default for RoleConfig {
    fn default() -> Self {
        Self {
            primary_model: String::new(),
            secondary_model: String::new(),
        }
    }
}

/// Configuracao de um provedor de API (chave vive no cofre, nao aqui).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderConfig {
    pub enabled: bool,
    pub base_url: String,
    /// Nome da chave no cofre.
    pub vault_key: String,
}

impl ProviderConfig {
    /// Provedores de nuvem suportados, com chave de cofre correspondente.
    pub fn presets() -> Vec<(&'static str, &'static str, &'static str)> {
        vec![
            ("openai", "https://api.openai.com/v1", "api/openai"),
            ("anthropic", "https://api.anthropic.com/v1", "api/anthropic"),
            ("deepseek", "https://api.deepseek.com/v1", "api/deepseek"),
            ("gemini", "https://generativelanguage.googleapis.com/v1beta", "api/gemini"),
            ("groq", "https://api.groq.com/openai/v1", "api/groq"),
            ("openrouter", "https://openrouter.ai/api/v1", "api/openrouter"),
            ("mistral", "https://api.mistral.ai/v1", "api/mistral"),
            ("lmstudio", "http://127.0.0.1:1234/v1", ""),
            ("ollama", "http://127.0.0.1:11434", ""),
        ]
    }
}

/// Configuracao completa do aplicativo.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AppConfig {
    /// Versao do formato de config.
    pub version: u32,
    /// Inferencia local.
    #[serde(default)]
    pub inference: InferenceConfig,
    /// Nivel de raciocinio global.
    #[serde(default = "default_reasoning")]
    pub reasoning_level: ReasoningLevel,
    /// Mapa papel -> modelo.
    #[serde(default)]
    pub roles: std::collections::BTreeMap<String, RoleConfig>,
    /// Provedores de API habilitados.
    #[serde(default)]
    pub providers: std::collections::BTreeMap<String, ProviderConfig>,
    /// Diretorio raiz do Modo Engineer.
    #[serde(default)]
    pub workspace: String,
    /// Politica de seguranca do Modo Engineer.
    #[serde(default = "default_approval")]
    pub approval_mode: ApprovalMode,
    /// Timeout padrao de comandos do sandbox (segundos).
    #[serde(default = "default_sandbox_timeout")]
    pub sandbox_timeout_secs: u64,
    /// Permite rede dentro do sandbox.
    #[serde(default)]
    pub sandbox_share_net: bool,
    /// Permite escrita fora do workspace no modo Auto-Edit.
    #[serde(default)]
    pub allow_write_outside_workspace: bool,
    /// Modelo selecionado manualmente (sobrescreve o papel).
    #[serde(default)]
    pub selected_model: String,
    /// Servidor local exposto em /v1 (OpenAI-compatible).
    #[serde(default)]
    pub local_server_enabled: bool,
    #[serde(default = "default_local_server_port")]
    pub local_server_port: u16,
    /// Exibe o terminal do Modo Engineer.
    #[serde(default = "default_true")]
    pub show_engineer_terminal: bool,
}

fn default_reasoning() -> ReasoningLevel {
    ReasoningLevel::Medium
}
fn default_approval() -> ApprovalMode {
    ApprovalMode::Suggest
}
fn default_sandbox_timeout() -> u64 {
    120
}
fn default_local_server_port() -> u16 {
    1234
}
fn default_true() -> bool {
    true
}

impl Default for AppConfig {
    fn default() -> Self {
        let mut roles = std::collections::BTreeMap::new();
        for r in Role::ALL {
            roles.insert(
                r.as_str().to_string(),
                RoleConfig {
                    primary_model: String::new(),
                    secondary_model: String::new(),
                },
            );
        }
        let mut providers = std::collections::BTreeMap::new();
        for (name, url, vault_key) in ProviderConfig::presets() {
            providers.insert(
                name.to_string(),
                ProviderConfig {
                    enabled: false,
                    base_url: url.to_string(),
                    vault_key: vault_key.to_string(),
                },
            );
        }
        Self {
            version: 1,
            inference: InferenceConfig::default(),
            reasoning_level: ReasoningLevel::Medium,
            roles,
            providers,
            workspace: paths::default_workspace().to_string_lossy().into_owned(),
            approval_mode: ApprovalMode::Suggest,
            sandbox_timeout_secs: default_sandbox_timeout(),
            sandbox_share_net: false,
            allow_write_outside_workspace: false,
            selected_model: String::new(),
            local_server_enabled: false,
            local_server_port: default_local_server_port(),
            show_engineer_terminal: default_true(),
        }
    }
}

impl AppConfig {
    /// Le a configuracao do disco, aplicando defaults ausentes.
    pub fn load() -> CoreResult<Self> {
        let path = paths::config_file();
        if !path.exists() {
            let cfg = Self::default();
            cfg.save()?;
            return Ok(cfg);
        }
        let raw = std::fs::read_to_string(&path)?;
        let cfg: AppConfig = toml::from_str(&raw)
            .map_err(|e| CoreError::Config(format!("config.toml invalido: {e}")))?;
        Ok(cfg)
    }

    /// Grava a configuracao com permissao 0600.
    pub fn save(&self) -> CoreResult<()> {
        let path = paths::config_file();
        let raw = toml::to_string_pretty(self)
            .map_err(|e| CoreError::Config(format!("falha ao serializar config: {e}")))?;
        secure_write(&path, raw.as_bytes())?;
        Ok(())
    }

    /// Configuracao do papel, criando entrada se necessario.
    pub fn role(&self, role: Role) -> RoleConfig {
        self.roles
            .get(role.as_str())
            .cloned()
            .unwrap_or_default()
    }

    /// Define o modelo primario de um papel.
    pub fn set_role_primary(&mut self, role: Role, model: &str) {
        self.roles
            .entry(role.as_str().to_string())
            .or_default()
            .primary_model = model.to_string();
    }

    /// Define o modelo secundario (fallback) de um papel.
    pub fn set_role_secondary(&mut self, role: Role, model: &str) {
        self.roles
            .entry(role.as_str().to_string())
            .or_default()
            .secondary_model = model.to_string();
    }

    /// Valida e corrige incoerencias (ex.: num_ctx acima do teto do motor).
    ///
    /// `model_ctx_limit` e o teto REAL do modelo carregado; quando `None`,
    /// nenhum truncamento e aplicado e o valor configurado e preservado.
    pub fn reconcile_inference(&mut self, model_ctx_limit: Option<u32>) {
        if let Some(limit) = model_ctx_limit {
            if limit > 0 && self.inference.num_ctx > limit {
                self.inference.num_ctx = limit;
            }
        }
        let hw = std::thread::available_parallelism()
            .map(|n| n.get() as u32)
            .unwrap_or(4);
        if self.inference.num_thread == 0 {
            self.inference.num_thread = 1;
        }
        if self.inference.num_thread > hw {
            self.inference.num_thread = hw;
        }
        if self.inference.num_batch < 128 {
            self.inference.num_batch = 128;
        }
        if self.inference.physical_batch_size < 64 {
            self.inference.physical_batch_size = 64;
        }
        if self.inference.max_concurrent_predictions == 0 {
            self.inference.max_concurrent_predictions = 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reasoning_level_maps_to_real_core_loops() {
        assert_eq!(ReasoningLevel::Instant.core_loops(), 1);
        assert_eq!(ReasoningLevel::Medium.core_loops(), 2);
        assert_eq!(ReasoningLevel::High.core_loops(), 3);
    }

    #[test]
    fn reasoning_level_parses_persisted_values() {
        assert_eq!(ReasoningLevel::from_str_lossy("instant"), ReasoningLevel::Instant);
        assert_eq!(ReasoningLevel::from_str_lossy("HIGH"), ReasoningLevel::High);
        assert_eq!(ReasoningLevel::from_str_lossy("lixo"), ReasoningLevel::Medium);
    }

    #[test]
    fn reconcile_truncates_to_real_model_limit() {
        let mut cfg = AppConfig::default();
        cfg.inference.num_ctx = 2_097_152;
        cfg.reconcile_inference(Some(32_768));
        assert_eq!(cfg.inference.num_ctx, 32_768);
    }

    #[test]
    fn reconcile_never_truncates_without_a_real_limit() {
        let mut cfg = AppConfig::default();
        cfg.inference.num_ctx = 2_097_152;
        cfg.reconcile_inference(None);
        assert_eq!(cfg.inference.num_ctx, 2_097_152, "teto 2M nao pode ser truncado sem limite real");
    }

    #[test]
    fn roles_cover_all_four() {
        let cfg = AppConfig::default();
        for r in Role::ALL {
            assert!(cfg.roles.contains_key(r.as_str()), "papel ausente: {}", r.as_str());
        }
    }

    #[test]
    fn config_roundtrips_through_toml() {
        let mut cfg = AppConfig::default();
        cfg.set_role_primary(Role::General, "mark-bin-32b");
        cfg.inference.num_ctx = 65_536;
        cfg.reasoning_level = ReasoningLevel::High;
        let raw = toml::to_string_pretty(&cfg).unwrap();
        let back: AppConfig = toml::from_str(&raw).unwrap();
        assert_eq!(back.role(Role::General).primary_model, "mark-bin-32b");
        assert_eq!(back.inference.num_ctx, 65_536);
        assert_eq!(back.reasoning_level, ReasoningLevel::High);
    }
}
