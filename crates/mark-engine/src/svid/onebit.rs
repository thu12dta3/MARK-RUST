//! Caminho 1-bit GPU-only do Mark-Bin-32B (32.054B).
//!
//! 26 camadas MoE com 136 experts 1-bit cada (~3.9 GB de planos de bits),
//! projecoes Highway INT8, LoRAs do delta V11, bloco recorrente LRD 30..39 em
//! 1-bit e LM head INT8. Todos os pesos vivem na VRAM; nao existe caminho CPU.
//!
//! Porte fiel do motor de referencia validado (`mark-v3-rs`,
//! `run_32b_1bit_gpu.rs`): mesmas invariantes numericas, mesma ordem de
//! operacoes e o mesmo kernel W1A4 (um warp de 32 lanes por linha, reducao
//! `shfl.sync.down.b32`, escala de linha em FP16).

use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{bail, Context, Result};

use crate::gpu::{GpuBuffer, GpuEngine};
use crate::kernels::rmsnorm_into;
use crate::safetensors::{f16_to_f32, SafeTensors};

use super::{
    GenerationState, C_KV, DENSE_INTER, EXPERT_INTER, HEAD_DIM, HIDDEN, N_LAYERS, N_HEADS,
    NOPE_DIM, ROPE_DIM, SHARED_INTER, VOCAB,
};

/// Experts roteados por camada no layout 1-bit (32.054B).
pub const N_EXPERTS_1BIT: usize = 136;
/// Experts ativados por token.
pub const TOP_K_1BIT: usize = 6;
/// Escala do roteador validada para 136 experts.
pub const GATE_SCALE_1BIT: f32 = 2.125;
/// Ganho do residuo homeostatico.
pub const HOMEOSTASIS: f32 = 1.8;
/// Limite do `alpha` das camadas LRD.
pub const LRD_ALPHA_LIMIT: f32 = 0.0015;
/// Primeira camada do bloco LRD.
pub const LRD_LAYER_FIRST: usize = 30;
/// Ultima camada (exclusiva) do bloco LRD.
pub const LRD_LAYER_LAST: usize = 40;
/// Arquivo com os planos de bits dos 136 experts.
pub const EXPERTS_1BIT_FILE: &str = "isometric_1bit_experts136.safetensors";
/// Arquivo com o roteador inicializado de 136 experts.
pub const GATE_136_FILE: &str = "gate_136_init.safetensors";
/// Pegada real de VRAM do layout 1-bit de 32.054B, medida com
/// `cuMemGetInfo_v2` antes e depois do carregamento (`free_before - free_after`).
/// Inclui os buffers temporarios do `GpuEngine`, os planos de bits dos 136
/// experts, o nucleo INT8, as 10 camadas LRD e o LM head.
pub const VRAM_MODEL_MIB: u64 = 5346;
/// Folga exigida alem da pegada do modelo.
pub const VRAM_MARGIN_MIB: u64 = 250;
/// VRAM livre minima aceita antes de iniciar o carregamento.
pub const VRAM_REQUIRED_MIB: u64 = VRAM_MODEL_MIB + VRAM_MARGIN_MIB;

/// Escala de atencao derivada das tabelas YaRN: `192^-0.5 * mscale_den^2`,
/// com `mscale_den = 0.1 * 0.707 * ln(40) + 1`. Calculada, nunca literal.
pub fn attn_scale() -> f32 {
    let mscale_den = 0.1f32 * 0.707f32 * 40.0f32.ln() + 1.0f32;
    (HEAD_DIM as f32).powf(-0.5) * mscale_den * mscale_den
}
/// Penalidade de repeticao aplicada aos ultimos 12 tokens gerados.
pub const REPETITION_WINDOW: usize = 12;
/// Fator da penalidade de repeticao.
pub const REPETITION_PENALTY: f32 = 1.12;

/// Projecao 1-bit: planos de bits, escala por linha (FP16 cru) e por coluna.
pub struct Proj {
    bits: GpuBuffer,
    rscale: GpuBuffer,
    cscale: Vec<f32>,
}

/// Projecao INT8 com escala por linha.
struct Q8Proj {
    q8: GpuBuffer,
    sc: GpuBuffer,
}

/// Expert 1-bit (gate/up/down).
struct Expert {
    gate: Proj,
    up: Proj,
    down: Proj,
}

/// Par LoRA (`a`: rank x in, `b`: out x rank).
struct Lora {
    a: Vec<f32>,
    b: Vec<f32>,
}

/// Camada do enxerto: atencao MLA INT8 + shared experts INT8 + 136 experts 1-bit.
struct Layer {
    in_norm: Vec<f32>,
    post_norm: Vec<f32>,
    kv_norm: Vec<f32>,
    q: Q8Proj,
    kv_a: Q8Proj,
    kv_b: Q8Proj,
    o: Q8Proj,
    sh_g: Q8Proj,
    sh_u: Q8Proj,
    sh_d: Q8Proj,
    gate: Vec<f32>,
    experts: Vec<Expert>,
    lora_q: Option<Lora>,
    lora_o: Option<Lora>,
    lora_sd: Option<Lora>,
}

/// Camada linear do bloco recorrente LRD.
struct LrdLayer {
    norm: Vec<f32>,
    gate: Proj,
    up: Proj,
    down: Proj,
    alpha: f32,
    gate_vec: Vec<f32>,
}

/// Motor 1-bit carregado, 100% na VRAM.
pub struct OneBitEngine {
    gpu: GpuEngine,
    /// `isometric_gpu_core.safetensors` (embeddings e projecoes INT8).
    st_core: Arc<SafeTensors>,
    /// `isometric_1bit_experts136.safetensors` (planos de bits).
    st_experts: Arc<SafeTensors>,
    /// Shard com os pesos empacotados das camadas LRD.
    st_lrd: Arc<SafeTensors>,
    /// Delta V11 mais novo (LoRAs, gate 136, normas).
    st_delta: Arc<SafeTensors>,
    /// Delta base do checkpoint (fallback numerico).
    st_delta_base: Arc<SafeTensors>,
    layers: Vec<Layer>,
    lrd: Vec<LrdLayer>,
    lm_q8: GpuBuffer,
    lm_sc: GpuBuffer,
    lm_lora: Option<Lora>,
    embed_scale: Vec<f32>,
    final_norm: Vec<f32>,
    cjk_mask: Vec<u8>,
    /// VRAM livre no inicio do carregamento (MiB).
    vram_before_mib: u64,
    /// Delta real de VRAM consumido pelo modelo (MiB).
    vram_model_mib: u64,
    /// Origem do `cjk_mask` efetivamente usado.
    cjk_source: String,
    core_dir: PathBuf,
    onebit_dir: PathBuf,
}

/// Resolve o diretorio do nucleo (enxerto) e o diretorio dos 136 experts 1-bit.
///
/// Procura, nesta ordem: o diretorio informado, `HD_32B`, o modelo baixado do
/// Hub e o diretorio local do upcycling. Devolve `None` quando os arquivos 1-bit
/// nao estao presentes (layout V10 INT4).
pub fn discover_layout(preferred_core: Option<&Path>) -> Option<(PathBuf, PathBuf)> {
    let models = mark_core::paths::models_dir();
    let mut core_candidates: Vec<PathBuf> = Vec::new();
    if let Some(p) = preferred_core {
        core_candidates.push(p.to_path_buf());
    }
    if let Ok(hd) = std::env::var("HD_32B") {
        if !hd.trim().is_empty() {
            core_candidates.push(PathBuf::from(hd));
        }
    }
    core_candidates.push(models.join("miceworks__Mark-Bin-32B"));
    core_candidates.push(models.join("mark_32b_1bit"));
    let core = core_candidates
        .into_iter()
        .find(|p| p.join("isometric_gpu_core.safetensors").is_file())?;

    let mut onebit_candidates = vec![core.clone(), models.join("mark_32b_1bit")];
    if let Ok(hd) = std::env::var("HD_32B") {
        if !hd.trim().is_empty() {
            onebit_candidates.push(PathBuf::from(hd));
        }
    }
    let onebit = onebit_candidates
        .into_iter()
        .find(|p| p.join(EXPERTS_1BIT_FILE).is_file())?;
    Some((core, onebit))
}

/// Indica se o layout 1-bit de 32.054B esta disponivel no disco.
pub fn layout_available(preferred_core: Option<&Path>) -> bool {
    discover_layout(preferred_core).is_some()
}

/// Escolhe o delta V11 mais novo disponivel, na ordem de prioridade acordada.
fn select_delta(onebit_dir: &Path, core_dir: &Path) -> PathBuf {
    let v11 = onebit_dir.join("checkpoints_v11");
    for name in [
        "mark_calibration_delta_v11.safetensors",
        "rolling_latest.safetensors",
        "delta_post_1h_calib.safetensors",
    ] {
        let candidate = v11.join(name);
        if candidate.is_file() {
            return candidate;
        }
    }
    core_dir.join("mark_calibration_delta.safetensors")
}

/// `true` quando todos os valores sao finitos (um delta corrompido nunca passa).
fn all_finite(values: &[f32]) -> bool {
    !values.is_empty() && values.iter().all(|v| v.is_finite())
}

/// Le um tensor F16 do delta primario e cai para o delta base quando vazio ou NaN.
fn read_f16_checked(primary: &SafeTensors, fallback: &SafeTensors, name: &str) -> Result<Vec<f32>> {
    if primary.has(name) {
        let values = primary.f32_vec(name)?;
        if all_finite(&values) {
            return Ok(values);
        }
    }
    fallback
        .f32_vec(name)
        .with_context(|| format!("tensor F16 '{name}' ausente nos dois deltas"))
}

/// Le `count` valores de um par LoRA (`_A` e `_B`) quando presentes.
fn read_lora(
    primary: &SafeTensors,
    fallback: &SafeTensors,
    a_name: &str,
    b_name: &str,
) -> Option<Lora> {
    if !primary.has(a_name) || !primary.has(b_name) {
        return None;
    }
    let a = read_f16_checked(primary, fallback, a_name).ok()?;
    let b = read_f16_checked(primary, fallback, b_name).ok()?;
    Some(Lora { a, b })
}

/// Norma L2 de um vetor (usada no traco de diagnostico).
fn vec_norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

/// Soma o residuo homeostatico do motor de referencia:
/// `scale = min(max_ratio * ||h|| / max(||d||, 1e-8), 1)`.
fn homeostatic_add(h: &mut [f32], delta: &[f32], max_ratio: f32) {
    let h_sq: f32 = h.iter().map(|v| v * v).sum();
    let d_sq: f32 = delta.iter().map(|v| v * v).sum();
    let h_norm = h_sq.sqrt();
    let d_norm = d_sq.sqrt().max(1e-8);
    let scale = ((max_ratio * h_norm) / d_norm).min(1.0);
    for i in 0..h.len() {
        h[i] += delta[i] * scale;
    }
}

/// Soma `x @ A^T @ B^T` na saida (LoRA de posto `rank`).
fn add_lora(x: &[f32], lora: &Lora, rank: usize, in_f: usize, out_f: usize, out: &mut [f32]) {
    if lora.a.len() != rank * in_f || lora.b.len() != out_f * rank {
        return;
    }
    if x.len() < in_f || out.len() < out_f {
        return;
    }
    let mut mid = vec![0.0f32; rank];
    for (r, slot) in mid.iter_mut().enumerate() {
        let row = &lora.a[r * in_f..(r + 1) * in_f];
        let mut acc = 0.0f32;
        for c in 0..in_f {
            acc += x[c] * row[c];
        }
        *slot = acc;
    }
    for o in 0..out_f {
        let row = &lora.b[o * rank..(o + 1) * rank];
        let mut acc = 0.0f32;
        for (r, m) in mid.iter().enumerate() {
            acc += m * row[r];
        }
        out[o] += acc;
    }
}

/// Frequencias inversas YaRN (`factor 40`, `orig_max 4096`, betas 32/1).
fn yarn_inv_freq() -> [f32; 32] {
    let (dim, base, orig_max, factor) = (64.0f32, 10000.0f32, 4096.0f32, 40.0f32);
    let (beta_fast, beta_slow) = (32.0f32, 1.0f32);
    let low = (dim * (orig_max / (beta_fast * 2.0 * std::f32::consts::PI)).ln()
        / (2.0 * base.ln()))
    .floor()
    .max(0.0);
    let high = (dim * (orig_max / (beta_slow * 2.0 * std::f32::consts::PI)).ln()
        / (2.0 * base.ln()))
    .ceil()
    .min(31.0);
    let mut inv_freq = [0.0f32; 32];
    for (i, slot) in inv_freq.iter_mut().enumerate() {
        let pf = base.powf((i * 2) as f32 / dim);
        let ramp = ((i as f32 - low) / (high - low).max(0.001)).clamp(0.0, 1.0);
        let mask = 1.0 - ramp;
        *slot = (1.0 / (factor * pf)) * (1.0 - mask) + (1.0 / pf) * mask;
    }
    inv_freq
}

/// RoPE intercalado: pares `(2i, 2i+1)` girados por `cos`/`sin`.
fn apply_rope_interleaved(v: &mut [f32], cos: &[f32], sin: &[f32]) {
    for i in 0..32 {
        let (a, b) = (v[2 * i], v[2 * i + 1]);
        v[2 * i] = a * cos[i] - b * sin[i];
        v[2 * i + 1] = a * sin[i] + b * cos[i];
    }
}

impl OneBitEngine {
    /// Carrega o motor 1-bit GPU-only. Qualquer falha de CUDA vira erro explicito.
    pub fn load(core_dir: &Path, onebit_dir: &Path) -> Result<Self> {
        let core_file = core_dir.join("isometric_gpu_core.safetensors");
        let experts_file = onebit_dir.join(EXPERTS_1BIT_FILE);
        let gate_file = onebit_dir.join(GATE_136_FILE);
        let lrd_file = core_dir.join("model-00004-of-00004.safetensors");
        let base_delta_file = core_dir.join("mark_calibration_delta.safetensors");
        for path in [&core_file, &experts_file, &gate_file, &lrd_file, &base_delta_file] {
            if !path.is_file() {
                bail!("arquivo do layout 1-bit ausente: {}", path.display());
            }
        }
        let delta_file = select_delta(onebit_dir, core_dir);
        if !delta_file.is_file() {
            bail!("delta de calibracao ausente: {}", delta_file.display());
        }

        // A trava usa a pegada REAL medida do modelo + folga: um limite fixo
        // alto demais bloqueia uma placa de 8 GB com Wayland e navegador abertos.
        let free_before = crate::gpu::free_memory_mib()
            .context("nao foi possivel ler a VRAM livre (layout 1-bit exige GPU)")?;
        if free_before < VRAM_REQUIRED_MIB {
            bail!(
                "VRAM insuficiente para o motor 1-bit: {free_before} MiB livres, {VRAM_REQUIRED_MIB} MiB necessarios (pegada medida {VRAM_MODEL_MIB} MiB + folga {VRAM_MARGIN_MIB} MiB)"
            );
        }
        let gpu = GpuEngine::create()
            .context("CUDA indisponivel para o motor 1-bit (GPU-only, sem fallback)")?;
        let st_core = Arc::new(SafeTensors::open(&core_file)?);
        let st_experts = Arc::new(SafeTensors::open(&experts_file)?);
        let st_gate = SafeTensors::open(&gate_file)?;
        let st_lrd = Arc::new(SafeTensors::open(&lrd_file)?);
        let st_delta = Arc::new(SafeTensors::open(&delta_file)?);
        let st_base = Arc::new(SafeTensors::open(&base_delta_file)?);

        let embed_scale = st_core.f32_vec("embed_tokens.scale")?;
        if embed_scale.len() != VOCAB {
            bail!("escala de embeddings com {} linhas, esperado {VOCAB}", embed_scale.len());
        }
        let final_norm = read_f16_checked(&st_delta, &st_base, "norm.weight")?;
        if final_norm.len() != HIDDEN {
            bail!("norm.weight com {} valores, esperado {HIDDEN}", final_norm.len());
        }
        // O delta V11 carrega um `cjk_mask` zerado pelo treino multilingue; um
        // mascaramento com 0 entradas ativas e o mesmo que nao mascarar nada, e
        // o modelo responde em chines para prompt em portugues. So aceitamos o
        // do delta quando ele tem entradas ativas.
        let (cjk_mask, cjk_source) = if st_delta.has("cjk_mask") {
            let raw = st_delta.raw("cjk_mask")?;
            if raw.iter().any(|b| *b != 0) {
                (raw.to_vec(), "delta")
            } else if st_core.has("cjk_mask") {
                (st_core.u8_slice("cjk_mask")?.to_vec(), "core (delta zerado)")
            } else {
                (vec![0u8; VOCAB], "ausente")
            }
        } else if st_core.has("cjk_mask") {
            (st_core.u8_slice("cjk_mask")?.to_vec(), "core")
        } else {
            (vec![0u8; VOCAB], "ausente")
        };
        let lm_lora = read_lora(&st_delta, &st_base, "lm_lora_A", "lm_lora_B");

        let mut layers = Vec::with_capacity(N_LAYERS);
        for lid in 0..N_LAYERS {
            let sp = format!("layers.{lid}");
            let in_norm = read_f16_checked(&st_delta, &st_core, &format!("{sp}.input_layernorm.weight"))?;
            let post_norm =
                read_f16_checked(&st_delta, &st_core, &format!("{sp}.post_attention_layernorm.weight"))?;
            let kv_norm = st_core.f32_vec(&format!("{sp}.self_attn.kv_a_layernorm.weight"))?;
            let q = load_q8(&st_core, &gpu, &format!("{sp}.self_attn.q_proj"))?;
            let kv_a = load_q8(&st_core, &gpu, &format!("{sp}.self_attn.kv_a_proj_with_mqa"))?;
            let kv_b = load_q8(&st_core, &gpu, &format!("{sp}.self_attn.kv_b_proj"))?;
            let o = load_q8(&st_core, &gpu, &format!("{sp}.self_attn.o_proj"))?;
            let (sh_g, sh_u, sh_d) = if lid == 0 {
                (
                    load_q8(&st_core, &gpu, "layers.0.mlp.gate_proj")?,
                    load_q8(&st_core, &gpu, "layers.0.mlp.up_proj")?,
                    load_q8(&st_core, &gpu, "layers.0.mlp.down_proj")?,
                )
            } else {
                (
                    load_q8(&st_core, &gpu, &format!("{sp}.mlp.shared_experts.gate_proj"))?,
                    load_q8(&st_core, &gpu, &format!("{sp}.mlp.shared_experts.up_proj"))?,
                    load_q8(&st_core, &gpu, &format!("{sp}.mlp.shared_experts.down_proj"))?,
                )
            };
            let lora_q = read_lora(
                &st_delta,
                &st_base,
                &format!("{sp}.lora_q_A"),
                &format!("{sp}.lora_q_B"),
            );
            let lora_o = read_lora(
                &st_delta,
                &st_base,
                &format!("{sp}.lora_o_A"),
                &format!("{sp}.lora_o_B"),
            );
            let lora_sd = read_lora(
                &st_delta,
                &st_base,
                &format!("{sp}.lora_sd_A"),
                &format!("{sp}.lora_sd_B"),
            );
            let (gate, experts) = if lid == 0 {
                (Vec::new(), Vec::new())
            } else {
                let gate = read_f16_checked(&st_delta, &st_gate, &format!("{sp}.mlp.gate_136.weight"))
                    .with_context(|| format!("roteador 136 ausente na camada {lid}"))?;
                if gate.len() != N_EXPERTS_1BIT * HIDDEN {
                    bail!(
                        "roteador da camada {lid} com {} valores, esperado {}",
                        gate.len(),
                        N_EXPERTS_1BIT * HIDDEN
                    );
                }
                (gate, load_layer_experts(&st_experts, &gpu, lid)?)
            };
            layers.push(Layer {
                in_norm,
                post_norm,
                kv_norm,
                q,
                kv_a,
                kv_b,
                o,
                sh_g,
                sh_u,
                sh_d,
                gate,
                experts,
                lora_q,
                lora_o,
                lora_sd,
            });
        }

        let mut lrd = Vec::with_capacity(LRD_LAYER_LAST - LRD_LAYER_FIRST);
        for lid in LRD_LAYER_FIRST..LRD_LAYER_LAST {
            let norm = read_f16_checked(&st_delta, &st_base, &format!("lrd.{lid}.norm"))?;
            let alpha_raw = read_f16_checked(&st_delta, &st_base, &format!("lrd.{lid}.alpha"))?;
            let alpha = alpha_raw
                .first()
                .copied()
                .unwrap_or(0.0)
                .clamp(-LRD_ALPHA_LIMIT, LRD_ALPHA_LIMIT);
            let gate_vec = read_f16_checked(&st_delta, &st_base, &format!("lrd.{lid}.gate_vec"))?;
            if gate_vec.len() != HIDDEN {
                bail!("lrd.{lid}.gate_vec com {} valores, esperado {HIDDEN}", gate_vec.len());
            }
            lrd.push(LrdLayer {
                norm,
                gate: load_lrd_proj(
                    &st_lrd, &st_delta, &st_base, &gpu, lid, "gate_proj", 2496, 48, 32, 2048,
                )?,
                up: load_lrd_proj(
                    &st_lrd, &st_delta, &st_base, &gpu, lid, "up_proj", 2496, 48, 32, 2048,
                )?,
                down: load_lrd_proj(
                    &st_lrd, &st_delta, &st_base, &gpu, lid, "down_proj", 2048, 39, 39, 2496,
                )?,
                alpha,
                gate_vec,
            });
        }

        let lm_q8 = gpu.upload_i8(st_core.i8_slice("lm_head.q8")?)?;
        let lm_sc = gpu.upload_f32(&st_core.f32_vec("lm_head.scale")?)?;

        // O page cache dos planos de bits ja copiados nao precisa mais ficar residente.
        for name in st_experts.tensor_names() {
            if let Some((a, b)) = st_experts.file_range(name) {
                st_experts.drop_cache(a, b);
            }
        }

        let free_after = crate::gpu::free_memory_mib().unwrap_or(0);
        let model_mib = free_before.saturating_sub(free_after);
        println!(
            "svid-1bit: free_before={free_before} MiB, model_delta_mib={model_mib} MiB, required_mib={VRAM_REQUIRED_MIB} MiB (pegada medida {VRAM_MODEL_MIB} MiB + folga {VRAM_MARGIN_MIB} MiB)"
        );
        println!(
            "svid-1bit: cjk_mask de {cjk_source} com {} entradas ativas",
            cjk_mask.iter().filter(|b| **b != 0).count()
        );

        Ok(Self {
            gpu,
            vram_before_mib: free_before,
            vram_model_mib: model_mib,
            cjk_source: cjk_source.to_string(),
            st_core,
            st_experts,
            st_lrd,
            st_delta,
            st_delta_base: st_base,
            layers,
            lrd,
            lm_q8,
            lm_sc,
            lm_lora,
            embed_scale,
            final_norm,
            cjk_mask,
            core_dir: core_dir.to_path_buf(),
            onebit_dir: onebit_dir.to_path_buf(),
        })
    }

    /// Diretorio do nucleo INT8 carregado.
    pub fn core_dir(&self) -> &Path {
        &self.core_dir
    }

    /// Diretorio dos 136 experts 1-bit.
    pub fn onebit_dir(&self) -> &Path {
        &self.onebit_dir
    }

    /// Nome do dispositivo CUDA em uso.
    pub fn device(&self) -> Option<String> {
        crate::gpu::device_name()
    }

    /// Numero de camadas carregadas.
    pub fn layer_count(&self) -> usize {
        self.layers.len()
    }

    /// Numero de experts 1-bit por camada.
    pub fn expert_count(&self) -> usize {
        self.layers
            .get(1)
            .map(|l| l.experts.len())
            .unwrap_or(N_EXPERTS_1BIT)
    }

    /// Numero de camadas LRD carregadas.
    pub fn lrd_count(&self) -> usize {
        self.lrd.len()
    }

    /// Executa um passo do forward 1-bit e devolve os logits quando `is_last`.
    ///
    /// O bloco LRD de 10 camadas roda uma unica vez por passo, como no motor
    /// validado (a profundidade de raciocinio nao repete o bloco).
    pub fn forward(
        &self,
        state: &mut GenerationState,
        token_id: u32,
        pos: usize,
        is_last: bool,
        apply_cjk_mask: bool,
    ) -> Result<Vec<f32>> {
        let tid = token_id as usize;
        if tid >= VOCAB {
            bail!("token id fora do vocabulario: {token_id}");
        }
        if state.k_cache.len() != N_LAYERS || state.v_cache.len() != N_LAYERS {
            bail!("estado de geracao inconsistente com as {N_LAYERS} camadas");
        }
        let embed = self.st_core.i8_slice("embed_tokens.q8")?;
        if embed.len() < VOCAB * HIDDEN {
            bail!("embeddings com {} valores, esperado {}", embed.len(), VOCAB * HIDDEN);
        }
        let mut h = vec![0.0f32; HIDDEN];
        let esc = self.embed_scale[tid];
        let row = &embed[tid * HIDDEN..(tid + 1) * HIDDEN];
        for j in 0..HIDDEN {
            h[j] = (row[j] as f32) * esc;
        }

        let scale = attn_scale();
        let trace = std::env::var("MARK_TRACE").is_ok() && is_last;
        let inv_freq = yarn_inv_freq();
        let mut cos = [0.0f32; 32];
        let mut sin = [0.0f32; 32];
        for i in 0..32 {
            let angle = pos as f32 * inv_freq[i];
            cos[i] = angle.cos();
            sin[i] = angle.sin();
        }

        let mut xn = vec![0.0f32; HIDDEN];
        let mut xn2 = vec![0.0f32; HIDDEN];
        let mut q_buf = vec![0.0f32; N_HEADS * HEAD_DIM];
        let mut kv_a_buf = vec![0.0f32; C_KV + ROPE_DIM];
        let mut c_kv_n = vec![0.0f32; C_KV];
        let mut kv_b_buf = vec![0.0f32; N_HEADS * 2 * NOPE_DIM];
        let mut attn_flat = vec![0.0f32; HIDDEN];
        let mut o_buf = vec![0.0f32; HIDDEN];
        let mut sh_g = vec![0.0f32; SHARED_INTER];
        let mut sh_u = vec![0.0f32; SHARED_INTER];
        let mut ex_g = vec![0.0f32; EXPERT_INTER];
        let mut ex_u = vec![0.0f32; EXPERT_INTER];
        let mut ex_d = vec![0.0f32; HIDDEN];
        let mut k_pe = [0.0f32; ROPE_DIM];

        if trace {
            println!("T embed l2={:.6} h0={:.6} h1={:.6}", vec_norm(&h), h[0], h[1]);
        }

        for (lid, layer) in self.layers.iter().enumerate() {
            // Na ultima camada, tokens que nao o ultimo do prompt so precisam
            // alimentar o cache K/V.
            let kv_only = !is_last && lid + 1 == N_LAYERS;

            rmsnorm_into(&h, &layer.in_norm, 1e-6, &mut xn);
            if !kv_only {
                self.gpu
                    .matvec_i8(&xn, &layer.q.q8, &layer.q.sc, None, N_HEADS * HEAD_DIM, HIDDEN, &mut q_buf)?;
                if let Some(lora) = &layer.lora_q {
                    add_lora(&xn, lora, 32, HIDDEN, N_HEADS * HEAD_DIM, &mut q_buf);
                }
            }
            self.gpu
                .matvec_i8(&xn, &layer.kv_a.q8, &layer.kv_a.sc, None, C_KV + ROPE_DIM, HIDDEN, &mut kv_a_buf)?;
            rmsnorm_into(&kv_a_buf[..C_KV], &layer.kv_norm, 1e-6, &mut c_kv_n);
            self.gpu
                .matvec_i8(&c_kv_n, &layer.kv_b.q8, &layer.kv_b.sc, None, N_HEADS * 2 * NOPE_DIM, C_KV, &mut kv_b_buf)?;

            k_pe.copy_from_slice(&kv_a_buf[C_KV..C_KV + ROPE_DIM]);
            apply_rope_interleaved(&mut k_pe, &cos, &sin);

            for hd in 0..N_HEADS {
                if !kv_only {
                    let q_off = hd * HEAD_DIM;
                    apply_rope_interleaved(&mut q_buf[q_off + NOPE_DIM..q_off + HEAD_DIM], &cos, &sin);
                }
                let kb_off = hd * 2 * NOPE_DIM;
                state.k_cache[lid].extend_from_slice(&kv_b_buf[kb_off..kb_off + NOPE_DIM]);
                state.k_cache[lid].extend_from_slice(&k_pe);
                state.v_cache[lid]
                    .extend_from_slice(&kv_b_buf[kb_off + NOPE_DIM..kb_off + 2 * NOPE_DIM]);
            }
            if kv_only {
                continue;
            }

            let seq_len = state.k_cache[lid].len() / (N_HEADS * HEAD_DIM);
            if seq_len != state.v_cache[lid].len() / (N_HEADS * NOPE_DIM) {
                bail!("cache K/V inconsistente na camada {lid}");
            }
            let k_tok = state.k_cache[lid].as_slice();
            let v_tok = state.v_cache[lid].as_slice();
            for hd in 0..N_HEADS {
                let q_vec = &q_buf[hd * HEAD_DIM..(hd + 1) * HEAD_DIM];
                let mut scores = vec![0.0f32; seq_len];
                let mut max_s = f32::NEG_INFINITY;
                for (t, slot) in scores.iter_mut().enumerate() {
                    let k_base = (t * N_HEADS + hd) * HEAD_DIM;
                    let k_h = &k_tok[k_base..k_base + HEAD_DIM];
                    let mut dot = 0.0f32;
                    for d in 0..HEAD_DIM {
                        dot += q_vec[d] * k_h[d];
                    }
                    let scaled = dot * scale;
                    if scaled > max_s {
                        max_s = scaled;
                    }
                    *slot = scaled;
                }
                let mut sum_e = 0.0f32;
                for s in scores.iter_mut() {
                    *s = (*s - max_s).exp();
                    sum_e += *s;
                }
                let inv_e = 1.0 / sum_e.max(1e-9);
                let out_hd = &mut attn_flat[hd * NOPE_DIM..(hd + 1) * NOPE_DIM];
                for d in out_hd.iter_mut() {
                    *d = 0.0;
                }
                for (t, s) in scores.iter().enumerate() {
                    let w = *s * inv_e;
                    let v_base = (t * N_HEADS + hd) * NOPE_DIM;
                    let v_h = &v_tok[v_base..v_base + NOPE_DIM];
                    for d in 0..NOPE_DIM {
                        out_hd[d] += w * v_h[d];
                    }
                }
            }

            self.gpu
                .matvec_i8(&attn_flat, &layer.o.q8, &layer.o.sc, None, HIDDEN, HIDDEN, &mut o_buf)?;
            if let Some(lora) = &layer.lora_o {
                add_lora(&attn_flat, lora, 32, HIDDEN, HIDDEN, &mut o_buf);
            }
            homeostatic_add(&mut h, &o_buf, HOMEOSTASIS);

            rmsnorm_into(&h, &layer.post_norm, 1e-6, &mut xn2);
            if lid == 0 {
                let mut dense_g = vec![0.0f32; DENSE_INTER];
                let mut dense_u = vec![0.0f32; DENSE_INTER];
                self.gpu.matvec_i8(
                    &xn2,
                    &layer.sh_g.q8,
                    &layer.sh_g.sc,
                    None,
                    DENSE_INTER,
                    HIDDEN,
                    &mut dense_g,
                )?;
                self.gpu.matvec_i8(
                    &xn2,
                    &layer.sh_u.q8,
                    &layer.sh_u.sc,
                    None,
                    DENSE_INTER,
                    HIDDEN,
                    &mut dense_u,
                )?;
                for i in 0..DENSE_INTER {
                    let g = dense_g[i];
                    dense_g[i] = (g / (1.0 + (-g).exp())) * dense_u[i];
                }
                self.gpu.matvec_i8(
                    &dense_g,
                    &layer.sh_d.q8,
                    &layer.sh_d.sc,
                    None,
                    HIDDEN,
                    DENSE_INTER,
                    &mut o_buf,
                )?;
                homeostatic_add(&mut h, &o_buf, HOMEOSTASIS);
                if trace {
                    println!("T l{lid} l2={:.6} h0={:.6} h1={:.6}", vec_norm(&h), h[0], h[1]);
                }
                continue;
            }

            self.gpu
                .matvec_i8(&xn2, &layer.sh_g.q8, &layer.sh_g.sc, None, SHARED_INTER, HIDDEN, &mut sh_g)?;
            self.gpu
                .matvec_i8(&xn2, &layer.sh_u.q8, &layer.sh_u.sc, None, SHARED_INTER, HIDDEN, &mut sh_u)?;
            for i in 0..SHARED_INTER {
                let g = sh_g[i];
                sh_g[i] = (g / (1.0 + (-g).exp())) * sh_u[i];
            }
            self.gpu
                .matvec_i8(&sh_g, &layer.sh_d.q8, &layer.sh_d.sc, None, HIDDEN, SHARED_INTER, &mut o_buf)?;
            if let Some(lora) = &layer.lora_sd {
                if lora.a.len() == 32 * SHARED_INTER {
                    add_lora(&sh_g, lora, 32, SHARED_INTER, HIDDEN, &mut o_buf);
                } else {
                    add_lora(&xn2, lora, 32, HIDDEN, HIDDEN, &mut o_buf);
                }
            }

            for (eid, weight) in self.route(layer, &xn2) {
                let expert = layer
                    .experts
                    .get(eid)
                    .with_context(|| format!("expert {eid} ausente na camada {lid}"))?;
                self.w1a4(&xn2, &expert.gate, EXPERT_INTER, &mut ex_g)?;
                self.w1a4(&xn2, &expert.up, EXPERT_INTER, &mut ex_u)?;
                for i in 0..EXPERT_INTER {
                    let g = ex_g[i];
                    ex_g[i] = (g / (1.0 + (-g).exp())) * ex_u[i];
                }
                self.w1a4(&ex_g, &expert.down, HIDDEN, &mut ex_d)?;
                for i in 0..HIDDEN {
                    o_buf[i] += weight * ex_d[i];
                }
            }
            homeostatic_add(&mut h, &o_buf, HOMEOSTASIS);
            if trace {
                println!("T l{lid} l2={:.6} h0={:.6} h1={:.6}", vec_norm(&h), h[0], h[1]);
            }
        }

        if !is_last {
            return Ok(Vec::new());
        }

        // Bloco recorrente LRD 1-bit (camadas 30..39), uma passada por passo.
        let mut lrd_g = vec![0.0f32; 2496];
        let mut lrd_u = vec![0.0f32; 2496];
        let mut lrd_d = vec![0.0f32; HIDDEN];
        for lrd in &self.lrd {
            rmsnorm_into(&h, &lrd.norm, 1e-6, &mut xn);
            self.w1a4(&xn, &lrd.gate, 2496, &mut lrd_g)?;
            self.w1a4(&xn, &lrd.up, 2496, &mut lrd_u)?;
            for i in 0..2496 {
                let g = lrd_g[i];
                lrd_g[i] = (g / (1.0 + (-g).exp())) * lrd_u[i];
            }
            self.w1a4(&lrd_g, &lrd.down, HIDDEN, &mut lrd_d)?;
            let mut dot_gv = 0.0f32;
            for i in 0..HIDDEN {
                dot_gv += xn[i] * lrd.gate_vec[i];
            }
            let gate_l = 0.5 + 1.0 / (1.0 + (-dot_gv).exp());
            for i in 0..HIDDEN {
                h[i] += lrd_d[i] * (lrd.alpha * gate_l);
            }
        }

        if trace {
            println!("T lrd l2={:.6} h0={:.6}", vec_norm(&h), h[0]);
        }
        rmsnorm_into(&h, &self.final_norm, 1e-6, &mut xn);
        if trace {
            println!("T fnorm l2={:.6} x0={:.6}", vec_norm(&xn), xn[0]);
        }
        let mut logits = vec![0.0f32; VOCAB];
        self.gpu
            .matvec_i8(&xn, &self.lm_q8, &self.lm_sc, None, VOCAB, HIDDEN, &mut logits)?;
        if let Some(lora) = &self.lm_lora {
            add_lora(&xn, lora, 64, HIDDEN, VOCAB, &mut logits);
        }

        if apply_cjk_mask && self.cjk_mask.len() == VOCAB {
            for (idx, &mask) in self.cjk_mask.iter().enumerate() {
                if mask != 0 {
                    logits[idx] = -1.0e9;
                }
            }
        }
        // Penalidade de repeticao sobre os ultimos tokens JA gerados.
        for &prev in state.ids.iter().rev().take(REPETITION_WINDOW) {
            let p = prev as usize;
            if p < logits.len() {
                if logits[p] > 0.0 {
                    logits[p] /= REPETITION_PENALTY;
                } else {
                    logits[p] *= REPETITION_PENALTY;
                }
            }
        }
        Ok(logits)
    }

    /// W1A4 na GPU com o buffer de escala FP16 ja carregado.
    fn w1a4(&self, x: &[f32], proj: &Proj, rows: usize, out: &mut [f32]) -> Result<()> {
        self.gpu
            .w1a4_matvec(x, &proj.cscale, &proj.bits, &proj.rscale, rows, out)
    }

    /// Top-6 do roteador de 136 experts com escala `2.125`.
    fn route(&self, layer: &Layer, xn2: &[f32]) -> Vec<(usize, f32)> {
        let mut logits: Vec<(usize, f32)> = (0..N_EXPERTS_1BIT)
            .map(|e| {
                let row = &layer.gate[e * HIDDEN..(e + 1) * HIDDEN];
                let mut dot = 0.0f32;
                for i in 0..HIDDEN {
                    dot += xn2[i] * row[i];
                }
                (e, dot)
            })
            .collect();
        let max_g = logits
            .iter()
            .map(|x| x.1)
            .fold(f32::NEG_INFINITY, f32::max);
        let mut sum_e = 0.0f32;
        for item in logits.iter_mut() {
            item.1 = (item.1 - max_g).exp();
            sum_e += item.1;
        }
        let inv = 1.0 / sum_e.max(1e-9);
        for item in logits.iter_mut() {
            item.1 = item.1 * inv * GATE_SCALE_1BIT;
        }
        logits.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        logits.truncate(TOP_K_1BIT);
        logits
    }

    /// Relatorio de VRAM: `(free_before_mib, model_delta_mib, required_mib)`.
    pub fn vram_report(&self) -> (u64, u64, u64) {
        (self.vram_before_mib, self.vram_model_mib, VRAM_REQUIRED_MIB)
    }

    /// Origem do `cjk_mask` em uso (`delta`, `core` ou `ausente`).
    pub fn cjk_source(&self) -> &str {
        &self.cjk_source
    }

    /// Numero de entradas ativas na mascara CJK aplicada.
    pub fn cjk_masked_tokens(&self) -> usize {
        self.cjk_mask.iter().filter(|b| **b != 0).count()
    }

    /// Numero de tensores mapeados vivos no motor (mantem os mmaps em uso).
    pub fn mapped_tensors(&self) -> usize {
        self.st_core.tensor_names().len()
            + self.st_experts.tensor_names().len()
            + self.st_lrd.tensor_names().len()
            + self.st_delta.tensor_names().len()
            + self.st_delta_base.tensor_names().len()
    }

    /// Diagnostico: nomes dos arquivos efetivamente carregados.
    pub fn loaded_files(&self) -> Vec<String> {
        vec![
            self.core_dir.join("isometric_gpu_core.safetensors").display().to_string(),
            self.onebit_dir.join(EXPERTS_1BIT_FILE).display().to_string(),
            self.onebit_dir.join(GATE_136_FILE).display().to_string(),
            self.core_dir.join("model-00004-of-00004.safetensors").display().to_string(),
            select_delta(&self.onebit_dir, &self.core_dir).display().to_string(),
        ]
    }
}

/// Carrega as projecoes Highway INT8 de uma camada.
fn load_q8(st: &SafeTensors, gpu: &GpuEngine, name: &str) -> Result<Q8Proj> {
    Ok(Q8Proj {
        q8: gpu.upload_i8(st.i8_slice(&format!("{name}.q8"))?)?,
        sc: gpu.upload_f32(&st.f32_vec(&format!("{name}.scale"))?)?,
    })
}

/// Carrega os 136 experts 1-bit de uma camada e libera o page cache usado.
fn load_layer_experts(st: &SafeTensors, gpu: &GpuEngine, lid: usize) -> Result<Vec<Expert>> {
    let gate_name = format!("layers.{lid}.experts.gate_proj.bits");
    let up_name = format!("layers.{lid}.experts.up_proj.bits");
    let down_name = format!("layers.{lid}.experts.down_proj.bits");
    let gate_bits = st.raw(&gate_name)?;
    let up_bits = st.raw(&up_name)?;
    let down_bits = st.raw(&down_name)?;
    let gate_rs = st.raw(&format!("layers.{lid}.experts.gate_proj.rscale"))?;
    let up_rs = st.raw(&format!("layers.{lid}.experts.up_proj.rscale"))?;
    let down_rs = st.raw(&format!("layers.{lid}.experts.down_proj.rscale"))?;
    let gate_cs = st.raw(&format!("layers.{lid}.experts.gate_proj.cscale"))?;
    let up_cs = st.raw(&format!("layers.{lid}.experts.up_proj.cscale"))?;
    let down_cs = st.raw(&format!("layers.{lid}.experts.down_proj.cscale"))?;

    let mut experts = Vec::with_capacity(N_EXPERTS_1BIT);
    for eid in 0..N_EXPERTS_1BIT {
        experts.push(Expert {
            gate: build_proj(gpu, gate_bits, gate_rs, gate_cs, eid, EXPERT_INTER, HIDDEN)?,
            up: build_proj(gpu, up_bits, up_rs, up_cs, eid, EXPERT_INTER, HIDDEN)?,
            down: build_proj(gpu, down_bits, down_rs, down_cs, eid, HIDDEN, EXPERT_INTER)?,
        });
    }
    for name in [gate_name, up_name, down_name] {
        if let Some((a, b)) = st.file_range(&name) {
            st.drop_cache(a, b);
        }
    }
    Ok(experts)
}

/// Monta uma projecao 1-bit a partir das fatias de um expert.
fn build_proj(
    gpu: &GpuEngine,
    bits: &[u8],
    rscale: &[u8],
    cscale: &[u8],
    eid: usize,
    rows: usize,
    cols: usize,
) -> Result<Proj> {
    let n_blocks = cols / 64;
    let bits_per_expert = rows * n_blocks * 8;
    let rs_per_expert = rows * 2;
    let cs_per_expert = cols * 2;
    let b_off = eid * bits_per_expert;
    let r_off = eid * rs_per_expert;
    let c_off = eid * cs_per_expert;
    if b_off + bits_per_expert > bits.len()
        || r_off + rs_per_expert > rscale.len()
        || c_off + cs_per_expert > cscale.len()
    {
        bail!(
            "expert {eid}: fatias fora dos limites (bits={}, rscale={}, cscale={})",
            bits.len(),
            rscale.len(),
            cscale.len()
        );
    }
    let cs_raw = &cscale[c_off..c_off + cs_per_expert];
    let mut col_scale = Vec::with_capacity(cols);
    for chunk in cs_raw.chunks_exact(2) {
        col_scale.push(f16_to_f32(u16::from_le_bytes([chunk[0], chunk[1]])));
    }
    if !col_scale.iter().all(|v| v.is_finite()) {
        bail!("expert {eid}: escala de coluna nao finita");
    }
    Ok(Proj {
        bits: gpu.upload_u8(&bits[b_off..b_off + bits_per_expert])?,
        rscale: gpu.upload_u8(&rscale[r_off..r_off + rs_per_expert])?,
        cscale: col_scale,
    })
}

/// Carrega uma projecao do bloco LRD 1-bit a partir do shard empacotado.
#[allow(clippy::too_many_arguments)]
fn load_lrd_proj(
    st_lrd: &SafeTensors,
    st_delta: &SafeTensors,
    st_base: &SafeTensors,
    gpu: &GpuEngine,
    lid: usize,
    proj: &str,
    rows: usize,
    total_words: usize,
    active_words: usize,
    cols: usize,
) -> Result<Proj> {
    let packed_name = format!("model.layers.{lid}.mlp.shared_experts.0.{proj}.packed_bits");
    let full = st_lrd.raw(&packed_name)?;
    let need = rows * total_words * 8;
    if full.len() < need {
        bail!(
            "{packed_name}: {} bytes, esperado ao menos {need}",
            full.len()
        );
    }
    let mut active = Vec::with_capacity(rows * active_words * 8);
    for r in 0..rows {
        let off = r * total_words * 8;
        active.extend_from_slice(&full[off..off + active_words * 8]);
    }

    let rs_key = format!("lrd.{lid}.{}_rs", &proj[..1]);
    let need_rs = rows * 2;
    let rs_bytes: Vec<u8> = {
        let mut chosen: Option<Vec<u8>> = None;
        if st_delta.has(&rs_key) {
            let candidate = st_delta.raw(&rs_key)?;
            if candidate.len() >= need_rs {
                let values: Vec<f32> = candidate[..need_rs]
                    .chunks_exact(2)
                    .map(|c| f16_to_f32(u16::from_le_bytes([c[0], c[1]])))
                    .collect();
                if all_finite(&values) {
                    chosen = Some(candidate[..need_rs].to_vec());
                }
            }
        }
        match chosen {
            Some(bytes) => bytes,
            None => {
                let fallback = st_base.raw(&rs_key)?;
                if fallback.len() < need_rs {
                    bail!("{rs_key}: {} bytes, esperado {need_rs}", fallback.len());
                }
                fallback[..need_rs].to_vec()
            }
        }
    };

    let cs_name = format!("model.layers.{lid}.mlp.shared_experts.0.{proj}.col_scale");
    let cs_full = st_lrd.f32_vec(&cs_name)?;
    if cs_full.len() < cols {
        bail!("{cs_name}: {} valores, esperado {cols}", cs_full.len());
    }
    Ok(Proj {
        bits: gpu.upload_u8(&active)?,
        rscale: gpu.upload_u8(&rs_bytes)?,
        cscale: cs_full[..cols].to_vec(),
    })
}
