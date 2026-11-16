//! Cliente MCP (Model Context Protocol) sobre stdio e HTTP.
//!
//! Le a secao `mcp_servers:` do `config.yaml` do Hermes (resolvido via XDG) e
//! fala JSON-RPC 2.0 delimitado por linha com o servidor escolhido.
//! O estado ligado/desligado vem do `config.json` do MARK, escrito pelo modal
//! Plugins (`mcp_server_state`).

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

/// Prefixo do nome qualificado usado no catalogo de ferramentas do Engineer.
pub const MCP_TOOL_PREFIX: &str = "mcp__";

impl McpTool {
    /// Nome unico no catalogo: `mcp__servidor__ferramenta`.
    ///
    /// Servidores diferentes podem publicar o mesmo nome de ferramenta, entao o
    /// catalogo sempre qualifica com o servidor de origem.
    pub fn qualified_name(&self) -> String {
        format!("{MCP_TOOL_PREFIX}{}__{}", self.server, self.name)
    }
}

/// Separa `mcp__servidor__ferramenta` em `(servidor, ferramenta)`.
pub fn split_qualified_name(qualified: &str) -> Option<(String, String)> {
    let rest = qualified.strip_prefix(MCP_TOOL_PREFIX)?;
    let (server, tool) = rest.split_once("__")?;
    if server.is_empty() || tool.is_empty() {
        return None;
    }
    Some((server.to_string(), tool.to_string()))
}

/// Aplica o estado persistido pela UI (`mcp_server_state`) a uma lista de servidores.
///
/// Um servidor desativado no modal Plugins nao e carregado: suas ferramentas
/// simplesmente nao entram no registry do `mark-engineer`.
pub fn apply_enabled_state(
    servers: Vec<McpServerConfig>,
    state: &std::collections::HashMap<String, bool>,
) -> Vec<McpServerConfig> {
    servers
        .into_iter()
        .filter(|server| *state.get(&server.name).unwrap_or(&true))
        .collect()
}

/// Le `mcp_server_state` do config.json do MARK (escrito pelo modal Plugins).
pub fn read_mark_state(path: &Path) -> std::collections::HashMap<String, bool> {
    let mut out = std::collections::HashMap::new();
    let Ok(raw) = std::fs::read_to_string(path) else {
        return out;
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return out;
    };
    if let Some(map) = value.get("mcp_server_state").and_then(|v| v.as_object()) {
        for (name, enabled) in map {
            out.insert(name.clone(), enabled.as_bool().unwrap_or(true));
        }
    }
    out
}

/// Carrega os servidores do Hermes, aplica o estado do MARK e devolve so os ativos.
pub fn load_enabled_servers(
    hermes_config: &Path,
    mark_config: &Path,
) -> Result<Vec<McpServerConfig>> {
    let servers = load_mcp_servers(hermes_config)?;
    let state = read_mark_state(mark_config);
    Ok(apply_enabled_state(servers, &state))
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

/// Conjunto de clientes MCP ativos com o catalogo agregado de ferramentas.
///
/// So entram aqui os servidores que passaram por `load_enabled_servers`: os
/// desativados no modal Plugins nunca sao iniciados nem expostos.
pub struct McpRegistry {
    clients: Vec<McpClient>,
    tools: Vec<McpTool>,
    skipped: Vec<(String, String)>,
}

impl McpRegistry {
    /// Registry vazio: usado quando nenhum servidor MCP esta habilitado.
    pub fn empty() -> Self {
        Self {
            clients: Vec::new(),
            tools: Vec::new(),
            skipped: Vec::new(),
        }
    }

    /// Inicia cada servidor e faz o handshake, agregando as ferramentas.
    ///
    /// Um servidor que falha ao subir nao derruba o loop: vai para `skipped`
    /// com o motivo real, para a UI poder reportar honestamente.
    pub fn start(configs: &[McpServerConfig]) -> Self {
        let mut registry = Self::empty();
        for cfg in configs {
            match McpClient::start(cfg).and_then(|mut client| {
                client.initialize()?;
                Ok(client)
            }) {
                Ok(client) => {
                    registry.tools.extend(client.tools().iter().cloned());
                    registry.clients.push(client);
                }
                Err(err) => registry
                    .skipped
                    .push((cfg.name.clone(), format!("{err:#}"))),
            }
        }
        registry.tools.sort_by(|a, b| a.qualified_name().cmp(&b.qualified_name()));
        registry
    }

    /// Ferramentas agregadas de todos os servidores ativos.
    pub fn tools(&self) -> &[McpTool] {
        &self.tools
    }

    /// Nomes dos servidores que responderam ao handshake.
    pub fn servers(&self) -> Vec<String> {
        self.clients
            .iter()
            .map(|client| client.server().to_string())
            .collect()
    }

    /// Servidores habilitados que falharam ao iniciar, com o motivo.
    pub fn skipped(&self) -> &[(String, String)] {
        &self.skipped
    }

    /// Indica se nenhum servidor ativo publicou ferramentas.
    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    /// Executa uma ferramenta pelo nome qualificado do catalogo.
    pub fn call(&mut self, qualified: &str, args: Value) -> Result<Value> {
        let (server, tool) = split_qualified_name(qualified)
            .with_context(|| format!("nome de ferramenta MCP invalido: {qualified}"))?;
        self.call_server_tool(&server, &tool, args)
    }

    /// Executa uma ferramenta de um servidor ativo.
    pub fn call_server_tool(&mut self, server: &str, tool: &str, args: Value) -> Result<Value> {
        let client = self
            .clients
            .iter_mut()
            .find(|client| client.server() == server)
            .with_context(|| format!("servidor MCP '{server}' nao esta ativo"))?;
        client.call_tool(tool, args)
    }
}

/// Servidor MCP de teste: ecoa o campo `text` recebido.
///
/// Visivel apenas em builds de teste, compartilhado entre `mcp` e `engineer`
/// para que o teste ponta-a-ponta use o mesmo protocolo real.
#[cfg(test)]
pub(crate) mod testing {
    use super::*;

    pub const STDIO_STUB: &str = r#"
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
        name = msg["params"].get("name","")
        if name != "echo":
            out = {"jsonrpc":"2.0","id":mid,"error":{"code":-32602,"message":"ferramenta desconhecida: " + str(name)}}
        else:
            txt = str(msg["params"]["arguments"].get("text",""))
            out = {"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":txt}],"isError":False}}
    elif mid is None:
        continue
    else:
        out = {"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"metodo desconhecido"}}
    print(json.dumps(out), flush=True)
"#;

    /// Configuracao stdio apontando para o servidor de teste.
    pub fn stub_config(name: &str) -> McpServerConfig {
        McpServerConfig {
            name: name.to_string(),
            command: Some("python3".to_string()),
            args: vec!["-u".to_string(), "-c".to_string(), STDIO_STUB.to_string()],
            env: BTreeMap::new(),
            url: None,
            enabled: true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::testing::stub_config;
    use super::*;

    fn stub_cfg() -> McpServerConfig {
        stub_config("stub")
    }

    #[test]
    fn stdio_handshake_and_tool_call() {
        let mut c = McpClient::start(&stub_cfg()).expect("servidor stub deve iniciar");
        c.initialize().expect("handshake deve funcionar");
        assert_eq!(c.tools().len(), 1);
        assert_eq!(c.tools()[0].name, "echo");
        assert_eq!(c.tools()[0].qualified_name(), "mcp__stub__echo");
        let res = c
            .call_tool("echo", json!({"text": "ping-mark"}))
            .expect("chamada deve funcionar");
        assert_eq!(McpClient::result_text(&res), "ping-mark");
    }

    #[test]
    fn registry_splits_qualified_names() {
        assert_eq!(
            split_qualified_name("mcp__graphify__search"),
            Some(("graphify".to_string(), "search".to_string()))
        );
        assert_eq!(split_qualified_name("search"), None);
        assert_eq!(split_qualified_name("mcp__sem_ferramenta"), None);
        assert_eq!(split_qualified_name("mcp____vazio"), None);
    }

    #[test]
    fn registry_executes_a_tool_over_stdio() {
        let mut registry = McpRegistry::start(&[stub_cfg()]);
        assert_eq!(registry.servers(), vec!["stub".to_string()]);
        assert_eq!(registry.tools().len(), 1);
        assert!(registry.skipped().is_empty());
        let res = registry
            .call("mcp__stub__echo", json!({"text": "ponte"}))
            .expect("chamada pelo nome qualificado");
        assert_eq!(McpClient::result_text(&res), "ponte");
        let err = registry
            .call("mcp__ausente__echo", json!({}))
            .expect_err("servidor ausente deve falhar");
        assert!(err.to_string().contains("nao esta ativo"));
    }

    #[test]
    fn disabled_state_removes_servers_from_the_registry() {
        let tmp = tempfile::tempdir().expect("tmp");
        let hermes = tmp.path().join("config.yaml");
        std::fs::write(
            &hermes,
            "mcp_servers:\n  ligado:\n    command: echo\n    args: [\"a\"]\n    enabled: true\n  desligado:\n    command: echo\n    args: [\"b\"]\n    enabled: true\n",
        )
        .expect("yaml");
        let mark_cfg = tmp.path().join("config.json");

        // Sem estado da UI: os dois servidores entram.
        std::fs::write(&mark_cfg, r#"{"mcp_server_state":{}}"#).expect("json");
        let both = load_enabled_servers(&hermes, &mark_cfg).expect("load");
        assert_eq!(both.len(), 2, "estado vazio deveria manter os dois servidores");

        // Desligado no modal Plugins: sai do registry.
        std::fs::write(&mark_cfg, r#"{"mcp_server_state":{"desligado":false}}"#).expect("json");
        let filtered = load_enabled_servers(&hermes, &mark_cfg).expect("load");
        assert_eq!(filtered.len(), 1, "servidor desativado nao foi removido");
        assert_eq!(filtered[0].name, "ligado");

        // Religado: volta a aparecer.
        std::fs::write(&mark_cfg, r#"{"mcp_server_state":{"desligado":true}}"#).expect("json");
        let again = load_enabled_servers(&hermes, &mark_cfg).expect("load");
        assert_eq!(again.len(), 2, "servidor religado nao voltou ao registry");
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
