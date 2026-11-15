use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use mark_engine::svid::{EngineConfig, SvidEngine};

fn checkpoint() -> Option<std::path::PathBuf> {
    let p = mark_core::paths::mark_bin_32b_checkpoint()?;
    if p.join("rust_tokenizer_v10.bin").exists() {
        Some(p)
    } else {
        None
    }
}

fn greedy_cfg(core_loops: u32) -> EngineConfig {
    EngineConfig {
        temperature: 0.2,
        top_k: 40,
        seed: Some(7),
        core_loops,
        greedy: true,
    }
}

#[test]
fn greedy_generation_matches_reference_motor() {
    let Some(ckpt) = checkpoint() else {
        eprintln!("checkpoint Mark-Bin-32B ausente: teste ignorado");
        return;
    };
    // O texto de referencia abaixo foi produzido pelo layout V10 INT4: o
    // layout 1-bit de 32.054B tem outro motor (ver `svid_parity`).
    // O layout V10 mantem ~4.5 GB de experts int4 na VRAM; sem espaco o motor
    // cai para a CPU e o texto de referencia deixa de ser reproduzivel.
    let free_mib = mark_engine::gpu::free_memory_mib().unwrap_or(0);
    if free_mib < 5600 {
        eprintln!("VRAM livre {free_mib} MiB (< 5600): teste do layout V10 ignorado");
        return;
    }
    let engine = SvidEngine::load_v10(&ckpt)
        .expect("motor V10 deve carregar o checkpoint real");
    let tok = engine.tokenizer();

    assert_eq!(
        tok.encode_chat(&[], &tok.prompt),
        tok.prompt_ids,
        "encoder BPE divergiu dos ids gravados no checkpoint"
    );

    let top = engine.prefill_logits(&tok.prompt_ids, 1).expect("prefill");
    let mut idx: Vec<usize> = (0..top.len()).collect();
    idx.sort_by(|a, b| top[*b].partial_cmp(&top[*a]).unwrap());
    let best: Vec<(u32, &str)> = idx[..8]
        .iter()
        .map(|&i| (i as u32, tok.decode_token(i as u32)))
        .collect();
    eprintln!("--- TOP8 APOS PREFILL --- {best:?}");

    let cancel = Arc::new(AtomicBool::new(false));
    let out = Arc::new(std::sync::Mutex::new(String::new()));
    let o2 = out.clone();
    let mut n = 0usize;
    engine
        .generate_streaming(&tok.prompt_ids, &greedy_cfg(1), cancel, |_id, text| {
            o2.lock().unwrap().push_str(text);
            n += 1;
            // 12 tokens cobrem a frase de referencia completa neste tokenizador.
            n < 12
        })
        .expect("geracao deve executar");

    let text = out.lock().unwrap().clone();
    eprintln!("--- SAIDA GREEDY ---\n{text}\n--- FIM ---");
    let norm = text.trim_start();
    assert!(
        norm.starts_with("Aqui está uma função em Rust"),
        "saida divergiu do motor de referencia: {text:?}"
    );
    assert!(!text.contains('\u{FFFD}'), "saida contem caracteres invalidos");
}

#[test]
fn freeform_prompt_produces_text() {
    let Some(ckpt) = checkpoint() else {
        eprintln!("checkpoint Mark-Bin-32B ausente: teste ignorado");
        return;
    };
    if !onebit_vram_ready() {
        eprintln!(
            "VRAM livre insuficiente (< {} MiB): teste do motor 1-bit ignorado",
            mark_engine::svid::onebit::VRAM_REQUIRED_MIB
        );
        return;
    }
    let engine = SvidEngine::load(&ckpt).expect("motor deve carregar");
    let ids = engine
        .tokenizer()
        .encode_chat(&[], "Diga em uma frase o que e Rust.");
    assert!(ids.len() > 2, "prompt curto demais: {ids:?}");

    let cancel = Arc::new(AtomicBool::new(false));
    let out = Arc::new(std::sync::Mutex::new(String::new()));
    let o2 = out.clone();
    let mut n = 0usize;
    engine
        .generate_streaming(&ids, &greedy_cfg(2), cancel, |_id, text| {
            o2.lock().unwrap().push_str(text);
            n += 1;
            n < 12
        })
        .expect("geracao deve executar");

    let text = out.lock().unwrap().clone();
    eprintln!("--- SAIDA LIVRE (core_loops=2) ---\n{text}\n--- FIM ---");
    assert!(!text.trim().is_empty(), "nenhum texto gerado");
    assert!(
        text.chars().any(|c| c.is_alphanumeric()),
        "saida sem conteudo alfanumerico: {text:?}"
    );
}

/// O motor 1-bit de 32.054B exige ~6 GiB livres de VRAM; sem isso o teste nao
/// tem como rodar e o motivo e reportado em vez de mascarado.
fn onebit_vram_ready() -> bool {
    match mark_engine::gpu::free_memory_mib() {
        Some(mib) => mib >= mark_engine::svid::onebit::VRAM_REQUIRED_MIB,
        None => false,
    }
}
