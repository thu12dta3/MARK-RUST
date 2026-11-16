//! Ferramentas reais do MARK: sandbox bwrap, skills do Hermes, MCP, web e Modo Engineer.

pub mod engineer;
pub mod hf;
pub mod mcp;
pub mod sandbox;
pub mod palette;
pub mod skills;
pub mod web;

pub use engineer::{
    apply_unified_diff, native_tools, Action, ActionKind, EngineerSession, StepOutcome,
    ToolDescriptor, ToolOrigin,
};
pub use mcp::{
    apply_enabled_state, load_enabled_servers, load_mcp_servers, read_mark_state,
    split_qualified_name, McpClient, McpRegistry, McpServerConfig, McpTool, MCP_TOOL_PREFIX,
};
pub use sandbox::{bwrap_available, SandboxConfig, SandboxResult};
pub use palette::{fuzzy_score, Command, PaletteAction, Registry};
pub use skills::{load_skills, render_skill, SkillInfo};
pub use web::{web_fetch, web_search, FetchResult, SearchHit};
