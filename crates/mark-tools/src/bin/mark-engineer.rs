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
}

fn parse_args() -> Result<Args> {
    let mut args = Args {
        approval: ApprovalMode::Suggest,
        workspace: mark_core::paths::default_workspace(),
        list_skills: false,
        web_search: None,
        web_fetch: None,
        limit: 5,
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

fn main() -> Result<()> {
    let args = parse_args()?;
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
