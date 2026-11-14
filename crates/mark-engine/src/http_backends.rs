//! Backends HTTP de inferencia: Ollama e endpoints OpenAI-compatible.

use anyhow::{bail, Context, Result};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};

/// Uma mensagem de conversa.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

impl ChatMessage {
    /// Cria mensagem de sistema.
    pub fn system(content: impl Into<String>) -> Self {
        Self {
            role: "system".into(),
            content: content.into(),
        }
    }
    /// Cria mensagem de usuario.
    pub fn user(content: impl Into<String>) -> Self {
        Self {
            role: "user".into(),
            content: content.into(),
        }
    }
    /// Cria mensagem de assistente.
    pub fn assistant(content: impl Into<String>) -> Self {
        Self {
            role: "assistant".into(),
            content: content.into(),
        }
    }
}

/// Opcoes de uma requisicao de inferencia.
#[derive(Debug, Clone)]
pub struct CompletionRequest {
    pub model: String,
    pub messages: Vec<ChatMessage>,
    pub temperature: f32,
    pub max_tokens: u32,
    pub top_p: f32,
    pub top_k: u32,
    pub stream: bool,
    pub seed: Option<u64>,
    pub keep_alive: Option<String>,
    /// Payload extra enviado como `options` (Ollama) ou `extra_body`.
    pub extra_options: std::collections::BTreeMap<String, serde_json::Value>,
}

impl Default for CompletionRequest {
    fn default() -> Self {
        Self {
            model: String::new(),
            messages: Vec::new(),
            temperature: 0.7,
            max_tokens: 2048,
            top_p: 0.8,
            top_k: 20,
            stream: true,
            seed: None,
            keep_alive: None,
            extra_options: Default::default(),
        }
    }
}

/// Resposta de inferencia.
#[derive(Debug, Clone)]
pub struct CompletionResponse {
    pub content: String,
    pub model: String,
    pub prompt_tokens: Option<u32>,
    pub completion_tokens: Option<u32>,
}

/// Cliente Ollama via HTTP.
#[derive(Clone)]
pub struct OllamaClient {
    base_url: String,
    http: reqwest::Client,
}

impl OllamaClient {
    /// Cria cliente apontando para `base_url` (ex.: `http://127.0.0.1:11434`).
    pub fn new(base_url: &str) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(600))
            .build()?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            http,
        })
    }

    /// Verifica se o daemon responde.
    pub async fn is_alive(&self) -> bool {
        self.http
            .get(format!("{}/api/tags", self.base_url))
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false)
    }

    /// Lista os modelos instalados (JSON cru da API).
    pub async fn list_models_raw(&self) -> Result<String> {
        let text = self
            .http
            .get(format!("{}/api/tags", self.base_url))
            .send()
            .await
            .context("falha ao contacting o daemon Ollama")?
            .text()
            .await?;
        Ok(text)
    }

    /// Gera uma resposta (nao-streaming).
    pub async fn complete(&self, req: &CompletionRequest) -> Result<CompletionResponse> {
        let mut options = serde_json::Map::new();
        options.insert("temperature".into(), req.temperature.into());
        options.insert("top_p".into(), req.top_p.into());
        options.insert("top_k".into(), req.top_k.into());
        options.insert("num_predict".into(), req.max_tokens.into());
        for (k, v) in &req.extra_options {
            options.insert(k.clone(), v.clone());
        }
        let mut body = serde_json::json!({
            "model": req.model,
            "messages": req.messages,
            "stream": false,
            "options": serde_json::Value::Object(options),
        });
        if let Some(ka) = &req.keep_alive {
            body["keep_alive"] = serde_json::Value::String(ka.clone());
        }
        if let Some(seed) = req.seed {
            body["options"]["seed"] = serde_json::Value::from(seed);
        }

        let value: serde_json::Value = self
            .http
            .post(format!("{}/api/chat", self.base_url))
            .json(&body)
            .send()
            .await
            .context("falha na requisicao ao Ollama")?
            .error_for_status()
            .context("Ollama respondeu com erro")?
            .json()
            .await?;

        let content = value
            .get("message")
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or_default()
            .to_string();
        Ok(CompletionResponse {
            content,
            model: value
                .get("model")
                .and_then(|m| m.as_str())
                .unwrap_or(&req.model)
                .to_string(),
            prompt_tokens: value
                .get("prompt_eval_count")
                .and_then(|v| v.as_u64())
                .map(|v| v as u32),
            completion_tokens: value
                .get("eval_count")
                .and_then(|v| v.as_u64())
                .map(|v| v as u32),
        })
    }

    /// Gera uma resposta em streaming, emitindo fragments.
    pub async fn stream(
        &self,
        req: &CompletionRequest,
        cancel: std::sync::Arc<std::sync::atomic::AtomicBool>,
        mut on_chunk: impl FnMut(&str) -> bool,
    ) -> Result<CompletionResponse> {
        let mut options = serde_json::Map::new();
        options.insert("temperature".into(), req.temperature.into());
        options.insert("top_p".into(), req.top_p.into());
        options.insert("top_k".into(), req.top_k.into());
        options.insert("num_predict".into(), req.max_tokens.into());
        for (k, v) in &req.extra_options {
            options.insert(k.clone(), v.clone());
        }
        let mut body = serde_json::json!({
            "model": req.model,
            "messages": req.messages,
            "stream": true,
            "options": serde_json::Value::Object(options),
        });
        if let Some(ka) = &req.keep_alive {
            body["keep_alive"] = serde_json::Value::String(ka.clone());
        }

        let resp = self
            .http
            .post(format!("{}/api/chat", self.base_url))
            .json(&body)
            .send()
            .await
            .context("falha na requisicao de streaming ao Ollama")?;
        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            bail!("Ollama respondeu {status}: {body}");
        }

        let mut stream = resp.bytes_stream();
        let mut buf = String::new();
        let mut full = String::new();
        while let Some(item) = stream.next().await {
            if cancel.load(std::sync::atomic::Ordering::Relaxed) {
                break;
            }
            let bytes = item.context("falha ao ler o stream do Ollama")?;
            buf.push_str(&String::from_utf8_lossy(&bytes));
            while let Some(pos) = buf.find('\n') {
                let line = buf[..pos].trim().to_string();
                buf.drain(..=pos);
                if line.is_empty() {
                    continue;
                }
                let Ok(v) = serde_json::from_str::<serde_json::Value>(&line) else {
                    continue;
                };
                if let Some(msg) = v.get("message").and_then(|m| m.get("content")).and_then(|c| c.as_str())
                {
                    full.push_str(msg);
                    if !on_chunk(msg) {
                        return Ok(CompletionResponse {
                            content: full,
                            model: req.model.clone(),
                            prompt_tokens: None,
                            completion_tokens: None,
                        });
                    }
                }
                if v.get("done").and_then(|d| d.as_bool()) == Some(true) {
                    return Ok(CompletionResponse {
                        content: full,
                        model: req.model.clone(),
                        prompt_tokens: None,
                        completion_tokens: None,
                    });
                }
            }
        }
        Ok(CompletionResponse {
            content: full,
            model: req.model.clone(),
            prompt_tokens: None,
            completion_tokens: None,
        })
    }
}

/// Cliente de qualquer endpoint OpenAI-compatible (LM Studio, vLLM, llama-server).
#[derive(Clone)]
pub struct OpenAiClient {
    base_url: String,
    api_key: Option<String>,
    http: reqwest::Client,
}

impl OpenAiClient {
    /// Cria cliente. `api_key` e opcional para endpoints locais.
    pub fn new(base_url: &str, api_key: Option<String>) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(600))
            .build()?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key,
            http,
        })
    }

    fn auth(&self, rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        match &self.api_key {
            Some(k) if !k.is_empty() => rb.bearer_auth(k),
            _ => rb,
        }
    }

    /// Verifica se o endpoint responde.
    pub async fn is_alive(&self) -> bool {
        self.auth(self.http.get(format!("{}/models", self.base_url)))
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false)
    }

    /// Lista os modelos disponiveis (JSON cru).
    pub async fn list_models_raw(&self) -> Result<String> {
        let text = self
            .auth(self.http.get(format!("{}/models", self.base_url)))
            .send()
            .await
            .context("falha ao consultar /models")?
            .text()
            .await?;
        Ok(text)
    }

    /// Gera uma resposta.
    pub async fn complete(&self, req: &CompletionRequest) -> Result<CompletionResponse> {
        let mut body = serde_json::json!({
            "model": req.model,
            "messages": req.messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "top_p": req.top_p,
            "stream": false,
        });
        if let Some(seed) = req.seed {
            body["seed"] = serde_json::Value::from(seed);
        }
        let value: serde_json::Value = self
            .auth(self.http.post(format!("{}/chat/completions", self.base_url)))
            .json(&body)
            .send()
            .await
            .context("falha na requisicao ao endpoint OpenAI-compatible")?
            .error_for_status()
            .context("endpoint OpenAI-compatible respondeu com erro")?
            .json()
            .await?;

        let content = value
            .get("choices")
            .and_then(|c| c.as_array())
            .and_then(|a| a.first())
            .and_then(|c| c.get("message"))
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or_default()
            .to_string();
        let usage = value.get("usage");
        Ok(CompletionResponse {
            content,
            model: value
                .get("model")
                .and_then(|m| m.as_str())
                .unwrap_or(&req.model)
                .to_string(),
            prompt_tokens: usage
                .and_then(|u| u.get("prompt_tokens"))
                .and_then(|v| v.as_u64())
                .map(|v| v as u32),
            completion_tokens: usage
                .and_then(|u| u.get("completion_tokens"))
                .and_then(|v| v.as_u64())
                .map(|v| v as u32),
        })
    }

    /// Gera uma resposta em streaming (SSE).
    pub async fn stream(
        &self,
        req: &CompletionRequest,
        cancel: std::sync::Arc<std::sync::atomic::AtomicBool>,
        mut on_chunk: impl FnMut(&str) -> bool,
    ) -> Result<CompletionResponse> {
        let mut body = serde_json::json!({
            "model": req.model,
            "messages": req.messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "top_p": req.top_p,
            "stream": true,
        });
        if let Some(seed) = req.seed {
            body["seed"] = serde_json::Value::from(seed);
        }

        let resp = self
            .auth(self.http.post(format!("{}/chat/completions", self.base_url)))
            .json(&body)
            .send()
            .await
            .context("falha na requisicao de streaming")?
            .error_for_status()
            .context("endpoint OpenAI-compatible respondeu com erro")?;

        let mut stream = resp.bytes_stream();
        let mut buf = String::new();
        let mut full = String::new();
        while let Some(item) = stream.next().await {
            if cancel.load(std::sync::atomic::Ordering::Relaxed) {
                break;
            }
            let bytes = item.context("falha ao ler o stream SSE")?;
            buf.push_str(&String::from_utf8_lossy(&bytes));
            while let Some(pos) = buf.find('\n') {
                let line = buf[..pos].trim().to_string();
                buf.drain(..=pos);
                if line.is_empty() {
                    continue;
                }
                let Some(payload) = line.strip_prefix("data:") else {
                    continue;
                };
                let payload = payload.trim();
                if payload == "[DONE]" {
                    return Ok(CompletionResponse {
                        content: full,
                        model: req.model.clone(),
                        prompt_tokens: None,
                        completion_tokens: None,
                    });
                }
                let Ok(v) = serde_json::from_str::<serde_json::Value>(payload) else {
                    continue;
                };
                let delta = v
                    .get("choices")
                    .and_then(|c| c.as_array())
                    .and_then(|a| a.first())
                    .and_then(|c| c.get("delta"))
                    .and_then(|d| d.get("content"))
                    .and_then(|c| c.as_str());
                if let Some(d) = delta {
                    full.push_str(d);
                    if !on_chunk(d) {
                        return Ok(CompletionResponse {
                            content: full,
                            model: req.model.clone(),
                            prompt_tokens: None,
                            completion_tokens: None,
                        });
                    }
                }
            }
        }
        Ok(CompletionResponse {
            content: full,
            model: req.model.clone(),
            prompt_tokens: None,
            completion_tokens: None,
        })
    }
}

/// Extrai a lista de modelos de uma resposta `/models` OpenAI-compatible.
pub fn parse_openai_models(json: &str) -> Vec<String> {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(json) else {
        return Vec::new();
    };
    v.get("data")
        .and_then(|d| d.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m.get("id").and_then(|i| i.as_str()))
                .map(|s| s.to_string())
                .collect()
        })
        .unwrap_or_default()
}

/// Verifica se um arquivo e um GGUF valido (magic `GGUF`).
pub fn is_gguf(path: &std::path::Path) -> bool {
    use std::io::Read;
    let Ok(mut f) = std::fs::File::open(path) else {
        return false;
    };
    let mut magic = [0u8; 4];
    if f.read_exact(&mut magic).is_err() {
        return false;
    }
    if &magic == b"GGUF" {
        return true;
    }
    // TinyLlama usa "GGUF" tambem; alguns usam little-endian "FUGG".
    &magic == b"FUGG"
}

/// Le o campo `general.architecture` de um GGUF.
pub fn gguf_architecture(path: &std::path::Path) -> Result<String> {
    use std::io::Read;
    let mut f = std::fs::File::open(path).context("abrindo GGUF")?;
    let mut magic = [0u8; 4];
    f.read_exact(&mut magic)?;
    if &magic != b"GGUF" {
        bail!("arquivo nao e um GGUF valido");
    }
    let mut ver = [0u8; 4];
    f.read_exact(&mut ver)?;
    let version = u32::from_le_bytes(ver);
    // v1: u32 n_tensors, u32 n_kv; v2: u64 n_tensors, u64 n_kv; v3: u64,u64
    let (n_kv, kv_len) = match version {
        1 => {
            let mut b = [0u8; 8];
            f.read_exact(&mut b)?;
            (u32::from_le_bytes(b[4..8].try_into().unwrap()) as u64, 4usize)
        }
        _ => {
            let mut b = [0u8; 16];
            f.read_exact(&mut b)?;
            (u64::from_le_bytes(b[8..16].try_into().unwrap()), 8usize)
        }
    };
    let mut _n_tensors = [0u8; 8];
    f.read_exact(&mut _n_tensors)?;

    let read_string = |f: &mut std::fs::File| -> Result<String> {
        let mut lb = [0u8; 8];
        f.read_exact(&mut lb)?;
        let len = u64::from_le_bytes(lb) as usize;
        let mut s = vec![0u8; len];
        f.read_exact(&mut s)?;
        Ok(String::from_utf8_lossy(&s).into_owned())
    };

    for _ in 0..n_kv {
        let key = read_string(&mut f)?;
        let vtype = {
            let mut t = [0u8; 4];
            f.read_exact(&mut t)?;
            u32::from_le_bytes(t)
        };
        // String = 1
        if vtype == 1 {
            let val = read_string(&mut f)?;
            if key == "general.architecture" {
                return Ok(val);
            }
        } else {
            // Pula o valor conforme o tipo.
            let size = match vtype {
                0 => 1,   // UINT8
                1 => 0,   // STRING (tratado acima)
                2 => 2,   // INT16
                3 => 4,   // INT32
                4 => 8,   // FLOAT32
                5 => 1,   // BOOL
                6 => 8,   // STRING (array)
                7 => 8,   // INT64
                10 => 8,  // FLOAT64
                12 => 8,  // ARRAY (depende)
                _ => bail!("tipo de valor GGUF desconhecido: {vtype}"),
            };
            if vtype == 1 {
                continue;
            }
            if vtype == 12 {
                // ARRAY: le tipo do elemento + comprimento + dados.
                let et = {
                    let mut t = [0u8; 4];
                    f.read_exact(&mut t)?;
                    u32::from_le_bytes(t)
                };
                let elen = {
                    let mut t = [0u8; 8];
                    f.read_exact(&mut t)?;
                    u64::from_le_bytes(t)
                } as usize;
                let esize = match et {
                    0 | 1 | 5 | 6 | 7 => 1,
                    2 => 2,
                    3 | 4 => 4,
                    10 => 8,
                    _ => bail!("tipo de array GGUF desconhecido: {et}"),
                };
                let mut skip = vec![0u8; elen * esize];
                f.read_exact(&mut skip)?;
                continue;
            }
            let mut skip = vec![0u8; size];
            f.read_exact(&mut skip)?;
        }
        let _ = kv_len;
    }
    bail!("campo general.architecture nao encontrado no GGUF")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chat_message_roles_are_valid() {
        assert_eq!(ChatMessage::user("oi").role, "user");
        assert_eq!(ChatMessage::system("s").role, "system");
        assert_eq!(ChatMessage::assistant("a").role, "assistant");
    }

    #[test]
    fn parse_openai_models_extracts_ids() {
        let json = r#"{"data":[{"id":"a"},{"id":"b"}]}"#;
        assert_eq!(parse_openai_models(json), vec!["a", "b"]);
        assert!(parse_openai_models("lixo").is_empty());
    }

    #[test]
    fn is_gguf_rejects_non_gguf() {
        let p = std::env::temp_dir().join(format!("not_gguf_{}.bin", uuid::Uuid::new_v4()));
        std::fs::write(&p, b"NOTGGUF-data").unwrap();
        assert!(!is_gguf(&p));
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn is_gguf_accepts_magic() {
        let p = std::env::temp_dir().join(format!("gguf_{}.bin", uuid::Uuid::new_v4()));
        let mut data = b"GGUF".to_vec();
        data.extend_from_slice(&3u32.to_le_bytes());
        data.extend_from_slice(&0u64.to_le_bytes());
        data.extend_from_slice(&0u64.to_le_bytes());
        std::fs::write(&p, &data).unwrap();
        assert!(is_gguf(&p));
        let _ = std::fs::remove_file(&p);
    }
}
