//! Motor SVID 1-Bit nativo para Mark-Bin-32B.
//!
//! Implementa o forward pass REAL sobre os pesos do checkpoint, com paridade
//! matematica exata com o motor Rust validado (`mark-v3-rs`):
//! - Embeddings int8 (`embed_tokens.q8`) + escala F16, lidos direto do mmap.
//! - 27 camadas do enxerto DeepSeek-V2-Lite (hidden 2048) com atencao MLA
//!   (q_proj 3072, kv_a 576 = 512 c_kv + 64 rope, kv_b 4096, o_proj 2048).
//! - Camada 0 densa (gate/up/down 10944); camadas 1..26 com MoE (64 experts
//!   roteados top-6 em int4 + shared experts int8).
//! - `forward_moe_gpu_fused` nas camadas 1..13 (GUS/DAW fundidos em PTX sm_75,
//!   shared MLP assincrona) e `routed_six_experts` AVX2/FMA em 48 chunks nas
//!   camadas 14..26, cujos experts permanecem em RAM com page cache quente.
//! - Camada LRD 1-bit (layer 30) via W1A4 XNOR-POPCNT, repetida `core_loops`
//!   vezes (profundidade de raciocinio).
//! - RoPE YaRN intercalado, `routed_scaling_factor = 1.0`, homeostase 1.8,
//!   `bos_token_id = 100000` e mascara CJK no LM head.
//!
//! Nao existe nenhum caminho que produza texto sem executar o forward pass.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use anyhow::{bail, Context, Result};
use rayon::prelude::*;

use crate::avx2::{routed_six_experts, ExpertBatch};
use crate::gpu::{GpuBuffer, GpuEngine, GpuExperts};
use crate::kernels::{
    homeostatic_residual_add_inplace, matvec_i8_f32, rmsnorm_into,
    svid_1bit_linear_subspace_w1a4, YarnRopeSeq,
};
use crate::safetensors::{BinTokenizer, SafeTensors};

pub mod onebit;

use onebit::OneBitEngine;

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
/// Fator de escala do roteamento (DeepSeek-V2 usa 1.0 neste checkpoint).
pub const ROUTED_SCALING_FACTOR: f32 = 1.0;
/// Primeira camada cujos experts ficam fora da VRAM (RAM + page cache).
pub const GPU_EXPERT_LAYERS: usize = 13;
/// Token BOS do checkpoint.
pub const BOS_TOKEN_ID: u32 = 100_000;

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
    lrd_gate_bits: GpuBuffer,
    lrd_gate_row_scale: GpuBuffer,
    lrd_down_bits: GpuBuffer,
    lrd_down_row_scale: GpuBuffer,
    layers: Vec<GpuLayer>,
}

/// Tabelas host de uma camada (normas, escalas e roteador).
struct LayerHost {
    input_norm: Vec<f32>,
    post_norm: Vec<f32>,
    kv_a_norm: Vec<f32>,
    q_scale: Vec<f32>,
    kva_scale: Vec<f32>,
    kvb_scale: Vec<f32>,
    o_scale: Vec<f32>,
    sh_gate_scale: Vec<f32>,
    sh_up_scale: Vec<f32>,
    sh_down_scale: Vec<f32>,
    router: Option<Vec<f32>>,
    exp_gate_scale: Vec<f32>,
    exp_up_scale: Vec<f32>,
    exp_down_scale: Vec<f32>,
    /// `true` quando os experts desta camada estao na VRAM (1..13).
    experts_on_gpu: bool,
}

/// Motor do layout V10 INT4 (64 experts em `isometric_mmap_experts.safetensors`).
struct V10Engine {
    /// `isometric_gpu_core.safetensors` (mmap, zero-copy).
    st: Arc<SafeTensors>,
    /// `isometric_mmap_experts.safetensors` (mmap, zero-copy).
    st_exp: Arc<SafeTensors>,
    layers: Vec<LayerHost>,
    embed_scale: Vec<f32>,
    lm_scale: Vec<f32>,
    cjk_mask: Vec<u8>,
    final_norm: Vec<f32>,
    lrd_gate_bits: Vec<u64>,
    lrd_gate_row_scale: Vec<f32>,
    lrd_gate_col_scale: Vec<f32>,
    lrd_down_bits: Vec<u64>,
    lrd_down_row_scale: Vec<f32>,
    lrd_down_col_scale: Vec<f32>,
    rope: YarnRopeSeq,
    gpu: Option<GpuState>,
    /// Serializa forwards: os buffers temporarios da GPU sao compartilhados.
    exec: Mutex<()>,
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
    /// Contexto K/V por camada (layout `(t * N_HEADS + head) * dim`).
    k_cache: Vec<Vec<f32>>,
    v_cache: Vec<Vec<f32>>,
}

impl V10Engine {

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
        let st_s4 = SafeTensors::open(&shard4)?;
        let st_delta = SafeTensors::open(&delta)?;

        let embed_scale = st.f32_vec("embed_tokens.scale")?;
        let lm_scale = st.f32_vec("lm_head.scale")?;
        let cjk_mask = st.u8_slice("cjk_mask")?.to_vec();
        let final_norm = st_delta.f32_vec("norm.weight")?;
        if embed_scale.len() != VOCAB || lm_scale.len() != VOCAB || cjk_mask.len() != VOCAB {
            bail!("tabelas do vocabulario com tamanho inesperado");
        }

        let mut layers = Vec::with_capacity(N_LAYERS);
        for l in 0..N_LAYERS {
            let sp = format!("layers.{l}");
            let mut lh = LayerHost {
                input_norm: st.f32_vec(&format!("{sp}.input_layernorm.weight"))?,
                post_norm: st.f32_vec(&format!("{sp}.post_attention_layernorm.weight"))?,
                kv_a_norm: st.f32_vec(&format!("{sp}.self_attn.kv_a_layernorm.weight"))?,
                q_scale: st.f32_vec(&format!("{sp}.self_attn.q_proj.scale"))?,
                kva_scale: st.f32_vec(&format!("{sp}.self_attn.kv_a_proj_with_mqa.scale"))?,
                kvb_scale: st.f32_vec(&format!("{sp}.self_attn.kv_b_proj.scale"))?,
                o_scale: st.f32_vec(&format!("{sp}.self_attn.o_proj.scale"))?,
                sh_gate_scale: Vec::new(),
                sh_up_scale: Vec::new(),
                sh_down_scale: Vec::new(),
                router: None,
                exp_gate_scale: Vec::new(),
                exp_up_scale: Vec::new(),
                exp_down_scale: Vec::new(),
                experts_on_gpu: (1..=GPU_EXPERT_LAYERS).contains(&l),
            };
            if l == 0 {
                lh.sh_gate_scale = st.f32_vec("layers.0.mlp.gate_proj.scale")?;
                lh.sh_up_scale = st.f32_vec("layers.0.mlp.up_proj.scale")?;
                lh.sh_down_scale = st.f32_vec("layers.0.mlp.down_proj.scale")?;
            } else {
                lh.router = Some(st.f32_vec(&format!("{sp}.mlp.gate.weight"))?);
                lh.sh_gate_scale =
                    st.f32_vec(&format!("{sp}.mlp.shared_experts.gate_proj.scale"))?;
                lh.sh_up_scale = st.f32_vec(&format!("{sp}.mlp.shared_experts.up_proj.scale"))?;
                lh.sh_down_scale = st.f32_vec(&format!("{sp}.mlp.shared_experts.down_proj.scale"))?;
                let src: &SafeTensors = if l <= 10 { &st } else { &st_exp };
                lh.exp_gate_scale =
                    src.f32_vec(&format!("{sp}.mlp.experts.gate_proj.scale"))?;
                lh.exp_up_scale = src.f32_vec(&format!("{sp}.mlp.experts.up_proj.scale"))?;
                lh.exp_down_scale = src.f32_vec(&format!("{sp}.mlp.experts.down_proj.scale"))?;
            }
            layers.push(lh);
        }

        let lrd_gate_bits =
            st_s4.u64_vec("model.layers.30.mlp.shared_experts.0.gate_proj.packed_bits")?;
        let lrd_gate_row_scale = st_delta.f32_vec("lrd.30.g_rs")?;
        let lrd_gate_col_scale =
            st_s4.f32_vec("model.layers.30.mlp.shared_experts.0.gate_proj.col_scale")?;
        let lrd_down_bits =
            st_s4.u64_vec("model.layers.30.mlp.shared_experts.0.down_proj.packed_bits")?;
        let lrd_down_row_scale = st_delta.f32_vec("lrd.30.d_rs")?;
        let lrd_down_col_scale =
            st_s4.f32_vec("model.layers.30.mlp.shared_experts.0.down_proj.col_scale")?;
        // O kernel W1A4 le a escala de linha em FP16 cru, exatamente como o
        // checkpoint (e o motor de referencia) a armazena.
        let lrd_gate_row_scale_f16 = st_delta.raw("lrd.30.g_rs")?.to_vec();
        let lrd_down_row_scale_f16 = st_delta.raw("lrd.30.d_rs")?.to_vec();

        let gpu = if std::env::var("MARK_FORCE_CPU").is_ok() {
            eprintln!("svid: MARK_FORCE_CPU definido, inferencia na CPU");
            None
        } else {
            // Nunca engolir o erro: um fallback silencioso para a CPU derruba a
            // taxa de ~31 tok/s para ~11 tok/s sem nenhum sinal no log.
            match build_gpu(
                &st,
                &st_exp,
                &lm_scale,
                &cjk_mask,
                &lrd_gate_bits,
                &lrd_gate_row_scale_f16,
                &lrd_down_bits,
                &lrd_down_row_scale_f16,
            ) {
                Ok(state) => Some(state),
                Err(error) => {
                    eprintln!("svid: GPU indisponivel ({error:#}); caindo para CPU");
                    None
                }
            }
        };

        // Page cache: o que foi para a VRAM sai; o que roda na CPU (14..26) fica.
        if gpu.is_some() {
            evict_uploaded_pages(&st, &st_exp);
            warm_cpu_expert_layers(&st_exp);
        }

        Ok(Self {
            st,
            st_exp,
            layers,
            embed_scale,
            lm_scale,
            cjk_mask,
            final_norm,
            lrd_gate_bits,
            lrd_gate_row_scale,
            lrd_gate_col_scale,
            lrd_down_bits,
            lrd_down_row_scale,
            lrd_down_col_scale,
            rope: YarnRopeSeq::new(ROPE_DIM, HEAD_DIM),
            gpu,
            exec: Mutex::new(()),
        })
    }





    /// Indica se o caminho GPU PTX esta ativo.
    pub fn gpu_active(&self) -> bool {
        self.gpu.is_some()
    }




    /// Executa o forward pass para um token e devolve os logits.
    fn forward(
        &self,
        state: &mut GenerationState,
        token_id: u32,
        pos: usize,
        core_loops: u32,
        is_last: bool,
    ) -> Result<Vec<f32>> {
        let tid = token_id as usize;
        if tid >= VOCAB {
            bail!("token id fora do vocabulario: {token_id}");
        }
        let _guard = self.exec.lock().unwrap_or_else(|e| e.into_inner());

        let emb = self.st.i8_slice("embed_tokens.q8")?;
        let mut h = vec![0.0f32; HIDDEN];
        let sc = self.embed_scale[tid];
        let row = &emb[tid * HIDDEN..(tid + 1) * HIDDEN];
        for j in 0..HIDDEN {
            h[j] = (row[j] as f32) * sc;
        }

        let mut xn = vec![0.0f32; HIDDEN];
        let mut q_buf = vec![0.0f32; N_HEADS * HEAD_DIM];
        let mut kva_buf = vec![0.0f32; C_KV + ROPE_DIM];
        let mut c_kv = vec![0.0f32; C_KV];
        let mut kvb_buf = vec![0.0f32; N_HEADS * 2 * NOPE_DIM];
        let mut ctx_buf = vec![0.0f32; HIDDEN];
        let mut attn_out = vec![0.0f32; HIDDEN];
        let mut mlp_out = vec![0.0f32; HIDDEN];
        let mut shared_out = vec![0.0f32; HIDDEN];
        let mut k_pe = [0.0f32; ROPE_DIM];
        let gpu_ref = self.gpu.as_ref();
        let attn_scale = self.rope.softmax_scale();
        let diag = is_last && std::env::var("MARK_DIAG").is_ok();
        // Diagnostico A/B: forca experts roteados pelo caminho AVX2 mesmo nas
        // camadas que tem copia na VRAM, para comparar os dois kernels.
        let force_cpu_moe = std::env::var("MARK_MOE_CPU").is_ok();
        if diag {
            let l2: f32 = h.iter().map(|v| v * v).sum::<f32>().sqrt();
            println!("DIAG embed l2={l2:.6} h0={:.6?}", &h[0..4]);
        }

        for l in 0..N_LAYERS {
            let lh = &self.layers[l];
            let sp = format!("layers.{l}");
            rmsnorm_into(&h, &lh.input_norm, 1e-6, &mut xn);

            // Prefill: a ultima camada so precisa alimentar o K/V dos tokens
            // anteriores ao ultimo; a saida deles nao alimenta nenhuma camada.
            let kv_only = l + 1 == N_LAYERS && !is_last;

            if !kv_only {
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
                        self.st.i8_slice(&format!("{sp}.self_attn.q_proj.q8"))?,
                        &lh.q_scale,
                        N_HEADS * HEAD_DIM,
                        HIDDEN,
                        &mut q_buf,
                    );
                    matvec_i8_f32(
                        &xn,
                        self.st
                            .i8_slice(&format!("{sp}.self_attn.kv_a_proj_with_mqa.q8"))?,
                        &lh.kva_scale,
                        C_KV + ROPE_DIM,
                        HIDDEN,
                        &mut kva_buf,
                    );
                }
                for hd in 0..N_HEADS {
                    let base = hd * HEAD_DIM;
                    self.rope
                        .apply_head_in_place(&mut q_buf[base + NOPE_DIM..base + HEAD_DIM], pos);
                }
            } else if let Some(g) = gpu_ref {
                let gl = &g.layers[l];
                g.engine.matvec_i8(
                    &xn,
                    &gl.kva_q8,
                    &gl.kva_sc,
                    None,
                    C_KV + ROPE_DIM,
                    HIDDEN,
                    &mut kva_buf,
                )?;
            } else {
                matvec_i8_f32(
                    &xn,
                    self.st
                        .i8_slice(&format!("{sp}.self_attn.kv_a_proj_with_mqa.q8"))?,
                    &lh.kva_scale,
                    C_KV + ROPE_DIM,
                    HIDDEN,
                    &mut kva_buf,
                );
            }

            rmsnorm_into(&kva_buf[0..C_KV], &lh.kv_a_norm, 1e-6, &mut c_kv);
            k_pe.copy_from_slice(&kva_buf[C_KV..C_KV + ROPE_DIM]);
            self.rope.apply_head_in_place(&mut k_pe, pos);

            if let Some(g) = gpu_ref {
                let gl = &g.layers[l];
                g.engine.matvec_i8(
                    &c_kv,
                    &gl.kvb_q8,
                    &gl.kvb_sc,
                    None,
                    N_HEADS * 2 * NOPE_DIM,
                    C_KV,
                    &mut kvb_buf,
                )?;
            } else {
                matvec_i8_f32(
                    &c_kv,
                    self.st.i8_slice(&format!("{sp}.self_attn.kv_b_proj.q8"))?,
                    &lh.kvb_scale,
                    N_HEADS * 2 * NOPE_DIM,
                    C_KV,
                    &mut kvb_buf,
                );
            }

            for hd in 0..N_HEADS {
                state.k_cache[l].extend_from_slice(&kvb_buf[hd * 256..hd * 256 + NOPE_DIM]);
                state.k_cache[l].extend_from_slice(&k_pe);
                state.v_cache[l]
                    .extend_from_slice(&kvb_buf[hd * 256 + NOPE_DIM..(hd + 1) * 256]);
            }
            if kv_only {
                continue;
            }

            let s_tot = pos + 1;
            let k_tok = state.k_cache[l].as_slice();
            let v_tok = state.v_cache[l].as_slice();
            ctx_buf
                .par_chunks_mut(NOPE_DIM)
                .enumerate()
                .for_each(|(hd, ctx_h)| {
                    let q_h = &q_buf[hd * HEAD_DIM..(hd + 1) * HEAD_DIM];
                    let mut scores = vec![0.0f32; s_tot];
                    let mut max_s = f32::NEG_INFINITY;
                    for t in 0..s_tot {
                        let k_base = (t * N_HEADS + hd) * HEAD_DIM;
                        let k_h = &k_tok[k_base..k_base + HEAD_DIM];
                        let mut dot = 0.0f32;
                        for d in 0..HEAD_DIM {
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
                    for d in ctx_h.iter_mut() {
                        *d = 0.0;
                    }
                    for t in 0..s_tot {
                        let p = scores[t] / sum_e;
                        let v_base = (t * N_HEADS + hd) * NOPE_DIM;
                        let v_h = &v_tok[v_base..v_base + NOPE_DIM];
                        for d in 0..NOPE_DIM {
                            ctx_h[d] += p * v_h[d];
                        }
                    }
                });

            if let Some(g) = gpu_ref {
                let gl = &g.layers[l];
                g.engine.matvec_i8(
                    &ctx_buf,
                    &gl.o_q8,
                    &gl.o_sc,
                    None,
                    HIDDEN,
                    HIDDEN,
                    &mut attn_out,
                )?;
            } else {
                matvec_i8_f32(
                    &ctx_buf,
                    self.st.i8_slice(&format!("{sp}.self_attn.o_proj.q8"))?,
                    &lh.o_scale,
                    HIDDEN,
                    HIDDEN,
                    &mut attn_out,
                );
            }
            homeostatic_residual_add_inplace(&mut h, &attn_out, 1.8);
            rmsnorm_into(&h, &lh.post_norm, 1e-6, &mut xn);
            // Os acumuladores sao zerados por camada: o caminho AVX2 dos experts
            // soma em `mlp_out`, enquanto os caminhos GPU escrevem por cima.
            mlp_out.fill(0.0);
            shared_out.fill(0.0);

            if l == 0 {
                // Camada densa: gate/up/down 10944.
                if let Some(g) = gpu_ref {
                    let gl = &g.layers[0];
                    g.engine.shared_mlp(
                        &xn,
                        &gl.sh_g_q8,
                        &gl.sh_g_sc,
                        &gl.sh_u_q8,
                        &gl.sh_u_sc,
                        &gl.sh_d_q8,
                        &gl.sh_d_sc,
                        DENSE_INTER,
                    )?;
                    g.engine.fetch_shared(&mut mlp_out)?;
                } else {
                    let mut g0 = vec![0.0f32; DENSE_INTER];
                    let mut u0 = vec![0.0f32; DENSE_INTER];
                    matvec_i8_f32(
                        &xn,
                        self.st.i8_slice("layers.0.mlp.gate_proj.q8")?,
                        &lh.sh_gate_scale,
                        DENSE_INTER,
                        HIDDEN,
                        &mut g0,
                    );
                    matvec_i8_f32(
                        &xn,
                        self.st.i8_slice("layers.0.mlp.up_proj.q8")?,
                        &lh.sh_up_scale,
                        DENSE_INTER,
                        HIDDEN,
                        &mut u0,
                    );
                    for i in 0..DENSE_INTER {
                        g0[i] = (g0[i] / (1.0 + (-g0[i]).exp())) * u0[i];
                    }
                    matvec_i8_f32(
                        &g0,
                        self.st.i8_slice("layers.0.mlp.down_proj.q8")?,
                        &lh.sh_down_scale,
                        HIDDEN,
                        DENSE_INTER,
                        &mut mlp_out,
                    );
                }
            } else {
                let top = self.route_top6(lh, &xn);
                let batch = ExpertBatch {
                    gate_q4: self.expert_slice(l, "gate_proj.q4")?,
                    gate_sc: &lh.exp_gate_scale,
                    up_q4: self.expert_slice(l, "up_proj.q4")?,
                    up_sc: &lh.exp_up_scale,
                    down_q4: self.expert_slice(l, "down_proj.q4")?,
                    down_sc: &lh.exp_down_scale,
                };
                if lh.experts_on_gpu && !force_cpu_moe {
                    // Shared MLP assincrona + GUS/DAW fundidos por expert.
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
                        if let Some(ex) = gl.experts.as_ref() {
                            for (eid, w) in top.iter() {
                                g.engine
                                    .moe_add_expert(&xn, ex, *eid, *w, EXPERT_INTER, HIDDEN)?;
                            }
                            g.engine.fetch_shared(&mut mlp_out)?;
                            homeostatic_residual_add_inplace(&mut h, &mlp_out, 1.8);
                            if diag {
                                let l2: f32 = h.iter().map(|v| v * v).sum::<f32>().sqrt();
                                println!("DIAG L{l} l2={l2:.6} h0={:.6?}", &h[0..4]);
                            }
                            continue;
                        }
                        g.engine.fetch_shared(&mut shared_out)?;
                    }
                    for j in 0..HIDDEN {
                        mlp_out[j] += shared_out[j];
                    }
                } else {
                    // Camadas 14..26: shared MLP na GPU em paralelo com 48 chunks AVX2.
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
                    } else {
                        let mut sh_g = vec![0.0f32; SHARED_INTER];
                        let mut sh_u = vec![0.0f32; SHARED_INTER];
                        matvec_i8_f32(
                            &xn,
                            self.st
                                .i8_slice(&format!("{sp}.mlp.shared_experts.gate_proj.q8"))?,
                            &lh.sh_gate_scale,
                            SHARED_INTER,
                            HIDDEN,
                            &mut sh_g,
                        );
                        matvec_i8_f32(
                            &xn,
                            self.st
                                .i8_slice(&format!("{sp}.mlp.shared_experts.up_proj.q8"))?,
                            &lh.sh_up_scale,
                            SHARED_INTER,
                            HIDDEN,
                            &mut sh_u,
                        );
                        for i in 0..SHARED_INTER {
                            sh_g[i] = (sh_g[i] / (1.0 + (-sh_g[i]).exp())) * sh_u[i];
                        }
                        matvec_i8_f32(
                            &sh_g,
                            self.st
                                .i8_slice(&format!("{sp}.mlp.shared_experts.down_proj.q8"))?,
                            &lh.sh_down_scale,
                            HIDDEN,
                            SHARED_INTER,
                            &mut shared_out,
                        );
                    }
                    routed_six_experts(&top, &xn, EXPERT_INTER, HIDDEN, &batch, &mut mlp_out);
                    if let Some(g) = gpu_ref {
                        g.engine.fetch_shared(&mut shared_out)?;
                    }
                    if diag && (l == 14 || l == 15) {
                        let e2: f32 = mlp_out.iter().map(|v| v * v).sum::<f32>().sqrt();
                        let s2: f32 = shared_out.iter().map(|v| v * v).sum::<f32>().sqrt();
                        let x2: f32 = xn.iter().map(|v| v * v).sum::<f32>().sqrt();
                        println!("DIAG MOE l={l} xn={x2:.6} exp={e2:.6} sh={s2:.6} top={top:?}");
                    }
                    for j in 0..HIDDEN {
                        mlp_out[j] += shared_out[j];
                    }
                }
            }
            homeostatic_residual_add_inplace(&mut h, &mlp_out, 1.8);
            if diag {
                let l2: f32 = h.iter().map(|v| v * v).sum::<f32>().sqrt();
                println!("DIAG L{l} l2={l2:.6} h0={:.6?}", &h[0..4]);
            }
        }

        // Bloco recorrente LRD 1-bit (camada 30 enxertada), `core_loops` vezes.
        let loops = core_loops.clamp(1, 4);
        let mut lrd_g = vec![0.0f32; self.lrd_gate_row_scale.len().min(HIDDEN)];
        let mut lrd_d = vec![0.0f32; self.lrd_down_row_scale.len().min(HIDDEN)];
        for _ in 0..loops {
            match gpu_ref {
                Some(g) => {
                    g.engine.w1a4_matvec(
                        &h,
                        &self.lrd_gate_col_scale,
                        &g.lrd_gate_bits,
                        &g.lrd_gate_row_scale,
                        self.lrd_gate_row_scale.len(),
                        &mut lrd_g,
                    )?;
                    g.engine.w1a4_matvec(
                        &lrd_g[0..HIDDEN],
                        &self.lrd_down_col_scale,
                        &g.lrd_down_bits,
                        &g.lrd_down_row_scale,
                        self.lrd_down_row_scale.len(),
                        &mut lrd_d,
                    )?;
                }
                None => {
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
                    lrd_d[..HIDDEN].copy_from_slice(&d1[0..HIDDEN]);
                }
            }
            homeostatic_residual_add_inplace(&mut h, &lrd_d[0..HIDDEN], 0.001);
        }
        if diag {
            let l2: f32 = h.iter().map(|v| v * v).sum::<f32>().sqrt();
            println!("DIAG LRD l2={l2:.6} h0={:.6?}", &h[0..4]);
        }

        rmsnorm_into(&h, &self.final_norm, 1e-6, &mut xn);

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
            let lm_q8 = self.st.i8_slice("lm_head.q8")?;
            logits.par_iter_mut().enumerate().for_each(|(r, y)| {
                if self.cjk_mask[r] != 0 {
                    *y = -1e9;
                    return;
                }
                let w = &lm_q8[r * HIDDEN..(r + 1) * HIDDEN];
                *y = crate::kernels::dot_i8_f32(w, &xn) * self.lm_scale[r];
            });
        }
        Ok(logits)
    }

    /// Visao zero-copy de um tensor de experts da camada `l`.
    fn expert_slice(&self, l: usize, suffix: &str) -> Result<&[u8]> {
        let name = format!("layers.{l}.mlp.experts.{suffix}");
        let src: &SafeTensors = if l <= 10 { &self.st } else { &self.st_exp };
        src.u8_slice(&name)
    }

    /// Roteamento top-6 com softmax sobre os 64 experts (fator de escala 1.0).
    fn route_top6(&self, lh: &LayerHost, xn: &[f32]) -> Vec<(usize, f32)> {
        let router = lh.router.as_ref().expect("router ausente em camada MoE");
        let mut e_scores: Vec<(usize, f32)> = (0..N_EXPERTS)
            .map(|e| {
                let r = &router[e * HIDDEN..(e + 1) * HIDDEN];
                (e, r.iter().zip(xn.iter()).map(|(a, b)| a * b).sum())
            })
            .collect();
        let max_g = e_scores
            .iter()
            .map(|x| x.1)
            .fold(f32::NEG_INFINITY, f32::max);
        let mut sum_eg = 0.0f32;
        for es in e_scores.iter_mut() {
            es.1 = (es.1 - max_g).exp();
            sum_eg += es.1;
        }
        let sum_eg = sum_eg.max(1e-9);
        for es in e_scores.iter_mut() {
            es.1 = es.1 / sum_eg * ROUTED_SCALING_FACTOR;
        }
        e_scores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        e_scores.truncate(TOP_K_EXPERTS);
        e_scores
    }

}


/// Motor de inferencia carregado: layout 1-bit de 32.054B (GPU-only) ou V10 INT4.
pub struct SvidEngine {
    inner: Inner,
    tokenizer: BinTokenizer,
    checkpoint_dir: PathBuf,
    /// `false` desliga a mascara CJK (prompt escrito em idioma CJK).
    cjk_suppression: AtomicBool,
    /// Serializa forwards do caminho 1-bit (buffers temporarios compartilhados).
    exec: Mutex<()>,
}

enum Inner {
    /// Layout historico V10 INT4 (64 experts), com fallback de CPU.
    V10(Box<V10Engine>),
    /// Layout 1-bit de 32.054B (136 experts), 100% na VRAM.
    OneBit(Box<OneBitEngine>),
}

impl SvidEngine {
    /// Localiza e carrega o checkpoint Mark-Bin-32B.
    pub fn discover() -> Result<PathBuf> {
        mark_core::paths::mark_bin_32b_checkpoint()
            .context("checkpoint Mark-Bin-32B nao encontrado no volume externo")
    }

    /// Carrega o motor a partir do diretorio do checkpoint.
    ///
    /// Quando os arquivos do layout 1-bit de 32.054B existem, esse caminho e o
    /// padrao e roda 100% na GPU: qualquer falha de CUDA vira erro propagado,
    /// nunca um fallback silencioso para a CPU.
    pub fn load(checkpoint_dir: &Path) -> Result<Self> {
        if let Some((core_dir, onebit_dir)) = onebit::discover_layout(Some(checkpoint_dir)) {
            let engine = OneBitEngine::load(&core_dir, &onebit_dir).with_context(|| {
                format!(
                    "motor 1-bit GPU-only (core {}, experts {})",
                    core_dir.display(),
                    onebit_dir.display()
                )
            })?;
            let tok_path = core_dir.join("rust_tokenizer_v10.bin");
            if !tok_path.is_file() {
                bail!("tokenizador ausente no layout 1-bit: {}", tok_path.display());
            }
            let tokenizer = BinTokenizer::load(&tok_path)?;
            if tokenizer.len() != VOCAB {
                bail!(
                    "tokenizador com {} entradas, esperado {VOCAB}",
                    tokenizer.len()
                );
            }
            return Ok(Self {
                inner: Inner::OneBit(Box::new(engine)),
                tokenizer,
                checkpoint_dir: core_dir,
                cjk_suppression: AtomicBool::new(true),
                exec: Mutex::new(()),
            });
        }
        Self::load_v10(checkpoint_dir)
    }

    /// Carrega explicitamente o layout V10 INT4, ignorando o layout 1-bit.
    ///
    /// Existe para testes de regressao do layout antigo (64 experts int4):
    /// `load` prefere o motor 1-bit de 32.054B quando ele esta no disco.
    pub fn load_v10(checkpoint_dir: &Path) -> Result<Self> {
        let v10 = V10Engine::load(checkpoint_dir)?;
        let tok_path = checkpoint_dir.join("rust_tokenizer_v10.bin");
        let tokenizer = BinTokenizer::load(&tok_path)?;
        Ok(Self {
            inner: Inner::V10(Box::new(v10)),
            tokenizer,
            checkpoint_dir: checkpoint_dir.to_path_buf(),
            cjk_suppression: AtomicBool::new(true),
            exec: Mutex::new(()),
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

    /// Indica se o caminho acelerado esta ativo (o layout 1-bit e GPU-only).
    pub fn gpu_active(&self) -> bool {
        match &self.inner {
            Inner::V10(engine) => engine.gpu_active(),
            Inner::OneBit(_) => true,
        }
    }

    /// `true` quando o motor carregado e o layout 1-bit de 32.054B.
    pub fn is_onebit(&self) -> bool {
        matches!(self.inner, Inner::OneBit(_))
    }

    /// Acesso ao motor 1-bit, quando ele e o layout ativo.
    pub fn onebit(&self) -> Option<&OneBitEngine> {
        match &self.inner {
            Inner::OneBit(engine) => Some(engine),
            Inner::V10(_) => None,
        }
    }

    /// Liga ou desliga a mascara CJK do LM head (prompt em idioma CJK nao leva mascara).
    pub fn set_cjk_suppression(&self, enabled: bool) {
        self.cjk_suppression.store(enabled, Ordering::Relaxed);
    }

    /// Executa o prefill completo e devolve os logits da proxima posicao.
    pub fn prefill_logits(&self, prompt_ids: &[u32], core_loops: u32) -> Result<Vec<f32>> {
        if prompt_ids.is_empty() {
            bail!("prompt vazio");
        }
        let mut state = self.new_state();
        let last = prompt_ids.len() - 1;
        let mut logits = Vec::new();
        for (i, &tid) in prompt_ids.iter().enumerate() {
            logits = self.forward(&mut state, tid, i, core_loops, i == last)?;
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
        self.forward(state, token_id, pos, core_loops, true)
    }

    /// Executa um unico forward pass e devolve os logits (usado em testes e diagnose).
    pub fn forward_for_test(&self, token_id: u32, pos: usize, core_loops: u32) -> Result<Vec<f32>> {
        let mut state = self.new_state();
        self.forward(&mut state, token_id, pos, core_loops, true)
    }

    /// Executa um passo do forward no layout ativo.
    fn forward(
        &self,
        state: &mut GenerationState,
        token_id: u32,
        pos: usize,
        core_loops: u32,
        is_last: bool,
    ) -> Result<Vec<f32>> {
        match &self.inner {
            Inner::V10(engine) => engine.forward(state, token_id, pos, core_loops, is_last),
            Inner::OneBit(engine) => {
                let _guard = self.exec.lock().unwrap_or_else(|e| e.into_inner());
                let apply_cjk = self.cjk_suppression.load(Ordering::Relaxed);
                engine.forward(state, token_id, pos, is_last, apply_cjk)
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
        if prompt_ids.is_empty() {
            bail!("prompt vazio");
        }
        let mut state = self.new_state();
        let mut ids: Vec<u32> = prompt_ids.to_vec();

        // Prefill: todos os tokens do prompt, com o atalho de K/V na ultima camada.
        let mut pending_logits: Option<Vec<f32>> = None;
        let last = ids.len() - 1;
        for i in 0..ids.len() {
            if cancel.load(Ordering::Relaxed) {
                return Ok(());
            }
            pending_logits = Some(self.forward(&mut state, ids[i], i, cfg.core_loops, i == last)?);
        }

        let mut rng = Rng::new(cfg.seed);
        loop {
            if cancel.load(Ordering::Relaxed) {
                return Ok(());
            }
            let logits = match pending_logits.take() {
                Some(l) => l,
                None => {
                    let last_tok = *ids.last().unwrap();
                    let pos = ids.len() - 1;
                    self.forward(&mut state, last_tok, pos, cfg.core_loops, true)?
                }
            };
            if logits.is_empty() {
                bail!("motor nao devolveu logits para a proxima posicao");
            }
            let next = sample(&logits, cfg, &mut rng);
            // Token de fim de sequencia nunca vira texto nem vai para o SSE:
            // a checagem acontece ANTES de emitir, nao depois.
            if is_stop_token(next) {
                break;
            }
            let text = self.tokenizer.decode_token(next).to_string();
            if is_special_token_text(&text) {
                break;
            }
            ids.push(next);
            state.ids.push(next);
            if !on_token(next, &text) {
                break;
            }
            if ids.len() > 100_000 {
                break;
            }
        }
        Ok(())
    }
}

/// Tokens de fim de sequencia do checkpoint (nunca viram texto).
fn is_stop_token(id: u32) -> bool {
    matches!(id, 1 | 100_001 | 100_015)
}

/// Texto de token especial (ex.: `<｜end_of_query｜>`): nunca vai para a bolha
/// nem para o SSE, mesmo que o id nao esteja na lista de parada.
fn is_special_token_text(text: &str) -> bool {
    text.contains("<|") || text.contains("<\u{ff5c}") || text.contains("end_of_sentence")
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

/// Envia para a VRAM tudo o que a GPU precisa e devolve os buffers.
#[allow(clippy::too_many_arguments)]
fn build_gpu(
    st: &SafeTensors,
    st_exp: &SafeTensors,
    host_lm_scale: &[f32],
    host_cjk_mask: &[u8],
    lrd_gate_bits: &[u64],
    lrd_gate_row_scale_f16: &[u8],
    lrd_down_bits: &[u64],
    lrd_down_row_scale_f16: &[u8],
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
        let experts = if (1..=GPU_EXPERT_LAYERS).contains(&l) {
            let p = format!("{sp}.mlp.experts");
            let src: &SafeTensors = if l <= 10 { st } else { st_exp };
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
    let lm_q8 = engine.upload_i8(st.i8_slice("lm_head.q8")?)?;
    let lm_sc = engine.upload_f32(host_lm_scale)?;
    let cjk_mask = engine.upload_u8(host_cjk_mask)?;
    let lrd_gate = engine.upload_u64(lrd_gate_bits)?;
    let lrd_gate_rs = engine.upload_u8(lrd_gate_row_scale_f16)?;
    let lrd_down = engine.upload_u64(lrd_down_bits)?;
    let lrd_down_rs = engine.upload_u8(lrd_down_row_scale_f16)?;
    engine.sync();
    Ok(GpuState {
        engine,
        lm_q8,
        lm_sc,
        cjk_mask,
        lrd_gate_bits: lrd_gate,
        lrd_gate_row_scale: lrd_gate_rs,
        lrd_down_bits: lrd_down,
        lrd_down_row_scale: lrd_down_rs,
        layers,
    })
}

/// Descarta do page cache tudo o que ja foi copiado para a VRAM.
///
/// `embed_tokens` fica de fora: a linha do token e lida do mmap a cada passo.
fn evict_uploaded_pages(st: &SafeTensors, st_exp: &SafeTensors) {
    let keep = ["embed_tokens.q8", "embed_tokens.scale"];
    let mut dropped = 0usize;
    for name in st.tensor_names() {
        if keep.contains(&name) {
            continue;
        }
        if let Some((a, b)) = st.file_range(name) {
            st.drop_cache(a, b);
            dropped += b - a;
        }
    }
    // Camadas 11..13 de st_exp foram para a VRAM; 14..26 ficam no page cache.
    for l in 11..=GPU_EXPERT_LAYERS {
        for proj in ["gate_proj.q4", "up_proj.q4", "down_proj.q4"] {
            let name = format!("layers.{l}.mlp.experts.{proj}");
            if let Some((a, b)) = st_exp.file_range(&name) {
                st_exp.drop_cache(a, b);
                dropped += b - a;
            }
        }
    }
    std::hint::black_box(dropped);
}

/// Aquece somente as camadas 14..26 (~3.1 GB) que rodam na CPU.
fn warm_cpu_expert_layers(st_exp: &SafeTensors) {
    if std::env::var("MARK_NO_WARM").is_ok() {
        return;
    }
    let mut warmed = 0usize;
    for l in (GPU_EXPERT_LAYERS + 1)..N_LAYERS {
        for proj in ["gate_proj.q4", "up_proj.q4", "down_proj.q4"] {
            let name = format!("layers.{l}.mlp.experts.{proj}");
            if let Some((a, b)) = st_exp.file_range(&name) {
                warmed += st_exp.warm_range(a, b);
            }
        }
    }
    std::hint::black_box(warmed);
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
        // O layout V10 mantem ~4.5 GB de experts int4 na VRAM.
        let free_mib = crate::gpu::free_memory_mib().unwrap_or(0);
        if free_mib < 5600 {
            eprintln!("VRAM livre {free_mib} MiB (< 5600): teste do layout V10 ignorado");
            return;
        }
        let engine = V10Engine::load(&ckpt).expect("motor deve carregar o checkpoint real");
        assert_eq!(engine.layers.len(), N_LAYERS);
        assert!(
            engine.gpu_active() || std::env::var("MARK_FORCE_CPU").is_ok(),
            "layout V10 sem GPU e sem MARK_FORCE_CPU"
        );
    }

    #[test]
    fn automatic_engine_picks_the_1bit_layout_when_present() {
        let Ok(ckpt) = SvidEngine::discover() else {
            eprintln!("checkpoint ausente: teste ignorado");
            return;
        };
        let Some((core, onebit_dir)) = onebit::discover_layout(Some(&ckpt)) else {
            eprintln!("layout 1-bit ausente: teste ignorado");
            return;
        };
        let free_mib = crate::gpu::free_memory_mib().unwrap_or(0);
        if free_mib < onebit::VRAM_REQUIRED_MIB {
            eprintln!(
                "VRAM livre {free_mib} MiB (< {}): teste do motor 1-bit ignorado",
                onebit::VRAM_REQUIRED_MIB
            );
            return;
        }
        let engine = SvidEngine::load(&ckpt).expect("motor deve carregar o checkpoint real");
        assert!(engine.is_onebit(), "layout 1-bit deveria ser o padrao");
        assert_eq!(engine.tokenizer().len(), VOCAB, "vocabulario inesperado");
        assert_eq!(engine.context_window(), 2_097_152);
        assert_eq!(engine.checkpoint_dir(), core.as_path());
        let ob = engine.onebit().expect("motor 1-bit presente");
        assert_eq!(ob.layer_count(), N_LAYERS);
        assert_eq!(ob.expert_count(), onebit::N_EXPERTS_1BIT);
        assert_eq!(ob.lrd_count(), onebit::LRD_LAYER_LAST - onebit::LRD_LAYER_FIRST);
        assert!(ob.mapped_tensors() > 0, "nenhum tensor mapeado");
        std::hint::black_box(onebit_dir);
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
            assert_eq!(
                sample(&logits, &cfg, &mut rng),
                1,
                "temperatura baixa deve ser gulosa"
            );
        }
    }
}
