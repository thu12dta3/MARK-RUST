use std::sync::atomic::Ordering;
use std::sync::Arc;

use futures_util::StreamExt;
use mark_engine::http_backends::OllamaClient;
use mark_engine::server::LocalServer;
use mark_engine::svid::EngineConfig;
use mark_engine::Engine;

const OLLAMA_MODEL: &str = "deepseek-r1:8b-q3_k_l";

fn client_rt() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime de teste")
}

#[test]
fn local_server_serves_openai_api() {
    let client = match OllamaClient::new("http://127.0.0.1:11434") {
        Ok(c) => c,
        Err(e) => {
            eprintln!("ollama indisponivel: {e}");
            return;
        }
    };
    let rt = client_rt();
    if !rt.block_on(client.is_alive()) {
        eprintln!("daemon ollama nao esta rodando: teste ignorado");
        return;
    }

    let engine = Arc::new(Engine::Ollama {
        client,
        model: OLLAMA_MODEL.to_string(),
        config: EngineConfig::default(),
    });
    let server = LocalServer::new(engine, OLLAMA_MODEL, 32_768);
    let shutdown = server.shutdown_flag();

    let server_rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("runtime do servidor");

    let addr = rt.block_on(async {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let handle = server_rt.spawn(async move { server.serve_on(listener).await });
        (addr, handle)
    });

    let (addr, handle) = addr;
    let base = format!("http://{addr}");

    let health = rt.block_on(async {
        reqwest::get(format!("{base}/health"))
            .await
            .expect("health deve responder")
    });
    assert_eq!(health.status(), 200);
    let body = rt.block_on(health.text()).unwrap();
    assert!(body.contains("\"ok\""), "resposta inesperada: {body}");

    let models = rt.block_on(async {
        reqwest::get(format!("{base}/v1/models"))
            .await
            .expect("/v1/models deve responder")
    });
    assert_eq!(models.status(), 200);
    let body = rt.block_on(models.text()).unwrap();
    assert!(body.contains(OLLAMA_MODEL), "modelo ausente: {body}");
    assert!(body.contains("\"object\":\"list\""), "payload inesperado: {body}");

    let bad = rt.block_on(async {
        reqwest::Client::new()
            .post(format!("{base}/v1/chat/completions"))
            .json(&serde_json::json!({"model": OLLAMA_MODEL, "messages": []}))
            .send()
            .await
            .expect("deve responder erro")
    });
    assert_eq!(bad.status(), 400);

    let stream = rt.block_on(async {
        reqwest::Client::new()
            .post(format!("{base}/v1/chat/completions"))
            .json(&serde_json::json!({
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": "Responda apenas: ok"}],
                "stream": true
            }))
            .send()
            .await
            .expect("stream deve abrir")
    });
    assert_eq!(stream.status(), 200);
    assert_eq!(
        stream
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .unwrap_or(""),
        "text/event-stream"
    );

    let mut first = String::new();
    let mut chunks = stream.bytes_stream();
    rt.block_on(async {
        while let Some(chunk) = chunks.next().await {
            let bytes = chunk.expect("chunk valido");
            first.push_str(&String::from_utf8_lossy(&bytes));
            if first.contains("data: ") && first.len() > 40 {
                break;
            }
        }
    });
    assert!(
        first.contains("chat.completion.chunk"),
        "SSE sem payload OpenAI: {first:?}"
    );

    shutdown.store(true, Ordering::SeqCst);
    handle.abort();
}
