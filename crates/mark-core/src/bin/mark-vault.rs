//! CLI do cofre do MARK: Argon2id + AES-256-GCM + mlock + ZeroizeOnDrop.
//!
//! Senhas entram por stdin (nunca por argv) e o resultado sai em JSON para a
//! interface PyQt6 consumir sem parsear texto livre.

use std::io::Read;

use anyhow::{bail, Context, Result};
use mark_core::paths;
use mark_core::vault::Vault;
use serde_json::json;

fn read_secrets() -> Vec<String> {
    let mut raw = String::new();
    let _ = std::io::stdin().read_to_string(&mut raw);
    raw.lines().map(|line| line.trim_end_matches(['\r', '\n']).to_string()).collect()
}

fn emit(value: serde_json::Value) {
    println!("{value}");
}

fn cmd_status() -> Result<()> {
    let path = paths::vault_file();
    let exists = Vault::is_initialized(&path);
    emit(json!({
        "ok": true,
        "exists": exists,
        "sealed": true,
        "path": path.to_string_lossy().into_owned(),
        "entries": 0,
        "backend": "rust",
        "store_dir": paths::conversations_dir().to_string_lossy().into_owned(),
    }));
    Ok(())
}

fn cmd_init(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    if password.len() < 4 {
        bail!("senha mestra precisa de ao menos 4 caracteres");
    }
    let path = paths::vault_file();
    if Vault::is_initialized(&path) {
        emit(json!({"ok": false, "message": "cofre ja existe; use rekey ou factory-reset"}));
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        paths::ensure_dir(parent)?;
    }
    let vault = Vault::create_fresh(&path, &password)?;
    vault.save()?;
    emit(json!({
        "ok": true,
        "message": "cofre criado",
        "path": path.to_string_lossy().into_owned(),
        "kdf": "Argon2id",
        "cipher": "AES-256-GCM",
    }));
    Ok(())
}

fn cmd_rekey(secrets: &[String]) -> Result<()> {
    let current = secrets.first().cloned().unwrap_or_default();
    let new = secrets.get(1).cloned().unwrap_or_default();
    if new.trim().len() < 4 {
        bail!("senha nova precisa de ao menos 4 caracteres");
    }
    let path = paths::vault_file();
    if !Vault::is_initialized(&path) {
        emit(json!({"ok": false, "message": "nenhum cofre para re-encriptar"}));
        return Ok(());
    }
    let mut vault = Vault::open(&path).context("abrir cofre")?;
    vault.rekey(&current, &new).context("rekey")?;
    vault.save()?;
    emit(json!({
        "ok": true,
        "message": "senha mestra trocada, registros preservados",
        "entries": vault.keys().len(),
    }));
    Ok(())
}

fn cmd_factory_reset(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    if password.len() < 4 {
        bail!("senha mestra precisa de ao menos 4 caracteres");
    }
    let path = paths::vault_file();
    if let Some(parent) = path.parent() {
        paths::ensure_dir(parent)?;
    }
    let vault = Vault::factory_reset(&path, &password)?;
    vault.save()?;
    emit(json!({
        "ok": true,
        "message": "cofre reinicializado do zero",
        "path": path.to_string_lossy().into_owned(),
    }));
    Ok(())
}

fn cmd_list(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    let path = paths::vault_file();
    if !Vault::is_initialized(&path) {
        emit(json!({"ok": false, "error": "vault-missing", "keys": []}));
        return Ok(());
    }
    let mut vault = Vault::open(&path)?;
    if let Err(error) = vault.unlock_verified(&password) {
        emit(json!({"ok": false, "error": "bad-password", "message": format!("{error}"), "keys": []}));
        return Ok(());
    }
    let mut keys = vault.keys();
    keys.retain(|name| name != mark_core::vault::VERIFY_RECORD);
    keys.sort();
    emit(json!({"ok": true, "keys": keys, "count": keys.len()}));
    Ok(())
}

fn cmd_set(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    let name = secrets.get(1).cloned().unwrap_or_default();
    let value = secrets.get(2).cloned().unwrap_or_default();
    if name.trim().is_empty() {
        bail!("nome da chave obrigatorio");
    }
    let path = paths::vault_file();
    if !Vault::is_initialized(&path) {
        emit(json!({"ok": false, "error": "vault-missing"}));
        return Ok(());
    }
    let mut vault = Vault::open(&path)?;
    if let Err(error) = vault.unlock_verified(&password) {
        emit(json!({"ok": false, "error": "bad-password", "message": format!("{error}")}));
        return Ok(());
    }
    vault.put(&name, value.as_bytes())?;
    vault.save()?;
    emit(json!({"ok": true, "name": name, "count": vault.keys().len()}));
    Ok(())
}

fn cmd_get(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    let name = secrets.get(1).cloned().unwrap_or_default();
    let path = paths::vault_file();
    if !Vault::is_initialized(&path) {
        emit(json!({"ok": false, "error": "vault-missing"}));
        return Ok(());
    }
    let mut vault = Vault::open(&path)?;
    if let Err(error) = vault.unlock_verified(&password) {
        emit(json!({"ok": false, "error": "bad-password", "message": format!("{error}")}));
        return Ok(());
    }
    match vault.get_string(&name) {
        Ok(value) => emit(json!({"ok": true, "name": name, "value": value})),
        Err(error) => emit(json!({"ok": false, "error": "not-found", "message": format!("{error}")})),
    }
    Ok(())
}

fn cmd_delete(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    let name = secrets.get(1).cloned().unwrap_or_default();
    let path = paths::vault_file();
    if !Vault::is_initialized(&path) {
        emit(json!({"ok": false, "error": "vault-missing"}));
        return Ok(());
    }
    let mut vault = Vault::open(&path)?;
    if let Err(error) = vault.unlock_verified(&password) {
        emit(json!({"ok": false, "error": "bad-password", "message": format!("{error}")}));
        return Ok(());
    }
    let removed = vault.remove(&name)?;
    vault.save()?;
    emit(json!({"ok": true, "removed": removed, "count": vault.keys().len()}));
    Ok(())
}

fn cmd_unlock(secrets: &[String]) -> Result<()> {
    let password = secrets.first().cloned().unwrap_or_default();
    let path = paths::vault_file();
    if !Vault::is_initialized(&path) {
        emit(json!({"ok": false, "error": "vault-missing"}));
        return Ok(());
    }
    let mut vault = Vault::open(&path)?;
    match vault.unlock_verified(&password) {
        Ok(()) => {
            let mut keys = vault.keys();
            keys.retain(|name| name != mark_core::vault::VERIFY_RECORD);
            emit(json!({"ok": true, "unlocked": true, "count": keys.len()}));
        }
        Err(error) => emit(json!({"ok": false, "error": "bad-password", "message": format!("{error}")})),
    }
    Ok(())
}

fn cmd_engine() -> Result<()> {
    let checkpoint = paths::mark_bin_32b_checkpoint();
    emit(json!({
        "ok": true,
        "gpu": mark_engine_probe::gpu(),
        "backend": "svid-1bit",
        "checkpoint": checkpoint.map(|p| p.to_string_lossy().into_owned()),
        "vault": paths::vault_file().to_string_lossy().into_owned(),
        "conversations": paths::conversations_dir().to_string_lossy().into_owned(),
    }));
    Ok(())
}

/// Deteccao de GPU sem arrastar mark-engine para dentro do mark-core.
mod mark_engine_probe {
    /// Indica se existe uma GPU utilizavel via nvidia-smi.
    pub fn gpu() -> bool {
        std::process::Command::new("nvidia-smi")
            .arg("-L")
            .output()
            .map(|out| out.status.success() && !out.stdout.is_empty())
            .unwrap_or(false)
    }
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "status".to_string());
    let _json_flag = args.any(|a| a == "--json");
    let secrets = read_secrets();
    match command.as_str() {
        "status" => cmd_status(),
        "init" => cmd_init(&secrets),
        "rekey" => cmd_rekey(&secrets),
        "factory-reset" => cmd_factory_reset(&secrets),
        "list" => cmd_list(&secrets),
        "set" => cmd_set(&secrets),
        "get" => cmd_get(&secrets),
        "delete" => cmd_delete(&secrets),
        "unlock" => cmd_unlock(&secrets),
        "engine" => cmd_engine(),
        other => {
            emit(json!({"ok": false, "message": format!("comando desconhecido: {other}")}));
            Ok(())
        }
    }
}
