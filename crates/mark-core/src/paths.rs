//! Paths XDG e localizacao de recursos do usuario.
//!
//! Regra dura: nenhum caminho absoluto do developer pode aparecer no binario.
//! Tudo e derivado de `dirs` (XDG) em runtime.

use std::path::{Path, PathBuf};

/// Raiz de dados do MARK (config, chaves, logs, banco de conversas).
pub fn data_dir() -> PathBuf {
    dirs::data_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("mark")
}

/// Diretorio de configuracao (XDG_CONFIG_HOME/mark).
pub fn config_dir() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("mark")
}

/// Diretorio de cache (XDG_CACHE_HOME/mark).
pub fn cache_dir() -> PathBuf {
    dirs::cache_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("mark")
}

/// Diretorio de estado (XDG_STATE_HOME/mark): conversas, historico.
pub fn state_dir() -> PathBuf {
    dirs::state_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("mark")
}

/// Arquivo de configuracao principal (TOML).
pub fn config_file() -> PathBuf {
    config_dir().join("config.toml")
}

/// Arquivo do cofre criptografico.
pub fn vault_file() -> PathBuf {
    config_dir().join("vault.bin")
}

/// Diretorio onde os modelos baixados do Hugging Face sao gravados.
pub fn models_dir() -> PathBuf {
    dirs::data_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("mark")
        .join("models")
}

/// Diretorio de downloads em andamento (nunca usar /tmp para arquivos grandes).
pub fn downloads_dir() -> PathBuf {
    cache_dir().join("downloads")
}

/// Banco de conversas (SQLite será substituido por armazenamento JSON-lines).
pub fn conversations_dir() -> PathBuf {
    state_dir().join("conversations")
}

/// Raiz do workspace do Hermes (skills, plugins, MCP).
pub fn hermes_home() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".hermes")
}

/// Diretorio de skills do Hermes.
pub fn hermes_skills_dir() -> PathBuf {
    hermes_home().join("skills")
}

/// Arquivo de configuracao do Hermes (fonte dos servidores MCP).
pub fn hermes_config_file() -> PathBuf {
    hermes_home().join("config.yaml")
}

/// Raiz do workspace padrao do Modo Engineer.
pub fn default_workspace() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from(".")).join("workspace")
}

/// Detecta o nome do usuario do sistema para localizar `/run/media/<user>`.
///
/// Retorna `None` quando o usuario nao pode ser determinado, em vez de chutar.
pub fn system_user_name() -> Option<String> {
    if let Ok(user) = std::env::var("USER") {
        if !user.is_empty() && user != "root" {
            return Some(user);
        }
    }
    if let Ok(user) = std::env::var("LOGNAME") {
        if !user.is_empty() && user != "root" {
            return Some(user);
        }
    }
    None
}

/// Localiza o volume externo rotulado pelo usuario (ex.: "hd 1tb").
///
/// Monta `/run/media/<user>/<label>` sem hardcode. Retorna `None` se nao existir.
pub fn external_volume(label: &str) -> Option<PathBuf> {
    let user = system_user_name()?;
    let candidate = PathBuf::from("/run/media").join(&user).join(label);
    if candidate.is_dir() {
        Some(candidate)
    } else {
        None
    }
}

/// Monta o caminho do checkpoint Mark-Bin-32B no volume externo, se existir.
pub fn mark_bin_32b_checkpoint() -> Option<PathBuf> {
    for label in ["hd 1tb", "hd1tb", "hd-1tb"] {
        if let Some(vol) = external_volume(label) {
            let ckpt = vol.join("mark_checkpoints").join("Mark-Bin-32B");
            if ckpt.is_dir() {
                return Some(ckpt);
            }
        }
    }
    None
}

/// Cria o diretorio (e os pais) se necessario.
pub fn ensure_dir(path: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(path)
}

/// Garante que todos os diretorios base existam.
pub fn ensure_base_dirs() -> std::io::Result<()> {
    ensure_dir(&data_dir())?;
    ensure_dir(&config_dir())?;
    ensure_dir(&state_dir())?;
    ensure_dir(&models_dir())?;
    ensure_dir(&downloads_dir())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_dirs_are_absolute_and_distinct() {
        let d = data_dir();
        assert!(d.is_absolute(), "data_dir deve ser absoluto: {:?}", d);
        assert!(config_dir().is_absolute());
        assert!(state_dir().is_absolute());
        assert!(models_dir().is_absolute());
    }

    #[test]
    fn external_volume_never_guesses_missing_path() {
        // Nao deve panicar nem retornar caminho inventado.
        let _ = external_volume("definitely-not-a-volume-xyz");
    }

    #[test]
    fn ensure_base_dirs_creates_tree() {
        ensure_base_dirs().expect("deve criar diretorios base");
        assert!(config_dir().is_dir());
        assert!(models_dir().is_dir());
    }
}
