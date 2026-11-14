//! Acesso real a internet: `web_fetch` e `web_search` com reqwest + rustls.

use anyhow::{bail, Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};

const USER_AGENT: &str =
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

/// Pagina baixada e convertida para texto.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FetchResult {
    pub url: String,
    pub status: u16,
    pub title: String,
    pub text: String,
}

/// Um resultado de busca.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SearchHit {
    pub title: String,
    pub url: String,
    pub snippet: String,
}

fn client() -> Result<reqwest::Client> {
    reqwest::Client::builder()
        .user_agent(USER_AGENT)
        .timeout(std::time::Duration::from_secs(45))
        .build()
        .context("cliente HTTP indisponivel")
}

fn decode_entities(s: &str) -> String {
    let mut out = s
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&nbsp;", " ");
    out = out.replace('\u{a0}', " ");
    out
}

/// Converte HTML em texto legivel.
pub fn html_to_text(html: &str) -> String {
    let script = Regex::new(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</(script|style|noscript|svg)>")
        .expect("regex de script");
    let cleaned = script.replace_all(html, " ");
    let block = Regex::new(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>").expect("regex de bloco");
    let spaced = block.replace_all(&cleaned, "\n");
    let tags = Regex::new(r"(?is)<[^>]+>").expect("regex de tag");
    let stripped = tags.replace_all(&spaced, " ");
    let ws = Regex::new(r"[ \t]+").expect("regex de espaco");
    let lines: Vec<String> = decode_entities(&stripped)
        .lines()
        .map(|l| ws.replace_all(l.trim(), " ").into_owned())
        .filter(|l| !l.is_empty())
        .collect();
    lines.join("\n")
}

fn extract_title(html: &str) -> String {
    let re = Regex::new(r"(?is)<title[^>]*>(.*?)</title>").expect("regex de titulo");
    re.captures(html)
        .map(|c| decode_entities(c[1].trim()))
        .unwrap_or_default()
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or("");
            if let Ok(v) = u8::from_str_radix(hex, 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn unwrap_ddg_link(href: &str) -> String {
    let href = decode_entities(href);
    if let Some(pos) = href.find("uddg=") {
        let rest = &href[pos + 5..];
        let end = rest.find('&').unwrap_or(rest.len());
        return percent_decode(&rest[..end]);
    }
    if href.starts_with("//") {
        return format!("https:{href}");
    }
    href
}

/// Baixa uma URL e devolve o texto limpo.
pub async fn web_fetch(url: &str, max_chars: usize) -> Result<FetchResult> {
    let parsed = url::Url::parse(url).with_context(|| format!("URL invalida: {url}"))?;
    if parsed.scheme() != "http" && parsed.scheme() != "https" {
        bail!("esquema nao suportado: {}", parsed.scheme());
    }
    let resp = client()?.get(parsed.as_str()).send().await?;
    let status = resp.status().as_u16();
    let body = resp.text().await?;
    let title = extract_title(&body);
    let mut text = html_to_text(&body);
    if text.chars().count() > max_chars {
        text = text.chars().take(max_chars).collect();
    }
    Ok(FetchResult {
        url: parsed.to_string(),
        status,
        title,
        text,
    })
}

/// Executa uma busca web real via DuckDuckGo HTML.
pub async fn web_search(query: &str, limit: usize) -> Result<Vec<SearchHit>> {
    let form = [("q", query)];
    let resp = client()?
        .post("https://html.duckduckgo.com/html/")
        .form(&form)
        .header("accept-language", "pt-BR,pt;q=0.9,en;q=0.8")
        .send()
        .await?;
    if !resp.status().is_success() {
        bail!("busca retornou status {}", resp.status());
    }
    let body = resp.text().await?;
    let link = Regex::new(r#"(?is)<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>"#)
        .expect("regex de link");
    let snip = Regex::new(r#"(?is)class="result__snippet"[^>]*>(.*?)</a>"#)
        .expect("regex de snippet");
    let snippets: Vec<String> = snip
        .captures_iter(&body)
        .map(|c| html_to_text(&c[1]))
        .collect();
    let mut out = Vec::new();
    for (i, c) in link.captures_iter(&body).enumerate() {
        if out.len() >= limit {
            break;
        }
        let url = unwrap_ddg_link(&c[1]);
        let title = html_to_text(&c[2]);
        if url.is_empty() || title.is_empty() {
            continue;
        }
        out.push(SearchHit {
            title,
            url,
            snippet: snippets.get(i).cloned().unwrap_or_default(),
        });
    }
    if out.is_empty() {
        bail!("nenhum resultado extraido para a consulta '{query}'");
    }
    Ok(out)
}

fn block_on<F: std::future::Future>(fut: F) -> Result<F::Output> {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("runtime tokio indisponivel")?;
    Ok(rt.block_on(fut))
}

/// Versao bloqueante de [`web_fetch`] para uso na GUI e nas ferramentas.
pub fn web_fetch_blocking(url: &str, max_chars: usize) -> Result<FetchResult> {
    block_on(web_fetch(url, max_chars))?
}

/// Versao bloqueante de [`web_search`].
pub fn web_search_blocking(query: &str, limit: usize) -> Result<Vec<SearchHit>> {
    block_on(web_search(query, limit))?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn html_becomes_plain_text() {
        let html = "<html><head><title>Teste</title><style>b{}</style></head><body><h1>Ola</h1><p>mundo &amp; cia</p><script>x()</script></body></html>";
        let text = html_to_text(html);
        assert!(text.contains("Ola"));
        assert!(text.contains("mundo & cia"));
        assert!(!text.contains("x()"));
        assert_eq!(extract_title(html), "Teste");
    }

    #[test]
    fn ddg_link_unwrap_decodes_target() {
        let href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.rust-lang.org%2F&rut=abc";
        assert_eq!(unwrap_ddg_link(href), "https://www.rust-lang.org/");
    }

    #[test]
    fn fetch_real_page_from_internet() {
        let res = web_fetch_blocking("https://example.com", 4000).expect("fetch deve funcionar");
        assert_eq!(res.status, 200);
        assert_eq!(res.title, "Example Domain");
        assert!(
            res.text.contains("Example Domain"),
            "conteudo inesperado: {}",
            res.text
        );
    }

    #[test]
    fn search_returns_real_results() {
        let hits = web_search_blocking("rust programming language", 5).expect("busca deve funcionar");
        assert!(!hits.is_empty(), "nenhum resultado retornado");
        assert!(
            hits.iter().any(|h| h.url.starts_with("http")),
            "resultado sem URL absoluta: {hits:?}"
        );
        assert!(
            hits.iter().any(|h| !h.title.is_empty()),
            "resultado sem titulo: {hits:?}"
        );
    }
}
