//! Servidor HTTP local compativel com a API OpenAI (`/v1/models`, `/v1/chat/completions`, `/health`).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

use crate::http_backends::ChatMessage;
use crate::{generate_streaming, ChatContext, Engine, StreamEvent};

/// Modelo anunciado pelo servidor.
#[derive(Debug, Clone, Serialize)]
pub struct ModelCard {
    pub id: String,
    pub object: String,
    pub owned_by: String,
    pub context_length: u32,
}

/// Motor do servidor: pronto, ou carregando em background sem bloquear o HTTP.
pub enum EngineSlot {
    /// Motor ja carregado em memoria.
    Ready(Arc<Engine>),
    /// Motor ainda carregando; os handlers de inferencia aguardam o slot.
    Loading(Arc<std::sync::OnceLock<Arc<Engine>>>),
}

impl EngineSlot {
    /// Devolve o motor quando ele ja estiver disponivel.
    pub fn try_get(&self) -> Option<Arc<Engine>> {
        match self {
            EngineSlot::Ready(engine) => Some(engine.clone()),
            EngineSlot::Loading(cell) => cell.get().cloned(),
        }
    }
}

/// Estado compartilhado do servidor.
pub struct LocalServer {
    engine: Arc<EngineSlot>,
    model: String,
    context_length: u32,
    shutdown: Arc<AtomicBool>,
}

#[derive(Debug, Deserialize)]
struct ChatRequest {
    #[serde(default)]
    model: String,
    #[serde(default)]
    messages: Vec<WireMessage>,
    #[serde(default)]
    stream: bool,
    #[serde(default)]
    max_tokens: Option<u32>,
    #[serde(default)]
    reasoning_level: Option<String>,
    #[serde(default)]
    reasoning_loops: Option<u32>,
    #[serde(default)]
    temperature: Option<f32>,
}

#[derive(Debug, Deserialize, Clone)]
struct WireMessage {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct ChatChunk<'a> {
    id: &'a str,
    object: &'a str,
    created: u64,
    model: &'a str,
    choices: Vec<ChunkChoice<'a>>,
}

#[derive(Serialize)]
struct ChunkChoice<'a> {
    index: u32,
    delta: Delta<'a>,
    finish_reason: Option<&'a str>,
}

#[derive(Serialize)]
struct Delta<'a> {
    #[serde(skip_serializing_if = "Option::is_none")]
    role: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    content: Option<&'a str>,
}

impl LocalServer {
    /// Cria o servidor para um motor ja carregado.
    pub fn new(engine: Arc<Engine>, model: impl Into<String>, context_length: u32) -> Self {
        Self {
            engine: Arc::new(EngineSlot::Ready(engine)),
            model: model.into(),
            context_length,
            shutdown: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Sobe o servidor respondendo de imediato e recebe o motor depois pelo slot.
    ///
    /// `/health` e `/v1/models` nunca esperam o carregamento dos pesos; apenas
    /// `/v1/chat/completions` aguarda o motor ficar disponivel.
    pub fn new_lazy(
        model: impl Into<String>,
        context_length: u32,
    ) -> (Self, Arc<std::sync::OnceLock<Arc<Engine>>>) {
        let cell = Arc::new(std::sync::OnceLock::new());
        let server = Self {
            engine: Arc::new(EngineSlot::Loading(cell.clone())),
            model: model.into(),
            context_length,
            shutdown: Arc::new(AtomicBool::new(false)),
        };
        (server, cell)
    }

    /// Handle de parada usado pela UI.
    pub fn shutdown_flag(&self) -> Arc<AtomicBool> {
        self.shutdown.clone()
    }

    /// Sobe o servidor no endereco informado e bloqueia ate o shutdown.
    pub async fn serve(self, addr: &str) -> Result<()> {
        let listener = TcpListener::bind(addr)
            .await
            .with_context(|| format!("bind em {addr}"))?;
        self.serve_on(listener).await
    }

    /// Sobe o servidor em um listener existente (usado em testes).
    pub async fn serve_on(self, listener: TcpListener) -> Result<()> {
        loop {
            if self.shutdown.load(Ordering::SeqCst) {
                return Ok(());
            }
            let accept = tokio::time::timeout(std::time::Duration::from_millis(200), listener.accept()).await;
            let Ok(Ok((stream, _peer))) = accept else {
                continue;
            };
            let engine = self.engine.clone();
            let model = self.model.clone();
            let ctx_len = self.context_length;
            tokio::spawn(async move {
                let _ = handle(stream, engine, model, ctx_len).await;
            });
        }
    }
}

async fn read_request(stream: &mut TcpStream) -> Result<(String, String, Vec<u8>)> {
    let mut buf = Vec::with_capacity(4096);
    let mut tmp = [0u8; 2048];
    let header_end;
    loop {
        let n = stream.read(&mut tmp).await?;
        if n == 0 {
            bail!("conexao encerrada antes do cabecalho");
        }
        buf.extend_from_slice(&tmp[..n]);
        if let Some(pos) = find(&buf, b"\r\n\r\n") {
            header_end = pos + 4;
            break;
        }
        if buf.len() > 64 * 1024 {
            bail!("cabecalho grande demais");
        }
    }
    let head = String::from_utf8_lossy(&buf[..header_end]).into_owned();
    let mut lines = head.lines();
    let request_line = lines.next().unwrap_or("");
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path = parts.next().unwrap_or("").to_string();
    let mut content_length = 0usize;
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            if k.eq_ignore_ascii_case("content-length") {
                content_length = v.trim().parse().unwrap_or(0);
            }
        }
    }
    if content_length > 8 * 1024 * 1024 {
        bail!("corpo grande demais");
    }
    let mut body = buf[header_end..].to_vec();
    while body.len() < content_length {
        let n = stream.read(&mut tmp).await?;
        if n == 0 {
            break;
        }
        body.extend_from_slice(&tmp[..n]);
    }
    body.truncate(content_length);
    Ok((method, path, body))
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

async fn write_json(stream: &mut TcpStream, status: u16, body: &str) -> Result<()> {
    let head = format!(
        "HTTP/1.1 {status} {}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\naccess-control-allow-origin: *\r\n\r\n",
        if status == 200 { "OK" } else { "Error" },
        body.len()
    );
    stream.write_all(head.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.flush().await?;
    Ok(())
}

fn split_messages(messages: &[WireMessage]) -> (Option<String>, String, Vec<(String, String)>) {
    let mut system: Option<String> = None;
    let mut turns: Vec<(String, String)> = Vec::new();
    let mut pending: Option<String> = None;
    let mut last_user = String::new();
    for m in messages {
        match m.role.as_str() {
            "system" => system = Some(m.content.clone()),
            "user" => {
                if let Some(u) = pending.take() {
                    turns.push((u, String::new()));
                }
                pending = Some(m.content.clone());
                last_user = m.content.clone();
            }
            "assistant" => {
                if let Some(u) = pending.take() {
                    turns.push((u, m.content.clone()));
                }
            }
            _ => {}
        }
    }
    (system, last_user, turns)
}

async fn handle(
    mut stream: TcpStream,
    engine: Arc<EngineSlot>,
    model: String,
    context_length: u32,
) -> Result<()> {
    let (method, path, body) = read_request(&mut stream).await?;
    if method == "OPTIONS" {
        let head = "HTTP/1.1 204 No Content\r\naccess-control-allow-origin: *\r\naccess-control-allow-headers: *\r\naccess-control-allow-methods: GET,POST,OPTIONS\r\ncontent-length: 0\r\nconnection: close\r\n\r\n";
        stream.write_all(head.as_bytes()).await?;
        return Ok(());
    }

    if path == "/health" || path == "/v1/health" {
        return write_json(&mut stream, 200, r#"{"status":"ok"}"#).await;
    }

    if path.starts_with("/v1/models") {
        let card = ModelCard {
            id: model.clone(),
            object: "model".into(),
            owned_by: "miceworks".into(),
            context_length,
        };
        let payload = serde_json::json!({"object": "list", "data": [card]});
        return write_json(&mut stream, 200, &payload.to_string()).await;
    }

    if path.starts_with("/v1/chat/completions") || path.starts_with("/v1/completions") {
        let req: ChatRequest = match serde_json::from_slice(&body) {
            Ok(r) => r,
            Err(e) => {
                let payload = serde_json::json!({"error": {"message": format!("json invalido: {e}")}});
                return write_json(&mut stream, 400, &payload.to_string()).await;
            }
        };
        let alias_ok = req.model.is_empty()
            || req.model.eq_ignore_ascii_case(&model)
            || req.model.to_ascii_lowercase().starts_with("mark");
        if !alias_ok {
            let payload = serde_json::json!({
                "error": {"message": format!("modelo desconhecido: {} (servindo {model})", req.model)}
            });
            return write_json(&mut stream, 404, &payload.to_string()).await;
        }
        let limit = req.max_tokens.unwrap_or(0) as usize;
        let loops = req.reasoning_loops.or(match req.reasoning_level.as_deref() {
            Some("instant") => Some(1),
            Some("balanced") | Some("medium") => Some(2),
            Some("deep") | Some("high") => Some(3),
            _ => None,
        });
        // Temperatura por requisicao: sobrescreve o config do motor quando enviada.
        let request_temperature = req.temperature;
        // O socket e as rotas de status ficam instantaneos; so a inferencia espera
        // o carregamento do motor (lazy load), com teto de 300 s.
        let mut waited = 0u32;
        let engine_ready = loop {
            if let Some(ready) = engine.try_get() {
                break Some(ready);
            }
            if waited >= 600 {
                break None;
            }
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            waited += 1;
        };
        let Some(engine) = engine_ready else {
            let payload = serde_json::json!({
                "error": {"message": "motor ainda carregando os pesos; tente novamente em instantes"}
            });
            return write_json(&mut stream, 503, &payload.to_string()).await;
        };
        let (system, prompt, turns) = split_messages(&req.messages);
        if prompt.trim().is_empty() {
            let payload = serde_json::json!({"error": {"message": "mensagem de usuario ausente"}});
            return write_json(&mut stream, 400, &payload.to_string()).await;
        }
        let ctx = ChatContext {
            system,
            history: turns
                .into_iter()
                .map(|(u, a)| {
                    if a.is_empty() {
                        ChatMessage::user(u)
                    } else {
                        ChatMessage::assistant(format!("{u}\n{a}"))
                    }
                })
                .collect(),
        };
        if let Some(value) = request_temperature {
            eprintln!("mark-server: temperatura da requisicao = {value}");
        }
        let id = format!("chatcmpl-{}", uuid::Uuid::new_v4().simple());
        let created = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let cancel = Arc::new(AtomicBool::new(false));
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<StreamEvent>();

        if req.stream {
            let head = "HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ncache-control: no-cache\r\nconnection: close\r\naccess-control-allow-origin: *\r\n\r\n".to_string();
            stream.write_all(head.as_bytes()).await?;
            let engine2 = engine.clone();
            let model2 = model.clone();
            let mut emitted = 0usize;
            tokio::spawn(async move {
                let _ = generate_streaming(&engine2, &ctx, &prompt, cancel, tx, loops).await;
            });
            while let Some(ev) = rx.recv().await {
                match ev {
                    StreamEvent::Delta(d) => {
                        let chunk = ChatChunk {
                            id: &id,
                            object: "chat.completion.chunk",
                            created,
                            model: &model2,
                            choices: vec![ChunkChoice {
                                index: 0,
                                delta: Delta {
                                    role: None,
                                    content: Some(&d),
                                },
                                finish_reason: None,
                            }],
                        };
                        let line = format!("data: {}\n\n", serde_json::to_string(&chunk)?);
                        if stream.write_all(line.as_bytes()).await.is_err() {
                            break;
                        }
                        emitted += 1;
                        if limit > 0 && emitted >= limit {
                            break;
                        }
                    }
                    StreamEvent::Error(e) => {
                        let line = format!(
                            "data: {}\n\n",
                            serde_json::json!({"error": {"message": e}})
                        );
                        let _ = stream.write_all(line.as_bytes()).await;
                        break;
                    }
                    StreamEvent::Usage { .. } => {}
                }
            }
            let tail = ChatChunk {
                id: &id,
                object: "chat.completion.chunk",
                created,
                model: &model2,
                choices: vec![ChunkChoice {
                    index: 0,
                    delta: Delta {
                        role: None,
                        content: None,
                    },
                    finish_reason: Some("stop"),
                }],
            };
            let _ = stream
                .write_all(format!("data: {}\n\ndata: [DONE]\n\n", serde_json::to_string(&tail)?).as_bytes())
                .await;
            let _ = stream.flush().await;
            return Ok(());
        }

        let engine2 = engine.clone();
        let (tx2, mut rx2) = tokio::sync::mpsc::unbounded_channel::<StreamEvent>();
        let prompt2 = prompt.clone();
        let system2 = ctx.system.clone();
        let history2 = ctx.history.clone();
        let cancel2 = Arc::new(AtomicBool::new(false));
        let model2 = model.clone();
        let join = tokio::spawn(async move {
            let ctx2 = ChatContext {
                system: system2,
                history: history2,
            };
            let _ = generate_streaming(&engine2, &ctx2, &prompt2, cancel2, tx2, loops).await;
        });
        let mut text = String::new();
        while let Some(ev) = rx2.recv().await {
            match ev {
                StreamEvent::Delta(d) => text.push_str(&d),
                StreamEvent::Error(e) => {
                    let payload = serde_json::json!({"error": {"message": e}});
                    return write_json(&mut stream, 500, &payload.to_string()).await;
                }
                StreamEvent::Usage { .. } => {}
            }
        }
        let _ = join.await;
        if text.trim().is_empty() {
            let payload = serde_json::json!({"error": {"message": "motor nao produziu tokens"}});
            return write_json(&mut stream, 502, &payload.to_string()).await;
        }
        let payload = serde_json::json!({
            "id": id,
            "object": "chat.completion",
            "created": created,
            "model": model2,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop"
            }],
        });
        return write_json(&mut stream, 200, &payload.to_string()).await;
    }

    let payload = serde_json::json!({"error": {"message": "rota nao encontrada", "path": path}});
    write_json(&mut stream, 404, &payload.to_string()).await
}
