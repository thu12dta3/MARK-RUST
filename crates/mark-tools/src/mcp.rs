//! Cliente MCP (Model Context Protocol) sobre stdio e HTTP.
//!
//! Le a secao `mcp_servers:` de `/home/thu12/.hermes/config.yaml` e fala
//! JSON-RPC 2.0 delimitado por linha com o servidor escolhido.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// Configuracao de um servidor MCP declarado no Hermes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct McpServerConfig {
    pub name: String,
    pub command: Option<String>,
    pub args: Vec<String>,
    pub env: BTreeMap<String, String>,
    pub url: Option<String>,
    pub enabled: bool,
}

/// Ferramenta exposta por um servidor MCP.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct McpTool {
    pub server: String,
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

/// Carrega os servidores MCP habilitados a partir do config.yaml do Hermes.
pub fn load_mcp_servers(path: &Path) -> Result<Vec<McpServerConfig>> {
    if !path.is_file() {
        return Ok(Vec::new());
    }
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("lendo {}", path.display()))?;
    let root: serde_yaml::Value = serde_yaml::from_str(&raw)
        .with_context(|| format!("config.yaml invalido em {}", path.display()))?;
    let Some(map) = root.get("mcp_servers").and_then(|v| v.as_mapping()) else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for (k, v) in map {
        let Some(name) = k.as_str() else { continue };
        let enabled = v.get("enabled").and_then(|e| e.as_bool()).unwrap_or(true);
        let command = v
            .get("command")
            .and_then(|c| c.as_str())
            .map(|s| s.to_string());
        let url = v.get("url").and_then(|u| u.as_str()).map(|s| s.to_string());
        let mut args = Vec::new();
        if let Some(list) = v.get("args").and_then(|a| a.as_sequence()) {
            for a in list {
                if let Some(s) = a.as_str() {
                    args.push(s.to_string());
                }
            }
        }
        let mut env = BTreeMap::new();
        if let Some(m) = v.get("env").and_then(|e| e.as_mapping()) {
            for (ek, ev) in m {
                if let (Some(k2), Some(v2)) = (ek.as_str(), ev.as_str()) {
                    env.insert(k2.to_string(), v2.to_string());
                }
            }
        }
        out.push(McpServerConfig {
            name: name.to_string(),
            command,
            args,
            env,
            url,
            enabled,
        });
    }
    out.retain(|c| c.enabled);
    out.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(out)
}

enum Transport {
    Stdio {
        child: Child,
        stdin: ChildStdin,
        stdout: BufReader<ChildStdout>,
    },
    Http {
        url: String,
        client: reqwest::Client,
        session: Option<String>,
    },
}

/// Cliente de um servidor MCP.
pub struct McpClient {
    server: String,
    transport: Transport,
    next_id: u64,
    tools: Vec<McpTool>,
    initialized: bool,
}

impl McpClient {
    /// Inicia o cliente a partir da configuracao do servidor.
    pub fn start(cfg: &McpServerConfig) -> Result<Self> {
        let transport = if let Some(url) = &cfg.url {
            Transport::Http {
                url: url.clone(),
                client: reqwest::Client::builder()
                    .timeout(std::time::Duration::from_secs(60))
                    .build()
                    .context("cliente HTTP do MCP indisponivel")?,
                session: None,
            }
        } else if let Some(cmd) = &cfg.command {
            let mut child = Command::new(cmd)
                .args(&cfg.args)
                .envs(&cfg.env)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .with_context(|| format!("falha ao iniciar o servidor MCP '{}'", cfg.name))?;
            let stdin = child.stdin.take().context("stdin do MCP indisponivel")?;
            let stdout = BufReader::new(child.stdout.take().context("stdout do MCP indisponivel")?);
            Transport::Stdio {
                child,
                stdin,
                stdout,
            }
        } else {
            bail!("servidor MCP '{}' sem command nem url", cfg.name);
        };
        Ok(Self {
            server: cfg.name.clone(),
            transport,
            next_id: 1,
            tools: Vec::new(),
            initialized: false,
        })
    }

    /// Nome do servidor.
    pub fn server(&self) -> &str {
        &self.server
    }

    /// Ferramentas descobertas.
    pub fn tools(&self) -> &[McpTool] {
        &self.tools
    }

    fn take_id(&mut self) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        id
    }

    fn read_line_json<R: BufRead>(reader: &mut R) -> Result<Value> {
        let mut line = String::new();
        loop {
            line.clear();
            let n = reader.read_line(&mut line)?;
            if n == 0 {
                bail!("servidor MCP encerrou a conexao");
            }
            let t = line.trim();
            if t.is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str::<Value>(t) {
                return Ok(v);
            }
        }
    }

    fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        let id = self.take_id();
        let payload = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        match &mut self.transport {
            Transport::Stdio {
                stdin, stdout, ..
            } => {
                writeln!(stdin, "{}", serde_json::to_string(&payload)?)?;
                stdin.flush()?;
                loop {
                    let resp = Self::read_line_json(stdout)?;
                    if resp.get("id").and_then(|v| v.as_u64()) == Some(id) {
                        if let Some(err) = resp.get("error") {
                            bail!("erro do MCP em {method}: {err}");
                        }
                        return Ok(resp.get("result").cloned().unwrap_or(Value::Null));
                    }
                }
            }
            Transport::Http {
                url,
                client,
                session,
            } => {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .context("runtime tokio indisponivel")?;
                let body = serde_json::to_string(&payload)?;
                let url = url.clone();
                let session_id = session.clone();
                let client = client.clone();
                let text = rt.block_on(async move {
                    let mut req = client
                        .post(&url)
                        .header("content-type", "application/json")
                        .header("accept", "application/json, text/event-stream")
                        .body(body);
                    if let Some(s) = session_id {
                        req = req.header("mcp-session-id", s);
                    }
                    let resp = req.send().await?;
                    let status = resp.status();
                    let session = resp
                        .headers()
                        .get("mcp-session-id")
                        .and_then(|v| v.to_str().ok())
                        .map(|s| s.to_string());
                    let text = resp.text().await?;
                    Ok::<_, reqwest::Error>((status, session, text))
                })?;
                let (status, new_session, text) = text;
                if let Some(s) = new_session {
                    if let Transport::Http { session, .. } = &mut self.transport {
                        *session = Some(s);
                    }
                }
                if !status.is_success() {
                    bail!("MCP HTTP {} retornou {}", method, status);
                }
                for line in text.lines() {
                    let t = line.trim();
                    let candidate = t.strip_prefix("data:").map(|s| s.trim()).unwrap_or(t);
                    if candidate.is_empty() {
                        continue;
                    }
                    if let Ok(v) = serde_json::from_str::<Value>(candidate) {
                        if v.get("id").and_then(|x| x.as_u64()) == Some(id) {
                            if let Some(err) = v.get("error") {
                                bail!("erro do MCP em {method}: {err}");
                            }
                            return Ok(v.get("result").cloned().unwrap_or(Value::Null));
                        }
                    }
                }
                bail!("resposta do MCP sem o id {id} em {method}")
            }
        }
    }

    fn notify(&mut self, method: &str, params: Value) -> Result<()> {
        let payload = json!({"jsonrpc": "2.0", "method": method, "params": params});
        if let Transport::Stdio { stdin, .. } = &mut self.transport {
            writeln!(stdin, "{}", serde_json::to_string(&payload)?)?;
            stdin.flush()?;
        }
        Ok(())
    }

    /// Executa o handshake MCP e descobre as ferramentas.
    pub fn initialize(&mut self) -> Result<()> {
        let res = self.request(
            "initialize",
            json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "mark-desktop", "version": "1.0.0"},
            }),
        )?;
        if res.get("protocolVersion").is_none() && res.get("serverInfo").is_none() {
            bail!("handshake MCP invalido: {res}");
        }
        self.notify("notifications/initialized", json!({}))?;
        self.initialized = true;
        self.refresh_tools()?;
        Ok(())
    }

    /// Reconsulta a lista de ferramentas.
    pub fn refresh_tools(&mut self) -> Result<()> {
        let res = self.request("tools/list", json!({}))?;
        let mut tools = Vec::new();
        if let Some(list) = res.get("tools").and_then(|t| t.as_array()) {
            for t in list {
                let name = t.get("name").and_then(|n| n.as_str()).unwrap_or("");
                if name.is_empty() {
                    continue;
                }
                tools.push(McpTool {
                    server: self.server.clone(),
                    name: name.to_string(),
                    description: t
                        .get("description")
                        .and_then(|d| d.as_str())
                        .unwrap_or("")
                        .to_string(),
                    input_schema: t
                        .get("inputSchema")
                        .cloned()
                        .unwrap_or_else(|| json!({})),
                });
            }
        }
        self.tools = tools;
        Ok(())
    }

    /// Chama uma ferramenta e devolve o resultado cru.
    pub fn call_tool(&mut self, name: &str, args: Value) -> Result<Value> {
        if !self.initialized {
            bail!("cliente MCP nao inicializado");
        }
        let res = self.request("tools/call", json!({"name": name, "arguments": args}))?;
        if let Some(err) = res.get("isError").and_then(|e| e.as_bool()) {
            if err {
                bail!("ferramenta MCP '{name}' retornou erro: {res}");
            }
        }
        Ok(res)
    }

    /// Extrai o texto concatenado de um resultado MCP.
    pub fn result_text(res: &Value) -> String {
        let mut s = String::new();
        if let Some(items) = res.get("content").and_then(|c| c.as_array()) {
            for it in items {
                if let Some(t) = it.get("text").and_then(|t| t.as_str()) {
                    s.push_str(t);
                }
            }
        }
        s
    }
}

impl Drop for McpClient {
    fn drop(&mut self) {
        if let Transport::Stdio { child, .. } = &mut self.transport {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const STUB: &str = r#"
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        out = {"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"stub","version":"0.1"}}}
    elif method == "tools/list":
        out = {"jsonrpc":"2.0","id":mid,"result":{"tools":[{"name":"echo","description":"repetidor","inputSchema":{"type":"object"}}]}}
    elif method == "tools/call":
        txt = str(msg["params"]["arguments"].get("text",""))
        out = {"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":txt}],"isError":False}}
    elif mid is None:
        continue
    else:
        out = {"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"metodo desconhecido"}}
    print(json.dumps(out), flush=True)
"#;

    fn stub_cfg() -> McpServerConfig {
        McpServerConfig {
            name: "stub".into(),
            command: Some("python3".into()),
            args: vec!["-u".into(), "-c".into(), STUB.into()],
            env: BTreeMap::new(),
            url: None,
            enabled: true,
        }
    }

    #[test]
    fn stdio_handshake_and_tool_call() {
        let mut c = McpClient::start(&stub_cfg()).expect("servidor stub deve iniciar");
        c.initialize().expect("handshake deve funcionar");
        assert_eq!(c.tools().len(), 1);
        assert_eq!(c.tools()[0].name, "echo");
        let res = c
            .call_tool("echo", json!({"text": "ping-mark"}))
            .expect("chamada deve funcionar");
        assert_eq!(McpClient::result_text(&res), "ping-mark");
    }

    #[test]
    fn config_parses_mcp_servers_section() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("config.yaml");
        std::fs::write(
            &path,
            "mcp_servers:\n  graphify_local:\n    command: graphify-mcp\n    args: [\"--stdio\"]\n    enabled: true\n  desligado:\n    command: nada\n    enabled: false\n",
        )
        .unwrap();
        let servers = load_mcp_servers(&path).unwrap();
        assert_eq!(servers.len(), 1);
        assert_eq!(servers[0].name, "graphify_local");
        assert_eq!(servers[0].command.as_deref(), Some("graphify-mcp"));
        assert_eq!(servers[0].args, vec!["--stdio".to_string()]);
    }
}
