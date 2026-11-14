//! Sonda de diagnostico do motor SVID 1-Bit.

use std::time::Instant;

use anyhow::{bail, Result};
use mark_engine::svid::SvidEngine;

fn argmax(v: &[f32]) -> usize {
    v.iter()
        .enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(i, _)| i)
        .unwrap_or(0)
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let n_new: usize = args
        .first()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8usize);

    let ckpt = match mark_core::paths::mark_bin_32b_checkpoint() {
        Some(p) => p,
        None => bail!("checkpoint Mark-Bin-32B nao encontrado"),
    };
    let t0 = Instant::now();
    let engine = SvidEngine::load(&ckpt)?;
    println!("carga: {:.2}s gpu={}", t0.elapsed().as_secs_f32(), engine.gpu_active());

    let tok = engine.tokenizer();
    let mut prompt_ids = tok.prompt_ids.clone();
    if let Ok(n) = std::env::var("MARK_PROMPT_LEN") {
        if let Ok(n) = n.parse::<usize>() {
            prompt_ids.truncate(n.max(1));
        }
    }
    if prompt_ids.len() < 2 {
        bail!("checkpoint sem prompt de referencia");
    }

    let t1 = Instant::now();
    let mut state = engine.new_state();
    let mut logits = Vec::new();
    for (i, &tid) in prompt_ids.iter().enumerate() {
        logits = engine.decode_step(&mut state, tid, i, 1)?;
    }
    let prefill = t1.elapsed().as_secs_f64();
    println!(
        "prefill: {} tokens em {:.2}s ({:.2} tok/s)",
        prompt_ids.len(),
        prefill,
        prompt_ids.len() as f64 / prefill
    );

    let mut ids_sorted: Vec<usize> = (0..logits.len()).collect();
    ids_sorted.sort_by(|a, b| logits[*b].partial_cmp(&logits[*a]).unwrap());
    let top: Vec<String> = ids_sorted[..8]
        .iter()
        .map(|&i| format!("{}:{:?}", i, tok.decode_token(i as u32)))
        .collect();
    println!("top8: {top:?}");

    let mut out = String::new();
    let mut ids = prompt_ids.clone();
    let t2 = Instant::now();
    for _ in 0..n_new {
        let next = argmax(&logits) as u32;
        out.push_str(tok.decode_token(next));
        ids.push(next);
        let pos = ids.len() - 1;
        logits = engine.decode_step(&mut state, next, pos, 1)?;
    }
    let dec = t2.elapsed().as_secs_f64();
    println!("decode: {} tokens em {:.2}s ({:.1} ms/token)", n_new, dec, dec * 1000.0 / n_new as f64);
    println!("saida: {out}");
    Ok(())
}
