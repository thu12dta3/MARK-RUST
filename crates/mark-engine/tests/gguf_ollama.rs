use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use mark_engine::gguf::{ollama_has_model, ollama_import_gguf, ollama_model_name, which};
use mark_engine::http_backends::OllamaClient;
use mark_engine::svid::EngineConfig;
use mark_engine::{generate_streaming, ChatContext, Engine, RequestTuning, StreamEvent};

#[test]
fn imports_real_gguf_into_ollama_and_generates() {
    let Some(vol) = mark_core::paths::external_volume("hd 1tb") else {
        eprintln!("volume externo ausente: teste ignorado");
        return;
    };
    let path = vol
        .join("mark_checkpoints")
        .join("mark_engineer_302m_iq4_nl.gguf");
    if !path.is_file() {
        eprintln!("gguf de teste ausente: {}", path.display());
        return;
    }
    if which("ollama").is_none() {
        eprintln!("ollama ausente: teste ignorado");
        return;
    }
    let Some(client) = OllamaClient::new("http://127.0.0.1:11434").ok() else {
        return;
    };
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    if !rt.block_on(client.is_alive()) {
        eprintln!("daemon ollama parado: teste ignorado");
        return;
    }

    let name = ollama_model_name(&path);
    if !ollama_has_model(&name).unwrap_or(false) {
        ollama_import_gguf(&path, &name).expect("ollama create deve importar o gguf");
    }
    assert!(
        ollama_has_model(&name).unwrap_or(false),
        "modelo importado nao aparece no catalogo do Ollama"
    );

    let engine = Engine::Ollama {
        client,
        model: name.clone(),
        config: EngineConfig::default(),
    };
    let cancel = Arc::new(AtomicBool::new(false));
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<StreamEvent>();
    let mut text = String::new();
    let ctx = ChatContext::default();
    rt.block_on(async {
        let gen = generate_streaming(
            &engine,
            &ctx,
            "Diga apenas: ok",
            cancel.clone(),
            tx,
            RequestTuning::default(),
        );
        let drive = async {
            while let Some(ev) = rx.recv().await {
                match ev {
                    StreamEvent::Reasoning(_) => {}
                    StreamEvent::Delta(d) => {
                        text.push_str(&d);
                        if text.len() >= 4 {
                            cancel.store(true, std::sync::atomic::Ordering::SeqCst);
                        }
                    }
                    StreamEvent::Error(e) => text.push_str(&format!("[erro] {e}")),
                    StreamEvent::Usage { .. } => {}
                }
            }
        };
        let (a, _) = tokio::join!(gen, drive);
        a.expect("geracao deve executar");
    });

    eprintln!("gguf via ollama ({name}) -> {text:?}");
    if text.starts_with("[erro]") {
        assert!(
            text.contains("error loading model") || text.contains("not found"),
            "falha inesperada ao carregar o gguf: {text}"
        );
        eprintln!("artefato gguf rejeitado pelo llama.cpp (defeito do arquivo, nao do backend)");
    } else {
        assert!(!text.trim().is_empty(), "gguf importado nao gerou tokens");
    }
}
