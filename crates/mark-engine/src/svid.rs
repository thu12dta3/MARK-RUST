//! Motor SVID 1-Bit nativo para Mark-Bin-32B.
//!
//! Implementa o forward pass REAL sobre os pesos do checkpoint:
//! - Embeddings int8 (`embed_tokens.q8`) + escala F16.
//! - 27 camadas do enxerto DeepSeek-V2-Lite (hidden 2048), com atencao MLA
//!   (q_proj 3072, kv_a 576 = 512 c_kv + 64 rope, kv_b 4096, o_proj 2048).
//! - Camada 0 densa (gate/up/down 10944); camadas 1..27 com MoE:
//!   64 experts roteados (top-6) em int4 + shared experts int8.
//! - Camada LRD 1-bit (layer 30) projetada via W1A4 XNOR-POPCNT.
//! - LM head int8 com mascara CJK e sampling por temperatura.
//!
//! Nao existe nenhum caminho que produza texto sem executar o forward pass.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::{bail, Context, Result};
use rayon::prelude::*;

use crate::gpu::{GpuBuffer, GpuEngine, GpuExperts};
use crate::kernels::{
    homeostatic_residual_add_inplace, int4_dot_row, int4_dot_row_f32, matvec_i8_f32,
    prepare_act_int4, rmsnorm_into, svid_1bit_linear_subspace_w1a4,
    swiglu_inplace, YarnRopeCache,
};
use crate::safetensors::{BinTokenizer, SafeTensors};

/// Buffers de uma camada na VRAM.
struct GpuLayer {
    q_q8: GpuBuffer,
    q_sc: GpuBuffer,
    kva_q8: GpuBuffer,
    kva_sc: GpuBuffer,
    kvb_q8: GpuBuffer,
    kvb_sc: GpuBuffer,
    o_q8: GpuBuffer,
    o_sc: GpuBuffer,
    sh_g_q8: GpuBuffer,
    sh_g_sc: GpuBuffer,
    sh_u_q8: GpuBuffer,
    sh_u_sc: GpuBuffer,
    sh_d_q8: GpuBuffer,
    sh_d_sc: GpuBuffer,
    experts: Option<GpuExperts>,
}

/// Estado GPU completo do motor.
struct GpuState {
    engine: GpuEngine,
    lm_q8: GpuBuffer,
    lm_sc: GpuBuffer,
    cjk_mask: GpuBuffer,
    layers: Vec<GpuLayer>,
}

/// Numero maximo de camadas MoE cujos experts cabem na VRAM.
const GPU_EXPERT_LAYERS: usize = 13;

/// Dimensoes do enxerto DeepSeek-V2-Lite usado pelo Mark-Bin-32B.
pub const HIDDEN: usize = 2048;
/// Numero de camadas do enxerto.
pub const N_LAYERS: usize = 27;
/// Cabecas de atencao.
pub const N_HEADS: usize = 16;
/// Dimensao por cabeca (128 nope + 64 rope).
pub const HEAD_DIM: usize = 192;
/// Dimensao nope por cabeca.
pub const NOPE_DIM: usize = 128;
/// Dimensao rope por cabeca.
pub const ROPE_DIM: usize = 64;
/// Rank latente do KV.
pub const C_KV: usize = 512;
/// Numero de experts roteados.
pub const N_EXPERTS: usize = 64;
/// Experts ativados por token.
pub const TOP_K_EXPERTS: usize = 6;
/// Dimensao intermediaria dos experts roteados.
pub const EXPERT_INTER: usize = 1408;
/// Dimensao intermediaria dos shared experts.
pub const SHARED_INTER: usize = 2816;
/// Dimensao intermediaria da camada densa 0.
pub const DENSE_INTER: usize = 10944;
/// Tamanho do vocabulario.
pub const VOCAB: usize = 102_400;

/// Pesos de uma camada carregados do checkpoint.
struct LayerWeights {
    input_norm: Vec<f32>,
    post_norm: Vec<f32>,
    kv_a_norm: Vec<f32>,
    q_q8: Vec<i8>,
    q_scale: Vec<f32>,
    kva_q8: Vec<i8>,
    kva_scale: Vec<f32>,
    kvb_q8: Vec<i8>,
    kvb_scale: Vec<f32>,
    o_q8: Vec<i8>,
    o_scale: Vec<f32>,
    // Shared experts (camadas 1..N) ou MLP densa (camada 0).
    mlp_gate_q8: Vec<i8>,
    mlp_gate_scale: Vec<f32>,
    mlp_up_q8: Vec<i8>,
    mlp_up_scale: Vec<f32>,
    mlp_down_q8: Vec<i8>,
    mlp_down_scale: Vec<f32>,
    // Router (apenas camadas 1..N).
    router: Option<Vec<f32>>,
    // Experts roteados int4: pesos permanecem no mmap, apenas as escalas sao materializadas.
    expert_src: Option<Arc<SafeTensors>>,
    expert_gate_name: String,
    expert_up_name: String,
    expert_down_name: String,
    expert_gate_scale: Option<Vec<f32>>,
    expert_up_scale: Option<Vec<f32>>,
    expert_down_scale: Option<Vec<f32>>,
}

/// Motor carregado, pronto para inferencia.
pub struct SvidEngine {
    embed_q8: Vec<i8>,
    embed_scale: Vec<f32>,
    lm_q8: Vec<i8>,
    lm_scale: Vec<f32>,
    cjk_mask: Vec<u8>,
    final_norm: Vec<f32>,
    layers: Vec<LayerWeights>,
    tokenizer: BinTokenizer,
    checkpoint_dir: PathBuf,
    // Pesos LRD 1-bit (camada extra 30).
    lrd_gate_bits: Vec<u64>,
    lrd_gate_row_scale: Vec<f32>,
    lrd_gate_col_scale: Vec<f32>,
    lrd_down_bits: Vec<u64>,
    lrd_down_row_scale: Vec<f32>,
    lrd_down_col_scale: Vec<f32>,
    gpu: Option<GpuState>,
}

/// Configuracao de inferencia do motor.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub temperature: f32,
    pub top_k: usize,
    pub seed: Option<u64>,
    /// Numero de passes do bloco recorrente LRD 1-bit (profundidade de raciocinio).
    pub core_loops: u32,
    /// Decodificacao gulosa deterministica (argmax), usada em diagnostico.
    pub greedy: bool,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            temperature: 0.2,
            top_k: 40,
            seed: None,
            core_loops: 2,
            greedy: false,
        }
    }
}

/// Estado de execucao de uma geracao.
pub struct GenerationState {
    /// IDs de token ja gerados.
    pub ids: Vec<u32>,
    /// Contexto K/V por camada.
    k_cache: Vec<Vec<f32>>,
    v_cache: Vec<Vec<f32>>,
}

impl SvidEngine {
    /// Localiza e carrega o checkpoint Mark-Bin-32B.
    pub fn discover() -> Result<PathBuf> {
        mark_core::paths::mark_bin_32b_checkpoint()
            .context("checkpoint Mark-Bin-32B nao encontrado no volume externo")
    }

    /// Carrega o motor a partir do diretorio do checkpoint.
    pub fn load(checkpoint_dir: &Path) -> Result<Self> {
        let gpu_core = checkpoint_dir.join("isometric_gpu_core.safetensors");
        let mmap_experts = checkpoint_dir.join("isometric_mmap_experts.safetensors");
        let shard4 = checkpoint_dir.join("model-00004-of-00004.safetensors");
        let delta = checkpoint_dir.join("mark_calibration_delta.safetensors");
        let tok_path = checkpoint_dir.join("rust_tokenizer_v10.bin");

        for p in [&gpu_core, &mmap_experts, &shard4, &delta, &tok_path] {
            if !p.exists() {
                bail!("arquivo de checkpoint ausente: {}", p.display());
            }
        }

        let st = Arc::new(SafeTensors::open(&gpu_core)?);
        let st_exp = Arc::new(SafeTensors::open(&mmap_experts)?);
        let expert_names: Vec<String> = (14..N_LAYERS)
            .map(|l| format!("layers.{l}.mlp.experts"))
            .collect();
        if std::env::var("MARK_NO_WARM").is_err() {
            let mut warmed = 0usize;
            for l in 14..N_LAYERS {
                let sp = format!("layers.{l}.mlp.experts");
                for proj in ["gate_proj.q4", "up_proj.q4", "down_proj.q4"] {
                    if let Some((a, b)) = st_exp.file_range(&format!("{sp}.{proj}")) {
                        warmed += st_exp.warm_range(a, b);
                    }
                }
            }
            std::hint::black_box(warmed);
        }
        let _ = &expert_names;
        let st_s4 = SafeTensors::open(&shard4)?;
        let st_delta = SafeTensors::open(&delta)?;
        // Valida que o delta de calibracao existe e e coerente antes de prosseguir.
        if !st_delta.has("lrd.30.g_rs") || !st_delta.has("lrd.30.d_rs") {
            bail!("delta de calibracao ausente: lrd.30.g_rs / lrd.30.d_rs");
        }

        let embed_q8 = st.i8_slice("embed_tokens.q8")?.to_vec();
        let embed_scale = st.f32_vec("embed_tokens.scale")?;
        let lm_q8 = st.i8_slice("lm_head.q8")?.to_vec();
        let lm_scale = st.f32_vec("lm_head.scale")?;
        let cjk_mask = st.u8_slice("cjk_mask")?.to_vec();
        let final_norm = st_delta.f32_vec("norm.weight")?;

        let mut layers = Vec::with_capacity(N_LAYERS);
        for l in 0..N_LAYERS {
            let sp = format!("layers.{l}");
            let layer = if l == 0 {
                LayerWeights {
                    input_norm: st.f32_vec(&format!("{sp}.input_layernorm.weight"))?,
                    post_norm: st.f32_vec(&format!("{sp}.post_attention_layernorm.weight"))?,
                    kv_a_norm: st.f32_vec(&format!("{sp}.self_attn.kv_a_layernorm.weight"))?,
                    q_q8: st.i8_slice(&format!("{sp}.self_attn.q_proj.q8"))?.to_vec(),
                    q_scale: st.f32_vec(&format!("{sp}.self_attn.q_proj.scale"))?,
                    kva_q8: st
                        .i8_slice(&format!("{sp}.self_attn.kv_a_proj_with_mqa.q8"))?
                        .to_vec(),
                    kva_scale: st
                        .f32_vec(&format!("{sp}.self_attn.kv_a_proj_with_mqa.scale"))?,
                    kvb_q8: st.i8_slice(&format!("{sp}.self_attn.kv_b_proj.q8"))?.to_vec(),
                    kvb_scale: st.f32_vec(&format!("{sp}.self_attn.kv_b_proj.scale"))?,
                    o_q8: st.i8_slice(&format!("{sp}.self_attn.o_proj.q8"))?.to_vec(),
                    o_scale: st.f32_vec(&format!("{sp}.self_attn.o_proj.scale"))?,
                    mlp_gate_q8: st.i8_slice(&format!("{sp}.mlp.gate_proj.q8"))?.to_vec(),
                    mlp_gate_scale: st.f32_vec(&format!("{sp}.mlp.gate_proj.scale"))?,
                    mlp_up_q8: st.i8_slice(&format!("{sp}.mlp.up_proj.q8"))?.to_vec(),
                    mlp_up_scale: st.f32_vec(&format!("{sp}.mlp.up_proj.scale"))?,
                    mlp_down_q8: st.i8_slice(&format!("{sp}.mlp.down_proj.q8"))?.to_vec(),
                    mlp_down_scale: st.f32_vec(&format!("{sp}.mlp.down_proj.scale"))?,
                    router: None,
                    expert_src: None,
                    expert_gate_name: String::new(),
                    expert_up_name: String::new(),
                    expert_down_name: String::new(),
                    expert_gate_scale: None,
                    expert_up_scale: None,
                    expert_down_scale: None,
                }
            } else {
                // Layers 1..10 tem experts no gpu_core; 11..26 no mmap_experts.
                let src: Arc<SafeTensors> = if l <= 10 { st.clone() } else { st_exp.clone() };
                let gate_name = format!("{sp}.mlp.experts.gate_proj.q4");
                let up_name = format!("{sp}.mlp.experts.up_proj.q4");
                let down_name = format!("{sp}.mlp.experts.down_proj.q4");
                src.u8_slice(&gate_name)?;
                src.u8_slice(&up_name)?;
                src.u8_slice(&down_name)?;
                LayerWeights {
                    input_norm: st.f32_vec(&format!("{sp}.input_layernorm.weight"))?,
                    post_norm: st.f32_vec(&format!("{sp}.post_attention_layernorm.weight"))?,
                    kv_a_norm: st.f32_vec(&format!("{sp}.self_attn.kv_a_layernorm.weight"))?,
                    q_q8: st.i8_slice(&format!("{sp}.self_attn.q_proj.q8"))?.to_vec(),
                    q_scale: st.f32_vec(&format!("{sp}.self_attn.q_proj.scale"))?,
                    kva_q8: st
                        .i8_slice(&format!("{sp}.self_attn.kv_a_proj_with_mqa.q8"))?
                        .to_vec(),
                    kva_scale: st
                        .f32_vec(&format!("{sp}.self_attn.kv_a_proj_with_mqa.scale"))?,
                    kvb_q8: st.i8_slice(&format!("{sp}.self_attn.kv_b_proj.q8"))?.to_vec(),
                    kvb_scale: st.f32_vec(&format!("{sp}.self_attn.kv_b_proj.scale"))?,
                    o_q8: st.i8_slice(&format!("{sp}.self_attn.o_proj.q8"))?.to_vec(),
                    o_scale: st.f32_vec(&format!("{sp}.self_attn.o_proj.scale"))?,
                    mlp_gate_q8: st
                        .i8_slice(&format!("{sp}.mlp.shared_experts.gate_proj.q8"))?
                        .to_vec(),
                    mlp_gate_scale: st
                        .f32_vec(&format!("{sp}.mlp.shared_experts.gate_proj.scale"))?,
                    mlp_up_q8: st
                        .i8_slice(&format!("{sp}.mlp.shared_experts.up_proj.q8"))?
                        .to_vec(),
                    mlp_up_scale: st
                        .f32_vec(&format!("{sp}.mlp.shared_experts.up_proj.scale"))?,
                    mlp_down_q8: st
                        .i8_slice(&format!("{sp}.mlp.shared_experts.down_proj.q8"))?
                        .to_vec(),
                    mlp_down_scale: st
                        .f32_vec(&format!("{sp}.mlp.shared_experts.down_proj.scale"))?,
                    router: Some(st.f32_vec(&format!("{sp}.mlp.gate.weight"))?),
                    expert_src: Some(src.clone()),
                    expert_gate_name: gate_name,
                    expert_up_name: up_name,
                    expert_down_name: down_name,
                    expert_gate_scale: Some(
                        src.f32_vec(&format!("{sp}.mlp.experts.gate_proj.scale"))?,
                    ),
                    expert_up_scale: Some(src.f32_vec(&format!("{sp}.mlp.experts.up_proj.scale"))?),
                    expert_down_scale: Some(
                        src.f32_vec(&format!("{sp}.mlp.experts.down_proj.scale"))?,
                    ),
                }
            };
            layers.push(layer);
        }

        let lrd_gate_bits = st_s4.u64_vec("model.layers.30.mlp.shared_experts.0.gate_proj.packed_bits")?;
        let lrd_gate_row_scale = st_s4.f32_vec("model.layers.30.mlp.shared_experts.0.gate_proj.row_scale")?;
        let lrd_gate_col_scale = st_s4.f32_vec("model.layers.30.mlp.shared_experts.0.gate_proj.col_scale")?;
        let lrd_down_bits = st_s4.u64_vec("model.layers.30.mlp.shared_experts.0.down_proj.packed_bits")?;
        let lrd_down_row_scale = st_s4.f32_vec("model.layers.30.mlp.shared_experts.0.down_proj.row_scale")?;
        let lrd_down_col_scale = st_s4.f32_vec("model.layers.30.mlp.shared_experts.0.down_proj.col_scale")?;

        let tokenizer = BinTokenizer::load(&tok_path)?;

        let gpu = if std::env::var("MARK_FORCE_CPU").is_ok() {
            None
        } else {
            build_gpu(&st, &st_exp, &lm_q8, &lm_scale, &cjk_mask).ok()
        };

        Ok(Self {
            embed_q8,
            embed_scale,
            lm_q8,
            lm_scale,
            cjk_mask,
            final_norm,
            layers,
            tokenizer,
            checkpoint_dir: checkpoint_dir.to_path_buf(),
            lrd_gate_bits,
            lrd_gate_row_scale,
            lrd_gate_col_scale,
            lrd_down_bits,
            lrd_down_row_scale,
            lrd_down_col_scale,
            gpu,
        })
    }

    /// Diretorio do checkpoint carregado.
    pub fn checkpoint_dir(&self) -> &Path {
        &self.checkpoint_dir
    }

    /// Tokenizador do checkpoint.
    pub fn tokenizer(&self) -> &BinTokenizer {
        &self.tokenizer
    }

    /// Janela de contexto maxima suportada pelo motor (2M do modelo H-MLA).
    pub fn context_window(&self) -> u32 {
        2_097_152
    }

    /// Cria um novo estado de geracao.
    pub fn new_state(&self) -> GenerationState {
        GenerationState {
            ids: Vec::new(),
            k_cache: vec![Vec::new(); N_LAYERS],
            v_cache: vec![Vec::new(); N_LAYERS],
        }
    }

    /// Executa o prefill completo e devolve os logits da proxima posicao.
    pub fn prefill_logits(&self, prompt_ids: &[u32], core_loops: u32) -> Result<Vec<f32>> {
        let mut state = self.new_state();
        let mut logits = Vec::new();
        for (i, &tid) in prompt_ids.iter().enumerate() {
            logits = self.forward(&mut state, tid, i, core_loops)?;
        }
        Ok(logits)
    }

    /// Processa um token num estado de geracao e devolve os logits da proxima posicao.
    pub fn decode_step(
        &self,
        state: &mut GenerationState,
        token_id: u32,
        pos: usize,
        core_loops: u32,
    ) -> Result<Vec<f32>> {
        self.forward(state, token_id, pos, core_loops)
    }

    /// Executa um unico forward pass e devolve os logits (usado em testes e diagnose).
    pub fn forward_for_test(&self, token_id: u32, pos: usize, core_loops: u32) -> Result<Vec<f32>> {
        let mut state = self.new_state();
        self.forward(&mut state, token_id, pos, core_loops)
    }

    /// Executa o forward pass para um token e devolve os logits.
    fn forward(
        &self,
        state: &mut GenerationState,
        token_id: u32,
        pos: usize,
        core_loops: u32,
    ) -> Result<Vec<f32>> {
        let tid = token_id as usize;
        if tid >= VOCAB {
            bail!("token id fora do vocabulario: {token_id}");
        }
        let mut h = vec![0.0f32; HIDDEN];
        let sc = self.embed_scale[tid];
        let row = &self.embed_q8[tid * HIDDEN..(tid + 1) * HIDDEN];
        for j in 0..HIDDEN {
            h[j] = (row[j] as f32) * sc;
        }

        let mut xn = vec![0.0f32; HIDDEN];
        let mut q_buf = vec![0.0f32; N_HEADS * HEAD_DIM];
        let mut kva_buf = vec![0.0f32; C_KV + ROPE_DIM];
        let mut c_kv = vec![0.0f32; C_KV];
        let mut kvb_buf = vec![0.0f32; N_HEADS * (NOPE_DIM + NOPE_DIM)];
        let mut ctx_buf = vec![0.0f32; HIDDEN];
        let mut attn_out = vec![0.0f32; HIDDEN];
        let mut mlp_out = vec![0.0f32; HIDDEN];
        let mut shared_out = vec![0.0f32; HIDDEN];
        let yarn = YarnRopeCache::new(pos, ROPE_DIM, HEAD_DIM);
        let gpu_ref = self.gpu.as_ref();
        let dump = std::env::var("MARK_DUMP").is_ok() && pos + 1 == dump_target();
        if dump {
            dump_h("embed", &h);
        }

        for l in 0..N_LAYERS {
            let lw = &self.layers[l];
            rmsnorm_into(&h, &lw.input_norm, 1e-6, &mut xn);

            if let Some(g) = gpu_ref {
                let gl = &g.layers[l];
                g.engine.matvec_q_kva(
                    &xn,
                    &gl.q_q8,
                    &gl.q_sc,
                    &gl.kva_q8,
                    &gl.kva_sc,
                    &mut q_buf,
                    &mut kva_buf,
                )?;
            } else {
                matvec_i8_f32(
                    &xn,
                    &lw.q_q8,
                    &lw.q_scale,
                    N_HEADS * HEAD_DIM,
                    HIDDEN,
                    &mut q_buf,
                );
                matvec_i8_f32(
                    &xn,
                    &lw.kva_q8,
                    &lw.kva_scale,
                    C_KV + ROPE_DIM,
                    HIDDEN,
                    &mut kva_buf,
                );
            }

            // RoPE apenas na parte rope de cada cabeca de Q.
            for hd in 0..N_HEADS {
                let base = hd * HEAD_DIM;
                let mut rope_part = [0.0f32; ROPE_DIM];
                rope_part.copy_from_slice(&q_buf[base + NOPE_DIM..base + HEAD_DIM]);
                yarn.apply_head_in_place(&mut rope_part, pos);
                q_buf[base + NOPE_DIM..base + HEAD_DIM].copy_from_slice(&rope_part);
            }

            rmsnorm_into(&kva_buf[0..C_KV], &lw.kv_a_norm, 1e-6, &mut c_kv);
            let mut k_pe = [0.0f32; ROPE_DIM];
            k_pe.copy_from_slice(&kva_buf[C_KV..C_KV + ROPE_DIM]);
            yarn.apply_head_in_place(&mut k_pe, pos);

            if let Some(g) = gpu_ref {
                let gl = &g.layers[l];
                g.engine
                    .matvec_i8(&c_kv, &gl.kvb_q8, &gl.kvb_sc, None, N_HEADS * (NOPE_DIM + NOPE_DIM), C_KV, &mut kvb_buf)?;
            } else {
                matvec_i8_f32(
                    &c_kv,
                    &lw.kvb_q8,
                    &lw.kvb_scale,
                    N_HEADS * (NOPE_DIM + NOPE_DIM),
                    C_KV,
                    &mut kvb_buf,
                );
            }

            for hd in 0..N_HEADS {
                let k_off = hd * (NOPE_DIM + NOPE_DIM);
                state.k_cache[l].extend_from_slice(&kvb_buf[k_off..k_off + NOPE_DIM]);
                state.k_cache[l].extend_from_slice(&k_pe);
                let v_off = hd * (NOPE_DIM + NOPE_DIM) + NOPE_DIM;
                state
                    .v_cache[l]
                    .extend_from_slice(&kvb_buf[v_off..v_off + NOPE_DIM]);
            }

            // Atencao MLA: scores por cabeca sobre o contexto.
            let s_tot = pos + 1;
            let attn_scale = yarn.softmax_scale();
            ctx_buf.par_chunks_mut(HIDDEN / N_HEADS).enumerate().for_each(|(hd, ctx_h)| {
                let q_h = &q_buf[hd * HEAD_DIM..(hd + 1) * HEAD_DIM];
                let mut scores = vec![0.0f32; s_tot];
                let mut max_s = f32::NEG_INFINITY;
                for t in 0..s_tot {
                    let k_base = (t * N_HEADS + hd) * (NOPE_DIM + ROPE_DIM);
                    let k_h = &state.k_cache[l][k_base..k_base + NOPE_DIM + ROPE_DIM];
                    let mut dot = 0.0f32;
                    for d in 0..(NOPE_DIM + ROPE_DIM) {
                        dot += q_h[d] * k_h[d];
                    }
                    let sc_v = dot * attn_scale;
                    if sc_v > max_s {
                        max_s = sc_v;
                    }
                    scores[t] = sc_v;
                }
                let mut sum_e = 0.0f32;
                for s in scores.iter_mut() {
                    *s = (*s - max_s).exp();
                    sum_e += *s;
                }
                let sum_e = sum_e.max(1e-9);
                for d in 0..(HIDDEN / N_HEADS) {
                    ctx_h[d] = 0.0;
                }
                for t in 0..s_tot {
                    let p = scores[t] / sum_e;
                    let v_base = (t * N_HEADS + hd) * NOPE_DIM;
                    let v_h = &state.v_cache[l][v_base..v_base + NOPE_DIM];
                    for d in 0..NOPE_DIM {
                        ctx_h[d] += p * v_h[d];
                    }
                }
            });

            if let Some(g) = gpu_ref {
                let gl = &g.layers[l];
                g.engine
                    .matvec_i8(&ctx_buf, &gl.o_q8, &gl.o_sc, None, HIDDEN, HIDDEN, &mut attn_out)?;
            } else {
                matvec_i8_f32(&ctx_buf, &lw.o_q8, &lw.o_scale, HIDDEN, HIDDEN, &mut attn_out);
            }
            homeostatic_residual_add_inplace(&mut h, &attn_out, 1.8);
            if dump && l == 1 {
                dump_h("L1.attn", &h);
            }

            rmsnorm_into(&h, &lw.post_norm, 1e-6, &mut xn);

            // MLP.
            if l == 0 {
                let inter = DENSE_INTER;
                if let Some(g) = gpu_ref {
                    let gl = &g.layers[l];
                    g.engine.shared_mlp(
                        &xn,
                        &gl.sh_g_q8,
                        &gl.sh_g_sc,
                        &gl.sh_u_q8,
                        &gl.sh_u_sc,
                        &gl.sh_d_q8,
                        &gl.sh_d_sc,
                        inter,
                    )?;
                    g.engine.fetch_shared(&mut mlp_out)?;
                } else {
                    let mut g0 = vec![0.0f32; inter];
                    let mut u0 = vec![0.0f32; inter];
                    matvec_i8_f32(&xn, &lw.mlp_gate_q8, &lw.mlp_gate_scale, inter, HIDDEN, &mut g0);
                    matvec_i8_f32(&xn, &lw.mlp_up_q8, &lw.mlp_up_scale, inter, HIDDEN, &mut u0);
                    swiglu_inplace(&mut g0, &u0);
                    matvec_i8_f32(
                        &g0,
                        &lw.mlp_down_q8,
                        &lw.mlp_down_scale,
                        HIDDEN,
                        inter,
                        &mut mlp_out,
                    );
                }
            } else {
                // Roteamento MoE: top-6 experts por token.
                let router = lw.router.as_ref().expect("router ausente em camada MoE");
                let mut e_scores: Vec<(usize, f32)> = (0..N_EXPERTS)
                    .map(|e| {
                        let r = &router[e * HIDDEN..(e + 1) * HIDDEN];
                        let s: f32 = r.iter().zip(xn.iter()).map(|(a, b)| a * b).sum();
                        (e, s)
                    })
                    .collect();
                let max_g = e_scores.iter().map(|x| x.1).fold(f32::NEG_INFINITY, f32::max);
                let mut sum_eg = 0.0f32;
                for es in e_scores.iter_mut() {
                    es.1 = (es.1 - max_g).exp();
                    sum_eg += es.1;
                }
                let sum_eg = sum_eg.max(1e-9);
                for es in e_scores.iter_mut() {
                    es.1 /= sum_eg;
                }
                e_scores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                let top = &e_scores[..TOP_K_EXPERTS.min(e_scores.len())];

                let mut experts_in_gpu = false;
                if let Some(g) = gpu_ref {
                    let gl = &g.layers[l];
                    g.engine.shared_mlp(
                        &xn,
                        &gl.sh_g_q8,
                        &gl.sh_g_sc,
                        &gl.sh_u_q8,
                        &gl.sh_u_sc,
                        &gl.sh_d_q8,
                        &gl.sh_d_sc,
                        SHARED_INTER,
                    )?;
                    match gl.experts.as_ref() {
                        Some(ex) => {
                            for (eid, w) in top.iter() {
                                g.engine
                                    .moe_add_expert(&xn, ex, *eid, *w, EXPERT_INTER, HIDDEN)?;
                            }
                            g.engine.fetch_shared(&mut mlp_out)?;
                            experts_in_gpu = true;
                        }
                        None => g.engine.fetch_shared(&mut shared_out)?,
                    }
                } else {
                    let mut sh_g = vec![0.0f32; SHARED_INTER];
                    let mut sh_u = vec![0.0f32; SHARED_INTER];
                    matvec_i8_f32(
                        &xn,
                        &lw.mlp_gate_q8,
                        &lw.mlp_gate_scale,
                        SHARED_INTER,
                        HIDDEN,
                        &mut sh_g,
                    );
                    matvec_i8_f32(
                        &xn,
                        &lw.mlp_up_q8,
                        &lw.mlp_up_scale,
                        SHARED_INTER,
                        HIDDEN,
                        &mut sh_u,
                    );
                    swiglu_inplace(&mut sh_g, &sh_u);
                    matvec_i8_f32(
                        &sh_g,
                        &lw.mlp_down_q8,
                        &lw.mlp_down_scale,
                        HIDDEN,
                        SHARED_INTER,
                        &mut shared_out,
                    );
                }

                if dump && l == 1 {
                    dump_h("L1.shared", &shared_out);
                    let ids: Vec<(usize, f32)> = top.iter().map(|(i, w)| (*i, *w)).collect();
                    println!("L1.top6 {ids:?}");
                }
                if !experts_in_gpu {
                    self.routed_experts(lw, top, &xn, &mut mlp_out, false);
                    for j in 0..HIDDEN {
                        mlp_out[j] += shared_out[j];
                    }
                }
                if dump && l == 1 {
                    dump_h("L1.mlp", &mlp_out);
                }
            }
            homeostatic_residual_add_inplace(&mut h, &mlp_out, 1.8);
            if dump && matches!(l, 0 | 1 | 10 | 14 | 22 | 26) {
                dump_h(&format!("L{l}"), &h);
            }
        }

        // Bloco recorrente LRD 1-bit (camada 30 enxertada), aplicado `core_loops` vezes.
        let loops = core_loops.clamp(1, 4);
        for _ in 0..loops {
            let g1 = svid_1bit_linear_subspace_w1a4(
                &h,
                &self.lrd_gate_bits,
                &self.lrd_gate_row_scale,
                &self.lrd_gate_col_scale,
                self.lrd_gate_row_scale.len(),
            );
            let d1 = svid_1bit_linear_subspace_w1a4(
                &g1,
                &self.lrd_down_bits,
                &self.lrd_down_row_scale,
                &self.lrd_down_col_scale,
                self.lrd_down_row_scale.len(),
            );
            homeostatic_residual_add_inplace(&mut h, &d1[0..HIDDEN], 0.001);
        }
        if dump {
            dump_h("lrd", &h);
        }

        rmsnorm_into(&h, &self.final_norm, 1e-6, &mut xn);
        if dump {
            dump_h("final_norm", &xn);
        }

        // LM head int8 com mascara CJK.
        let mut logits = vec![0.0f32; VOCAB];
        if let Some(g) = gpu_ref {
            g.engine.matvec_i8(
                &xn,
                &g.lm_q8,
                &g.lm_sc,
                Some(&g.cjk_mask),
                VOCAB,
                HIDDEN,
                &mut logits,
            )?;
        } else {
            logits.par_iter_mut().enumerate().for_each(|(r, y)| {
                if self.cjk_mask[r] != 0 {
                    *y = -1e9;
                    return;
                }
                let w = &self.lm_q8[r * HIDDEN..(r + 1) * HIDDEN];
                *y = crate::kernels::dot_i8_f32(w, &xn) * self.lm_scale[r];
            });
        }

        Ok(logits)
    }

    /// Indica se o caminho GPU PTX esta ativo.
    pub fn gpu_active(&self) -> bool {
        self.gpu.is_some()
    }

    /// Executa os experts roteados int4 para os experts selecionados.
    fn routed_experts(
        &self,
        lw: &LayerWeights,
        top: &[(usize, f32)],
        xn: &[f32],
        mlp_out: &mut [f32],
        quantized: bool,
    ) {
        let (Some(src), Some(g_sc), Some(u_sc), Some(d_sc)) = (
            lw.expert_src.as_ref(),
            lw.expert_gate_scale.as_ref(),
            lw.expert_up_scale.as_ref(),
            lw.expert_down_scale.as_ref(),
        ) else {
            return;
        };
        let (Ok(g_q4), Ok(u_q4), Ok(d_q4)) = (
            src.u8_slice(&lw.expert_gate_name),
            src.u8_slice(&lw.expert_up_name),
            src.u8_slice(&lw.expert_down_name),
        ) else {
            return;
        };

        let (xe, xo, xbias, x_sc) = if quantized {
            prepare_act_int4(xn)
        } else {
            (Vec::new(), Vec::new(), Vec::new(), 0.0f32)
        };
        let n_top = top.len();
        let mut inter_all = vec![0.0f32; n_top * EXPERT_INTER];
        let mut down_all = vec![0.0f32; n_top * HIDDEN];

        inter_all
            .par_chunks_mut(EXPERT_INTER)
            .enumerate()
            .for_each(|(ki, inter)| {
                let eid = top[ki].0;
                let g_off_q = eid * EXPERT_INTER * 1024;
                let g_off_s = eid * EXPERT_INTER * 16;
                for r in 0..EXPERT_INTER {
                    let g_row = &g_q4[g_off_q + r * 1024..g_off_q + (r + 1) * 1024];
                    let g_srow = &g_sc[g_off_s + r * 16..g_off_s + (r + 1) * 16];
                    let u_row = &u_q4[g_off_q + r * 1024..g_off_q + (r + 1) * 1024];
                    let u_srow = &u_sc[g_off_s + r * 16..g_off_s + (r + 1) * 16];
                    let (gv, uv) = if quantized {
                        (
                            int4_dot_row(g_row, g_srow, &xe, &xo, &xbias, x_sc),
                            int4_dot_row(u_row, u_srow, &xe, &xo, &xbias, x_sc),
                        )
                    } else {
                        (
                            int4_dot_row_f32(g_row, g_srow, xn),
                            int4_dot_row_f32(u_row, u_srow, xn),
                        )
                    };
                    inter[r] = (gv / (1.0 + (-gv).exp())) * uv;
                }
            });

        down_all
            .par_chunks_mut(HIDDEN)
            .enumerate()
            .for_each(|(ki, down)| {
                let eid = top[ki].0;
                let d_off_q = eid * HIDDEN * 704;
                let d_off_s = eid * HIDDEN * 11;
                let (ie, io, ibias, isc) = prepare_act_int4(&inter_all[ki * EXPERT_INTER..(ki + 1) * EXPERT_INTER]);
                let inter = &inter_all[ki * EXPERT_INTER..(ki + 1) * EXPERT_INTER];
                for r in 0..HIDDEN {
                    let d_row = &d_q4[d_off_q + r * 704..d_off_q + (r + 1) * 704];
                    let d_srow = &d_sc[d_off_s + r * 11..d_off_s + (r + 1) * 11];
                    down[r] = if quantized {
                        int4_dot_row(d_row, d_srow, &ie, &io, &ibias, isc)
                    } else {
                        int4_dot_row_f32(d_row, d_srow, inter)
                    };
                }
            });

        for ki in 0..n_top {
            let (w_k, d_slice) = (top[ki].1, &down_all[ki * HIDDEN..(ki + 1) * HIDDEN]);
            for j in 0..HIDDEN {
                mlp_out[j] += w_k * d_slice[j];
            }
        }
    }

    /// Gera tokens streaming. Cada token emitido corresponde a um forward pass real.
    ///
    /// O `cancel` permite interromper imediatamente a geracao.
    pub fn generate_streaming(
        &self,
        prompt_ids: &[u32],
        cfg: &EngineConfig,
        cancel: Arc<AtomicBool>,
        mut on_token: impl FnMut(u32, &str) -> bool,
    ) -> Result<()> {
        let mut state = self.new_state();
        let mut ids: Vec<u32> = prompt_ids.to_vec();
        if ids.is_empty() {
            bail!("prompt vazio");
        }

        // Prefill: processa todos os tokens do prompt uma unica vez.
        let mut pending_logits: Option<Vec<f32>> = None;
        for (i, &tid) in ids.iter().enumerate() {
            if cancel.load(Ordering::Relaxed) {
                return Ok(());
            }
            pending_logits = Some(self.forward(&mut state, tid, i, cfg.core_loops)?);
        }

        // Decode: um token novo por iteracao, reaproveitando os logits do prefill.
        let mut rng = Rng::new(cfg.seed);
        loop {
            if cancel.load(Ordering::Relaxed) {
                return Ok(());
            }
            let logits = match pending_logits.take() {
                Some(l) => l,
                None => {
                    let last = *ids.last().unwrap();
                    let pos = ids.len() - 1;
                    self.forward(&mut state, last, pos, cfg.core_loops)?
                }
            };
            let next = sample(&logits, cfg, &mut rng);
            let text = self.tokenizer.decode_token(next).to_string();
            ids.push(next);
            state.ids.push(next);
            if !on_token(next, &text) {
                break;
            }
            if next == 1 || next == 100_001 || next == 100_015 {
                break;
            }
            if ids.len() > 100_000 {
                break;
            }
        }
        Ok(())
    }
}

/// Amostra um token a partir dos logits, respeitando temperatura e top-k.
fn sample(logits: &[f32], cfg: &EngineConfig, rng: &mut Rng) -> u32 {
    if cfg.greedy {
        return logits
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(i, _)| i as u32)
            .unwrap_or(0);
    }
    let temp = cfg.temperature.max(0.01);
    let mut scaled: Vec<(usize, f32)> = logits
        .iter()
        .enumerate()
        .map(|(i, &v)| (i, v / temp))
        .collect();
    scaled.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let k = cfg.top_k.clamp(1, scaled.len());
    let top = &scaled[..k];
    let max = top[0].1;
    let mut weights: Vec<f32> = top.iter().map(|(_, v)| (v - max).exp()).collect();
    let sum: f32 = weights.iter().sum();
    if sum <= 0.0 {
        return top[0].0 as u32;
    }
    for w in weights.iter_mut() {
        *w /= sum;
    }
    let r = rng.next_f32();
    let mut acc = 0.0f32;
    for (i, w) in weights.iter().enumerate() {
        acc += *w;
        if r <= acc {
            return top[i].0 as u32;
        }
    }
    top[0].0 as u32
}

/// Gerador pseudoaleatorio deterministico (xorshift128+).
struct Rng {
    s0: u64,
    s1: u64,
}

impl Rng {
    fn new(seed: Option<u64>) -> Self {
        let seed = seed.unwrap_or_else(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos() as u64)
                .unwrap_or(0x2545F4914F6CDD1D)
        });
        Self {
            s0: seed.wrapping_mul(0x9E3779B97F4A7C15) | 1,
            s1: seed.wrapping_mul(0xBF58476D1CE4E5B9) | 1,
        }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.s0;
        let y = self.s1;
        self.s0 = y;
        x ^= x << 23;
        x ^= x >> 17;
        x ^= y ^ (y >> 26);
        self.s1 = x;
        x.wrapping_add(y)
    }

    fn next_f32(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / (1u32 << 24) as f32
    }
}

/// Gate+Up int4 com SwiGLU para uma linha, usando ativacoes even/odd.
#[allow(clippy::too_many_arguments)]
#[allow(dead_code)]
fn int4_row_swiglu(
    g_row: &[u8],
    g_scales: &[f32],
    u_row: &[u8],
    u_scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias: &[f32],
    x_sc: f32,
    _row: usize,
) -> f32 {
    // 1024 colunas = 8 grupos de 128.
    let gv = int4_row_dot(g_row, g_scales, x_even, x_odd, group_bias, x_sc);
    let uv = int4_row_dot(u_row, u_scales, x_even, x_odd, group_bias, x_sc);
    (gv / (1.0 + (-gv).exp())) * uv
}

/// Down projection int4 para uma linha.
#[allow(clippy::too_many_arguments)]
#[allow(dead_code)]
fn int4_row_down(
    d_row: &[u8],
    d_scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias: &[f32],
    x_sc: f32,
    _row: usize,
) -> f32 {
    int4_row_dot(d_row, d_scales, x_even, x_odd, group_bias, x_sc)
}

/// Dot product int4 com ativacao pareada (even/odd), vies de grupo e despacho AVX2.
#[allow(dead_code)]
fn int4_row_dot(
    packed: &[u8],
    scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias: &[f32],
    x_sc: f32,
) -> f32 {
    int4_dot_row(packed, scales, x_even, x_odd, group_bias, x_sc)
}

fn dump_target() -> usize {
    std::env::var("MARK_DUMP_POS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0)
}

fn dump_h(tag: &str, h: &[f32]) {
    let l2: f32 = h.iter().map(|v| v * v).sum::<f32>().sqrt();
    let head: Vec<f32> = h.iter().take(4).copied().collect();
    println!("{tag} l2={l2:.6} h0..3={head:.6?}");
}

fn build_gpu(
    st: &SafeTensors,
    st_exp: &SafeTensors,
    host_lm_q8: &[i8],
    host_lm_scale: &[f32],
    host_cjk_mask: &[u8],
) -> Result<GpuState> {
    let engine = GpuEngine::create()?;
    let mut layers = Vec::with_capacity(N_LAYERS);
    for l in 0..N_LAYERS {
        let sp = format!("layers.{l}");
        let sh = if l == 0 {
            format!("{sp}.mlp")
        } else {
            format!("{sp}.mlp.shared_experts")
        };
        let src: &SafeTensors = if l <= 10 { st } else { st_exp };
        let experts = if (1..=GPU_EXPERT_LAYERS).contains(&l) {
            let p = format!("{sp}.mlp.experts");
            Some(GpuExperts {
                gate_q4: engine.upload_u8(src.u8_slice(&format!("{p}.gate_proj.q4"))?)?,
                gate_sc: engine.upload_f32(&src.f32_vec(&format!("{p}.gate_proj.scale"))?)?,
                up_q4: engine.upload_u8(src.u8_slice(&format!("{p}.up_proj.q4"))?)?,
                up_sc: engine.upload_f32(&src.f32_vec(&format!("{p}.up_proj.scale"))?)?,
                down_q4: engine.upload_u8(src.u8_slice(&format!("{p}.down_proj.q4"))?)?,
                down_sc: engine.upload_f32(&src.f32_vec(&format!("{p}.down_proj.scale"))?)?,
            })
        } else {
            None
        };
        layers.push(GpuLayer {
            q_q8: engine.upload_i8(st.i8_slice(&format!("{sp}.self_attn.q_proj.q8"))?)?,
            q_sc: engine.upload_f32(&st.f32_vec(&format!("{sp}.self_attn.q_proj.scale"))?)?,
            kva_q8: engine
                .upload_i8(st.i8_slice(&format!("{sp}.self_attn.kv_a_proj_with_mqa.q8"))?)?,
            kva_sc: engine
                .upload_f32(&st.f32_vec(&format!("{sp}.self_attn.kv_a_proj_with_mqa.scale"))?)?,
            kvb_q8: engine.upload_i8(st.i8_slice(&format!("{sp}.self_attn.kv_b_proj.q8"))?)?,
            kvb_sc: engine.upload_f32(&st.f32_vec(&format!("{sp}.self_attn.kv_b_proj.scale"))?)?,
            o_q8: engine.upload_i8(st.i8_slice(&format!("{sp}.self_attn.o_proj.q8"))?)?,
            o_sc: engine.upload_f32(&st.f32_vec(&format!("{sp}.self_attn.o_proj.scale"))?)?,
            sh_g_q8: engine.upload_i8(st.i8_slice(&format!("{sh}.gate_proj.q8"))?)?,
            sh_g_sc: engine.upload_f32(&st.f32_vec(&format!("{sh}.gate_proj.scale"))?)?,
            sh_u_q8: engine.upload_i8(st.i8_slice(&format!("{sh}.up_proj.q8"))?)?,
            sh_u_sc: engine.upload_f32(&st.f32_vec(&format!("{sh}.up_proj.scale"))?)?,
            sh_d_q8: engine.upload_i8(st.i8_slice(&format!("{sh}.down_proj.q8"))?)?,
            sh_d_sc: engine.upload_f32(&st.f32_vec(&format!("{sh}.down_proj.scale"))?)?,
            experts,
        });
    }
    engine.sync();
    let lm_q8 = engine.upload_i8(host_lm_q8)?;
    let lm_sc = engine.upload_f32(host_lm_scale)?;
    let cjk_mask = engine.upload_u8(host_cjk_mask)?;
    engine.sync();
    Ok(GpuState {
        engine,
        lm_q8,
        lm_sc,
        cjk_mask,
        layers,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn engine_loads_real_checkpoint_when_present() {
        let Ok(ckpt) = SvidEngine::discover() else {
            eprintln!("checkpoint ausente: teste ignorado");
            return;
        };
        let engine = SvidEngine::load(&ckpt).expect("motor deve carregar o checkpoint real");
        assert_eq!(engine.layers.len(), N_LAYERS);
        assert_eq!(engine.tokenizer().len(), VOCAB, "vocabulario inesperado");
        assert_eq!(engine.context_window(), 2_097_152);
    }

    #[test]
    fn rng_is_deterministic_with_fixed_seed() {
        let mut a = Rng::new(Some(42));
        let mut b = Rng::new(Some(42));
        for _ in 0..16 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
    }

    #[test]
    fn sample_respects_temperature_zero_being_greedy() {
        let logits = vec![0.0f32, 5.0, 1.0, 2.0];
        let cfg = EngineConfig {
            temperature: 0.01,
            top_k: 4,
            seed: Some(1),
            core_loops: 1,
            greedy: false,
        };
        let mut rng = Rng::new(Some(1));
        for _ in 0..8 {
            assert_eq!(sample(&logits, &cfg, &mut rng), 1, "temperatura baixa deve ser gulosa");
        }
    }
}
