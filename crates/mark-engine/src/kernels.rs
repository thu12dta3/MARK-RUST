//! Primitivas numericas do motor 1-bit: RMSNorm, FWHT, W1A4 XNOR-POPCNT e SwiGLU.
//!
//! Estas sao as MESMAS primitivas usadas pelo motor Rust original
//! (`mark-v3-rs/src/v10_self_reg.rs`), reimplementadas de forma limpa e testavel.

use rayon::prelude::*;

/// RMSNorm: normaliza pela media quadratica e aplica o peso aprendido.
pub fn rmsnorm_into(x: &[f32], weight: &[f32], eps: f32, out: &mut [f32]) {
    let n = x.len();
    assert_eq!(weight.len(), n, "rmsnorm: peso com tamanho divergente");
    assert_eq!(out.len(), n, "rmsnorm: saida com tamanho divergente");
    let mut sum_sq = 0.0f32;
    for &v in x {
        sum_sq += v * v;
    }
    let inv_rms = 1.0f32 / ((sum_sq / (n as f32)) + eps).sqrt();
    for i in 0..n {
        out[i] = x[i] * inv_rms * weight[i];
    }
}

/// Residuo homeostatico: soma o delta normalizado, limitado por `max_ratio`.
pub fn homeostatic_residual_add_inplace(h: &mut [f32], delta: &[f32], max_ratio: f32) {
    assert_eq!(h.len(), delta.len(), "residuo: tamanho divergente");
    let mut h_sq = 0.0f32;
    let mut d_sq = 0.0f32;
    for i in 0..h.len() {
        h_sq += h[i] * h[i];
        d_sq += delta[i] * delta[i];
    }
    let h_norm = h_sq.sqrt().max(1e-5f32);
    let d_norm = d_sq.sqrt().max(1e-5f32);
    let scale = ((max_ratio * h_norm) / d_norm).min(1.0f32);
    for i in 0..h.len() {
        h[i] += delta[i] * scale;
    }
}

/// FWHT (Fast Walsh-Hadamard Transform) in-place em um bloco de 64.
pub fn fwht64_block_inplace(block: &mut [f32; 64]) {
    let mut h = 1usize;
    while h < 64 {
        let mut i = 0usize;
        while i < 64 {
            let mut j = i;
            while j < i + h {
                let x = block[j];
                let y = block[j + h];
                block[j] = x + y;
                block[j + h] = x - y;
                j += 1;
            }
            i += h * 2;
        }
        h *= 2;
    }
    let norm = 0.125f32; // 1/sqrt(64)
    for v in block.iter_mut() {
        *v *= norm;
    }
}

/// FWHT in-place em um slice cujo comprimento e multiplo de 64.
pub fn fwht64_slice_inplace(x: &mut [f32]) {
    assert_eq!(x.len() % 64, 0, "fwht: comprimento precisa ser multiplo de 64");
    for chunk in x.chunks_exact_mut(64) {
        let mut block = [0.0f32; 64];
        block.copy_from_slice(chunk);
        fwht64_block_inplace(&mut block);
        chunk.copy_from_slice(&block);
    }
}

/// Empacota 64 floats em 4 planos de bits W1A4 + escala do bloco.
///
/// Retorna `(m_blk, planes)`: `m_blk` e a amplitude maxima do bloco e
/// `planes` sao os 4 planos de 1 bit (2 bits por sinal, 16 niveis).
pub fn w1a4_pack_block64(v: &[f32]) -> (f32, [u64; 4]) {
    assert_eq!(v.len(), 64, "w1a4: bloco precisa ter 64 elementos");
    let mut m_blk = 0.0f32;
    for &val in v {
        let a = val.abs();
        if a > m_blk {
            m_blk = a;
        }
    }
    if m_blk < 1e-8 {
        return (0.0, [0u64; 4]);
    }
    let inv_m = 1.0 / m_blk;
    let mut planes = [0u64; 4];
    for (j, &val) in v.iter().enumerate() {
        let norm01 = ((val * inv_m) + 1.0) * 0.5;
        let q = (norm01 * 15.0).round().clamp(0.0, 15.0) as u64;
        planes[0] |= (q & 1) << j;
        planes[1] |= ((q >> 1) & 1) << j;
        planes[2] |= ((q >> 2) & 1) << j;
        planes[3] |= ((q >> 3) & 1) << j;
    }
    (m_blk, planes)
}

/// Dot product XNOR-POPCNT entre um peso W1A4 e um bloco de ativacao.
pub fn w1a4_xnor_popcnt_block64(w_u64: u64, x_planes: &[u64; 4], m_blk: f32) -> f32 {
    if m_blk == 0.0 {
        return 0.0;
    }
    let c0 = (!(w_u64 ^ x_planes[0])).count_ones() as i32;
    let c1 = (!(w_u64 ^ x_planes[1])).count_ones() as i32;
    let c2 = (!(w_u64 ^ x_planes[2])).count_ones() as i32;
    let c3 = (!(w_u64 ^ x_planes[3])).count_ones() as i32;
    let weighted_sum = (2 * c0 - 64)
        + 2 * (2 * c1 - 64)
        + 4 * (2 * c2 - 64)
        + 8 * (2 * c3 - 64);
    (weighted_sum as f32) * (m_blk / 15.0)
}

/// Camada linear W1A4 em subespaco: projeta `x_in` usando bits empacotados.
///
/// `packed_bits` tem `m_rows * (in_dim/64)` palavras; `row_scale` escala a saida
/// e `col_scale` escala a entrada antes da transformada.
pub fn svid_1bit_linear_subspace_w1a4(
    x_in: &[f32],
    packed_bits: &[u64],
    row_scale: &[f32],
    col_scale: &[f32],
    m_rows: usize,
) -> Vec<f32> {
    let in_dim = col_scale.len();
    assert_eq!(in_dim % 64, 0, "w1a4: dimensao de entrada precisa ser multiplo de 64");
    let n_blocks = in_dim / 64;
    assert_eq!(
        packed_bits.len(),
        m_rows * n_blocks,
        "w1a4: numero de palavras empacotadas divergente"
    );
    assert_eq!(row_scale.len(), m_rows, "w1a4: row_scale divergente");

    let mut x_buf = vec![0.0f32; in_dim];
    let copy_len = x_in.len().min(in_dim);
    for i in 0..copy_len {
        x_buf[i] = x_in[i] * col_scale[i];
    }
    fwht64_slice_inplace(&mut x_buf);

    let mut m_blks = Vec::with_capacity(n_blocks);
    let mut planes_vec = Vec::with_capacity(n_blocks);
    for b in 0..n_blocks {
        let (mb, pl) = w1a4_pack_block64(&x_buf[b * 64..(b + 1) * 64]);
        m_blks.push(mb);
        planes_vec.push(pl);
    }

    let out_dim = m_rows.min(2048);
    let mut out = vec![0.0f32; out_dim];
    for r in 0..out_dim {
        let r_off = r * n_blocks;
        let mut sum = 0.0f32;
        for b in 0..n_blocks {
            sum += w1a4_xnor_popcnt_block64(packed_bits[r_off + b], &planes_vec[b], m_blks[b]);
        }
        out[r] = sum * row_scale[r];
    }
    out
}

/// Quantiza ativacoes para int8 simetrico. Retorna `(quantizados, escala)`.
pub fn quantize_act_i8(x: &[f32]) -> (Vec<i8>, f32) {
    let mut amax = 1e-6f32;
    for &v in x {
        let a = v.abs();
        if a > amax {
            amax = a;
        }
    }
    let (sc, inv) = (amax / 127.0, 127.0 / amax);
    (
        x.iter()
            .map(|&v| (v * inv).round().clamp(-127.0, 127.0) as i8)
            .collect(),
        sc,
    )
}

/// Prepara ativacoes para multiplicacao int4 com viés de grupo.
///
/// Separa os elementos em pares even/odd (quebecando o grupo de 128 em 64+64)
/// e calcula o vies por grupo.
pub fn prepare_act_int4(x: &[f32]) -> (Vec<i8>, Vec<i8>, Vec<f32>, f32) {
    assert_eq!(x.len() % 128, 0, "int4: comprimento precisa ser multiplo de 128");
    let mut amax = 1e-6f32;
    for &v in x {
        let a = v.abs();
        if a > amax {
            amax = a;
        }
    }
    let (sc, inv) = (amax / 127.0, 127.0 / amax);
    let g_cnt = x.len() / 128;
    let mut x_even = vec![0i8; x.len() / 2];
    let mut x_odd = vec![0i8; x.len() / 2];
    let mut group_bias8 = vec![0.0f32; g_cnt];
    for g in 0..g_cnt {
        let (base_in, base_out) = (g * 128, g * 64);
        let mut sum_x = 0i32;
        for i in 0..64 {
            let qe = (x[base_in + 2 * i] * inv).round().clamp(-127.0, 127.0) as i8;
            let qo = (x[base_in + 2 * i + 1] * inv).round().clamp(-127.0, 127.0) as i8;
            x_even[base_out + i] = qe;
            x_odd[base_out + i] = qo;
            sum_x += (qe as i32) + (qo as i32);
        }
        group_bias8[g] = (8 * sum_x) as f32;
    }
    (x_even, x_odd, group_bias8, sc)
}

/// Dot product int4 (nibble) com escalas por grupo e correcao de vies.
///
/// Cada nibble e lido sem deslocamento; o vies de grupo (`8 * soma(x)`) e
/// subtraido no final, exatamente como no kernel AVX2 de referencia.
pub fn int4_dot_row(
    packed: &[u8],
    scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias: &[f32],
    x_sc: f32,
) -> f32 {
    #[cfg(target_arch = "x86_64")]
    {
        if is_x86_feature_detected!("avx2") && is_x86_feature_detected!("fma") {
            return unsafe { avx2_int4_dot_row(packed, scales, x_even, x_odd, group_bias, x_sc) };
        }
    }
    let g_cnt = scales.len();
    let mut acc = 0.0f32;
    let mut bias = 0.0f32;
    for g in 0..g_cnt {
        let off = g * 64;
        let mut group_sum = 0.0f32;
        for i in 0..64 {
            let byte = packed[off + i];
            group_sum += ((byte & 0x0F) as f32) * (x_even[off + i] as f32)
                + ((byte >> 4) as f32) * (x_odd[off + i] as f32);
        }
        acc += group_sum * scales[g];
        bias += group_bias[g] * scales[g];
    }
    (acc - bias) * x_sc
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2", enable = "fma")]
unsafe fn avx2_int4_dot_row(
    packed: &[u8],
    scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias: &[f32],
    x_sc: f32,
) -> f32 {
    use std::arch::x86_64::*;
    let mask_0f = _mm256_set1_epi8(0x0F);
    let ones = _mm256_set1_epi16(1);
    let mut acc = _mm256_setzero_ps();
    let mut bias = 0.0f32;
    for g in 0..scales.len() {
        let off = g * 64;
        let p0 = _mm256_loadu_si256(packed.as_ptr().add(off) as *const __m256i);
        let p1 = _mm256_loadu_si256(packed.as_ptr().add(off + 32) as *const __m256i);
        let xe0 = _mm256_loadu_si256(x_even.as_ptr().add(off) as *const __m256i);
        let xo0 = _mm256_loadu_si256(x_odd.as_ptr().add(off) as *const __m256i);
        let xe1 = _mm256_loadu_si256(x_even.as_ptr().add(off + 32) as *const __m256i);
        let xo1 = _mm256_loadu_si256(x_odd.as_ptr().add(off + 32) as *const __m256i);
        let lo0 = _mm256_maddubs_epi16(_mm256_and_si256(p0, mask_0f), xe0);
        let hi0 = _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(p0, 4), mask_0f), xo0);
        let lo1 = _mm256_maddubs_epi16(_mm256_and_si256(p1, mask_0f), xe1);
        let hi1 = _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(p1, 4), mask_0f), xo1);
        let s0 = _mm256_madd_epi16(_mm256_add_epi16(lo0, hi0), ones);
        let s1 = _mm256_madd_epi16(_mm256_add_epi16(lo1, hi1), ones);
        let sum32 = _mm256_add_epi32(s0, s1);
        let sc = scales[g];
        acc = _mm256_fmadd_ps(_mm256_cvtepi32_ps(sum32), _mm256_set1_ps(sc), acc);
        bias += group_bias[g] * sc;
    }
    let s4 = _mm_add_ps(_mm256_castps256_ps128(acc), _mm256_extractf128_ps(acc, 1));
    let s2 = _mm_add_ps(s4, _mm_movehl_ps(s4, s4));
    let total = _mm_cvtss_f32(_mm_add_ss(s2, _mm_shuffle_ps(s2, s2, 1)));
    (total - bias) * x_sc
}


/// Dot product int8 escalado: `q8` sao os pesos, `scale` a escala por linha.
pub fn int8_matvec(x: &[f32], q8: &[i8], scale: &[f32], m_rows: usize, k_cols: usize, out: &mut [f32]) {
    assert!(out.len() >= m_rows, "matvec: buffer de saida pequeno");
    assert_eq!(q8.len(), m_rows * k_cols, "matvec: pesos com tamanho divergente");
    assert_eq!(scale.len(), m_rows, "matvec: escala com tamanho divergente");
    let (x_i8, x_sc) = quantize_act_i8(x);
    out[..m_rows].par_iter_mut().enumerate().for_each(|(r, y)| {
        let w_row = &q8[r * k_cols..(r + 1) * k_cols];
        *y = (dot_i8(w_row, &x_i8) as f32) * scale[r] * x_sc;
    });
}

/// Dot product de dois vetores int8 com acumulacao i32 (AVX2 com fallback escalar).
#[inline]
pub fn dot_i8(a: &[i8], b: &[i8]) -> i32 {
    assert_eq!(a.len(), b.len(), "dot_i8: tamanhos divergentes");
    #[cfg(target_arch = "x86_64")]
    {
        if is_x86_feature_detected!("avx2") {
            return unsafe { avx2_dot_i8(a, b) };
        }
    }
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (*x as i32) * (*y as i32))
        .sum()
}

/// Dot product int8 com `maddubs` (AVX2).
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn avx2_dot_i8(a: &[i8], b: &[i8]) -> i32 {
    use std::arch::x86_64::*;
    let n = a.len();
    let ones = _mm256_set1_epi16(1);
    let mut acc = _mm256_setzero_si256();
    let mut i = 0usize;
    while i + 32 <= n {
        let va = _mm256_loadu_si256(a.as_ptr().add(i) as *const __m256i);
        let vb = _mm256_loadu_si256(b.as_ptr().add(i) as *const __m256i);
        // |a| * sign(b, a) = a*b em 16 bits, depois soma em pares para i32.
        let prod16 = _mm256_maddubs_epi16(_mm256_abs_epi8(va), _mm256_sign_epi8(vb, va));
        acc = _mm256_add_epi32(acc, _mm256_madd_epi16(prod16, ones));
        i += 32;
    }
    let mut sum = hsum_epi32(acc);
    while i < n {
        sum += (a[i] as i32) * (b[i] as i32);
        i += 1;
    }
    sum
}

/// Soma horizontal dos 8 lanes de um vetor i32 AVX2.
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn hsum_epi32(v: std::arch::x86_64::__m256i) -> i32 {
    use std::arch::x86_64::*;
    let s4 = _mm_add_epi32(
        _mm256_castsi256_si128(v),
        _mm256_extracti128_si256(v, 1),
    );
    let s2 = _mm_add_epi32(s4, _mm_srli_si128(s4, 8));
    _mm_cvtsi128_si32(_mm_add_epi32(s2, _mm_srli_si128(s2, 4)))
}

/// Dot product int4 empacotado por grupos de 128, com escalas por grupo.
pub fn int4_group128_matvec_row(packed_row: &[u8], scales_row: &[f32], x: &[f32]) -> f32 {
    let k_dim = x.len();
    assert_eq!(k_dim % 128, 0, "int4: dimensao precisa ser multiplo de 128");
    let g_cnt = k_dim / 128;
    assert_eq!(scales_row.len(), g_cnt, "int4: escalas com tamanho divergente");
    let mut acc = 0.0f32;
    for g in 0..g_cnt {
        let sc = scales_row[g];
        let p_base = g * 64;
        let x_base = g * 128;
        let mut group_sum = 0.0f32;
        for i in 0..64 {
            let byte = packed_row[p_base + i];
            let q_lo = ((byte & 0x0F) as f32) - 8.0;
            let q_hi = ((byte >> 4) as f32) - 8.0;
            group_sum += q_lo * x[x_base + 2 * i] + q_hi * x[x_base + 2 * i + 1];
        }
        acc += group_sum * sc;
    }
    acc
}

/// Aplica SwiGLU: `silu(gate) * up`.
pub fn swiglu_inplace(gate: &mut [f32], up: &[f32]) {
    assert_eq!(gate.len(), up.len(), "swiglu: tamanhos divergentes");
    for i in 0..gate.len() {
        let g = gate[i];
        gate[i] = (g / (1.0 + (-g).exp())) * up[i];
    }
}

/// Entropia de Shannon dos `k` maiores logits e um fator de boost derivado.
pub fn shannon_entropy_top16_and_boost(logits: &[f32]) -> (f32, f32) {
    let k = 16usize.min(logits.len());
    if k == 0 {
        return (0.0, 1.0);
    }
    let mut top_k: Vec<f32> = logits.iter().copied().take(k).collect();
    top_k.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
    let max = top_k[0];
    let mut sum_exp = 0.0f32;
    for &v in &top_k {
        sum_exp += (v - max).exp();
    }
    let mut entropy = 0.0f32;
    for &v in &top_k {
        let p = (v - max).exp() / sum_exp.max(1e-9);
        if p > 1e-9 {
            entropy -= p * p.log2();
        }
    }
    let boost = 1.0 + (1.0 - entropy / (k as f32).log2()).max(0.0) * 0.1;
    (entropy, boost)
}

/// RoPE YARN com layout intercalado por par (2i, 2i+1) e tabela por posicao.
pub struct YarnRopeCache {
    pos: usize,
    cos: Vec<f32>,
    sin: Vec<f32>,
    scale: f32,
}

impl YarnRopeCache {
    /// Pre-computa cos/sin YARN para uma posicao e dimensoes dadas.
    ///
    /// `rope_dim` e a fatia rotacionada por cabeca; `head_dim` e a dimensao total
    /// da cabeca usada na escala de softmax.
    pub fn new(pos: usize, rope_dim: usize, head_dim: usize) -> Self {
        let half = rope_dim / 2;
        let base = 10_000.0f32;
        let orig_max = 4096.0f32;
        let factor = 40.0f32;
        let beta_fast = 32.0f32;
        let beta_slow = 1.0f32;
        let mscale = 0.707f32;
        let mscale_all = 0.707f32;

        let low_raw = ((rope_dim as f32) * (orig_max / (beta_fast * 2.0 * std::f32::consts::PI)).ln())
            / (2.0 * base.ln());
        let high_raw = ((rope_dim as f32) * (orig_max / (beta_slow * 2.0 * std::f32::consts::PI)).ln())
            / (2.0 * base.ln());
        let low = low_raw.floor().max(0.0);
        let high = high_raw.ceil().min((rope_dim - 1) as f32);
        let denom = (high - low).max(0.001);

        let mut inv_freq = vec![0.0f32; half];
        for (i, slot) in inv_freq.iter_mut().enumerate() {
            let exponent = (2 * i) as f32 / (rope_dim as f32);
            let freq_extra = 1.0 / base.powf(exponent);
            let freq_inter = 1.0 / (factor * base.powf(exponent));
            let ramp = (((i as f32) - low) / denom).clamp(0.0, 1.0);
            let mask = 1.0 - ramp;
            *slot = freq_inter * ramp + freq_extra * mask;
        }

        let mscale_num = 0.1 * mscale * factor.ln() + 1.0;
        let mscale_den = 0.1 * mscale_all * factor.ln() + 1.0;
        let rot_mscale = mscale_num / mscale_den;
        let scale = (head_dim as f32).powf(-0.5) * mscale_den * mscale_den;

        let t = pos as f32;
        let mut cos = Vec::with_capacity(half);
        let mut sin = Vec::with_capacity(half);
        for &inv in &inv_freq {
            let (s, c) = (t * inv).sin_cos();
            cos.push(c * rot_mscale);
            sin.push(s * rot_mscale);
        }

        Self {
            pos,
            cos,
            sin,
            scale,
        }
    }

    /// Escala de softmax aplicada aos scores de atencao.
    pub fn softmax_scale(&self) -> f32 {
        self.scale
    }

    /// Posicao atual.
    pub fn position(&self) -> usize {
        self.pos
    }

    /// Aplica RoPE intercalado a um vetor de `rope_dim` elementos.
    pub fn apply_head_in_place(&self, vec: &mut [f32], _pos: usize) {
        let half = vec.len() / 2;
        let n = half.min(self.cos.len());
        let mut first = vec![0.0f32; half];
        let mut second = vec![0.0f32; half];
        for i in 0..n {
            let x_even = vec[2 * i];
            let x_odd = vec[2 * i + 1];
            let c = self.cos[i];
            let s = self.sin[i];
            first[i] = x_even * c - x_odd * s;
            second[i] = x_odd * c + x_even * s;
        }
        vec[0..n].copy_from_slice(&first[0..n]);
        vec[n..2 * n].copy_from_slice(&second[0..n]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rmsnorm_normalizes_to_unit_rms() {
        let x = vec![3.0f32, 4.0, 0.0, -1.0];
        let w = vec![1.0f32; 4];
        let mut out = vec![0.0f32; 4];
        rmsnorm_into(&x, &w, 1e-6, &mut out);
        let mean_sq = out.iter().map(|v| v * v).sum::<f32>() / 4.0;
        assert!((mean_sq - 1.0).abs() < 1e-4, "rms nao normalizou: {mean_sq}");
    }

    #[test]
    fn fwht_is_orthogonal_and_preserves_energy() {
        let mut x: Vec<f32> = (0..64).map(|i| (i as f32) * 0.01).collect();
        let before: f32 = x.iter().map(|v| v * v).sum();
        fwht64_slice_inplace(&mut x);
        let after: f32 = x.iter().map(|v| v * v).sum();
        assert!((before - after).abs() / before.max(1e-9) < 1e-4, "FWHT nao preservou energia");
    }

    #[test]
    fn w1a4_roundtrip_preserves_direction() {
        // Um vetor qualquer empacotado e desempacotado deve correlacionar.
        let v: Vec<f32> = (0..64).map(|i| (i as f32 * 0.3).sin() * 2.0).collect();
        let (m, planes) = w1a4_pack_block64(&v);
        assert!(m > 0.0);
        // Reconstroi o bloco quantizado.
        let mut recon = vec![0.0f32; 64];
        for j in 0..64 {
            let q = ((planes[0] >> j) & 1)
                | (((planes[1] >> j) & 1) << 1)
                | (((planes[2] >> j) & 1) << 2)
                | (((planes[3] >> j) & 1) << 3);
            recon[j] = (q as f32 / 15.0 * 2.0 - 1.0) * m;
        }
        let err: f32 = recon
            .iter()
            .zip(v.iter())
            .map(|(a, b)| (a - b) * (a - b))
            .sum();
        let norm: f32 = v.iter().map(|x| x * x).sum();
        assert!(err / norm.max(1e-9) < 0.05, "erro de quantizacao alto: {err}/{norm}");
    }

    #[test]
    fn int8_matvec_matches_naive_reference() {
        let x = vec![0.5f32, -0.25];
        let q8 = vec![2i8, -3, 4, 1];
        let scale = vec![0.5f32, 0.25];
        let mut out = vec![0.0f32; 2];
        int8_matvec(&x, &q8, &scale, 2, 2, &mut out);
        // Verifica contra calculo direto com o mesmo esquema de quantizacao.
        let (xq, xsc) = quantize_act_i8(&x);
        let acc0: i32 = (0..2).map(|i| (q8[i] as i32) * (xq[i] as i32)).sum();
        assert!((out[0] - (acc0 as f32) * 0.5 * xsc).abs() < 1e-5);
        let acc1: i32 = (0..2).map(|i| (q8[2 + i] as i32) * (xq[i] as i32)).sum();
        assert!((out[1] - (acc1 as f32) * 0.25 * xsc).abs() < 1e-5);
    }

    #[test]
    fn swiglu_is_finite_for_extremes() {
        let mut g = vec![-100.0f32, 0.0, 100.0];
        let u = vec![1.0f32, 2.0, 3.0];
        swiglu_inplace(&mut g, &u);
        assert!(g.iter().all(|v| v.is_finite()));
    }

    #[test]
    fn homeostatic_residual_respects_ratio() {
        let mut h = vec![1.0f32; 8];
        let d = vec![100.0f32; 8];
        homeostatic_residual_add_inplace(&mut h, &d, 1.8);
        let h_sq: f32 = h.iter().map(|v| v * v).sum();
        let d_sq: f32 = d.iter().map(|v| v * v).sum();
        assert!((h_sq / d_sq).sqrt() <= 1.8 + 1e-3);
    }

    #[test]
    fn entropy_of_uniform_logits_is_maximal() {
        let logits = vec![0.0f32; 16];
        let (h, _) = shannon_entropy_top16_and_boost(&logits);
        assert!((h - 4.0).abs() < 1e-4, "entropia uniforme deveria ser 4.0, veio {h}");
    }
}
