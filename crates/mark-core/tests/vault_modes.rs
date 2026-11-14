use std::path::PathBuf;

use mark_core::vault::{VERIFY_RECORD, VERIFY_VALUE};
use mark_core::Vault;

fn tmp(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mark-vault-{tag}-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&dir).unwrap();
    dir.join("vault.bin")
}

#[test]
fn brand_new_vault_requires_setup_then_verifies_password() {
    let path = tmp("brandnew");
    assert!(!Vault::is_initialized(&path), "cofre nao pode existir no primeiro boot");
    let mut v = Vault::create_fresh(&path, "senha-nova-123").unwrap();
    assert!(Vault::is_initialized(&path));
    assert_eq!(v.get(VERIFY_RECORD).unwrap(), VERIFY_VALUE);
    v.put("api/openai", b"sk-1").unwrap();
    v.save().unwrap();
    v.lock();

    let mut back = Vault::open(&path).unwrap();
    assert!(back.unlock_verified("senha-errada").is_err());
    back.unlock_verified("senha-nova-123").unwrap();
    assert_eq!(back.get_string("api/openai").unwrap(), "sk-1");
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn mode_a_rekey_keeps_every_record() {
    let path = tmp("rekey");
    let mut v = Vault::create_fresh(&path, "antiga-senha").unwrap();
    v.put("api/a", b"AAA").unwrap();
    v.put("conv/1", b"{\"m\":\"ola\"}").unwrap();
    v.save().unwrap();

    v.rekey("antiga-senha", "nova-senha-456").unwrap();
    v.lock();

    let mut back = Vault::open(&path).unwrap();
    assert!(back.unlock_verified("antiga-senha").is_err());
    back.unlock_verified("nova-senha-456").unwrap();
    assert_eq!(back.get_string("api/a").unwrap(), "AAA");
    assert_eq!(back.get_string("conv/1").unwrap(), "{\"m\":\"ola\"}");
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn mode_a_rejects_wrong_current_password() {
    let path = tmp("rekey-bad");
    let mut v = Vault::create_fresh(&path, "certa").unwrap();
    v.put("k", b"v").unwrap();
    let err = v.rekey("errada", "outra-senha").unwrap_err();
    assert!(err.to_string().contains("cofre"), "erro inesperado: {err}");
    assert!(!v.is_unlocked(), "falha de senha deve trancar o cofre");
    v.unlock_verified("certa").unwrap();
    assert_eq!(v.get_string("k").unwrap(), "v");
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn mode_b_factory_reset_wipes_all_data() {
    let path = tmp("reset");
    let mut v = Vault::create_fresh(&path, "senha-velha").unwrap();
    v.put("api/antiga", b"segredo").unwrap();
    v.save().unwrap();

    let mut fresh = Vault::factory_reset(&path, "senha-nova").unwrap();
    assert!(fresh.keys().iter().all(|k| k == VERIFY_RECORD));
    assert!(fresh.get("api/antiga").is_err());
    fresh.lock();

    let mut back = Vault::open(&path).unwrap();
    assert!(back.unlock_verified("senha-velha").is_err());
    back.unlock_verified("senha-nova").unwrap();
    assert!(back.get("api/antiga").is_err());
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn reset_and_rekey_reject_short_passwords() {
    let path = tmp("short");
    assert!(Vault::factory_reset(&path, "ab").is_err());
    let mut v = Vault::create_fresh(&path, "senha-ok").unwrap();
    assert!(v.rekey("senha-ok", "xy").is_err());
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn vault_file_never_contains_plaintext_secrets() {
    let path = tmp("plain");
    let mut v = Vault::create_fresh(&path, "senha-mestra").unwrap();
    v.put("api/secret", b"sk-nao-pode-vazar-123").unwrap();
    v.save().unwrap();
    let raw = std::fs::read(&path).unwrap();
    assert!(
        !raw.windows(23).any(|w| w == b"sk-nao-pode-vazar-123"),
        "segredo em texto puro no cofre"
    );
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}
