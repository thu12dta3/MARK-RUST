//! Teste de integracao do motor SVID 1-Bit.
//!
//! Prova, com o checkpoint REAL, que:
//! - o motor carrega pesos verdadeiros (nao constantes sinteticas);
//! - o forward pass produz logits NAO-DEGENERADOS (nao todos iguais);
//! - a geracao emite tokens reais, diferentes do texto do prompt;
//! - o cancelamento interrompe a geracao.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;

use mark_engine::svid::{EngineConfig, SvidEngine};

fn checkpoint_available() -> Option<std::path::PathBuf> {
    let p = mark_core::paths::mark_bin_32b_checkpoint()?;
    if p.join("isometric_gpu_core.safetensors").exists() {
        Some(p)
    } else {
        None
    }
}

#[test]
fn real_checkpoint_loads_and_forward_is_not_degenerate() {
    let Some(ckpt) = checkpoint_available() else {
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

    // O tokenizador real tem 102400 entradas.
    assert_eq!(engine.tokenizer().len(), 102_400);

    // Forward pass real: processa o token BOS e inspeciona os logits.
    let mut state = engine.new_state();
    let logits = engine
        .forward_for_test(100_000, 0, 1)
        .expect("forward pass deve executar");
    assert_eq!(logits.len(), 102_400);

    // Os logits nao podem ser todos iguais (indicaria pesos constantes).
    let min = logits.iter().cloned().fold(f32::INFINITY, f32::min);
    let max = logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
    assert!(
        (max - min).abs() > 1e-4,
        "logits degenerados: min={min} max={max} (pesos nao estao sendo usados)"
    );

    // A maior parte dos logits deve estar mascarada (CJK) e o restante ativo.
    let masked = logits.iter().filter(|v| **v <= -1e8).count();
    assert!(masked < logits.len(), "todos os logits foram mascarados");

    // O argmax deve ser um token valido do vocabulario real.
    let best = logits
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
        .map(|(i, _)| i as u32)
        .expect("argmax");
    assert!(best < 102_400);
    let _ = &mut state;
}

#[test]
fn real_generation_emits_distinct_tokens_and_stops_on_cancel() {
    let Some(ckpt) = checkpoint_available() else {
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

    let cfg = EngineConfig {
        temperature: 0.2,
        top_k: 40,
        seed: Some(1234),
        core_loops: 2,
        greedy: false,
    };
    let cancel = Arc::new(AtomicBool::new(false));
    let count = Arc::new(AtomicUsize::new(0));
    let text = Arc::new(std::sync::Mutex::new(String::new()));

    let c2 = count.clone();
    let t2 = text.clone();
    let cancel2 = cancel.clone();
    engine
        .generate_streaming(
            &[100_000, 1, 2],
            &cfg,
            cancel2.clone(),
            |_id, t| {
                c2.fetch_add(1, Ordering::SeqCst);
                t2.lock().unwrap().push_str(t);
                // Cancela apos 3 tokens para provar o cancelamento imediato.
                if c2.load(Ordering::SeqCst) >= 3 {
                    cancel2.store(true, Ordering::SeqCst);
                }
                true
            },
        )
        .expect("geracao deve executar");

    let emitted = count.load(Ordering::SeqCst);
    assert!(emitted >= 1, "nenhum token foi emitido");
    assert!(
        emitted <= 5,
        "cancelamento nao interrompeu a geracao: {emitted} tokens"
    );
    let out = text.lock().unwrap().clone();
    assert!(
        !out.contains("Motor Rust 1-Bit W1A4"),
        "saida contem string de diagnostico falsa: {out}"
    );
    assert!(
        !out.contains("1-Bit]"),
        "saida contem eco do prompt: {out}"
    );
}

#[test]
fn generation_is_deterministic_with_fixed_seed() {
    let Some(ckpt) = checkpoint_available() else {
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
    let cfg = EngineConfig {
        temperature: 0.2,
        top_k: 40,
        seed: Some(99),
        core_loops: 1,
        greedy: false,
    };

    let run = || {
        let cancel = Arc::new(AtomicBool::new(false));
        let ids = Arc::new(std::sync::Mutex::new(Vec::new()));
        let ids2 = ids.clone();
        engine
            .generate_streaming(
                &[100_000, 1, 2],
                &cfg,
                cancel,
                |id, _t| {
                    ids2.lock().unwrap().push(id);
                    ids2.lock().unwrap().len() < 4
                },
            )
            .unwrap();
        let out = ids.lock().unwrap().clone();
        out
    };

    let a = run();
    let b = run();
    assert_eq!(a, b, "mesma seed deve produzir os mesmos tokens");
    assert!(!a.is_empty());
}

/// O motor 1-bit de 32.054B exige ~6 GiB livres de VRAM; sem isso o teste nao
/// tem como rodar e o motivo e reportado em vez de mascarado.
fn onebit_vram_ready() -> bool {
    match mark_engine::gpu::free_memory_mib() {
        Some(mib) => mib >= mark_engine::svid::onebit::VRAM_REQUIRED_MIB,
        None => false,
    }
}
