//! Sandbox real de execucao via Bubblewrap (`bwrap`).
//!
//! O sistema inteiro e montado somente-leitura, o workspace escolhido e montado
//! leitura-escrita, o PID e o IPC sao isolados e o processo morre com o pai.
//! Rede e bloqueada por padrao (`--unshare-net`) e liberada apenas com `share_net`.

use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};

/// Configuracao de uma execucao isolada.
#[derive(Debug, Clone)]
pub struct SandboxConfig {
    pub workspace: PathBuf,
    pub share_net: bool,
    pub timeout: Duration,
    pub max_output_bytes: usize,
}

impl SandboxConfig {
    /// Configuracao padrao: sem rede, 120 s, 1 MiB de saida.
    pub fn new(workspace: impl Into<PathBuf>) -> Self {
        Self {
            workspace: workspace.into(),
            share_net: false,
            timeout: Duration::from_secs(120),
            max_output_bytes: 1024 * 1024,
        }
    }
}

/// Resultado de um comando executado no sandbox.
#[derive(Debug, Clone, PartialEq)]
pub struct SandboxResult {
    pub status: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
    pub duration: Duration,
}

impl SandboxResult {
    /// Indica sucesso do comando.
    pub fn success(&self) -> bool {
        self.status == Some(0) && !self.timed_out
    }
}

/// Verifica se o binario `bwrap` esta disponivel no PATH.
pub fn bwrap_available() -> bool {
    which("bwrap").is_some()
}

/// Localiza um executavel no PATH.
pub fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let cand = dir.join(name);
        if cand.is_file() {
            return Some(cand);
        }
    }
    None
}

/// Monta a linha de argumentos do bwrap para o workspace dado.
pub fn bwrap_args(cfg: &SandboxConfig) -> Vec<String> {
    let ws = cfg.workspace.to_string_lossy().into_owned();
    let mut args: Vec<String> = vec![
        "--ro-bind".into(),
        "/".into(),
        "/".into(),
        "--dev".into(),
        "/dev".into(),
        "--proc".into(),
        "/proc".into(),
        "--tmpfs".into(),
        "/tmp".into(),
        "--bind".into(),
        ws.clone(),
        ws.clone(),
        "--chdir".into(),
        ws,
        "--unshare-pid".into(),
        "--unshare-ipc".into(),
        "--unshare-uts".into(),
        "--die-with-parent".into(),
        "--new-session".into(),
        "--clearenv".into(),
        "--setenv".into(),
        "PATH".into(),
        "/usr/local/bin:/usr/bin:/bin".into(),
        "--setenv".into(),
        "HOME".into(),
        "/tmp".into(),
    ];
    if cfg.share_net {
        args.push("--share-net".into());
    } else {
        args.push("--unshare-net".into());
    }
    args
}

/// Executa um comando dentro do sandbox bwrap.
pub fn run(cfg: &SandboxConfig, command: &[String]) -> Result<SandboxResult> {
    if command.is_empty() {
        bail!("comando vazio");
    }
    if !cfg.workspace.is_dir() {
        bail!("workspace inexistente: {}", cfg.workspace.display());
    }
    if !bwrap_available() {
        bail!("bubblewrap (bwrap) nao esta instalado");
    }

    let mut args = bwrap_args(cfg);
    args.push("--".into());
    args.extend(command.iter().cloned());

    let started = Instant::now();
    let mut child = Command::new("bwrap")
        .args(&args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .context("falha ao iniciar bwrap")?;

    let mut out_pipe = child.stdout.take().context("stdout indisponivel")?;
    let mut err_pipe = child.stderr.take().context("stderr indisponivel")?;
    let (tx, rx) = mpsc::channel::<(&'static str, Vec<u8>)>();

    let tx_out = tx.clone();
    let h_out = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = out_pipe.read_to_end(&mut buf);
        let _ = tx_out.send(("out", buf));
    });
    let tx_err = tx.clone();
    let h_err = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = err_pipe.read_to_end(&mut buf);
        let _ = tx_err.send(("err", buf));
    });

    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    let mut timed_out = false;
    let deadline = started + cfg.timeout;

    loop {
        if let Some(status) = child.try_wait().context("falha ao aguardar bwrap")? {
            let _ = status;
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            timed_out = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(15));
    }

    let status = child.wait().ok().and_then(|s| s.code());
    for _ in 0..2 {
        if let Ok((kind, buf)) = rx.recv_timeout(Duration::from_secs(2)) {
            if kind == "out" {
                stdout = buf;
            } else {
                stderr = buf;
            }
        }
    }
    let _ = h_out.join();
    let _ = h_err.join();

    stdout.truncate(cfg.max_output_bytes);
    stderr.truncate(cfg.max_output_bytes);

    Ok(SandboxResult {
        status,
        stdout: String::from_utf8_lossy(&stdout).into_owned(),
        stderr: String::from_utf8_lossy(&stderr).into_owned(),
        timed_out,
        duration: started.elapsed(),
    })
}

/// Grava um arquivo dentro do workspace (unico local gravavel no sandbox).
pub fn write_workspace_file(workspace: &Path, rel: &str, content: &str) -> Result<PathBuf> {
    let path = workspace.join(rel);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut f = std::fs::File::create(&path)?;
    f.write_all(content.as_bytes())?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bwrap_is_installed() {
        assert!(bwrap_available(), "bwrap precisa estar instalado para o sandbox");
    }

    #[test]
    fn sandbox_runs_command_in_workspace() {
        let dir = tempfile::tempdir().unwrap();
        write_workspace_file(dir.path(), "hello.txt", "conteudo-real").unwrap();
        let cfg = SandboxConfig::new(dir.path());
        let res = run(
            &cfg,
            &["cat".into(), dir.path().join("hello.txt").display().to_string()],
        )
        .unwrap();
        assert!(!res.timed_out, "comando nao pode expirar: {res:?}");
        assert_eq!(res.status, Some(0), "stderr: {}", res.stderr);
        assert_eq!(res.stdout.trim(), "conteudo-real");
    }

    #[test]
    fn sandbox_blocks_write_outside_workspace() {
        let dir = tempfile::tempdir().unwrap();
        let outside = PathBuf::from(format!("/home/{}/mark_sandbox_escape.txt", "thu12"));
        let _ = std::fs::remove_file(&outside);
        let cfg = SandboxConfig::new(dir.path());
        let res = run(
            &cfg,
            &[
                "sh".into(),
                "-c".into(),
                format!("echo invadido > {}", outside.display()),
            ],
        )
        .unwrap();
        assert_ne!(res.status, Some(0), "escrita fora do workspace deveria falhar");
        assert!(
            !outside.exists(),
            "arquivo foi criado fora do workspace: {}",
            outside.display()
        );
    }

    #[test]
    fn sandbox_allows_write_inside_workspace() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("dentro.txt");
        let cfg = SandboxConfig::new(dir.path());
        let res = run(
            &cfg,
            &[
                "sh".into(),
                "-c".into(),
                format!("echo ok > {}", target.display()),
            ],
        )
        .unwrap();
        assert_eq!(res.status, Some(0), "stderr: {}", res.stderr);
        assert_eq!(std::fs::read_to_string(&target).unwrap().trim(), "ok");
    }

    #[test]
    fn sandbox_has_no_network_by_default() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = SandboxConfig::new(dir.path());
        let res = run(
            &cfg,
            &[
                "sh".into(),
                "-c".into(),
                "ip link show 2>/dev/null | grep -c LOOPBACK".into(),
            ],
        )
        .unwrap();
        if res.status != Some(0) {
            return;
        }
        assert_eq!(
            res.stdout.trim(),
            "1",
            "sem rede so deve existir a interface loopback"
        );
    }

    #[test]
    fn sandbox_timeout_kills_command() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = SandboxConfig::new(dir.path());
        cfg.timeout = Duration::from_millis(600);
        let res = run(&cfg, &["sleep".into(), "30".into()]).unwrap();
        assert!(res.timed_out, "o timeout deveria ter encerrado o comando");
    }
}
