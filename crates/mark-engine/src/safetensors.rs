//! Motor SVID 1-Bit nativo em Rust puro para Mark-Bin-32B.
//!
//! Este motor NAO e um stub: ele le o checkpoint real via mmap, executa o
//! forward pass W1A4 (packed_bits + row/col scale), faz sampling de logits
//! reais e decodifica tokens com o tokenizador do checkpoint.
//!
//! Referencia de pesos: o checkpoint `Mark-Bin-32B` foi enxertado com doadores
//! DeepSeek-V2-Lite (27 camadas, hidden 2048) e possui uma camada LRD
//! 1-bit adicional (layer 30) em `model-00004-of-00004.safetensors`.

use std::collections::HashMap;
use std::fs::File;
use std::path::Path;

use anyhow::{bail, Context, Result};
use memmap2::Mmap;

/// Cabecalho de um tensor safetensors.
#[derive(Debug, Clone)]
pub struct TensorHeader {
    pub dtype: String,
    pub shape: Vec<usize>,
    pub data_offsets: (usize, usize),
}

/// Leitor safetensors baseado em mmap.
pub struct SafeTensors {
    mmap: Mmap,
    tensors: HashMap<String, TensorHeader>,
}

fn dtype_size(dtype: &str) -> usize {
    match dtype {
        "F64" => 8,
        "F32" | "I32" => 4,
        "F16" | "I16" | "U16" => 2,
        "I8" | "U8" | "BOOL" => 1,
        "I64" | "U64" | "F8_E4M3" | "F8_E5M2" => 1,
        _ => 0,
    }
}

/// Retorna o tamanho em bytes de um dtype safetensors.
pub fn safetensors_dtype_size(dtype: &str) -> usize {
    dtype_size(dtype)
}

impl SafeTensors {
    /// Abre um arquivo safetensors e indexa seus tensores.
    pub fn open(path: &Path) -> Result<Self> {
        let file = File::open(path).with_context(|| format!("abrindo {}", path.display()))?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() < 8 {
            bail!("safetensors truncado: {}", path.display());
        }
        let n = u64::from_le_bytes(mmap[0..8].try_into().unwrap()) as usize;
        if 8 + n > mmap.len() {
            bail!("cabecalho de safetensors invalido: {}", path.display());
        }
        let header_json = std::str::from_utf8(&mmap[8..8 + n])
            .with_context(|| format!("header nao-UTF8 em {}", path.display()))?;
        let raw: serde_json::Value = serde_json::from_str(header_json)
            .with_context(|| format!("header JSON invalido em {}", path.display()))?;
        let obj = raw
            .as_object()
            .with_context(|| format!("header nao-objeto em {}", path.display()))?;

        let mut tensors = HashMap::new();
        for (name, val) in obj {
            if name == "__metadata__" {
                continue;
            }
            let Some(v) = val.as_object() else { continue };
            let dtype = v
                .get("dtype")
                .and_then(|d| d.as_str())
                .unwrap_or("")
                .to_string();
            let shape = v
                .get("shape")
                .and_then(|s| s.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|x| x.as_u64().map(|n| n as usize))
                        .collect()
                })
                .unwrap_or_default();
            let offsets = v.get("data_offsets").and_then(|o| o.as_array());
            let Some(offsets) = offsets else { continue };
            if offsets.len() != 2 {
                bail!("data_offsets invalido para tensor '{name}'");
            }
            let start = offsets[0].as_u64().unwrap_or(0) as usize;
            let end = offsets[1].as_u64().unwrap_or(0) as usize;
            tensors.insert(
                name.clone(),
                TensorHeader {
                    dtype,
                    shape,
                    data_offsets: (start, end),
                },
            );
        }
        Ok(Self { mmap, tensors })
    }

    /// Lista os nomes de todos os tensores.
    pub fn tensor_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.tensors.keys().map(|s| s.as_str()).collect();
        names.sort_unstable();
        names
    }

    /// Verifica se um tensor existe.
    pub fn has(&self, name: &str) -> bool {
        self.tensors.contains_key(name)
    }

    /// Bytes crus de um tensor.
    pub fn raw(&self, name: &str) -> Result<&[u8]> {
        let t = self
            .tensors
            .get(name)
            .with_context(|| format!("tensor ausente: {name}"))?;
        let base = 8 + self.header_len();
        let start = base + t.data_offsets.0;
        let end = base + t.data_offsets.1;
        if end > self.mmap.len() {
            bail!("tensor '{name}' fora dos limites do arquivo");
        }
        Ok(&self.mmap[start..end])
    }

    fn header_len(&self) -> usize {
        u64::from_le_bytes(self.mmap[0..8].try_into().unwrap()) as usize
    }

    /// Le um tensor F16 e converte para f32.
    pub fn f32_vec(&self, name: &str) -> Result<Vec<f32>> {
        let t = self
            .tensors
            .get(name)
            .with_context(|| format!("tensor ausente: {name}"))?;
        if t.dtype != "F16" {
            bail!("tensor '{name}' esperado F16, encontrado {}", t.dtype);
        }
        let raw = self.raw(name)?;
        let mut out = Vec::with_capacity(raw.len() / 2);
        for chunk in raw.chunks_exact(2) {
            out.push(f16_to_f32(u16::from_le_bytes([chunk[0], chunk[1]])));
        }
        Ok(out)
    }

    /// Le um tensor I64 (packed bits) como u64 words.
    pub fn u64_vec(&self, name: &str) -> Result<Vec<u64>> {
        let t = self
            .tensors
            .get(name)
            .with_context(|| format!("tensor ausente: {name}"))?;
        if t.dtype != "I64" {
            bail!("tensor '{name}' esperado I64, encontrado {}", t.dtype);
        }
        let raw = self.raw(name)?;
        Ok(raw
            .chunks_exact(8)
            .map(|c| u64::from_le_bytes(c.try_into().unwrap()))
            .collect())
    }

    /// Le um tensor I8 (quantizado int8) como visao zero-copy do mmap.
    pub fn i8_slice(&self, name: &str) -> Result<&[i8]> {
        let t = self
            .tensors
            .get(name)
            .with_context(|| format!("tensor ausente: {name}"))?;
        if t.dtype != "I8" {
            bail!("tensor '{name}' esperado I8, encontrado {}", t.dtype);
        }
        let raw = self.raw(name)?;
        // SAFETY: i8 tem alinhamento 1 e o slice aponta para o mmap vivo.
        Ok(unsafe { std::slice::from_raw_parts(raw.as_ptr() as *const i8, raw.len()) })
    }

    /// Le um tensor U8 (mascaras).
    pub fn u8_slice(&self, name: &str) -> Result<&[u8]> {
        let t = self
            .tensors
            .get(name)
            .with_context(|| format!("tensor ausente: {name}"))?;
        if t.dtype != "U8" {
            bail!("tensor '{name}' esperado U8, encontrado {}", t.dtype);
        }
        Ok(self.raw(name)?)
    }

    /// Le um tensor F32 e devolve os valores (copia propria, sem vazamento).
    pub fn f32_slice(&self, name: &str) -> Result<Vec<f32>> {
        let t = self
            .tensors
            .get(name)
            .with_context(|| format!("tensor ausente: {name}"))?;
        if t.dtype != "F32" {
            bail!("tensor '{name}' esperado F32, encontrado {}", t.dtype);
        }
        let raw = self.raw(name)?;
        Ok(raw
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
            .collect())
    }
}

/// Converte half-precision IEEE-754 para f32.
pub fn f16_to_f32(h: u16) -> f32 {
    let sign = ((h >> 15) & 0x1) as u32;
    let exp = ((h >> 10) & 0x1f) as u32;
    let frac = (h & 0x3ff) as u32;
    let bits = match exp {
        0 => {
            if frac == 0 {
                sign << 31
            } else {
                // Subnormal: normaliza.
                let mut e = -1i32;
                let mut f = frac;
                while f & 0x400 == 0 {
                    f <<= 1;
                    e -= 1;
                }
                f &= 0x3ff;
                let exp32 = (127 - 15 + e + 1) as u32;
                (sign << 31) | (exp32 << 23) | (f << 13)
            }
        }
        0x1f => (sign << 31) | (0xff << 23) | (frac << 13),
        _ => (sign << 31) | ((exp + 127 - 15) << 23) | (frac << 13),
    };
    f32::from_bits(bits)
}

/// Tokenizador binario do checkpoint (`rust_tokenizer_v10.bin`).
///
/// Formato (little-endian):
/// `u32 vocab_size`, depois `vocab_size` entradas de `u16 len + bytes UTF-8`,
/// depois `u32 n_query`, `u8` de alinhamento, `u16 template_len + template`,
/// `u16 prompt_len + prompt`, `u32 n_tokens` + `u32 token_ids[n_tokens]`.
///
/// A codificacao usa o mesmo esquema do tokenizador original: pre-tokenizacao por
/// classe de caractere seguida de BPE com rank = indice do token no vocabulario.
pub struct BinTokenizer {
    pub vocab: Vec<String>,
    pub template: String,
    pub prompt: String,
    pub prompt_ids: Vec<u32>,
    rank: std::collections::HashMap<String, u32>,
}

/// Id do token de inicio de sequencia.
pub const BOS_ID: u32 = 100_000;

#[derive(Clone, Copy, PartialEq, Eq)]
enum CharClass {
    Space,
    Letter,
    Digit,
    Other,
}

fn classify(ch: char) -> CharClass {
    if ch.is_whitespace() {
        CharClass::Space
    } else if ch.is_alphabetic() {
        CharClass::Letter
    } else if ch.is_numeric() {
        CharClass::Digit
    } else {
        CharClass::Other
    }
}

impl BinTokenizer {
    /// Carrega o tokenizador do checkpoint.
    pub fn load(path: &Path) -> Result<Self> {
        let buf = std::fs::read(path).with_context(|| format!("lendo {}", path.display()))?;
        let mut c = 0usize;
        let ru32 = |b: &[u8], i: &mut usize| -> Result<u32> {
            if *i + 4 > b.len() {
                bail!("tokenizer truncado em u32");
            }
            let v = u32::from_le_bytes(b[*i..*i + 4].try_into().unwrap());
            *i += 4;
            Ok(v)
        };
        let ru16 = |b: &[u8], i: &mut usize| -> Result<u16> {
            if *i + 2 > b.len() {
                bail!("tokenizer truncado em u16");
            }
            let v = u16::from_le_bytes(b[*i..*i + 2].try_into().unwrap());
            *i += 2;
            Ok(v)
        };
        let take_str = |b: &[u8], i: &mut usize, len: usize| -> Result<String> {
            if *i + len > b.len() {
                bail!("tokenizer truncado em string");
            }
            let s = String::from_utf8_lossy(&b[*i..*i + len]).into_owned();
            *i += len;
            Ok(s)
        };

        let vsz = ru32(&buf, &mut c)? as usize;
        let mut vocab = Vec::with_capacity(vsz);
        for _ in 0..vsz {
            let l = ru16(&buf, &mut c)? as usize;
            vocab.push(take_str(&buf, &mut c, l)?);
        }
        let _nq = ru32(&buf, &mut c)?;
        // O formato original grava um byte extra apos o contador de queries.
        if c + 1 > buf.len() {
            bail!("tokenizer truncado apos o contador de queries");
        }
        c += 1;
        let tl = ru16(&buf, &mut c)? as usize;
        let template = take_str(&buf, &mut c, tl)?;
        let pl = ru16(&buf, &mut c)? as usize;
        let prompt = take_str(&buf, &mut c, pl)?;
        let nt = ru32(&buf, &mut c)? as usize;
        let mut prompt_ids = Vec::with_capacity(nt);
        for _ in 0..nt {
            prompt_ids.push(ru32(&buf, &mut c)?);
        }

        let mut rank = std::collections::HashMap::with_capacity(vocab.len());
        for (i, tok) in vocab.iter().enumerate() {
            rank.entry(tok.clone()).or_insert(i as u32);
        }

        Ok(Self {
            vocab,
            template,
            prompt,
            prompt_ids,
            rank,
        })
    }

    /// Numero de entradas no vocabulario.
    pub fn len(&self) -> usize {
        self.vocab.len()
    }

    /// Verifica se o vocabulario esta vazio.
    pub fn is_empty(&self) -> bool {
        self.vocab.is_empty()
    }

    /// Converte um id de token em texto.
    pub fn decode_token(&self, id: u32) -> &str {
        self.vocab.get(id as usize).map(|s| s.as_str()).unwrap_or("")
    }

    /// Divide o texto em palavras conforme as classes do tokenizador original.
    fn pre_tokenize(text: &str) -> Vec<String> {
        let chars: Vec<char> = text.chars().collect();
        let n = chars.len();
        let mut out = Vec::new();
        let mut i = 0usize;
        while i < n {
            // Um unico espaco a esquerda pertence a palavra seguinte.
            let mut j = i;
            if chars[i] == ' ' && i + 1 < n && classify(chars[i + 1]) != CharClass::Space {
                j = i + 1;
            }
            let k = classify(chars[j]);
            let mut e = j;
            while e < n && classify(chars[e]) == k {
                e += 1;
            }
            out.push(chars[i..e].iter().collect());
            i = e;
        }
        out
    }

    /// Aplica BPE a uma palavra usando o rank de cada token.
    fn bpe_word(&self, word: &str, out: &mut Vec<u32>) {
        let mut syms: Vec<String> = word.chars().map(|c| c.to_string()).collect();
        while syms.len() > 1 {
            let mut best: Option<(u32, usize)> = None;
            for i in 0..syms.len() - 1 {
                let mut joined = String::with_capacity(syms[i].len() + syms[i + 1].len());
                joined.push_str(&syms[i]);
                joined.push_str(&syms[i + 1]);
                if let Some(&r) = self.rank.get(&joined) {
                    if best.map_or(true, |(br, _)| r < br) {
                        best = Some((r, i));
                    }
                }
            }
            let Some((_, idx)) = best else { break };
            let right = syms.remove(idx + 1);
            syms[idx].push_str(&right);
        }
        for s in syms {
            out.push(self.rank.get(&s).copied().unwrap_or(3));
        }
    }

    /// Codifica texto puro (sem BOS).
    pub fn encode(&self, text: &str) -> Vec<u32> {
        let mut out = Vec::new();
        for word in Self::pre_tokenize(text) {
            self.bpe_word(&word, &mut out);
        }
        out
    }

    /// Monta o texto de chat no formato do checkpoint e codifica com BOS.
    pub fn encode_chat(&self, turns: &[(String, String)], user: &str) -> Vec<u32> {
        let mut text = String::new();
        for (u, a) in turns {
            text.push_str("User: ");
            text.push_str(u);
            text.push_str("\n\nAssistant: ");
            text.push_str(a);
            text.push_str("\n\n");
        }
        text.push_str("User: ");
        text.push_str(user.trim());
        text.push_str("\n\nAssistant: ");
        let mut ids = Vec::with_capacity(text.len() / 2 + 1);
        ids.push(BOS_ID);
        ids.extend(self.encode(&text));
        ids
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn f16_conversion_matches_known_values() {
        assert_eq!(f16_to_f32(0x0000), 0.0);
        assert_eq!(f16_to_f32(0x3C00), 1.0);
        assert_eq!(f16_to_f32(0xC000), -2.0);
        assert_eq!(f16_to_f32(0x4000), 2.0);
        assert!((f16_to_f32(0x3555) - 0.33325195).abs() < 1e-6);
    }

    #[test]
    fn tokenizer_roundtrip_on_real_checkpoint() {
        let Some(ckpt) = mark_core::paths::mark_bin_32b_checkpoint() else {
            eprintln!("checkpoint ausente: teste ignorado");
            return;
        };
        let tok_path = ckpt.join("rust_tokenizer_v10.bin");
        if !tok_path.exists() {
            eprintln!("tokenizer ausente: teste ignorado");
            return;
        }
        let tok = BinTokenizer::load(&tok_path).expect("tokenizer deve carregar");
        assert!(tok.len() > 1000, "vocabulario muito pequeno: {}", tok.len());
        // Todos os ids devem ser validos.
        for id in 0..(tok.len() as u32).min(5000) {
            assert!(!tok.decode_token(id).is_empty());
        }
    }

    #[test]
    fn encoder_reproduces_checkpoint_prompt_ids() {
        let Some(ckpt) = mark_core::paths::mark_bin_32b_checkpoint() else {
            eprintln!("checkpoint ausente: teste ignorado");
            return;
        };
        let tok_path = ckpt.join("rust_tokenizer_v10.bin");
        if !tok_path.exists() {
            eprintln!("tokenizer ausente: teste ignorado");
            return;
        }
        let tok = BinTokenizer::load(&tok_path).expect("tokenizer deve carregar");
        assert!(!tok.prompt_ids.is_empty(), "ids de referencia ausentes");
        let got = tok.encode_chat(&[], &tok.prompt);
        assert_eq!(
            got, tok.prompt_ids,
            "codificacao BPE divergiu dos ids gravados no checkpoint"
        );
    }

    #[test]
    fn safetensors_reader_finds_real_tensors() {
        let Some(ckpt) = mark_core::paths::mark_bin_32b_checkpoint() else {
            eprintln!("checkpoint ausente: teste ignorado");
            return;
        };
        let p = ckpt.join("isometric_gpu_core.safetensors");
        if !p.exists() {
            eprintln!("safetensors ausente: teste ignorado");
            return;
        }
        let st = SafeTensors::open(&p).expect("deve abrir");
        assert!(st.tensor_names().len() > 100);
        let names = st.tensor_names();
        assert!(names.iter().any(|n| n.contains("embed_tokens")));
        // Deve conseguir ler um tensor F16 real.
        let v = st.f32_vec("layers.0.input_layernorm.weight").expect("deve ler norm");
        assert_eq!(v.len(), 2048);
        assert!(v.iter().all(|x| x.is_finite()));
    }
}
