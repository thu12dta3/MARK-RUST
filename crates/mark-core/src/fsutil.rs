//! Escrita segura de arquivos sensiveis (0600) e criacao de diretorios.

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use crate::error::CoreResult;

/// Escreve `bytes` em `path` com permissao 0600, criando os pais.
///
/// A escrita e atomica: grava em arquivo temporario no mesmo diretorio e
/// renomeia, para que uma queda no meio nunca deixe um arquivo parcial.
pub fn secure_write(path: &Path, bytes: &[u8]) -> CoreResult<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension(format!(
        "tmp-{}",
        uuid::Uuid::new_v4().simple()
    ));
    {
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
    }
    std::fs::rename(&tmp, path)?;
    Ok(())
}

/// Cria um diretorio com permissao 0700.
pub fn secure_dir(path: &Path) -> CoreResult<()> {
    std::fs::create_dir_all(path)?;
    let mut perms = std::fs::metadata(path)?.permissions();
    use std::os::unix::fs::PermissionsExt;
    perms.set_mode(0o700);
    std::fs::set_permissions(path, perms)?;
    Ok(())
}

/// Grava um arquivo normal (0644) — usado para artefatos nao sensiveis.
pub fn plain_write(path: &Path, bytes: &[u8]) -> CoreResult<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut f = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o644)
        .open(path)?;
    f.write_all(bytes)?;
    Ok(())
}
