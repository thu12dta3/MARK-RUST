//! Runner do Modo Engineer: executa acoes reais no sandbox bwrap e reporta JSON.
//!
//! Tambem expoe o indice de skills do Hermes e as buscas web, para que a UI
//! PyQt6 tenha acesso real as 106 skills, aos MCPs e a Internet.

use std::path::PathBuf;

use anyhow::{bail, Result};
use mark_tools::engineer::{Action, ApprovalMode, EngineerSession};
use mark_tools::skills::load_skills;
use mark_tools::web::{web_fetch_blocking, web_search_blocking};
use serde_json::json;

struct Args {
    approval: ApprovalMode,
    workspace: PathBuf,
    list_skills: bool,
    web_search: Option<String>,
    web_fetch: Option<String>,
    limit: usize,
    hw_profile: bool,
    sentinel_scan: Option<String>,
    sentinel_delete: Option<String>,
    threat: Option<String>,
}

fn parse_args() -> Result<Args> {
    let mut args = Args {
        approval: ApprovalMode::Suggest,
        workspace: mark_core::paths::default_workspace(),
        list_skills: false,
        web_search: None,
        web_fetch: None,
        limit: 5,
        hw_profile: false,
        sentinel_scan: None,
        sentinel_delete: None,
        threat: None,
    };
    let mut raw = std::env::args().skip(1);
    while let Some(flag) = raw.next() {
        match flag.as_str() {
            "--approval" => {
                let value = raw.next().unwrap_or_default();
                args.approval = match value.as_str() {
                    "auto-edit" | "auto_edit" | "AutoEdit" => ApprovalMode::AutoEdit,
                    "full-auto" | "full_auto" | "FullAuto" => ApprovalMode::FullAuto,
                    _ => ApprovalMode::Suggest,
                };
            }
            "--workspace" => {
                args.workspace = raw.next().map(PathBuf::from).unwrap_or(args.workspace);
            }
            "--list-skills" => args.list_skills = true,
            "--hw-profile" => args.hw_profile = true,
            "--sentinel-scan" => args.sentinel_scan = raw.next(),
            "--sentinel-delete" => args.sentinel_delete = raw.next(),
            "--threat" => args.threat = raw.next(),
            "--web-search" => args.web_search = raw.next(),
            "--web-fetch" => args.web_fetch = raw.next(),
            "--limit" => {
                let value = raw.next().unwrap_or_default();
                args.limit = value.parse().unwrap_or(5);
            }
            "--json" => {}
            other => bail!("flag desconhecida: {other}"),
        }
    }
    Ok(args)
}

fn skills_payload() -> serde_json::Value {
    let root = mark_core::paths::hermes_skills_dir();
    let skills = load_skills(&root);
    let items: Vec<serde_json::Value> = skills
        .iter()
        .map(|skill| {
            json!({
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "dir": skill.dir.to_string_lossy().into_owned(),
            })
        })
        .collect();
    json!({
        "ok": true,
        "root": root.to_string_lossy().into_owned(),
        "count": items.len(),
        "skills": items,
    })
}


fn run_cmd(program: &str, args: &[&str]) -> Option<String> {
    let output = std::process::Command::new(program).args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn cpu_payload() -> serde_json::Value {
    let cpuinfo = std::fs::read_to_string("/proc/cpuinfo").unwrap_or_default();
    let mut model = String::from("unknown");
    let mut flags = String::new();
    let mut cores = 0u32;
    for line in cpuinfo.lines() {
        if let Some((key, value)) = line.split_once(':') {
            let key = key.trim();
            let value = value.trim();
            if key == "model name" && model == "unknown" {
                model = value.to_string();
            } else if key == "flags" {
                flags = value.to_string();
            } else if key == "cpu cores" {
                cores = value.parse().unwrap_or(cores);
            }
        }
    }
    let threads = std::thread::available_parallelism()
        .map(|value| value.get())
        .unwrap_or(0);
    let has_flag = |needle: &str| flags.split_whitespace().any(|flag| flag == needle);
    serde_json::json!({
        "model": model,
        "cores": cores,
        "threads": threads,
        "avx2": has_flag("avx2"),
        "fma": has_flag("fma"),
        "popcnt": has_flag("popcnt"),
    })
}

fn memory_payload() -> serde_json::Value {
    let meminfo = std::fs::read_to_string("/proc/meminfo").unwrap_or_default();
    let read_kib = |key: &str| -> f64 {
        meminfo
            .lines()
            .find_map(|line| {
                let (name, rest) = line.split_once(':')?;
                if name.trim() == key {
                    rest.split_whitespace().next()?.parse::<f64>().ok()
                } else {
                    None
                }
            })
            .unwrap_or(0.0)
    };
    let total_gib = read_kib("MemTotal") / 1024.0 / 1024.0;
    let available_gib = read_kib("MemAvailable") / 1024.0 / 1024.0;
    serde_json::json!({
        "total_gib": (total_gib * 10.0).round() / 10.0,
        "available_gib": (available_gib * 10.0).round() / 10.0,
        "tmp_is_tmpfs": std::fs::read_to_string("/proc/mounts")
            .map(|mounts| mounts.lines().any(|line| {
                let mut parts = line.split_whitespace();
                let _device = parts.next();
                let mount = parts.next().unwrap_or("");
                let fstype = parts.next().unwrap_or("");
                mount == "/tmp" && fstype == "tmpfs"
            }))
            .unwrap_or(false),
    })
}

fn gpu_payload() -> serde_json::Value {
    let attempts: [&[&str]; 3] = [
        &["--query-gpu=name,memory.total,compute_cap,driver_version", "--format=csv,noheader,nounits"],
        &["--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
        &["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
    ];
    for args in attempts {
        let Some(line) = run_cmd("nvidia-smi", args) else {
            continue;
        };
        if line.is_empty() {
            continue;
        }
        let fields: Vec<&str> = line.lines().next().unwrap_or("").split(',').map(|f| f.trim()).collect();
        let mib: f64 = fields.get(1).and_then(|v| v.parse().ok()).unwrap_or(0.0);
        let capability = fields
            .iter()
            .find(|field| field.contains('.'))
            .map(|field| format!("sm_{}", field.replace('.', "")))
            .unwrap_or_else(|| "unknown".to_string());
        let driver = fields
            .iter()
            .find(|field| field.parse::<f64>().is_ok() && field.contains('.') && !field.starts_with('8'))
            .copied()
            .unwrap_or("");
        return serde_json::json!({
            "name": fields.first().copied().unwrap_or("unknown"),
            "vram_gib": ((mib / 1024.0) * 10.0).round() / 10.0,
            "compute_capability": capability,
            "driver": driver,
            "cuda": true,
        });
    }
    // NVML pode falhar (driver/userspace divergentes); o modulo do kernel expoe o modelo.
    let mut model = String::new();
    if let Ok(entries) = std::fs::read_dir("/proc/driver/nvidia/gpus") {
        for entry in entries.flatten() {
            let info = entry.path().join("information");
            if let Ok(text) = std::fs::read_to_string(info) {
                for line in text.lines() {
                    if let Some(value) = line.strip_prefix("Model:") {
                        model = value.trim().to_string();
                    }
                }
            }
        }
    }
    let driver = std::fs::read_to_string("/proc/driver/nvidia/version")
        .ok()
        .and_then(|text| text.lines().next().map(|line| line.trim().to_string()))
        .unwrap_or_default();
    serde_json::json!({
        "name": if model.is_empty() { "none".to_string() } else { model },
        "vram_gib": serde_json::Value::Null,
        "compute_capability": "sm_75",
        "driver": driver,
        "cuda": false,
        "nvml_error": "nvidia-smi unavailable",
    })
}

fn disk_payload() -> serde_json::Value {
    let raw = run_cmd("df", &["-B1", "-x", "tmpfs", "-x", "devtmpfs"]).unwrap_or_default();
    let mut disks: Vec<serde_json::Value> = Vec::new();
    for line in raw.lines().skip(1) {
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.len() < 6 {
            continue;
        }
        let total: u64 = fields[1].parse().unwrap_or(0);
        if total < 1024 * 1024 * 1024 {
            continue;
        }
        disks.push(serde_json::json!({
            "device": fields[0],
            "mount": fields[5],
            "total_gib": ((total as f64 / 1_073_741_824.0) * 10.0).round() / 10.0,
            "free_gib": ((fields[3].parse::<u64>().unwrap_or(0) as f64 / 1_073_741_824.0) * 10.0).round() / 10.0,
            "external": fields[5].starts_with("/run/media"),
        }));
    }
    serde_json::json!(disks)
}

fn toolchains_payload() -> serde_json::Value {
    let probe = |name: &str, args: &[&str]| -> String {
        run_cmd(name, args).unwrap_or_default().lines().next().unwrap_or("").to_string()
    };
    serde_json::json!({
        "rustc": probe("rustc", &["--version"]),
        "cargo": probe("cargo", &["--version"]),
        "gcc": probe("gcc", &["--version"]),
        "python": probe("python3", &["--version"]),
        "bwrap": probe("bwrap", &["--version"]),
        "clamscan": probe("clamscan", &["--version"]),
    })
}

fn hardware_payload(register: bool) -> anyhow::Result<serde_json::Value> {
    let profile = serde_json::json!({
        "ok": true,
        "generated_at": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0),
        "cpu": cpu_payload(),
        "memory": memory_payload(),
        "gpu": gpu_payload(),
        "disks": disk_payload(),
        "toolchains": toolchains_payload(),
    });
    let mut payload = profile;
    if register {
        let path = mark_core::paths::config_dir().join("hardware_profile.json");
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&path, serde_json::to_string_pretty(&payload)?)?;
        payload["path"] = serde_json::Value::String(path.to_string_lossy().into_owned());
    }
    Ok(payload)
}

fn sha256_of(path: &std::path::Path) -> String {
    run_cmd("sha256sum", &[&path.to_string_lossy()])
        .and_then(|line| line.split_whitespace().next().map(|value| value.to_string()))
        .unwrap_or_default()
}

fn sentinel_scan(target: &str) -> anyhow::Result<serde_json::Value> {
    let root = std::path::Path::new(target);
    if !root.exists() {
        return Ok(serde_json::json!({"ok": false, "message": format!("caminho inexistente: {target}")}));
    }
    // Estritamente somente-leitura: --no-summary, nunca --remove.
    let output = std::process::Command::new("clamscan")
        .args(["--no-summary", "-r", target])
        .output();
    let mut infected: Vec<serde_json::Value> = Vec::new();
    let mut scanned = 0u32;
    let mut engine = "clamscan".to_string();
    match output {
        Ok(result) => {
            let text = format!(
                "{}{}",
                String::from_utf8_lossy(&result.stdout),
                String::from_utf8_lossy(&result.stderr)
            );
            for line in text.lines() {
                if let Some((file, rest)) = line.rsplit_once(": ") {
                    if rest.ends_with("FOUND") {
                        let threat = rest.trim_end_matches("FOUND").trim().to_string();
                        let path = std::path::Path::new(file);
                        infected.push(serde_json::json!({
                            "path": file,
                            "threat": threat,
                            "size": std::fs::metadata(path).map(|meta| meta.len()).unwrap_or(0),
                            "sha256": sha256_of(path),
                        }));
                        scanned += 1;
                    } else if rest.contains("OK") {
                        scanned += 1;
                    }
                }
            }
        }
        Err(_) => {
            engine = "unavailable".to_string();
        }
    }
    Ok(serde_json::json!({
        "ok": engine != "unavailable",
        "engine": engine,
        "read_only": true,
        "removed": 0,
        "scanned": scanned,
        "threats": infected.len(),
        "infected": infected,
        "message": if engine == "unavailable" { "clamscan nao encontrado no PATH" } else { "" },
    }))
}

fn sentinel_delete(target: &str, threat: &str) -> anyhow::Result<serde_json::Value> {
    let path = std::path::PathBuf::from(target);
    if !path.is_file() {
        return Ok(serde_json::json!({"ok": false, "message": "arquivo nao encontrado"}));
    }
    let digest = sha256_of(&path);
    std::fs::remove_file(&path)?;
    let audit_dir = mark_core::paths::state_dir();
    std::fs::create_dir_all(&audit_dir)?;
    let audit = audit_dir.join("sentinel_audit.log");
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let line = format!("{stamp}\tdeleted\t{target}\t{threat}\t{digest}\tauthorized-by-user\n");
    use std::io::Write;
    let mut handle = std::fs::OpenOptions::new().create(true).append(true).open(&audit)?;
    handle.write_all(line.as_bytes())?;
    Ok(serde_json::json!({
        "ok": true,
        "removed": true,
        "sha256": digest,
        "audit": audit.to_string_lossy(),
    }))
}

fn main() -> Result<()> {
    let args = parse_args()?;
    if args.hw_profile {
        println!("{}", hardware_payload(true)?);
        return Ok(());
    }
    if let Some(target) = &args.sentinel_scan {
        println!("{}", sentinel_scan(target)?);
        return Ok(());
    }
    if let Some(target) = &args.sentinel_delete {
        let threat = args.threat.clone().unwrap_or_else(|| "unknown".to_string());
        println!("{}", sentinel_delete(target, &threat)?);
        return Ok(());
    }
    if args.list_skills {
        println!("{}", skills_payload());
        return Ok(());
    }
    if let Some(query) = &args.web_search {
        let hits = web_search_blocking(query, args.limit)?;
        let payload = json!({
            "ok": true,
            "query": query,
            "hits": hits
                .iter()
                .map(|hit| json!({"title": hit.title, "url": hit.url, "snippet": hit.snippet}))
                .collect::<Vec<_>>(),
        });
        println!("{payload}");
        return Ok(());
    }
    if let Some(url) = &args.web_fetch {
        let page = web_fetch_blocking(url, 60_000)?;
        let payload = json!({
            "ok": true,
            "url": page.url,
            "title": page.title,
            "text": page.text,
        });
        println!("{payload}");
        return Ok(());
    }

    let mut raw = String::new();
    std::io::Read::read_to_string(&mut std::io::stdin(), &mut raw)?;
    let value: serde_json::Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!({}));
    let action = Action::from_json(&value)?;
    let mut session = EngineerSession::new(args.workspace.clone(), args.approval);
    let outcome = session.execute(action)?;
    let payload = json!({
        "ok": true,
        "approval": format!("{:?}", args.approval),
        "workspace": args.workspace.to_string_lossy().into_owned(),
        "outcome": format!("{outcome:?}"),
        "transcript": session.transcript(),
    });
    println!("{payload}");
    Ok(())
}
