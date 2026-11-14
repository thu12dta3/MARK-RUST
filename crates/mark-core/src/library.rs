//! Biblioteca cifrada de documentos locais (notas, codigo e referencias).

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::{CoreError, CoreResult};
use crate::store::EncryptedStore;

/// Documento persistido na biblioteca.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Document {
    pub id: String,
    pub title: String,
    pub kind: String,
    pub tags: Vec<String>,
    pub body: String,
    pub updated_at: u64,
}

/// Metadados de um documento (sem o corpo).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DocMeta {
    pub id: String,
    pub title: String,
    pub kind: String,
    pub tags: Vec<String>,
    pub bytes: usize,
}

/// Biblioteca cifrada sobre um [`EncryptedStore`].
pub struct Library {
    store: EncryptedStore,
}

impl Library {
    /// Abre a biblioteca em `dir`, destravando com a senha mestra.
    pub fn open(dir: impl Into<PathBuf>, password: &str) -> CoreResult<Self> {
        let mut store = EncryptedStore::open(dir)?;
        store.unlock(password)?;
        Ok(Self { store })
    }

    /// Bloqueia a biblioteca.
    pub fn lock(&mut self) {
        self.store.lock();
    }

    /// Indica se a chave esta carregada.
    pub fn is_unlocked(&self) -> bool {
        self.store.is_unlocked()
    }

    fn doc_id(&self, id: &str) -> String {
        format!("doc-{id}")
    }

    /// Insere um documento e devolve o identificador gerado.
    pub fn add(&self, title: &str, kind: &str, body: &str, tags: &[&str]) -> CoreResult<String> {
        if title.trim().is_empty() {
            return Err(CoreError::Config("titulo vazio".into()));
        }
        let id = uuid::Uuid::new_v4().simple().to_string();
        let doc = Document {
            id: id.clone(),
            title: title.trim().to_string(),
            kind: kind.trim().to_string(),
            tags: tags.iter().map(|t| t.to_string()).collect(),
            body: body.to_string(),
            updated_at: now_secs(),
        };
        self.store.put_json(&self.doc_id(&id), &doc)?;
        Ok(id)
    }

    /// Le um documento pelo identificador.
    pub fn get(&self, id: &str) -> CoreResult<Document> {
        self.store.get_json(&self.doc_id(id))
    }

    /// Remove um documento.
    pub fn remove(&self, id: &str) -> CoreResult<bool> {
        self.store.remove(&self.doc_id(id))
    }

    /// Lista os metadados de todos os documentos.
    pub fn list(&self) -> CoreResult<Vec<DocMeta>> {
        if !self.store.is_unlocked() {
            return Err(CoreError::VaultLocked);
        }
        let mut out = Vec::new();
        for key in self.store.list()? {
            let Some(id) = key.strip_prefix("doc-") else {
                continue;
            };
            if let Ok(doc) = self.get(id) {
                out.push(DocMeta {
                    id: doc.id,
                    title: doc.title,
                    kind: doc.kind,
                    tags: doc.tags,
                    bytes: doc.body.len(),
                });
            }
        }
        out.sort_by_key(|a| a.title.to_lowercase());
        Ok(out)
    }

    /// Busca por substring (sem diferenciar caixa) em titulo, corpo e tags.
    pub fn search(&self, query: &str) -> CoreResult<Vec<Document>> {
        if !self.store.is_unlocked() {
            return Err(CoreError::VaultLocked);
        }
        let needle = query.trim().to_lowercase();
        if needle.is_empty() {
            return Ok(Vec::new());
        }
        let mut out = Vec::new();
        for meta in self.list()? {
            let Ok(doc) = self.get(&meta.id) else {
                continue;
            };
            let hit = doc.title.to_lowercase().contains(&needle)
                || doc.body.to_lowercase().contains(&needle)
                || doc.tags.iter().any(|t| t.to_lowercase().contains(&needle));
            if hit {
                out.push(doc);
            }
        }
        Ok(out)
    }
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lib(dir: &std::path::Path) -> Library {
        Library::open(dir.join("library"), "senha-forte").unwrap()
    }

    #[test]
    fn stores_searches_and_removes_documents() {
        let tmp = tempfile::tempdir().unwrap();
        let l = lib(tmp.path());
        let a = l.add("Notas de Rust", "note", "ownership e borrow checker", &["rust"]).unwrap();
        let b = l.add("Receita", "note", "bolo de cenoura", &["cozinha"]).unwrap();
        assert_eq!(l.list().unwrap().len(), 2);
        let found = l.search("BORROW").unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].id, a);
        assert_eq!(l.get(&a).unwrap().title, "Notas de Rust");
        assert_eq!(l.search("cenoura").unwrap().len(), 1);
        assert!(l.remove(&b).unwrap());
        assert_eq!(l.list().unwrap().len(), 1);
    }

    #[test]
    fn content_is_encrypted_on_disk() {
        let tmp = tempfile::tempdir().unwrap();
        let l = lib(tmp.path());
        l.add("segredo", "note", "texto-confidencial-xyz", &[]).unwrap();
        let mut found = false;
        for e in walkdir::WalkDir::new(tmp.path()) {
            let e = e.unwrap();
            if !e.file_type().is_file() {
                continue;
            }
            let raw = std::fs::read(e.path()).unwrap();
            if raw.windows(21).any(|w| w == b"texto-confidencial-xyz") {
                found = true;
            }
        }
        assert!(!found, "conteudo em texto puro na biblioteca");
    }

    #[test]
    fn locked_library_refuses_access() {
        let tmp = tempfile::tempdir().unwrap();
        let mut l = lib(tmp.path());
        l.add("x", "note", "y", &[]).unwrap();
        l.lock();
        assert!(l.list().is_err());
        assert!(l.add("z", "note", "w", &[]).is_err());
    }

    #[test]
    fn rejects_empty_title() {
        let tmp = tempfile::tempdir().unwrap();
        let l = lib(tmp.path());
        assert!(l.add("   ", "note", "x", &[]).is_err());
    }
}
