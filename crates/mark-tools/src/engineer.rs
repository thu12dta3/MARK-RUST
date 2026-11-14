//! Modo Engineer: loop agentico com leitura, grep, patch, shell e testes.
//!
//! Cada acao e executada de verdade. `Suggest` nunca escreve nem executa;
//! `AutoEdit` aplica edicoes e exige aprovacao para shell; `FullAuto` executa
//! tudo dentro do sandbox bwrap.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use regex::Regex;
use serde_json::Value;

use crate::sandbox::{self, SandboxConfig, SandboxResult};

/// Tipo de acao do loop agentico.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActionKind {
    Plan,
    Read,
    Grep,
    Write,
    ApplyPatch,
    Shell,
    Test,
}

impl ActionKind {
    /// Converte o rotulo textual vindo do modelo.
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "plan" => Some(ActionKind::Plan),
            "read" | "inspect" => Some(ActionKind::Read),
            "grep" | "search" => Some(ActionKind::Grep),
            "write" => Some(ActionKind::Write),
            "apply_patch" | "patch" | "diff" => Some(ActionKind::ApplyPatch),
            "shell" | "exec" | "exec_command" => Some(ActionKind::Shell),
            "test" => Some(ActionKind::Test),
            _ => None,
        }
    }

    /// Indica se a acao altera o workspace.
    pub fn mutates(self) -> bool {
        matches!(
            self,
            ActionKind::Write | ActionKind::ApplyPatch | ActionKind::Shell | ActionKind::Test
        )
    }
}

/// Uma acao pedida pelo modelo.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Action {
    pub kind: ActionKind,
    pub path: Option<String>,
    pub query: Option<String>,
    pub content: Option<String>,
    pub command: Vec<String>,
}

impl Action {
    /// Interpreta a acao a partir do JSON devolvido pelo modelo.
    pub fn from_json(v: &Value) -> Result<Self> {
        let kind_s = v
            .get("action")
            .or_else(|| v.get("kind"))
            .and_then(|a| a.as_str())
            .context("acao sem o campo 'action'")?;
        let kind = ActionKind::parse(kind_s)
            .with_context(|| format!("acao desconhecida: {kind_s}"))?;
        let command = match v.get("command") {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|i| i.as_str().map(|s| s.to_string()))
                .collect(),
            Some(Value::String(s)) => vec!["sh".to_string(), "-c".to_string(), s.clone()],
            _ => Vec::new(),
        };
        Ok(Self {
            kind,
            path: v.get("path").and_then(|p| p.as_str()).map(|s| s.to_string()),
            query: v.get("query").and_then(|p| p.as_str()).map(|s| s.to_string()),
            content: v
                .get("content")
                .or_else(|| v.get("patch"))
                .and_then(|p| p.as_str())
                .map(|s| s.to_string()),
            command,
        })
    }
}

/// Resultado de um passo do loop.
#[derive(Debug, Clone, PartialEq)]
pub enum StepOutcome {
    /// Texto de plano ou explicacao.
    Text(String),
    /// Conteudo lido de um arquivo.
    FileText { path: String, content: String },
    /// Linhas que casaram com o padrao.
    Matches(Vec<(usize, String)>),
    /// Edicao proposta: diff renderizado, sem tocar no disco.
    ProposedDiff { path: String, preview: String },
    /// Arquivo gravado, com o diff aplicado.
    Written { path: String, preview: String },
    /// Comando executado no sandbox.
    Command(SandboxResult),
    /// Acao bloqueada aguardando aprovacao humana.
    NeedsApproval { reason: String },
}

/// Politica de aprovacao, identica em fluxo ao codex.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApprovalMode {
    Suggest,
    AutoEdit,
    FullAuto,
}

/// Sessao do Modo Engineer sobre um workspace.
pub struct EngineerSession {
    workspace: PathBuf,
    pub approval: ApprovalMode,
    sandbox: SandboxConfig,
    transcript: Vec<String>,
    shell_approved: bool,
}

impl EngineerSession {
    /// Cria uma sessao para o workspace informado.
    pub fn new(workspace: impl Into<PathBuf>, approval: ApprovalMode) -> Self {
        let workspace = workspace.into();
        let mut sandbox = SandboxConfig::new(workspace.clone());
        sandbox.timeout = std::time::Duration::from_secs(180);
        Self {
            workspace,
            approval,
            sandbox,
            transcript: Vec::new(),
            shell_approved: false,
        }
    }

    /// Workspace da sessao.
    pub fn workspace(&self) -> &Path {
        &self.workspace
    }

    /// Permite rede dentro do sandbox.
    pub fn set_share_net(&mut self, share_net: bool) {
        self.sandbox.share_net = share_net;
    }

    /// Define o timeout dos comandos do sandbox.
    pub fn set_timeout(&mut self, secs: u64) {
        self.sandbox.timeout = std::time::Duration::from_secs(secs.max(1));
    }

    /// Historico de passos executados.
    pub fn transcript(&self) -> &[String] {
        &self.transcript
    }

    /// Aprova a proxima execucao de shell do modo AutoEdit.
    pub fn approve_shell(&mut self) {
        self.shell_approved = true;
    }

    fn resolve(&self, rel: &str) -> Result<PathBuf> {
        if rel.trim().is_empty() {
            bail!("caminho vazio");
        }
        let p = Path::new(rel);
        if p.components().any(|c| matches!(c, std::path::Component::ParentDir)) {
            bail!("path traversal bloqueado: {rel}");
        }
        let root = self
            .workspace
            .canonicalize()
            .with_context(|| format!("workspace invalido: {}", self.workspace.display()))?;
        let full = if p.is_absolute() {
            p.to_path_buf()
        } else {
            root.join(p)
        };
        let checked = match full.canonicalize() {
            Ok(c) => c,
            Err(_) => {
                let parent = full.parent().unwrap_or(&root).canonicalize()?;
                parent.join(full.file_name().unwrap_or_default())
            }
        };
        if !checked.starts_with(&root) {
            bail!("caminho fora do workspace: {}", full.display());
        }
        Ok(checked)
    }

    /// Executa uma acao e devolve o resultado do passo.
    pub fn execute(&mut self, action: Action) -> Result<StepOutcome> {
        match action.kind {
            ActionKind::Plan => Ok(StepOutcome::Text(
                action.content.unwrap_or_default(),
            )),
            ActionKind::Read => {
                let path = self.resolve(action.path.as_deref().unwrap_or(""))?;
                let content = std::fs::read_to_string(&path)
                    .with_context(|| format!("lendo {}", path.display()))?;
                Ok(StepOutcome::FileText {
                    path: path.display().to_string(),
                    content,
                })
            }
            ActionKind::Grep => {
                let pattern = action
                    .query
                    .clone()
                    .context("grep sem 'query'")?;
                let re = Regex::new(&pattern)
                    .with_context(|| format!("padrao invalido: {pattern}"))?;
                let target = match action.path.as_deref() {
                    Some(p) => self.resolve(p)?,
                    None => self.workspace.clone(),
                };
                let mut hits = Vec::new();
                let files: Vec<PathBuf> = if target.is_file() {
                    vec![target]
                } else {
                    walkdir::WalkDir::new(&target)
                        .max_depth(6)
                        .into_iter()
                        .filter_map(|e| e.ok())
                        .filter(|e| e.file_type().is_file())
                        .map(|e| e.path().to_path_buf())
                        .take(2000)
                        .collect()
                };
                for f in files {
                    let Ok(text) = std::fs::read_to_string(&f) else {
                        continue;
                    };
                    for (i, line) in text.lines().enumerate() {
                        if re.is_match(line) {
                            hits.push((i + 1, format!("{}:{}", f.display(), line)));
                            if hits.len() >= 200 {
                                break;
                            }
                        }
                    }
                }
                Ok(StepOutcome::Matches(hits))
            }
            ActionKind::Write => {
                let path = self.resolve(action.path.as_deref().unwrap_or(""))?;
                let content = action.content.unwrap_or_default();
                let before = std::fs::read_to_string(&path).unwrap_or_default();
                let preview = render_diff(&before, &content);
                if self.approval == ApprovalMode::Suggest {
                    return Ok(StepOutcome::ProposedDiff {
                        path: path.display().to_string(),
                        preview,
                    });
                }
                if let Some(parent) = path.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                std::fs::write(&path, content.as_bytes())?;
                self.transcript.push(format!("write {}", path.display()));
                Ok(StepOutcome::Written {
                    path: path.display().to_string(),
                    preview,
                })
            }
            ActionKind::ApplyPatch => {
                let path = self.resolve(action.path.as_deref().unwrap_or(""))?;
                let patch = action.content.context("apply_patch sem 'patch'")?;
                let before = std::fs::read_to_string(&path)
                    .with_context(|| format!("lendo {}", path.display()))?;
                let after = apply_unified_diff(&before, &patch)?;
                let preview = render_diff(&before, &after);
                if self.approval == ApprovalMode::Suggest {
                    return Ok(StepOutcome::ProposedDiff {
                        path: path.display().to_string(),
                        preview,
                    });
                }
                std::fs::write(&path, after.as_bytes())?;
                self.transcript.push(format!("patch {}", path.display()));
                Ok(StepOutcome::Written {
                    path: path.display().to_string(),
                    preview,
                })
            }
            ActionKind::Shell | ActionKind::Test => {
                if action.command.is_empty() {
                    bail!("comando vazio");
                }
                if self.approval == ApprovalMode::Suggest {
                    return Ok(StepOutcome::NeedsApproval {
                        reason: format!("modo Sugestao nao executa: {}", action.command.join(" ")),
                    });
                }
                if self.approval == ApprovalMode::AutoEdit && !self.shell_approved {
                    return Ok(StepOutcome::NeedsApproval {
                        reason: format!("confirme o comando: {}", action.command.join(" ")),
                    });
                }
                self.shell_approved = false;
                let res = sandbox::run(&self.sandbox, &action.command)?;
                self.transcript.push(format!(
                    "$ {} -> {:?}",
                    action.command.join(" "),
                    res.status
                ));
                Ok(StepOutcome::Command(res))
            }
        }
    }
}

/// Aplica um diff unificado sobre o texto original.
pub fn apply_unified_diff(original: &str, diff: &str) -> Result<String> {
    let hunk = Regex::new(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")?;
    let orig: Vec<&str> = original.lines().collect();
    let mut out: Vec<String> = Vec::new();
    let mut cursor = 0usize;
    let mut lines = diff.lines().peekable();
    let mut hunks = 0usize;

    while let Some(l) = lines.peek() {
        if l.starts_with("---") || l.starts_with("+++") || l.starts_with("diff ") || l.starts_with("index ") {
            lines.next();
        } else {
            break;
        }
    }

    while let Some(line) = lines.next() {
        let caps = match hunk.captures(line) {
            Some(c) => c,
            None => continue,
        };
        hunks += 1;
        let old_start: usize = caps[1].parse()?;
        let old_len: usize = match caps.get(2) {
            Some(m) => m.as_str().parse()?,
            None => 1,
        };
        let start = if old_len == 0 {
            old_start
        } else {
            old_start.saturating_sub(1)
        };
        if start < cursor || start > orig.len() {
            bail!("hunk fora de ordem: @@ -{old_start}");
        }
        while cursor < start {
            out.push(orig[cursor].to_string());
            cursor += 1;
        }

        let mut consumed = 0usize;
        while let Some(peek) = lines.peek() {
            if peek.starts_with("@@") || peek.starts_with("--- ") {
                break;
            }
            let raw = lines.next().unwrap_or("");
            if raw.starts_with('\\') {
                continue;
            }
            if raw.is_empty() {
                continue;
            }
            let (tag, body) = raw.split_at(1);
            match tag {
                " " => {
                    if cursor >= orig.len() || orig[cursor] != body {
                        bail!(
                            "contexto divergente na linha {}: esperado {:?}, encontrado {:?}",
                            cursor + 1,
                            body,
                            orig.get(cursor)
                        );
                    }
                    out.push(body.to_string());
                    cursor += 1;
                    consumed += 1;
                }
                "-" => {
                    if cursor >= orig.len() || orig[cursor] != body {
                        bail!(
                            "remocao divergente na linha {}: esperado {:?}, encontrado {:?}",
                            cursor + 1,
                            body,
                            orig.get(cursor)
                        );
                    }
                    cursor += 1;
                    consumed += 1;
                }
                "+" => out.push(body.to_string()),
                _ => bail!("linha de hunk invalida: {raw:?}"),
            }
        }
        if consumed != old_len {
            bail!("hunk consumiu {consumed} linhas, esperado {old_len}");
        }
    }

    if hunks == 0 {
        bail!("diff sem hunks");
    }
    while cursor < orig.len() {
        out.push(orig[cursor].to_string());
        cursor += 1;
    }
    let mut text = out.join("\n");
    if original.ends_with('\n') {
        text.push('\n');
    }
    Ok(text)
}

/// Renderiza um diff legivel entre dois textos, sem coloracao.
pub fn render_diff(before: &str, after: &str) -> String {
    let a: Vec<&str> = before.lines().collect();
    let b: Vec<&str> = after.lines().collect();
    let n = a.len();
    let m = b.len();
    if n * m > 4_000_000 {
        return format!("(diff grande: {} -> {} linhas)", n, m);
    }
    let mut lcs = vec![vec![0u32; m + 1]; n + 1];
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            lcs[i][j] = if a[i] == b[j] {
                lcs[i + 1][j + 1] + 1
            } else {
                lcs[i + 1][j].max(lcs[i][j + 1])
            };
        }
    }
    let mut out = Vec::new();
    let (mut i, mut j) = (0usize, 0usize);
    while i < n && j < m {
        if a[i] == b[j] {
            out.push(format!(" {}", a[i]));
            i += 1;
            j += 1;
        } else if lcs[i + 1][j] >= lcs[i][j + 1] {
            out.push(format!("-{}", a[i]));
            i += 1;
        } else {
            out.push(format!("+{}", b[j]));
            j += 1;
        }
    }
    while i < n {
        out.push(format!("-{}", a[i]));
        i += 1;
    }
    while j < m {
        out.push(format!("+{}", b[j]));
        j += 1;
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    const ORIGINAL: &str = "fn soma(a: i32, b: i32) -> i32 {\n    a - b\n}\n";

    #[test]
    fn applies_unified_patch() {
        let diff = "--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1,3 +1,4 @@\n fn soma(a: i32, b: i32) -> i32 {\n-    a - b\n+    a + b\n }\n+\n";
        let out = apply_unified_diff(ORIGINAL, diff).unwrap();
        assert!(out.contains("a + b"));
        assert!(!out.contains("a - b"));
    }

    #[test]
    fn rejects_divergent_context() {
        let diff = "@@ -1,3 +1,3 @@\n fn subtracao() {\n-    a - b\n+    a + b\n }\n";
        assert!(apply_unified_diff(ORIGINAL, diff).is_err());
    }

    #[test]
    fn suggest_mode_does_not_touch_disk() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(tmp.path().join("a.rs"), ORIGINAL).unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::Suggest);
        let outcome = s
            .execute(Action {
                kind: ActionKind::Write,
                path: Some("a.rs".into()),
                query: None,
                content: Some("outro conteudo\n".into()),
                command: Vec::new(),
            })
            .unwrap();
        assert!(matches!(outcome, StepOutcome::ProposedDiff { .. }));
        assert_eq!(std::fs::read_to_string(tmp.path().join("a.rs")).unwrap(), ORIGINAL);
    }

    #[test]
    fn auto_edit_writes_and_reports_diff() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(tmp.path().join("a.rs"), ORIGINAL).unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::AutoEdit);
        let outcome = s
            .execute(Action {
                kind: ActionKind::ApplyPatch,
                path: Some("a.rs".into()),
                query: None,
                content: Some("@@ -1,3 +1,3 @@\n fn soma(a: i32, b: i32) -> i32 {\n-    a - b\n+    a * b\n }\n".into()),
                command: Vec::new(),
            })
            .unwrap();
        match outcome {
            StepOutcome::Written { preview, .. } => {
                assert!(preview.contains("a * b"));
                assert!(preview.contains("-    a - b"));
            }
            other => panic!("esperava Written, veio {other:?}"),
        }
        assert!(std::fs::read_to_string(tmp.path().join("a.rs")).unwrap().contains("a * b"));
    }

    #[test]
    fn auto_edit_requires_approval_for_shell() {
        let tmp = tempfile::tempdir().unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::AutoEdit);
        let act = Action {
            kind: ActionKind::Shell,
            path: None,
            query: None,
            content: None,
            command: vec!["echo".into(), "ok".into()],
        };
        assert!(matches!(
            s.execute(act.clone()).unwrap(),
            StepOutcome::NeedsApproval { .. }
        ));
        s.approve_shell();
        match s.execute(act).unwrap() {
            StepOutcome::Command(r) => {
                assert_eq!(r.status, Some(0));
                assert_eq!(r.stdout.trim(), "ok");
            }
            other => panic!("esperava Command, veio {other:?}"),
        }
    }

    #[test]
    fn full_auto_executes_in_sandbox() {
        let tmp = tempfile::tempdir().unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::FullAuto);
        let outcome = s
            .execute(Action {
                kind: ActionKind::Shell,
                path: None,
                query: None,
                content: None,
                command: vec!["sh".into(), "-c".into(), "echo dentro > saida.txt && cat saida.txt".into()],
            })
            .unwrap();
        match outcome {
            StepOutcome::Command(r) => {
                assert_eq!(r.status, Some(0), "stderr: {}", r.stderr);
                assert_eq!(r.stdout.trim(), "dentro");
            }
            other => panic!("esperava Command, veio {other:?}"),
        }
        assert!(tmp.path().join("saida.txt").is_file());
    }

    #[test]
    fn grep_finds_lines_in_workspace() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(tmp.path().join("x.txt"), "alfa\nbeta\ngama\n").unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::Suggest);
        let outcome = s
            .execute(Action {
                kind: ActionKind::Grep,
                path: None,
                query: Some("beta".into()),
                content: None,
                command: Vec::new(),
            })
            .unwrap();
        match outcome {
            StepOutcome::Matches(hits) => {
                assert_eq!(hits.len(), 1);
                assert_eq!(hits[0].0, 2);
            }
            other => panic!("esperava Matches, veio {other:?}"),
        }
    }

    #[test]
    fn rejects_paths_outside_workspace() {
        let tmp = tempfile::tempdir().unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::FullAuto);
        let err = s
            .execute(Action {
                kind: ActionKind::Read,
                path: Some("/etc/passwd".into()),
                query: None,
                content: None,
                command: Vec::new(),
            })
            .unwrap_err();
        assert!(err.to_string().contains("fora do workspace"));
    }

    #[test]
    fn rejects_parent_dir_traversal() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(tmp.path().join("ok.txt"), "x").unwrap();
        let mut s = EngineerSession::new(tmp.path(), ApprovalMode::FullAuto);
        for bad in ["../fora.txt", "sub/../../fora.txt"] {
            let err = s
                .execute(Action {
                    kind: ActionKind::Write,
                    path: Some(bad.into()),
                    query: None,
                    content: Some("invasao".into()),
                    command: Vec::new(),
                })
                .unwrap_err();
            assert!(
                err.to_string().contains("path traversal"),
                "esperava bloqueio de traversal em {bad}: {err}"
            );
        }
    }
}
