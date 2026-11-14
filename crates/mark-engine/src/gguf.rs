//! Backend universal para arquivos `.gguf`: `llama-server` nativo ou importacao no Ollama.

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};

use crate::http_backends::{OllamaClient, OpenAiClient};
use crate::svid::EngineConfig;
use crate::Engine;

/// Localiza um executavel no PATH.
pub fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let cand = dir.join(name);
        if cand.is_file() {
            return Some(cand);
        }
    }
    None
}

/// Caminho do `llama-server`, quando instalado.
pub fn llama_server_path() -> Option<PathBuf> {
    which("llama-server").or_else(|| which("llama-server.exe"))
}

/// Argumentos reais passados ao `llama-server` para um modelo e configuracao dados.
pub fn llama_server_args(
    model: &Path,
    num_ctx: u32,
    n_gpu_layers: u32,
    threads: u32,
    mmap: bool,
    port: u16,
) -> Vec<String> {
    let mut args = vec![
        "-m".to_string(),
        model.display().to_string(),
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
        "-c".to_string(),
        num_ctx.to_string(),
        "-ngl".to_string(),
        n_gpu_layers.to_string(),
        "-t".to_string(),
        threads.to_string(),
        "--jinja".to_string(),
    ];
    if mmap {
        args.push("--mmap".to_string());
    } else {
        args.push("--no-mmap".to_string());
    }
    args
}

/// Verifica se o nome de arquivo corresponde a uma quantizacao 1-bit suportada.
pub fn is_one_bit_quant(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    name.contains("iq1_s") || name.contains("iq1_m") || name.contains("iq1")
        || name.contains("q1_") || name.contains("1bit")
}

/// Processo `llama-server` sob supervisao do motor.
pub struct LlamaProcess {
    child: Child,
    port: u16,
    model: PathBuf,
}

impl LlamaProcess {
    /// Sobe o `llama-server` para o modelo e espera o endpoint ficar saudavel.
    pub fn spawn(
        model: &Path,
        num_ctx: u32,
        n_gpu_layers: u32,
        threads: u32,
        mmap: bool,
    ) -> Result<Self> {
        let bin = llama_server_path().context(
            "llama-server nao encontrado no PATH (instale llama.cpp para carregar .gguf)",
        )?;
        if !model.is_file() {
            bail!("modelo gguf inexistente: {}", model.display());
        }
        let port = free_port()?;
        let args = llama_server_args(model, num_ctx, n_gpu_layers, threads, mmap, port);
        let child = Command::new(&bin)
            .args(&args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .with_context(|| format!("falha ao iniciar {}", bin.display()))?;
        let mut proc = Self {
            child,
            port,
            model: model.to_path_buf(),
        };
        proc.wait_ready(Duration::from_secs(180))?;
        Ok(proc)
    }

    fn wait_ready(&mut self, timeout: Duration) -> Result<()> {
        let client = OpenAiClient::new(&format!("http://127.0.0.1:{}/v1", self.port), None)?;
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if let Ok(Some(status)) = self.child.try_wait() {
                bail!("llama-server encerrou com status {status}");
            }
            if rt.block_on(client.is_alive()) {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(300));
        }
        bail!("llama-server nao respondeu em {}s", timeout.as_secs())
    }

    /// Base URL OpenAI-compatible do processo.
    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}/v1", self.port)
    }

    /// Modelo carregado.
    pub fn model_path(&self) -> &Path {
        &self.model
    }

    /// Constroi o motor OpenAI-compatible apontando para este processo.
    pub fn engine(&self, config: EngineConfig) -> Result<Engine> {
        let client = OpenAiClient::new(&self.base_url(), None)?;
        let name = self
            .model
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("gguf")
            .to_string();
        Ok(Engine::OpenAi {
            client,
            model: name,
            config,
        })
    }
}

impl Drop for LlamaProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn free_port() -> Result<u16> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

/// Nome de modelo usado ao importar um gguf para o Ollama.
pub fn ollama_model_name(path: &Path) -> String {
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("gguf")
        .to_ascii_lowercase()
        .replace([' ', '.'], "-");
    format!("mark-{stem}:latest")
}

/// Importa um `.gguf` para o daemon Ollama via `ollama create`.
pub fn ollama_import_gguf(path: &Path, name: &str) -> Result<()> {
    let bin = which("ollama").context("ollama nao encontrado no PATH")?;
    if !path.is_file() {
        bail!("modelo gguf inexistente: {}", path.display());
    }
    let dir = mark_core::paths::cache_dir().join("modelfiles");
    std::fs::create_dir_all(&dir)?;
    let modelfile = dir.join(format!(
        "mark-{}.Modelfile",
        name.replace([':', '/'], "_")
    ));
    std::fs::write(&modelfile, format!("FROM {}\n", path.display()))?;
    let out = Command::new(bin)
        .args(["create", name, "-f"])
        .arg(&modelfile)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .context("falha ao executar ollama create")?;
    let _ = std::fs::remove_file(&modelfile);
    if !out.status.success() {
        bail!(
            "ollama create falhou: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        );
    }
    Ok(())
}

/// Confirma que o Ollama conhece o modelo informado.
pub fn ollama_has_model(name: &str) -> Result<bool> {
    let client = OllamaClient::new("http://127.0.0.1:11434")?;
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let raw = rt.block_on(client.list_models_raw())?;
    Ok(mark_core::models::parse_ollama_models(&raw)
        .iter()
        .any(|m| m.name == name))
}

/// Prepara um `.gguf` para inferencia: `llama-server` quando existir, senao Ollama.
pub fn prepare_gguf_engine(path: &Path, config: EngineConfig) -> Result<Engine> {
    if llama_server_path().is_some() {
        let proc = LlamaProcess::spawn(path, 32_768, 99, 8, true)?;
        let engine = proc.engine(config)?;
        std::mem::forget(proc);
        return Ok(engine);
    }
    let name = ollama_model_name(path);
    if !ollama_has_model(&name).unwrap_or(false) {
        ollama_import_gguf(path, &name)?;
    }
    let client = OllamaClient::new("http://127.0.0.1:11434")?;
    Ok(Engine::Ollama {
        client,
        model: name,
        config,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_args_carry_real_configuration() {
        let args = llama_server_args(Path::new("/m/x.gguf"), 8192, 33, 6, true, 9099);
        assert_eq!(args[0], "-m");
        assert_eq!(args[1], "/m/x.gguf");
        assert!(args.contains(&"-c".to_string()));
        assert!(args.contains(&"8192".to_string()));
        assert!(args.contains(&"-ngl".to_string()));
        assert!(args.contains(&"33".to_string()));
        assert!(args.contains(&"-t".to_string()));
        assert!(args.contains(&"6".to_string()));
        assert!(args.contains(&"--mmap".to_string()));
        assert!(args.contains(&"9099".to_string()));
        let no_mmap = llama_server_args(Path::new("/m/x.gguf"), 4096, 0, 4, false, 9098);
        assert!(no_mmap.contains(&"--no-mmap".to_string()));
    }

    #[test]
    fn detects_one_bit_quantizations() {
        assert!(is_one_bit_quant(Path::new("Mark-Bin-32B-IQ1_S.gguf")));
        assert!(is_one_bit_quant(Path::new("model-iq1_m.gguf")));
        assert!(!is_one_bit_quant(Path::new("model-q4_k_m.gguf")));
        assert!(!is_one_bit_quant(Path::new("model-q8_0.gguf")));
    }

    #[test]
    fn ollama_name_is_stable() {
        assert_eq!(
            ollama_model_name(Path::new("/run/x/Mark Engineer 302M.gguf")),
            "mark-mark-engineer-302m:latest"
        );
    }

    #[test]
    fn free_port_is_bindable() {
        let port = free_port().unwrap();
        assert!(port > 1024);
    }
}
