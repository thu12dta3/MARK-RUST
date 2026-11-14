//! Thread de trabalho: inferencia, ferramentas e downloads fora da UI.

use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, Sender};
use std::sync::Arc;

use anyhow::{Context, Result};
use serde::Deserialize;

use mark_core::{InferenceConfig, ModelEntry, ReasoningLevel};
use mark_engine::http_backends::ChatMessage;
use mark_engine::{build_engine, generate_streaming, ChatContext, Engine, StreamEvent};

/// Pedido enviado da UI para o worker.
#[derive(Debug)]
pub enum Job {
    LoadModels,
    Chat {
        entry: ModelEntry,
        system: Option<String>,
        history: Vec<(String, String)>,
        prompt: String,
        reasoning: ReasoningLevel,
        max_tokens: u32,
    },
    HfSearch(String),
    HfFiles(String),
    Download {
        repo: String,
        file: String,
        size: u64,
        dest: PathBuf,
    },
}

/// Evento enviado do worker para a UI.
#[derive(Debug, Clone)]
pub enum Ev {
    Models(Vec<ModelEntry>),
    Delta(String),
    Done {
        prompt_tokens: Option<u32>,
        completion_tokens: Option<u32>,
    },
    Error(String),
    HfHits(Vec<HfHit>),
    HfFiles(Vec<HfFile>),
    Progress {
        label: String,
        done: u64,
        total: u64,
    },
    Info(String),
}

/// Resultado de busca no Hugging Face.
#[derive(Debug, Clone, Deserialize)]
pub struct HfHit {
    #[serde(rename = "id", alias = "modelId")]
    pub id: String,
    #[serde(default)]
    pub downloads: u64,
    #[serde(default)]
    #[allow(dead_code)]
    pub likes: u64,
}

/// Arquivo de um repositorio do Hugging Face.
#[derive(Debug, Clone, Deserialize)]
pub struct HfFile {
    pub path: String,
    #[serde(default)]
    pub size: u64,
    #[serde(rename = "type", default)]
    pub kind: String,
}

/// Handle do worker.
pub struct Worker {
    pub tx: Sender<Job>,
    pub cancel: Arc<AtomicBool>,
}

impl Worker {
    /// Inicia o thread de trabalho.
    pub fn spawn(tx_ev: Sender<Ev>) -> Self {
        let (tx, rx) = std::sync::mpsc::channel::<Job>();
        let cancel = Arc::new(AtomicBool::new(false));
        let cancel2 = cancel.clone();
        std::thread::Builder::new()
            .name("mark-worker".into())
            .spawn(move || run(rx, tx_ev, cancel2))
            .expect("thread de trabalho");
        Self { tx, cancel }
    }

    /// Envia um pedido; ignora falha se o worker morreu.
    pub fn send(&self, job: Job) {
        let _ = self.tx.send(job);
    }

    /// Sinaliza parada da geracao em andamento.
    pub fn stop(&self) {
        self.cancel.store(true, Ordering::SeqCst);
    }
}

fn run(rx: Receiver<Job>, tx: Sender<Ev>, cancel: Arc<AtomicBool>) {
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            let _ = tx.send(Ev::Error(format!("runtime tokio: {e}")));
            return;
        }
    };
    let client = reqwest::Client::builder()
        .user_agent("mark-desktop/1.0")
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .ok();

    let mut loaded: Option<(String, Engine)> = None;
    let cfg = InferenceConfig::default();

    while let Ok(job) = rx.recv() {
        match job {
            Job::LoadModels => {
                let mut models = mark_core::models::discover_local_files();
                if let Some(c) = &client {
                    let alive = rt.block_on(async {
                        c.get("http://127.0.0.1:11434/api/tags")
                            .timeout(std::time::Duration::from_secs(2))
                            .send()
                            .await
                            .map(|r| r.status().is_success())
                            .unwrap_or(false)
                    });
                    if alive {
                        let body = rt.block_on(async {
                            c.get("http://127.0.0.1:11434/api/tags")
                                .send()
                                .await
                                .ok()?
                                .text()
                                .await
                                .ok()
                        });
                        if let Some(body) = body {
                            models.extend(mark_core::models::parse_ollama_models(&body));
                        }
                    }
                }
                let _ = tx.send(Ev::Models(models));
            }
            Job::Chat {
                entry,
                system,
                history,
                prompt,
                reasoning,
                max_tokens,
            } => {
                cancel.store(false, Ordering::SeqCst);
                let need = loaded
                    .as_ref()
                    .map(|(id, _)| id != &entry.id)
                    .unwrap_or(true);
                if need {
                    let _ = tx.send(Ev::Info(format!("carregando {}", entry.name)));
                    match build_engine(&entry, &cfg, reasoning) {
                        Ok(engine) => loaded = Some((entry.id.clone(), engine)),
                        Err(e) => {
                            let _ = tx.send(Ev::Error(format!("{e:#}")));
                            continue;
                        }
                    }
                }
                let Some((_, engine)) = loaded.as_ref() else {
                    continue;
                };
                let ctx = ChatContext {
                    system,
                    history: history
                        .iter()
                        .map(|(u, a)| {
                            if a.is_empty() {
                                ChatMessage::user(u.clone())
                            } else {
                                ChatMessage::assistant(format!("{u}\n{a}"))
                            }
                        })
                        .collect(),
                };
                let (tx_stream, mut rx_stream) = tokio::sync::mpsc::unbounded_channel::<StreamEvent>();
                let cancel2 = cancel.clone();
                let cancel3 = cancel.clone();
                let sender = tx.clone();
                rt.block_on(async move {
                    let mut fut = Box::pin(generate_streaming(
                        engine,
                        &ctx,
                        &prompt,
                        cancel2,
                        tx_stream,
                    ));
                    let mut done = false;
                    let mut emitted = 0u32;
                    loop {
                        tokio::select! {
                            ev = rx_stream.recv() => {
                                match ev {
                                    Some(StreamEvent::Delta(d)) => {
                                        emitted += 1;
                                        let _ = sender.send(Ev::Delta(d));
                                        if emitted >= max_tokens.max(1) {
                                            cancel3.store(true, Ordering::SeqCst);
                                        }
                                    }
                                    Some(StreamEvent::Usage { prompt_tokens, completion_tokens }) => {
                                        let _ = sender.send(Ev::Done { prompt_tokens, completion_tokens });
                                    }
                                    Some(StreamEvent::Error(e)) => {
                                        let _ = sender.send(Ev::Error(e));
                                    }
                                    None => break,
                                }
                            }
                            res = &mut fut, if !done => {
                                done = true;
                                if let Err(e) = res {
                                    let _ = sender.send(Ev::Error(format!("{e:#}")));
                                }
                            }
                        }
                    }
                    let _ = sender.send(Ev::Done { prompt_tokens: None, completion_tokens: Some(emitted) });
                });
            }
            Job::HfSearch(query) => {
                let Some(c) = client.clone() else { continue };
                let url = format!(
                    "https://huggingface.co/api/models?search={}&limit=15&sort=downloads&direction=-1",
                    urlencode(&query)
                );
                let res = rt.block_on(async {
                    let r = c.get(&url).send().await?;
                    let hits: Vec<HfHit> = r.json().await?;
                    Ok::<_, reqwest::Error>(hits)
                });
                match res {
                    Ok(hits) => {
                        let _ = tx.send(Ev::HfHits(hits));
                    }
                    Err(e) => {
                        let _ = tx.send(Ev::Error(format!("busca HF: {e}")));
                    }
                }
            }
            Job::HfFiles(repo) => {
                let Some(c) = client.clone() else { continue };
                let url = format!("https://huggingface.co/api/models/{repo}/tree/main?recursive=true");
                let res = rt.block_on(async {
                    let r = c.get(&url).send().await?;
                    let mut files: Vec<HfFile> = r.json().await?;
                    files.retain(|f| f.kind != "directory");
                    Ok::<_, reqwest::Error>(files)
                });
                match res {
                    Ok(mut files) => {
                        files.sort_by_key(|f| std::cmp::Reverse(f.size));
                        let _ = tx.send(Ev::HfFiles(files));
                    }
                    Err(e) => {
                        let _ = tx.send(Ev::Error(format!("arquivos HF: {e}")));
                    }
                }
            }
            Job::Download {
                repo,
                file,
                size,
                dest,
            } => {
                let Some(c) = client.clone() else { continue };
                let label = file.clone();
                match rt.block_on(download(&c, &repo, &file, size, &dest, &tx, &label, &cancel)) {
                    Ok(()) => {
                        let _ = tx.send(Ev::Info(format!("baixado: {}", dest.display())));
                    }
                    Err(e) => {
                        let _ = tx.send(Ev::Error(format!("download: {e:#}")));
                    }
                }
            }
        }
    }
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

#[allow(clippy::too_many_arguments)]
async fn download(
    client: &reqwest::Client,
    repo: &str,
    file: &str,
    size: u64,
    dest: &PathBuf,
    tx: &Sender<Ev>,
    label: &str,
    cancel: &Arc<AtomicBool>,
) -> Result<()> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let part = dest.with_extension(format!(
        "{}part",
        dest.extension()
            .and_then(|e| e.to_str())
            .map(|e| format!("{e}."))
            .unwrap_or_default()
    ));
    let mut have = std::fs::metadata(&part).map(|m| m.len()).unwrap_or(0);
    if size > 0 && have >= size {
        std::fs::rename(&part, dest)?;
        return Ok(());
    }
    let url = format!("https://huggingface.co/{repo}/resolve/main/{file}");
    let mut req = client.get(&url);
    if have > 0 {
        req = req.header("range", format!("bytes={have}-"));
    }
    let mut resp = req.send().await.context("abrindo download")?;
    if !resp.status().is_success() {
        anyhow::bail!("HTTP {}", resp.status());
    }
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&part)?;
    let mut last = std::time::Instant::now();
    while let Some(chunk) = resp.chunk().await? {
        if cancel.load(Ordering::SeqCst) {
            anyhow::bail!("cancelado");
        }
        f.write_all(&chunk)?;
        have += chunk.len() as u64;
        if last.elapsed() >= std::time::Duration::from_millis(300) {
            let _ = tx.send(Ev::Progress {
                label: label.to_string(),
                done: have,
                total: if size > 0 { size } else { have },
            });
            last = std::time::Instant::now();
        }
    }
    f.flush()?;
    std::fs::rename(&part, dest)?;
    let _ = tx.send(Ev::Progress {
        label: label.to_string(),
        done: have,
        total: have,
    });
    Ok(())
}
