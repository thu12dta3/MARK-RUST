//! Cliente do Hugging Face Hub: busca, listagem e download com retomada por `Range`.

use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::Deserialize;

const API: &str = "https://huggingface.co/api";

/// Repositorio retornado pela busca.
#[derive(Debug, Clone, Deserialize)]
pub struct HfRepo {
    pub id: String,
    #[serde(default)]
    pub downloads: Option<u64>,
    #[serde(default)]
    pub likes: Option<u64>,
}

impl HfRepo {
    /// Downloads acumulados (0 quando o campo vem nulo).
    pub fn downloads(&self) -> u64 {
        self.downloads.unwrap_or(0)
    }

    /// Curtidas acumuladas (0 quando o campo vem nulo).
    pub fn likes(&self) -> u64 {
        self.likes.unwrap_or(0)
    }
}

/// Arquivo de um repositorio.
#[derive(Debug, Clone, Deserialize)]
pub struct HfFile {
    pub path: String,
    #[serde(default)]
    pub size: Option<u64>,
    #[serde(rename = "type", default)]
    pub kind: String,
}

impl HfFile {
    /// Tamanho em bytes (0 quando o campo vem nulo).
    pub fn size(&self) -> u64 {
        self.size.unwrap_or(0)
    }
}

fn client() -> Result<reqwest::Client> {
    reqwest::Client::builder()
        .user_agent("mark-desktop/1.0")
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .context("cliente HTTP indisponivel")
}

fn block_on<F: std::future::Future>(fut: F) -> Result<F::Output> {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("runtime tokio indisponivel")?;
    Ok(rt.block_on(fut))
}

/// Busca repositorios publicos por nome.
pub async fn search(query: &str, limit: usize) -> Result<Vec<HfRepo>> {
    let url = format!(
        "{API}/models?search={}&limit={}&sort=downloads&direction=-1",
        urlencode(query),
        limit.clamp(1, 50)
    );
    let resp = client()?.get(&url).send().await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        bail!("busca HF falhou ({status}): {body}");
    }
    let mut repos: Vec<HfRepo> = resp.json().await?;
    repos.retain(|r| !r.id.is_empty());
    Ok(repos)
}

/// Lista os arquivos de um repositorio, do maior para o menor.
pub async fn files(repo: &str) -> Result<Vec<HfFile>> {
    let url = format!("{API}/models/{repo}/tree/main?recursive=true");
    let resp = client()?.get(&url).send().await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        bail!("listagem HF falhou ({status}): {body}");
    }
    let mut files: Vec<HfFile> = resp.json().await?;
    files.retain(|f| f.kind != "directory" && !f.path.is_empty());
    files.sort_by(|a, b| b.size().cmp(&a.size()));
    Ok(files)
}

fn urlencode(s: &str) -> String {
    let mut out = String::new();
    for b in s.as_bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Baixa um arquivo do repositorio, retomando de onde o parcial parou.
pub async fn download<F>(
    repo: &str,
    file: &str,
    dest: &Path,
    mut on_progress: F,
) -> Result<u64>
where
    F: FnMut(u64, u64),
{
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let part = part_path(dest);
    let mut have = std::fs::metadata(&part).map(|m| m.len()).unwrap_or(0);
    let url = format!("https://huggingface.co/{repo}/resolve/main/{file}");
    let mut req = client()?.get(&url);
    if have > 0 {
        req = req.header("range", format!("bytes={have}-"));
    }
    let mut resp = req.send().await.context("abrindo download")?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        bail!("download HF falhou ({status}): {body}");
    }
    let resumed = resp.status() == reqwest::StatusCode::PARTIAL_CONTENT;
    if have > 0 && !resumed {
        have = 0;
        let _ = std::fs::remove_file(&part);
    }
    let total = have + resp.content_length().unwrap_or(0);
    let mut out = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&part)?;
    let mut last = std::time::Instant::now();
    while let Some(chunk) = resp.chunk().await? {
        out.write_all(&chunk)?;
        have += chunk.len() as u64;
        if last.elapsed() >= std::time::Duration::from_millis(250) {
            on_progress(have, total.max(have));
            last = std::time::Instant::now();
        }
    }
    out.flush()?;
    drop(out);
    std::fs::rename(&part, dest)?;
    on_progress(have, have);
    Ok(have)
}

fn part_path(dest: &Path) -> PathBuf {
    let name = dest
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("download");
    dest.with_file_name(format!(".{name}.part"))
}

/// Versao bloqueante de [`search`].
pub fn search_blocking(query: &str, limit: usize) -> Result<Vec<HfRepo>> {
    block_on(search(query, limit))?
}

/// Versao bloqueante de [`files`].
pub fn files_blocking(repo: &str) -> Result<Vec<HfFile>> {
    block_on(files(repo))?
}

/// Versao bloqueante de [`download`].
pub fn download_blocking<F>(repo: &str, file: &str, dest: &Path, on_progress: F) -> Result<u64>
where
    F: FnMut(u64, u64),
{
    block_on(download(repo, file, dest, on_progress))?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn search_returns_real_repos() {
        let repos = match search_blocking("miceworks", 5) { Ok(v) => v, Err(e) => panic!("busca falhou: {e:#}") };
        assert!(!repos.is_empty(), "nenhum repositorio retornado");
        assert!(repos.iter().any(|r| r.id.contains('/')));
    }

    #[test]
    fn lists_files_with_sizes() {
        let files = files_blocking("miceworks/Mark-SLM-V3-150M").expect("listagem deve funcionar");
        assert!(!files.is_empty(), "repositorio sem arquivos");
        assert!(
            files.iter().any(|f| f.path == "config.json"),
            "config.json ausente: {:?}",
            files.iter().map(|f| &f.path).collect::<Vec<_>>()
        );
    }

    #[test]
    fn downloads_and_resumes_with_range() {
        let dir = mark_core::paths::cache_dir().join(format!("hf-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let dest = dir.join("config.json");

        let mut progress_calls = 0usize;
        let n = download_blocking("miceworks/Mark-SLM-V3-150M", "config.json", &dest, |_, _| {
            progress_calls += 1;
        })
        .expect("download deve funcionar");
        assert!(n > 0, "arquivo vazio");
        let raw = std::fs::read_to_string(&dest).unwrap();
        assert!(raw.contains('{'), "conteudo inesperado: {raw}");
        let _ = serde_json::from_str::<serde_json::Value>(&raw).expect("config.json deve ser JSON");
        let _ = progress_calls;

        let part = part_path(&dest);
        std::fs::remove_file(&dest).unwrap();
        let half = (n / 2).max(1) as usize;
        std::fs::write(&part, std::fs::read(&part).unwrap_or_default()).ok();
        std::fs::write(&part, &raw.as_bytes()[..half.min(raw.len())]).unwrap();
        let n2 = download_blocking("miceworks/Mark-SLM-V3-150M", "config.json", &dest, |_, _| {})
            .expect("download com retomada deve funcionar");
        assert_eq!(n2, n, "tamanho final diferente apos retomada");
        assert!(!part.exists(), "arquivo parcial nao foi removido");

        std::fs::remove_dir_all(&dir).unwrap();
        assert!(!dir.exists(), "diretorio de teste nao foi limpo");
    }

    #[test]
    fn rejects_missing_file_with_clear_error() {
        let dir = mark_core::paths::cache_dir().join(format!("hf-err-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let err = download_blocking(
            "miceworks/Mark-SLM-V3-150M",
            "arquivo-que-nao-existe.bin",
            &dir.join("x.bin"),
            |_, _| {},
        )
        .unwrap_err();
        assert!(err.to_string().contains("404") || err.to_string().contains("falhou"));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
