//! Servidor OpenAI-compatible do MARK sobre o motor Rust real.
//!
//! Seleciona o backend na ordem: GGUF explicito, checkpoint SVID 1-Bit nativo,
//! daemon Ollama. Nenhum caminho de inferencia e simulado.

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{bail, Result};
use mark_engine::gguf::prepare_gguf_engine;
use mark_engine::http_backends::OllamaClient;
use mark_engine::server::LocalServer;
use mark_engine::svid::{EngineConfig, SvidEngine};
use mark_engine::Engine;

/// Parametros de linha de comando.
struct Args {
    host: String,
    port: u16,
    model: Option<String>,
    gguf: Option<PathBuf>,
    ctx: u32,
    probe: bool,
}

fn parse_args() -> Result<Args> {
    let mut args = Args {
        host: "127.0.0.1".to_string(),
        port: 8765,
        model: None,
        gguf: None,
        ctx: 8192,
        probe: false,
    };
    let mut raw = std::env::args().skip(1);
    while let Some(flag) = raw.next() {
        match flag.as_str() {
            "--host" => args.host = raw.next().unwrap_or_else(|| "127.0.0.1".into()),
            "--port" => {
                let value = raw.next().unwrap_or_default();
                args.port = value.parse().map_err(|_| anyhow::anyhow!("porta invalida: {value}"))?;
            }
            "--model" => args.model = raw.next(),
            "--gguf" => args.gguf = raw.next().map(PathBuf::from),
            "--ctx" => {
                let value = raw.next().unwrap_or_default();
                args.ctx = value.parse().map_err(|_| anyhow::anyhow!("ctx invalido: {value}"))?;
            }
            "--probe" => args.probe = true,
            "--help" | "-h" => {
                println!("uso: mark-server [--host IP] [--port N] [--model ID] [--gguf PATH] [--ctx N] [--probe]");
                std::process::exit(0);
            }
            other => bail!("flag desconhecida: {other}"),
        }
    }
    Ok(args)
}

fn probe() -> Result<()> {
    let checkpoint = mark_core::paths::mark_bin_32b_checkpoint();
    let payload = serde_json::json!({
        "ok": true,
        "gpu": mark_engine::gpu::gpu_available(),
        "device": mark_engine::gpu::device_name(),
        "backend": if checkpoint.is_some() { "svid-1bit" } else { "ollama" },
        "checkpoint": checkpoint.map(|p| p.to_string_lossy().into_owned()),
        "models_dir": mark_core::paths::models_dir().to_string_lossy().into_owned(),
        "vault": mark_core::paths::vault_file().to_string_lossy().into_owned(),
    });
    println!("{}", serde_json::to_string(&payload)?);
    Ok(())
}

/// Nome anunciado em /v1/models antes de os pesos carregarem.
fn announced_model(args: &Args) -> String {
    if let Some(path) = &args.gguf {
        return path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_else(|| "gguf".into());
    }
    args.model.clone().unwrap_or_else(|| "mark-svid-1bit".to_string())
}

fn build_engine(args: &Args) -> Result<(Engine, String)> {
    let config = EngineConfig::default();
    if let Some(path) = &args.gguf {
        if !path.is_file() {
            bail!("arquivo gguf inexistente: {}", path.display());
        }
        let engine = prepare_gguf_engine(path, config)?;
        let label = path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_else(|| "gguf".into());
        return Ok((engine, label));
    }
    if let Some(checkpoint) = mark_core::paths::mark_bin_32b_checkpoint() {
        let engine = SvidEngine::load(&checkpoint)?;
        let label = args
            .model
            .clone()
            .unwrap_or_else(|| "mark-svid-1bit".to_string());
        return Ok((
            Engine::Svid {
                engine: Arc::new(engine),
                config,
            },
            label,
        ));
    }
    let client = OllamaClient::new("http://127.0.0.1:11434")?;
    let model = args.model.clone().unwrap_or_else(|| "deepseek-r1:8b-q3_k_l".into());
    Ok((
        Engine::Ollama {
            client,
            model: model.clone(),
            config,
        },
        model,
    ))
}

fn main() -> Result<()> {
    let args = parse_args()?;
    if args.probe {
        return probe();
    }
    let addr = format!("{}:{}", args.host, args.port);
    let context = args.ctx.max(512);
    let model = announced_model(&args);
    // O socket abre e responde /health e /v1/models imediatamente; os pesos
    // carregam em background e a primeira inferencia aguarda o slot.
    let (server, slot) = LocalServer::new_lazy(model.clone(), context);
    eprintln!("mark-server: listening on {addr} model={model} ctx={context} (lazy engine load)");
    let loader = std::thread::Builder::new()
        .name("mark-engine-loader".into())
        .spawn(move || match build_engine(&args) {
            Ok((engine, label)) => {
                let _ = slot.set(Arc::new(engine));
                eprintln!("mark-server: engine ready ({label})");
            }
            Err(error) => eprintln!("mark-server: engine load failed: {error:#}"),
        })?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    let result = runtime.block_on(async move { server.serve(&addr).await });
    let _ = loader.join();
    result
}
