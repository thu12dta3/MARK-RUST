//! Command Palette (Ctrl+K) com busca fuzzy sobre comandos registrados.

/// Acao executavel por um comando da paleta.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PaletteAction {
    /// Abre uma aba pelo identificador (`chat`, `models`, `vault`, `download`, `engineer`).
    OpenTab(String),
    /// Insere texto no composer.
    InsertText(String),
    /// Executa um comando no sandbox do Modo Engineer.
    EngineerShell(String),
    /// Abre uma busca web.
    WebSearch(String),
}

/// Um comando disponivel na paleta.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Command {
    pub id: String,
    pub title: String,
    pub hint: String,
    pub action: PaletteAction,
}

/// Registro de comandos com pontuacao fuzzy.
pub struct Registry {
    commands: Vec<Command>,
}

impl Registry {
    /// Cria um registro vazio.
    pub fn new() -> Self {
        Self {
            commands: Vec::new(),
        }
    }

    /// Registro com os comandos nativos do app.
    pub fn with_builtin() -> Self {
        let mut r = Self::new();
        for (id, title, hint, tab) in [
            ("tab.chat", "Ir para Conversa", "chat", "chat"),
            ("tab.models", "Modelos & Papeis", "selecionar modelo", "models"),
            ("tab.vault", "Abrir Cofre", "chaves e senha mestra", "vault"),
            ("tab.download", "Baixar do Hugging Face", "modelos remotos", "download"),
            ("tab.engineer", "Modo Engineer", "sandbox e patches", "engineer"),
        ] {
            r.add(Command {
                id: id.to_string(),
                title: title.to_string(),
                hint: hint.to_string(),
                action: PaletteAction::OpenTab(tab.to_string()),
            });
        }
        r.add(Command {
            id: "action.clear".into(),
            title: "Nova conversa".into(),
            hint: "limpar historico".into(),
            action: PaletteAction::InsertText(String::new()),
        });
        r.add(Command {
            id: "action.web".into(),
            title: "Pesquisar na web".into(),
            hint: "web_search".into(),
            action: PaletteAction::WebSearch(String::new()),
        });
        r.add(Command {
            id: "action.shell".into(),
            title: "Executar comando no sandbox".into(),
            hint: "bwrap".into(),
            action: PaletteAction::EngineerShell(String::new()),
        });
        r
    }

    /// Registra um comando.
    pub fn add(&mut self, cmd: Command) {
        self.commands.push(cmd);
    }

    /// Quantidade de comandos registrados.
    pub fn len(&self) -> usize {
        self.commands.len()
    }

    /// Indica registro vazio.
    pub fn is_empty(&self) -> bool {
        self.commands.is_empty()
    }

    /// Todos os comandos.
    pub fn all(&self) -> &[Command] {
        &self.commands
    }

    /// Busca fuzzy: retorna no maximo `limit` comandos ordenados por pontuacao.
    pub fn search(&self, query: &str, limit: usize) -> Vec<&Command> {
        let q = query.trim().to_lowercase();
        if q.is_empty() {
            return self.commands.iter().take(limit.max(1)).collect();
        }
        let mut scored: Vec<(i32, &Command)> = self
            .commands
            .iter()
            .filter_map(|c| {
                let hay = format!("{} {}", c.title.to_lowercase(), c.hint.to_lowercase());
                fuzzy_score(&hay, &q).map(|s| (s, c))
            })
            .collect();
        scored.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.title.cmp(&b.1.title)));
        scored.into_iter().take(limit.max(1)).map(|(_, c)| c).collect()
    }
}

impl Default for Registry {
    fn default() -> Self {
        Self::new()
    }
}

/// Pontua uma consulta como subsequencia do texto, premiando trechos contiguos.
pub fn fuzzy_score(haystack: &str, needle: &str) -> Option<i32> {
    if needle.is_empty() {
        return Some(0);
    }
    let hay: Vec<char> = haystack.chars().collect();
    let mut score = 0i32;
    let mut hi = 0usize;
    let mut last: Option<usize> = None;
    for nc in needle.chars() {
        let mut found = None;
        while hi < hay.len() {
            if hay[hi] == nc {
                found = Some(hi);
                hi += 1;
                break;
            }
            hi += 1;
        }
        let idx = found?;
        score += 10;
        if let Some(p) = last {
            if idx == p + 1 {
                score += 6;
            }
        }
        if idx == 0 || hay[idx - 1] == ' ' {
            score += 8;
        }
        last = Some(idx);
    }
    Some(score - hay.len() as i32 / 4)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builtin_registry_has_tabs_and_actions() {
        let r = Registry::with_builtin();
        assert!(r.len() >= 8);
        let tabs = r
            .search("models", 3)
            .into_iter()
            .filter(|c| matches!(c.action, PaletteAction::OpenTab(_)))
            .count();
        assert!(tabs >= 1, "nenhum comando de aba casou 'models'");
    }

    #[test]
    fn fuzzy_matches_subsequences_with_prefix_bonus() {
        assert!(fuzzy_score("ir para conversa", "conv").unwrap() > 0);
        assert!(fuzzy_score("modo engineer", "eng").unwrap() > 0);
        assert!(fuzzy_score("cofre", "xyz").is_none());
        let adjacent = fuzzy_score("abc", "ab").unwrap();
        let spread = fuzzy_score("a_b_c", "ab").unwrap();
        assert!(adjacent > spread, "trecho contiguo deve pontuar mais");
    }

    #[test]
    fn empty_query_returns_first_commands() {
        let r = Registry::with_builtin();
        let hits = r.search("   ", 3);
        assert_eq!(hits.len(), 3);
        assert!(r.search("nada-que-exista", 5).is_empty());
    }
}
