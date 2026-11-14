//! Loader real das skills do Hermes.
//!
//! Le `/home/thu12/.hermes/skills/<categoria>/<skill>/SKILL.md`, extrai o
//! frontmatter YAML (`name`, `description`) e cataloga `scripts/` e `references/`.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use walkdir::WalkDir;

/// Skill carregada do disco.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SkillInfo {
    pub name: String,
    pub description: String,
    pub category: String,
    pub dir: PathBuf,
    pub scripts: Vec<PathBuf>,
    pub references: Vec<PathBuf>,
}

impl SkillInfo {
    /// Caminho do SKILL.md.
    pub fn skill_file(&self) -> PathBuf {
        self.dir.join("SKILL.md")
    }
}

/// Extrai o bloco de frontmatter de um SKILL.md.
fn split_frontmatter(text: &str) -> Option<(&str, &str)> {
    let mut lines = text.lines();
    if lines.next()?.trim() != "---" {
        return None;
    }
    let start = text.find("---").map(|i| i + 3)?;
    let rest = &text[start..];
    let end = rest.find("\n---")?;
    let front = rest[..end].trim_start_matches(['\n', '\r']);
    let body_start = start + end + 4;
    let body = text.get(body_start..).unwrap_or("");
    Some((front, body))
}

fn yaml_field(front: &str, key: &str) -> Option<String> {
    for line in front.lines() {
        let line = line.trim_end();
        if let Some(rest) = line.strip_prefix(&format!("{key}:")) {
            let v = rest.trim();
            let v = v.trim_matches('"').trim_matches('\'').trim();
            if !v.is_empty() {
                return Some(v.to_string());
            }
        }
    }
    None
}

fn collect_files(root: &Path, sub: &str) -> Vec<PathBuf> {
    let dir = root.join(sub);
    if !dir.is_dir() {
        return Vec::new();
    }
    let mut out: Vec<PathBuf> = WalkDir::new(&dir)
        .max_depth(3)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .map(|e| e.path().to_path_buf())
        .collect();
    out.sort();
    out
}

/// Carrega uma skill de um diretorio.
pub fn load_skill(dir: &Path) -> Result<SkillInfo> {
    let skill_md = dir.join("SKILL.md");
    if !skill_md.is_file() {
        bail!("SKILL.md ausente em {}", dir.display());
    }
    let text = std::fs::read_to_string(&skill_md)
        .with_context(|| format!("lendo {}", skill_md.display()))?;
    let (name, description) = match split_frontmatter(&text) {
        Some((front, _)) => (
            yaml_field(front, "name").unwrap_or_else(|| {
                dir.file_name()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default()
            }),
            yaml_field(front, "description").unwrap_or_default(),
        ),
        None => (
            dir.file_name()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_default(),
            String::new(),
        ),
    };
    let category = dir
        .parent()
        .and_then(|p| p.file_name())
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "root".to_string());
    Ok(SkillInfo {
        name,
        description,
        category,
        dir: dir.to_path_buf(),
        scripts: collect_files(dir, "scripts"),
        references: collect_files(dir, "references"),
    })
}

/// Carrega todas as skills sob uma raiz, em ordem estavel.
pub fn load_skills(root: &Path) -> Vec<SkillInfo> {
    let mut out = Vec::new();
    if !root.is_dir() {
        return out;
    }
    let mut dirs: Vec<PathBuf> = WalkDir::new(root)
        .min_depth(1)
        .max_depth(3)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_dir())
        .map(|e| e.path().to_path_buf())
        .collect();
    dirs.sort();
    for dir in dirs {
        if dir.join("SKILL.md").is_file() {
            if let Ok(s) = load_skill(&dir) {
                out.push(s);
            }
        }
    }
    out.sort_by(|a, b| a.category.cmp(&b.category).then(a.name.cmp(&b.name)));
    out.dedup_by(|a, b| a.dir == b.dir);
    out
}

/// Devolve o texto completo do SKILL.md de uma skill.
pub fn render_skill(skill: &SkillInfo) -> Result<String> {
    let path = skill.skill_file();
    std::fs::read_to_string(&path).with_context(|| format!("lendo {}", path.display()))
}

/// Monta o indice textual das skills para o prompt do Modo Engineer.
pub fn index_prompt(skills: &[SkillInfo]) -> String {
    let mut s = String::new();
    for k in skills {
        s.push_str(&format!(
            "- {} ({}): {}\n",
            k.name,
            k.category,
            k.description.trim()
        ));
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake_skill(root: &Path, cat: &str, name: &str, desc: &str) {
        let dir = root.join(cat).join(name);
        std::fs::create_dir_all(dir.join("scripts")).unwrap();
        std::fs::create_dir_all(dir.join("references")).unwrap();
        std::fs::write(
            dir.join("SKILL.md"),
            format!("---\nname: {name}\ndescription: {desc}\n---\n\n# Corpo\n"),
        )
        .unwrap();
        std::fs::write(dir.join("scripts").join("run.sh"), "#!/bin/sh\n").unwrap();
        std::fs::write(dir.join("references").join("api.md"), "# api\n").unwrap();
    }

    #[test]
    fn parses_frontmatter_and_collects_files() {
        let tmp = tempfile::tempdir().unwrap();
        fake_skill(tmp.path(), "research", "arxiv", "Search arXiv papers");
        let skills = load_skills(tmp.path());
        assert_eq!(skills.len(), 1);
        let s = &skills[0];
        assert_eq!(s.name, "arxiv");
        assert_eq!(s.description, "Search arXiv papers");
        assert_eq!(s.category, "research");
        assert_eq!(s.scripts.len(), 1);
        assert_eq!(s.references.len(), 1);
        assert!(render_skill(s).unwrap().contains("# Corpo"));
    }

    #[test]
    fn missing_root_yields_empty_index() {
        let skills = load_skills(Path::new("/caminho/que/nao/existe"));
        assert!(skills.is_empty());
        assert!(index_prompt(&skills).is_empty());
    }
}
