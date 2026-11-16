#![allow(clippy::needless_range_loop)]
//! Fachada do motor de inferencia: escolhe o backend real conforme o modelo.

pub mod avx2;
pub mod gguf;
pub mod gpu;
pub mod http_backends;
pub mod kernels;
pub mod safetensors;
pub mod server;
pub mod svid;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::{bail, Result};

use crate::http_backends::{
    ChatMessage, CompletionRequest, CompletionResponse, OllamaClient, OpenAiClient,
};
use crate::svid::{EngineConfig, SvidEngine};

/// Backend selecionado para uma sessao.
#[derive(Clone)]
pub enum Engine {
    /// Motor SVID 1-Bit nativo carregado do checkpoint.
    Svid {
        engine: Arc<SvidEngine>,
        config: EngineConfig,
    },
    /// Daemon Ollama.
    Ollama {
        client: OllamaClient,
        model: String,
        config: EngineConfig,
    },
    /// Endpoint OpenAI-compatible.
    OpenAi {
        client: OpenAiClient,
        model: String,
        config: EngineConfig,
    },
}

impl Engine {
    /// Identificador curto do backend em uso (aparece nas respostas HTTP).
    pub fn label(&self) -> &'static str {
        match self {
            Engine::Svid { .. } => "rust-1bit",
            Engine::Ollama { .. } => "ollama",
            Engine::OpenAi { .. } => "openai",
        }
    }
}

/// Evento emitido durante a geracao.
#[derive(Debug, Clone)]
pub enum StreamEvent {
    /// Fragmento de texto da resposta final.
    Delta(String),
    /// Fragmento de raciocinio (`reasoning_content` / `thinking`).
    Reasoning(String),
    /// Metadados de uso ao final.
    Usage {
        prompt_tokens: Option<u32>,
        completion_tokens: Option<u32>,
    },
    /// Erro durante a geracao.
    Error(String),
}

/// Contexto da conversa enviado ao modelo.
#[derive(Debug, Clone, Default)]
pub struct ChatContext {
    pub system: Option<String>,
    pub history: Vec<ChatMessage>,
}

/// Ajustes de amostragem vindos da requisicao (`/v1/chat/completions`).
///
/// `reasoning_loops` controla a profundidade do bloco recorrente LRD no motor
/// nativo e a temperatura/teto do backend remoto; `max_tokens` limita os tokens
/// realmente gerados; `temperature` sobrepoe a temperatura do motor.
#[derive(Debug, Clone, Copy, Default)]
pub struct RequestTuning {
    pub reasoning_loops: Option<u32>,
    pub max_tokens: Option<usize>,
    pub temperature: Option<f32>,
}

/// Executa a inferencia em streaming, emitindo eventos.
///
/// O cancelamento e imediato: `cancel` e verificado a cada fragmento.
pub async fn generate_streaming(
    engine: &Engine,
    ctx: &ChatContext,
    prompt: &str,
    cancel: Arc<AtomicBool>,
    tx: tokio::sync::mpsc::UnboundedSender<StreamEvent>,
    tuning: RequestTuning,
) -> Result<()> {
    let reasoning_loops = tuning.reasoning_loops;
    let mut messages: Vec<ChatMessage> = Vec::with_capacity(ctx.history.len() + 2);
    if let Some(s) = &ctx.system {
        if !s.trim().is_empty() {
            messages.push(ChatMessage::system(s.clone()));
        }
    }
    messages.extend(ctx.history.iter().cloned());
    messages.push(ChatMessage::user(prompt.to_string()));

    match engine {
        Engine::Svid { engine, config } => {
            // A mascara CJK do checkpoint so vale para prompts que NAO estao em
            // idioma CJK: pedir chines/coreano/japones nunca deve ser mascarado.
            let probe = format!("{}
{}", ctx.system.clone().unwrap_or_default(), prompt);
            engine.set_cjk_suppression(!prompt_has_cjk(&probe));
            // O motor nativo roda em thread dedicada (CPU-bound, nao async).
            let tx2 = tx.clone();
            let cancel2 = cancel.clone();
            let ctx2 = ctx.clone();
            let prompt2 = prompt.to_string();
            let engine2 = engine.clone();
            let mut config2 = config.clone();
            // Profundidade de raciocinio e temperatura efetivas por requisicao.
            if let Some(loops) = tuning.reasoning_loops {
                config2.core_loops = loops.clamp(1, 3);
            }
            if let Some(t) = tuning.temperature {
                if t > 0.0 {
                    config2.temperature = t;
                }
            }
            let max_tokens = tuning.max_tokens;
            let handle = tokio::task::spawn_blocking(move || {
                let mut emitted = 0usize;
                let mut full = String::new();
                let tok = engine2.tokenizer();
                let mut turns: Vec<(String, String)> = Vec::new();
                let mut last_user: Option<String> = None;
                for m in &ctx2.history {
                    if m.role == "user" {
                        last_user = Some(m.content.clone());
                    } else if m.role == "assistant" {
                        if let Some(u) = last_user.take() {
                            turns.push((u, m.content.clone()));
                        }
                    }
                }
                let mut user_text = String::new();
                if let Some(s) = &ctx2.system {
                    if !s.trim().is_empty() {
                        user_text.push_str(s);
                        user_text.push_str("\n\n");
                    }
                }
                if let Some(u) = last_user {
                    user_text.push_str(&u);
                    user_text.push_str("\n\n");
                }
                user_text.push_str(&prompt2);
                let prompt_ids = tok.encode_chat(&turns, &user_text);
                let res = engine2.generate_streaming(
                    &prompt_ids,
                    &config2,
                    cancel2.clone(),
                    |_id, text: &str| -> bool {
                        if cancel2.load(Ordering::Relaxed) {
                            return false;
                        }
                        full.push_str(text);
                        emitted += 1;
                        if tx2.send(StreamEvent::Delta(text.to_string())).is_err() {
                            return false;
                        }
                        !matches!(max_tokens, Some(limit) if emitted >= limit)
                    },
                );
                match res {
                    Ok(()) => {
                        let _ = tx2.send(StreamEvent::Usage {
                            prompt_tokens: None,
                            completion_tokens: None,
                        });
                    }
                    Err(e) => {
                        let _ = tx2.send(StreamEvent::Error(format!("{e:#}")));
                    }
                }
            });
            match handle.await {
                Ok(()) => Ok(()),
                Err(e) => bail!("tarefa do motor nativo falhou: {e}"),
            }
        }
        Engine::Ollama {
            client,
            model,
            config,
        } => {
            let req = CompletionRequest {
                model: model.clone(),
                messages,
                temperature: tuning
                    .temperature
                    .unwrap_or(if reasoning_loops.unwrap_or(2) >= 3 { 0.15 } else { config.temperature }),
                max_tokens: tuning.max_tokens.map(|m| m as u32).unwrap_or(match reasoning_loops
                    .unwrap_or(2)
                {
                    1 => 512,
                    3 => 4096,
                    _ => 2048,
                }),
                top_p: 0.8,
                top_k: 40,
                stream: true,
                seed: config.seed,
                keep_alive: Some("5m".into()),
                extra_options: Default::default(),
            };
            // I/O puro: nada de `spawn_blocking` com runtime aninhado aqui. O
            // `client.stream` roda na runtime async corrente e cada delta vai
            // direto para o canal SSE (antes o runtime aninhado prendia o
            // primeiro chunk e o cliente ficava sem receber bytes).
            let tx2 = tx.clone();
            let cancel2 = cancel.clone();
            let res = client
                .stream_full(
                    &req,
                    cancel.clone(),
                    |chunk| {
                        if cancel2.load(Ordering::Relaxed) {
                            return false;
                        }
                        tx2.send(StreamEvent::Delta(chunk.to_string())).is_ok()
                    },
                    |reasoning| {
                        if cancel2.load(Ordering::Relaxed) {
                            return false;
                        }
                        tx2.send(StreamEvent::Reasoning(reasoning.to_string())).is_ok()
                    },
                )
                .await;
            match res {
                Ok(r) => {
                    let _ = tx.send(StreamEvent::Usage {
                        prompt_tokens: r.prompt_tokens,
                        completion_tokens: r.completion_tokens,
                    });
                }
                Err(e) => {
                    let _ = tx.send(StreamEvent::Error(format!("{e:#}")));
                }
            }
            Ok(())
        }
        Engine::OpenAi {
            client,
            model,
            config,
        } => {
            let req = CompletionRequest {
                model: model.clone(),
                messages,
                temperature: tuning.temperature.unwrap_or(config.temperature),
                max_tokens: tuning.max_tokens.map(|m| m as u32).unwrap_or(2048),
                top_p: 0.8,
                top_k: 40,
                stream: true,
                seed: config.seed,
                keep_alive: None,
                extra_options: Default::default(),
            };
            // I/O puro: nada de `spawn_blocking` com runtime aninhado aqui. O
            // `client.stream` roda na runtime async corrente e cada delta vai
            // direto para o canal SSE (antes o runtime aninhado prendia o
            // primeiro chunk e o cliente ficava sem receber bytes).
            let tx2 = tx.clone();
            let cancel2 = cancel.clone();
            let res = client
                .stream_full(
                    &req,
                    cancel.clone(),
                    |chunk| {
                        if cancel2.load(Ordering::Relaxed) {
                            return false;
                        }
                        tx2.send(StreamEvent::Delta(chunk.to_string())).is_ok()
                    },
                    |reasoning| {
                        if cancel2.load(Ordering::Relaxed) {
                            return false;
                        }
                        tx2.send(StreamEvent::Reasoning(reasoning.to_string())).is_ok()
                    },
                )
                .await;
            match res {
                Ok(r) => {
                    let _ = tx.send(StreamEvent::Usage {
                        prompt_tokens: r.prompt_tokens,
                        completion_tokens: r.completion_tokens,
                    });
                }
                Err(e) => {
                    let _ = tx.send(StreamEvent::Error(format!("{e:#}")));
                }
            }
            Ok(())
        }
    }
}

/// `true` quando o texto tem caracteres CJK (han, hangul, kana, fullwidth).
fn prompt_has_cjk(text: &str) -> bool {
    text.chars().any(|c| {
        let u = c as u32;
        (0x2E80..=0x9FFF).contains(&u)
            || (0xAC00..=0xD7AF).contains(&u)
            || (0xF900..=0xFAFF).contains(&u)
            || (0xFF00..=0xFFEF).contains(&u)
    })
}

/// Constroi o motor para uma entrada de catalogo.
pub fn build_engine(
    entry: &mark_core::ModelEntry,
    inference: &mark_core::InferenceConfig,
    reasoning: mark_core::ReasoningLevel,
) -> Result<Engine> {
    let config = EngineConfig {
        temperature: 0.2,
        top_k: 40,
        seed: inference.seed,
        core_loops: reasoning.core_loops(),
        greedy: false,
    };
    match entry.backend {
        mark_core::Backend::MarkSvid1Bit => {
            let ckpt = mark_core::paths::mark_bin_32b_checkpoint()
                .ok_or_else(|| anyhow::anyhow!("checkpoint Mark-Bin-32B nao encontrado"))?;
            let engine = SvidEngine::load(&ckpt)?;
            Ok(Engine::Svid {
                engine: Arc::new(engine),
                config,
            })
        }
        mark_core::Backend::Ollama => {
            let name = entry
                .id
                .strip_prefix("ollama:")
                .unwrap_or(&entry.name)
                .to_string();
            let client = OllamaClient::new("http://127.0.0.1:11434")?;
            Ok(Engine::Ollama {
                client,
                model: name,
                config,
            })
        }
        mark_core::Backend::OpenAiCompatible => {
            let client = OpenAiClient::new("http://127.0.0.1:1234/v1", None)?;
            Ok(Engine::OpenAi {
                client,
                model: entry.name.clone(),
                config,
            })
        }
        mark_core::Backend::LlamaCppGguf => {
            let path = entry
                .path
                .as_ref()
                .map(std::path::PathBuf::from)
                .ok_or_else(|| anyhow::anyhow!("entrada gguf sem caminho local"))?;
            crate::gguf::prepare_gguf_engine(&path, config)
        }
        mark_core::Backend::MarkSafetensors => {
            let path = entry
                .path
                .as_ref()
                .map(std::path::PathBuf::from)
                .ok_or_else(|| anyhow::anyhow!("entrada safetensors sem caminho local"))?;
            if path.extension().and_then(|e| e.to_str()) == Some("gguf") {
                crate::gguf::prepare_gguf_engine(&path, config)
            } else {
                bail!(
                    "safetensors exige conversao previa: use convert_hf_to_gguf.py em {} e recarregue o catalogo",
                    path.display()
                )
            }
        }
    }
}

/// Reexporta o tipo de resposta para conveniência da GUI.
pub type Response = CompletionResponse;
