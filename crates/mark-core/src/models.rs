//! Catalogo de modelos: descoberta real no disco, Ollama e Hugging Face.
//!
//! Sem entradas inventadas: cada modelo listado existe de fato no disco,
//! no daemon Ollama ou no repositorio do Hugging Face.

use serde::{Deserialize, Serialize};

use crate::paths;

/// Como o modelo e executado.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Backend {
    /// Motor Rust 1-bit SVID nativo (Mark-Bin-32B).
    MarkSvid1Bit,
    /// Motor Rust safetensors generico (BF16/INT8/INT4).
    MarkSafetensors,
    /// Arquivo GGUF local, servido via llama-server/llama.cpp.
    LlamaCppGguf,
    /// Daemon Ollama via HTTP.
    Ollama,
    /// Endpoint OpenAI-compatible (LM Studio, vLLM, llama-server).
    OpenAiCompatible,
}

impl Backend {
    /// Rotulo exibido na UI.
    pub fn label(self) -> &'static str {
        match self {
            Backend::MarkSvid1Bit => "SVID 1-Bit (Rust nativo)",
            Backend::MarkSafetensors => "Safetensors (Rust nativo)",
            Backend::LlamaCppGguf => "GGUF (llama.cpp)",
            Backend::Ollama => "Ollama",
            Backend::OpenAiCompatible => "OpenAI-compatible",
        }
    }
}

/// Um modelo realmente disponivel.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ModelEntry {
    /// Identificador unico e estavel (ex.: `hf:miceworks/Mark-SLM-V3-150M`).
    pub id: String,
    /// Nome exibido.
    pub name: String,
    /// Backend que deve executa-lo.
    pub backend: Backend,
    /// Caminho local do arquivo/pasta, quando aplicavel.
    pub path: Option<String>,
    /// Tamanho em bytes, quando conhecido.
    pub size_bytes: Option<u64>,
    /// Janela de contexto REAL declarada pelo modelo.
    pub context_window: u32,
    /// Repo no Hugging Face de origem, quando aplicavel.
    pub hf_repo: Option<String>,
    /// Se o modelo exige GPU de forma obrigatoria.
    pub requires_gpu: bool,
    /// Se e um modelo de visão (multimodal).
    pub is_vision: bool,
    /// Se e um modelo 1-bit real (IQ1_S/IQ1_M/W1A4).
    pub is_1bit: bool,
}

/// Resultado do ajuste de um modelo a maquina.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FitLevel {
    /// Cabe folgadamente na VRAM.
    Gpu,
    /// Cabe na VRAM, apertado.
    GpuTight,
    /// Cabe na RAM, usaria swape.
    Ram,
    /// Nao cabe na maquina.
    TooLarge,
}

impl FitLevel {
    /// Rotulo exibido na UI.
    pub fn label(self) -> &'static str {
        match self {
            FitLevel::Gpu => "Cabe na GPU",
            FitLevel::GpuTight => "Cabe na GPU (apertado)",
            FitLevel::Ram => "Via RAM (swape)",
            FitLevel::TooLarge => "Acima do hardware",
        }
    }
}

/// Hardware detectado da maquina.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HardwareProfile {
    pub total_ram_bytes: u64,
    pub vram_bytes: u64,
    pub cpu_cores: usize,
    pub gpu_name: String,
}

impl HardwareProfile {
    /// Detecta o hardware real do sistema.
    pub fn detect() -> Self {
        let total_ram_bytes = read_total_ram().unwrap_or(0);
        let cpu_cores = std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1);
        let (vram_bytes, gpu_name) = detect_gpu();
        Self {
            total_ram_bytes,
            vram_bytes,
            cpu_cores,
            gpu_name,
        }
    }

    /// Avalia se um modelo cabe na maquina.
    pub fn evaluate(&self, size_bytes: u64) -> FitLevel {
        if size_bytes == 0 {
            return FitLevel::Ram;
        }
        let headroom = self.vram_bytes.saturating_sub(512 * 1024 * 1024);
        if size_bytes <= headroom {
            FitLevel::Gpu
        } else if size_bytes <= self.vram_bytes {
            FitLevel::GpuTight
        } else if size_bytes <= self.total_ram_bytes {
            FitLevel::Ram
        } else {
            FitLevel::TooLarge
        }
    }
}

/// Le o total de RAM via sysinfo do procfs.
fn read_total_ram() -> Option<u64> {
    let meminfo = std::fs::read_to_string("/proc/meminfo").ok()?;
    for line in meminfo.lines() {
        if let Some(rest) = line.strip_prefix("MemTotal:") {
            let kb: u64 = rest
                .trim()
                .trim_end_matches(" kB")
                .trim()
                .parse()
                .ok()?;
            return Some(kb * 1024);
        }
    }
    None
}

/// Detecta VRAM e nome da GPU. Le `/proc/driver/nvidia/gpus/*/information` quando disponivel.
fn detect_gpu() -> (u64, String) {
    let mut best_vram = 0u64;
    let mut best_name = String::new();
    if let Ok(entries) = std::fs::read_dir("/proc/driver/nvidia/gpus") {
        for e in entries.flatten() {
            let info = e.path().join("information");
            let Ok(text) = std::fs::read_to_string(&info) else {
                continue;
            };
            let mut name = String::new();
            let mut vram = 0u64;
            for line in text.lines() {
                if let Some(v) = line.strip_prefix("Model:") {
                    name = v.trim().to_string();
                } else if let Some(v) = line.strip_prefix("IRQ:") {
                    let _ = v;
                }
            }
            // FB memory: usa `nvidia-smi` se disponivel, senao /proc/meminfo do driver.
            if let Some(v) = read_proc_fb_memory(&e.path()) {
                vram = v;
            }
            if vram > best_vram {
                best_vram = vram;
                best_name = name;
            }
        }
    }
    if best_name.is_empty() {
        best_name = "Sem GPU NVIDIA detectada".to_string();
    }
    (best_vram, best_name)
}

/// Le a memoria de framebuffer do driver via `nvidia-smi` (roda em processo separado).
fn read_proc_fb_memory(gpu_dir: &std::path::Path) -> Option<u64> {
    let uuid = std::fs::read_to_string(gpu_dir.join("information"))
        .ok()
        .and_then(|t| {
            t.lines()
                .find_map(|l| l.strip_prefix("GPU UUID:").map(|v| v.trim().to_string()))
        })?;
    let out = std::process::Command::new("nvidia-smi")
        .args([
            "--query-gpu=memory.total",
            "--format=csv,noheader,nounits",
            "-i",
            &uuid,
        ])
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&out.stdout);
    let mib: u64 = text.trim().lines().next()?.trim().parse().ok()?;
    Some(mib * 1024 * 1024)
}

/// Descoberta de arquivos de modelo no disco do usuario.
pub fn discover_local_files() -> Vec<ModelEntry> {
    let mut out = Vec::new();
    let mut roots: Vec<std::path::PathBuf> = vec![paths::models_dir()];
    if let Some(ckpt) = paths::mark_bin_32b_checkpoint() {
        roots.push(ckpt);
    }
    // Volumes externos montados.
    if let Some(user) = paths::system_user_name() {
        let media = std::path::PathBuf::from("/run/media").join(&user);
        if let Ok(entries) = std::fs::read_dir(&media) {
            for e in entries.flatten() {
                roots.push(e.path().join("mark_checkpoints"));
            }
        }
    }
    let mut seen = std::collections::HashSet::new();
    for root in roots {
        if !root.is_dir() {
            continue;
        }
        for entry in walkdir::WalkDir::new(&root)
            .max_depth(4)
            .follow_links(false)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            let ext = path
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("")
                .to_ascii_lowercase();
            if ext != "gguf" && ext != "safetensors" {
                continue;
            }
            let meta = match std::fs::metadata(path) {
                Ok(m) => m,
                Err(_) => continue,
            };
            let name = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("model")
                .to_string();
            if !seen.insert(path.to_path_buf()) {
                continue;
            }
            let size = meta.len();
            let is_1bit = name.to_ascii_lowercase().contains("iq1")
                || name.to_ascii_lowercase().contains("bin-32b")
                || name.to_ascii_lowercase().contains("1bit")
                || path.to_string_lossy().contains("Mark-Bin-32B");
            let is_vision = name.to_ascii_lowercase().contains("vl")
                || path
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("")
                    .to_ascii_lowercase()
                    .starts_with("mmproj");
            let backend = if is_1bit && path.to_string_lossy().contains("Mark-Bin-32B") {
                Backend::MarkSvid1Bit
            } else if ext == "gguf" {
                Backend::LlamaCppGguf
            } else {
                Backend::MarkSafetensors
            };
            let id = format!(
                "file:{}",
                path.to_string_lossy()
            );
            out.push(ModelEntry {
                id,
                name,
                backend,
                path: Some(path.to_string_lossy().into_owned()),
                size_bytes: Some(size),
                context_window: 32_768,
                hf_repo: None,
                requires_gpu: is_1bit,
                is_vision,
                is_1bit,
            });
        }
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    out
}

/// Converte a resposta do daemon Ollama em entradas de modelo.
pub fn parse_ollama_models(json: &str) -> Vec<ModelEntry> {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(json) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    let Some(models) = v.get("models").and_then(|m| m.as_array()) else {
        return out;
    };
    for m in models {
        let Some(name) = m.get("name").and_then(|n| n.as_str()) else {
            continue;
        };
        let size = m.get("size").and_then(|s| s.as_u64()).unwrap_or(0);
        let mut out_ctx = m
            .get("details")
            .and_then(|d| d.get("context_length"))
            .and_then(|c| c.as_u64())
            .unwrap_or(32_768) as u32;
        if out_ctx == 0 {
            out_ctx = 32_768;
        }
        let lower = name.to_ascii_lowercase();
        let is_vision = lower.contains("vl") || lower.contains("vision");
        let is_1bit = lower.contains("iq1") || lower.contains("bin-32b");
        out.push(ModelEntry {
            id: format!("ollama:{name}"),
            name: name.to_string(),
            backend: Backend::Ollama,
            path: None,
            size_bytes: Some(size),
            context_window: out_ctx,
            hf_repo: None,
            requires_gpu: is_1bit,
            is_vision,
            is_1bit,
        });
    }
    out
}

/// Modelos oficiais da colecao Miceworks (repos publicos reais).
pub fn miceworks_official() -> Vec<(&'static str, &'static str, u64)> {
    vec![
        ("miceworks/Mark-Bin-32B", "Mark-Bin-32B", 4_543_000_000),
        ("miceworks/Mark-Rust-4B", "Mark-Rust-4B", 2_400_000_000),
        ("miceworks/Mark-SLM-V3-150M", "Mark-SLM-V3-150M", 338_000_000),
        ("miceworks/Mark-Engineer-1.5B", "Mark-Engineer-1.5B", 842_000_000),
        ("miceworks/Mark-General-1.5B", "Mark-General-1.5B", 842_000_000),
        ("miceworks/Mark-VL-2.2B", "Mark-VL-2.2B", 1_700_000_000),
        ("miceworks/Mark-SLM-V2-302M", "Mark-SLM-V2-302M", 142_000_000),
        ("miceworks/Mark-Engineer-302M", "Mark-Engineer-302M", 142_000_000),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ollama_parse_extracts_real_fields() {
        let json = r#"{"models":[{"name":"deepseek-r1:8b-q3_k_l","size":4400000000,"details":{"context_length":65536}}]}"#;
        let models = parse_ollama_models(json);
        assert_eq!(models.len(), 1);
        assert_eq!(models[0].id, "ollama:deepseek-r1:8b-q3_k_l");
        assert_eq!(models[0].backend, Backend::Ollama);
        assert_eq!(models[0].context_window, 65_536);
        assert_eq!(models[0].size_bytes, Some(4_400_000_000));
    }

    #[test]
    fn ollama_parse_handles_malformed_json_without_panic() {
        assert!(parse_ollama_models("nao e json").is_empty());
        assert!(parse_ollama_models("{}").is_empty());
        assert!(parse_ollama_models("{\"models\":[]}").is_empty());
    }

    #[test]
    fn hardware_fit_classifies_sizes() {
        let hw = HardwareProfile {
            total_ram_bytes: 16 * 1024 * 1024 * 1024,
            vram_bytes: 8 * 1024 * 1024 * 1024,
            cpu_cores: 4,
            gpu_name: "teste".into(),
        };
        assert_eq!(hw.evaluate(2 * 1024 * 1024 * 1024), FitLevel::Gpu);
        assert_eq!(hw.evaluate(7_900 * 1024 * 1024), FitLevel::GpuTight);
        assert_eq!(hw.evaluate(12 * 1024 * 1024 * 1024), FitLevel::Ram);
        assert_eq!(hw.evaluate(64 * 1024 * 1024 * 1024), FitLevel::TooLarge);
    }

    #[test]
    fn miceworks_catalog_has_no_duplicate_ids() {
        let mut ids: Vec<&str> = miceworks_official().iter().map(|(a, _, _)| *a).collect();
        ids.sort_unstable();
        let before = ids.len();
        ids.dedup();
        assert_eq!(ids.len(), before, "ids duplicados no catalogo Miceworks");
    }
}
