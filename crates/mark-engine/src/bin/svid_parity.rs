//! Gate de coerencia e determinismo do motor 1-bit GPU-only (32.054B).
//!
//! Metodologia de paridade (por que NAO se compara texto token a token):
//! o motor de referencia validado foi reexecutado com uma perturbacao de 1 ulp
//! na escala do residuo homeostatico e a sequencia gulosa mudou por completo
//! (`在 Rust 中，我们可以使用一个` -> `这是一个在 Rust 中验证一个字`), com o
//! primeiro token virando 37811 em vez de 612. Um MoE top-6 de 136 experts e
//! caotico no nivel de 1 ulp, entao igualdade de tokens nao e um criterio
//! valido; o que se verifica aqui e o que e reprodutivel: os ids do prompt
//! gravados no checkpoint, a nao-degenerescencia dos logits, a coerencia do
//! texto e o determinismo do proprio motor.

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use anyhow::{bail, Result};

use mark_engine::svid::{EngineConfig, SvidEngine};

/// Ids do prompt de referencia gravados em `rust_tokenizer_v10.bin`.
const REFERENCE_PROMPT_IDS: [u32; 35] = [
    100000, 5726, 25, 14001, 248, 1798, 83302, 829, 36120, 78, 996, 39069, 646, 2438, 76054, 386,
    83302, 2662, 1450, 15783, 5609, 656, 426, 421, 78, 3876, 21921, 1655, 83057, 13, 185, 185,
    77398, 25, 207,
];

fn greedy_cfg() -> EngineConfig {
    EngineConfig {
        temperature: 0.01,
        top_k: 1,
        seed: Some(7),
        core_loops: 1,
        greedy: true,
    }
}

fn generate(engine: &SvidEngine, ids: &[u32], limit: usize) -> Result<String> {
    let mut text = String::new();
    let mut n = 0usize;
    engine.generate_streaming(ids, &greedy_cfg(), Arc::new(AtomicBool::new(false)), |_id, piece| {
        text.push_str(piece);
        n += 1;
        n < limit
    })?;
    Ok(text)
}

fn main() -> Result<()> {
    let ckpt = match mark_core::paths::mark_bin_32b_checkpoint() {
        Some(p) => p,
        None => bail!("checkpoint Mark-Bin-32B nao encontrado"),
    };
    let t0 = std::time::Instant::now();
    let engine = SvidEngine::load(&ckpt)?;
    if !engine.is_onebit() {
        bail!("layout 1-bit nao ativado: o diretorio nao contem os 136 experts");
    }
    let ob = engine.onebit().expect("motor 1-bit presente");
    println!(
        "carga: {:.2}s gpu={} camadas={} experts={} lrd={} tensores={}",
        t0.elapsed().as_secs_f32(),
        engine.gpu_active(),
        ob.layer_count(),
        ob.expert_count(),
        ob.lrd_count(),
        ob.mapped_tensors()
    );
    println!("dispositivo: {:?}", ob.device());
    let (before, delta, required) = ob.vram_report();
    println!(
        "vram: free_before={before} MiB model_delta={delta} MiB required={required} MiB"
    );
    println!(
        "cjk_mask: origem={} ativos={}",
        ob.cjk_source(),
        ob.cjk_masked_tokens()
    );
    for file in ob.loaded_files() {
        println!("  arquivo: {file}");
    }
    if ob.expert_count() != 136 || ob.layer_count() != 27 || ob.lrd_count() != 10 {
        bail!("topologia inesperada: experts/camadas/lrd fora do layout de 32.054B");
    }

    let tok = engine.tokenizer();
    if tok.prompt_ids != REFERENCE_PROMPT_IDS {
        bail!(
            "prompt do checkpoint divergiu dos ids de referencia: {:?}",
            tok.prompt_ids
        );
    }
    let encoded = tok.encode_chat(&[], &tok.prompt);
    if encoded != tok.prompt_ids {
        bail!("encoder BPE divergiu: {} ids vs {} gravados", encoded.len(), tok.prompt_ids.len());
    }
    println!("prompt: {} ids, encoder BPE identico ao checkpoint", encoded.len());

    let pre = engine.prefill_logits(&tok.prompt_ids, 1)?;
    if pre.len() != 102_400 {
        bail!("logits com {} linhas, esperado 102400", pre.len());
    }
    if pre.iter().any(|v| !v.is_finite()) {
        bail!("logits nao finitos");
    }
    let mut order: Vec<usize> = (0..pre.len()).collect();
    order.sort_by(|a, b| pre[*b].partial_cmp(&pre[*a]).unwrap_or(std::cmp::Ordering::Equal));
    let top: Vec<(u32, f32, &str)> = order[..8]
        .iter()
        .map(|&i| (i as u32, pre[i], tok.decode_token(i as u32)))
        .collect();
    println!("top8 pos-prefill: {top:?}");
    let spread = pre[order[0]] - pre[order[1]];
    if spread <= 0.0 {
        bail!("argmax nao estrito: intervalo {spread}");
    }
    if pre[order[0]] - pre[order[7]] < 0.5 {
        bail!("distribuicao degenerada nos 8 primeiros logits");
    }

    let t1 = std::time::Instant::now();
    let text = generate(&engine, &tok.prompt_ids, 8)?;
    let elapsed = t1.elapsed().as_secs_f64();
    println!("texto: {text:?} ({:.2}s)", elapsed);
    if text.trim().is_empty() {
        bail!("motor nao emitiu texto");
    }
    if !text.chars().any(|c| c.is_alphanumeric()) {
        bail!("saida sem conteudo alfanumerico: {text:?}");
    }
    if text.contains("<|") || text.contains("end_of_sentence") || text.contains('\u{FFFD}') {
        bail!("saida vazou token especial: {text:?}");
    }

    // Determinismo: duas execucoes completas devem coincidir caractere a caractere.
    let again = generate(&engine, &tok.prompt_ids, 8)?;
    if again != text {
        bail!("motor nao deterministico: {text:?} vs {again:?}");
    }
    println!("COERENCIA OK: logits reais, texto alfanumerico, deterministico");
    Ok(())
}
