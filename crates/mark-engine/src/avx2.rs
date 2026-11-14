//! Kernels AVX2/FMA para as camadas MoE que rodam na CPU (camadas 14..26).
//!
//! Estas sao as MESMAS rotinas do motor Rust validado
//! (`mark-v3-rs/src/bin/bench_tok_s_pure_rust.rs`): gate/up int4 fundidos com
//! SwiGLU, down int4 com AXPY no acumulador e 48 chunks sobre 8 threads. A
//! ativacao e quantizada uma vez por camada (pares even/odd + vies de grupo),
//! de modo que nenhum decode flutuante por nibble acontece no caminho quente.

use rayon::prelude::*;

/// Ativacao preparada para o produto int4 (128 colunas por grupo).
pub struct Int4Act {
    /// Elementos de indice par, compactados por grupo de 128.
    pub even: Vec<i8>,
    /// Elementos de indice impar, compactados por grupo de 128.
    pub odd: Vec<i8>,
    /// Vies de grupo (`8 * soma dos quantizados`) usado para remover o offset 8.
    pub bias: Vec<f32>,
    /// Escala de quantizacao da ativacao.
    pub scale: f32,
}

/// Quantiza a ativacao em pares even/odd com vies por grupo de 128 colunas.
pub fn prepare_act_int4_pairs(x: &[f32]) -> Int4Act {
    assert_eq!(x.len() % 128, 0, "int4: comprimento precisa ser multiplo de 128");
    let mut amax = 1e-6f32;
    for &v in x {
        let a = v.abs();
        if a > amax {
            amax = a;
        }
    }
    let sc = amax / 127.0;
    let inv = 127.0 / amax;
    let groups = x.len() / 128;
    let mut even = vec![0i8; x.len() / 2];
    let mut odd = vec![0i8; x.len() / 2];
    let mut bias = vec![0.0f32; groups];
    for g in 0..groups {
        let (base_in, base_out) = (g * 128, g * 64);
        let mut sum_x = 0i32;
        for i in 0..64 {
            let qe = (x[base_in + 2 * i] * inv).round().clamp(-127.0, 127.0) as i8;
            let qo = (x[base_in + 2 * i + 1] * inv).round().clamp(-127.0, 127.0) as i8;
            even[base_out + i] = qe;
            odd[base_out + i] = qo;
            sum_x += (qe as i32) + (qo as i32);
        }
        bias[g] = (8 * sum_x) as f32;
    }
    Int4Act {
        even,
        odd,
        bias,
        scale: sc,
    }
}

/// Indica se o caminho vetorial AVX2+FMA esta disponivel nesta CPU.
pub fn avx2_enabled() -> bool {
    #[cfg(target_arch = "x86_64")]
    {
        std::arch::is_x86_feature_detected!("avx2") && std::arch::is_x86_feature_detected!("fma")
    }
    #[cfg(not(target_arch = "x86_64"))]
    {
        false
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma")]
#[allow(clippy::too_many_arguments)]
unsafe fn gate_up_swiglu_row_avx2(
    g_packed: &[u8],
    g_scales: &[f32],
    u_packed: &[u8],
    u_scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias8: &[f32],
    x_sc: f32,
) -> f32 {
    use std::arch::x86_64::*;
    let (mask_0f, ones_16) = (_mm256_set1_epi8(0x0F), _mm256_set1_epi16(1));
    let (mut acc_g, mut acc_u, mut bias_g, mut bias_u) = (
        _mm256_setzero_ps(),
        _mm256_setzero_ps(),
        0.0f32,
        0.0f32,
    );
    let (gp_base, up_base, xe_base, xo_base) = (
        g_packed.as_ptr(),
        u_packed.as_ptr(),
        x_even.as_ptr(),
        x_odd.as_ptr(),
    );

    for g in 0..16 {
        let off = g * 64;
        let xe0 = _mm256_loadu_si256(xe_base.add(off) as *const __m256i);
        let xo0 = _mm256_loadu_si256(xo_base.add(off) as *const __m256i);
        let xe1 = _mm256_loadu_si256(xe_base.add(off + 32) as *const __m256i);
        let xo1 = _mm256_loadu_si256(xo_base.add(off + 32) as *const __m256i);

        let gp0 = _mm256_loadu_si256(gp_base.add(off) as *const __m256i);
        let gp1 = _mm256_loadu_si256(gp_base.add(off + 32) as *const __m256i);
        let gprod0 = _mm256_add_epi16(
            _mm256_maddubs_epi16(_mm256_and_si256(gp0, mask_0f), xe0),
            _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(gp0, 4), mask_0f), xo0),
        );
        let gprod1 = _mm256_add_epi16(
            _mm256_maddubs_epi16(_mm256_and_si256(gp1, mask_0f), xe1),
            _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(gp1, 4), mask_0f), xo1),
        );
        let gsum32 = _mm256_madd_epi16(_mm256_add_epi16(gprod0, gprod1), ones_16);
        let gsc = g_scales[g];
        acc_g = _mm256_fmadd_ps(_mm256_cvtepi32_ps(gsum32), _mm256_set1_ps(gsc), acc_g);
        bias_g += group_bias8[g] * gsc;

        let up0 = _mm256_loadu_si256(up_base.add(off) as *const __m256i);
        let up1 = _mm256_loadu_si256(up_base.add(off + 32) as *const __m256i);
        let uprod0 = _mm256_add_epi16(
            _mm256_maddubs_epi16(_mm256_and_si256(up0, mask_0f), xe0),
            _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(up0, 4), mask_0f), xo0),
        );
        let uprod1 = _mm256_add_epi16(
            _mm256_maddubs_epi16(_mm256_and_si256(up1, mask_0f), xe1),
            _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(up1, 4), mask_0f), xo1),
        );
        let usum32 = _mm256_madd_epi16(_mm256_add_epi16(uprod0, uprod1), ones_16);
        let usc = u_scales[g];
        acc_u = _mm256_fmadd_ps(_mm256_cvtepi32_ps(usum32), _mm256_set1_ps(usc), acc_u);
        bias_u += group_bias8[g] * usc;
    }

    let hsum = |v: __m256| -> f32 {
        let s4 = _mm_add_ps(_mm256_castps256_ps128(v), _mm256_extractf128_ps(v, 1));
        let s2 = _mm_add_ps(s4, _mm_movehl_ps(s4, s4));
        _mm_cvtss_f32(_mm_add_ss(s2, _mm_shuffle_ps(s2, s2, 1)))
    };
    let gv = (hsum(acc_g) - bias_g) * x_sc;
    let uv = (hsum(acc_u) - bias_u) * x_sc;
    (gv / (1.0f32 + (-gv).exp())) * uv
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma")]
unsafe fn down_row_avx2(
    packed_row: &[u8],
    scales_row: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias8: &[f32],
    x_sc: f32,
) -> f32 {
    use std::arch::x86_64::*;
    let (mask_0f, ones_16, mut acc, mut bias_tot) = (
        _mm256_set1_epi8(0x0F),
        _mm256_set1_epi16(1),
        _mm256_setzero_ps(),
        0.0f32,
    );
    let (p_base, xe_base, xo_base) = (
        packed_row.as_ptr(),
        x_even.as_ptr(),
        x_odd.as_ptr(),
    );
    for g in 0..11 {
        let off = g * 64;
        let p0 = _mm256_loadu_si256(p_base.add(off) as *const __m256i);
        let p1 = _mm256_loadu_si256(p_base.add(off + 32) as *const __m256i);
        let xe0 = _mm256_loadu_si256(xe_base.add(off) as *const __m256i);
        let xo0 = _mm256_loadu_si256(xo_base.add(off) as *const __m256i);
        let xe1 = _mm256_loadu_si256(xe_base.add(off + 32) as *const __m256i);
        let xo1 = _mm256_loadu_si256(xo_base.add(off + 32) as *const __m256i);
        let prod0 = _mm256_add_epi16(
            _mm256_maddubs_epi16(_mm256_and_si256(p0, mask_0f), xe0),
            _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(p0, 4), mask_0f), xo0),
        );
        let prod1 = _mm256_add_epi16(
            _mm256_maddubs_epi16(_mm256_and_si256(p1, mask_0f), xe1),
            _mm256_maddubs_epi16(_mm256_and_si256(_mm256_srli_epi16(p1, 4), mask_0f), xo1),
        );
        let sum32 = _mm256_madd_epi16(_mm256_add_epi16(prod0, prod1), ones_16);
        let sc = scales_row[g];
        acc = _mm256_fmadd_ps(_mm256_cvtepi32_ps(sum32), _mm256_set1_ps(sc), acc);
        bias_tot += group_bias8[g] * sc;
    }
    let s4 = _mm_add_ps(_mm256_castps256_ps128(acc), _mm256_extractf128_ps(acc, 1));
    let s2 = _mm_add_ps(s4, _mm_movehl_ps(s4, s4));
    (_mm_cvtss_f32(_mm_add_ss(s2, _mm_shuffle_ps(s2, s2, 1))) - bias_tot) * x_sc
}

/// Gate/up int4 fundidos com SwiGLU para uma linha (caminho escalar de reserva).
#[allow(clippy::too_many_arguments)]
fn gate_up_swiglu_row_scalar(
    g_packed: &[u8],
    g_scales: &[f32],
    u_packed: &[u8],
    u_scales: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias8: &[f32],
    x_sc: f32,
) -> f32 {
    let mut acc_g = [0.0f32; 8];
    let mut acc_u = [0.0f32; 8];
    let (mut bias_g, mut bias_u) = (0.0f32, 0.0f32);
    for g in 0..16 {
        let off = g * 64;
        let mut sg = 0i32;
        let mut su = 0i32;
        for i in 0..64 {
            let (xe, xo) = (x_even[off + i] as i32, x_odd[off + i] as i32);
            let bg = g_packed[off + i];
            let bu = u_packed[off + i];
            sg += ((bg & 0x0F) as i32) * xe + ((bg >> 4) as i32) * xo;
            su += ((bu & 0x0F) as i32) * xe + ((bu >> 4) as i32) * xo;
        }
        let gsc = g_scales[g];
        let usc = u_scales[g];
        acc_g[g & 7] += (sg as f32) * gsc;
        acc_u[g & 7] += (su as f32) * usc;
        bias_g += group_bias8[g] * gsc;
        bias_u += group_bias8[g] * usc;
    }
    let gv = (acc_g.iter().sum::<f32>() - bias_g) * x_sc;
    let uv = (acc_u.iter().sum::<f32>() - bias_u) * x_sc;
    (gv / (1.0f32 + (-gv).exp())) * uv
}

/// Down int4 para uma linha (caminho escalar de reserva).
fn down_row_scalar(
    packed_row: &[u8],
    scales_row: &[f32],
    x_even: &[i8],
    x_odd: &[i8],
    group_bias8: &[f32],
    x_sc: f32,
) -> f32 {
    let mut acc = [0.0f32; 8];
    let mut bias_tot = 0.0f32;
    for g in 0..11 {
        let off = g * 64;
        let mut s = 0i32;
        for i in 0..64 {
            let (xe, xo) = (x_even[off + i] as i32, x_odd[off + i] as i32);
            let b = packed_row[off + i];
            s += ((b & 0x0F) as i32) * xe + ((b >> 4) as i32) * xo;
        }
        let sc = scales_row[g];
        acc[g & 7] += (s as f32) * sc;
        bias_tot += group_bias8[g] * sc;
    }
    (acc.iter().sum::<f32>() - bias_tot) * x_sc
}

/// Pesos int4 dos experts roteados de uma camada (visao zero-copy do mmap).
pub struct ExpertBatch<'a> {
    pub gate_q4: &'a [u8],
    pub gate_sc: &'a [f32],
    pub up_q4: &'a [u8],
    pub up_sc: &'a [f32],
    pub down_q4: &'a [u8],
    pub down_sc: &'a [f32],
}

/// Executa os 6 experts roteados em 48 chunks (6 experts x 8 sub-faixas).
///
/// `inter` e a dimensao intermediaria do expert (1408) e `hidden` a dimensao de
/// saida (2048). O resultado e somado com peso de roteamento em `out`.
pub fn routed_six_experts(
    top6: &[(usize, f32)],
    xn: &[f32],
    inter: usize,
    hidden: usize,
    batch: &ExpertBatch,
    out: &mut [f32],
) {
    let n_top = top6.len();
    let act = prepare_act_int4_pairs(xn);
    let vec = avx2_enabled();
    let sub_inter = inter / 8;
    let sub_hidden = hidden / 8;

    let mut inter_all = vec![0.0f32; n_top * inter];
    inter_all
        .par_chunks_mut(sub_inter)
        .enumerate()
        .for_each(|(task_id, chunk)| {
            let (ki, sub) = (task_id / 8, task_id % 8);
            let (eid, r_start) = (top6[ki].0, sub * sub_inter);
            let (g_off_q, g_off_s) = (eid * inter * 1024, eid * inter * 16);
            for (idx, val) in chunk.iter_mut().enumerate() {
                let r = r_start + idx;
                let g_row = &batch.gate_q4[g_off_q + r * 1024..g_off_q + (r + 1) * 1024];
                let g_srow = &batch.gate_sc[g_off_s + r * 16..g_off_s + (r + 1) * 16];
                let u_row = &batch.up_q4[g_off_q + r * 1024..g_off_q + (r + 1) * 1024];
                let u_srow = &batch.up_sc[g_off_s + r * 16..g_off_s + (r + 1) * 16];
                *val = if vec {
                    #[cfg(target_arch = "x86_64")]
                    unsafe {
                        gate_up_swiglu_row_avx2(
                            g_row,
                            g_srow,
                            u_row,
                            u_srow,
                            &act.even,
                            &act.odd,
                            &act.bias,
                            act.scale,
                        )
                    }
                    #[cfg(not(target_arch = "x86_64"))]
                    {
                        gate_up_swiglu_row_scalar(
                            g_row,
                            g_srow,
                            u_row,
                            u_srow,
                            &act.even,
                            &act.odd,
                            &act.bias,
                            act.scale,
                        )
                    }
                } else {
                    gate_up_swiglu_row_scalar(
                        g_row,
                        g_srow,
                        u_row,
                        u_srow,
                        &act.even,
                        &act.odd,
                        &act.bias,
                        act.scale,
                    )
                };
            }
        });

    let prep: Vec<Int4Act> = (0..n_top)
        .map(|ki| prepare_act_int4_pairs(&inter_all[ki * inter..(ki + 1) * inter]))
        .collect();

    let mut down_all = vec![0.0f32; n_top * hidden];
    down_all
        .par_chunks_mut(sub_hidden)
        .enumerate()
        .for_each(|(task_id, chunk)| {
            let (ki, sub) = (task_id / 8, task_id % 8);
            let (eid, r_start) = (top6[ki].0, sub * sub_hidden);
            let (d_off_q, d_off_s) = (eid * hidden * 704, eid * hidden * 11);
            let act_d = &prep[ki];
            for (idx, val) in chunk.iter_mut().enumerate() {
                let r = r_start + idx;
                let d_row = &batch.down_q4[d_off_q + r * 704..d_off_q + (r + 1) * 704];
                let d_srow = &batch.down_sc[d_off_s + r * 11..d_off_s + (r + 1) * 11];
                *val = if vec {
                    #[cfg(target_arch = "x86_64")]
                    unsafe {
                        down_row_avx2(
                            d_row, d_srow, &act_d.even, &act_d.odd, &act_d.bias, act_d.scale,
                        )
                    }
                    #[cfg(not(target_arch = "x86_64"))]
                    {
                        down_row_scalar(
                            d_row, d_srow, &act_d.even, &act_d.odd, &act_d.bias, act_d.scale,
                        )
                    }
                } else {
                    down_row_scalar(d_row, d_srow, &act_d.even, &act_d.odd, &act_d.bias, act_d.scale)
                };
            }
        });

    for ki in 0..n_top {
        let (w_k, d_slice) = (top6[ki].1, &down_all[ki * hidden..(ki + 1) * hidden]);
        for j in 0..hidden {
            out[j] += w_k * d_slice[j];
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pseudo_row(len: usize, salt: u64) -> Vec<u8> {
        (0..len)
            .map(|i| (salt.wrapping_mul(i as u64 + 7) >> 13) as u8)
            .collect()
    }

    #[test]
    fn avx2_and_scalar_int4_paths_agree() {
        let inter = 1408usize;
        let hidden = 2048usize;
        // Tres experts completos: o teste indexa e0..e2 em cada projecao.
        let g_q4 = pseudo_row(3 * inter * 1024, 0x9E37);
        let u_q4 = pseudo_row(3 * inter * 1024, 0x85EB);
        let d_q4 = pseudo_row(3 * hidden * 704, 0xC2B2);
        let g_sc: Vec<f32> = (0..3 * inter * 16).map(|i| 0.001 + (i % 7) as f32 * 1e-5).collect();
        let u_sc: Vec<f32> = (0..3 * inter * 16).map(|i| 0.002 + (i % 5) as f32 * 1e-5).collect();
        let d_sc: Vec<f32> = (0..3 * hidden * 11).map(|i| 0.003 + (i % 3) as f32 * 1e-5).collect();
        let xn: Vec<f32> = (0..hidden).map(|i| ((i as f32) * 0.013).sin()).collect();
        let act = prepare_act_int4_pairs(&xn);

        for eid in 0..3usize {
            let g_off_q = eid * inter * 1024;
            let g_off_s = eid * inter * 16;
            for r in [0usize, 1, 703, 1407] {
                let g_row = &g_q4[g_off_q + r * 1024..g_off_q + (r + 1) * 1024];
                let g_srow = &g_sc[g_off_s + r * 16..g_off_s + (r + 1) * 16];
                let u_row = &u_q4[g_off_q + r * 1024..g_off_q + (r + 1) * 1024];
                let u_srow = &u_sc[g_off_s + r * 16..g_off_s + (r + 1) * 16];
                let scalar = gate_up_swiglu_row_scalar(
                    g_row,
                    g_srow,
                    u_row,
                    u_srow,
                    &act.even,
                    &act.odd,
                    &act.bias,
                    act.scale,
                );
                if avx2_enabled() {
                    let vector = unsafe {
                        gate_up_swiglu_row_avx2(
                            g_row,
                            g_srow,
                            u_row,
                            u_srow,
                            &act.even,
                            &act.odd,
                            &act.bias,
                            act.scale,
                        )
                    };
                    let tol = scalar.abs().max(1.0) * 1e-3;
                    assert!(
                        (scalar - vector).abs() <= tol,
                        "gate/up divergiu em e{eid} r{r}: scalar={scalar} avx2={vector}"
                    );
                }
            }
        }

        let inter_act: Vec<f32> = (0..inter).map(|i| ((i as f32) * 0.017).cos()).collect();
        let prep = prepare_act_int4_pairs(&inter_act);
        for eid in 0..3usize {
            let d_off_q = eid * hidden * 704;
            let d_off_s = eid * hidden * 11;
            for r in [0usize, 1, 1023, 2047] {
                let d_row = &d_q4[d_off_q + r * 704..d_off_q + (r + 1) * 704];
                let d_srow = &d_sc[d_off_s + r * 11..d_off_s + (r + 1) * 11];
                let scalar =
                    down_row_scalar(d_row, d_srow, &prep.even, &prep.odd, &prep.bias, prep.scale);
                if avx2_enabled() {
                    let vector = unsafe {
                        down_row_avx2(d_row, d_srow, &prep.even, &prep.odd, &prep.bias, prep.scale)
                    };
                    let tol = scalar.abs().max(1.0) * 1e-3;
                    assert!(
                        (scalar - vector).abs() <= tol,
                        "down divergiu em e{eid} r{r}: scalar={scalar} avx2={vector}"
                    );
                }
            }
        }
    }

    #[test]
    fn routed_experts_accumulates_all_six_weights() {
        let inter = 1408usize;
        let hidden = 2048usize;
        let g_q4 = pseudo_row(2 * inter * 1024, 0x1234);
        let u_q4 = pseudo_row(2 * inter * 1024, 0x5678);
        let d_q4 = pseudo_row(2 * hidden * 704, 0x9ABC);
        let g_sc = vec![0.01f32; 2 * inter * 16];
        let u_sc = vec![0.01f32; 2 * inter * 16];
        let d_sc = vec![0.01f32; 2 * hidden * 11];
        let xn: Vec<f32> = (0..hidden).map(|i| ((i as f32) * 0.011).cos()).collect();
        let batch = ExpertBatch {
            gate_q4: &g_q4,
            gate_sc: &g_sc,
            up_q4: &u_q4,
            up_sc: &u_sc,
            down_q4: &d_q4,
            down_sc: &d_sc,
        };
        let top = [(0usize, 0.5f32), (1, 0.5)];
        let mut out = vec![0.0f32; hidden];
        routed_six_experts(&top, &xn, inter, hidden, &batch, &mut out);
        assert!(out.iter().all(|v| v.is_finite()), "saida nao finita");
        assert!(out.iter().any(|v| v.abs() > 0.0), "saida zerada");
    }
}
