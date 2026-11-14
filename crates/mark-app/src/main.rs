//! MARK Desktop: GUI egui/eframe sobre wgpu (Vulkan) com inferencia em thread separada.

mod worker;

use std::path::PathBuf;
use std::sync::mpsc::Receiver;

use egui::{Color32, RichText};
use worker::{Ev, HfFile, HfHit, Job, Worker};

use mark_core::{HardwareProfile, InferenceConfig, ModelEntry, ReasoningLevel, Role, Vault};
use mark_tools::engineer::{ApprovalMode, EngineerSession};

const BG: Color32 = Color32::from_rgb(0x12, 0x14, 0x17);
const PANEL: Color32 = Color32::from_rgb(0x0D, 0x0F, 0x11);
const SURFACE: Color32 = Color32::from_rgb(0x16, 0x19, 0x1D);
const ELEVATED: Color32 = Color32::from_rgb(0x1A, 0x1D, 0x22);
const HOVER: Color32 = Color32::from_rgb(0x26, 0x2B, 0x33);
const BORDER: Color32 = Color32::from_rgb(0x1E, 0x22, 0x28);
const ACCENT: Color32 = Color32::from_rgb(0x00, 0xD8, 0xF6);
const OK: Color32 = Color32::from_rgb(0x22, 0xC5, 0x5E);
const TEXT: Color32 = Color32::from_rgb(0xED, 0xED, 0xED);
const DIM: Color32 = Color32::from_rgb(0x8E, 0x95, 0xA0);
const MUTED: Color32 = Color32::from_rgb(0x5F, 0x66, 0x72);
const USER_BUBBLE: Color32 = Color32::from_rgb(0x20, 0x25, 0x2C);
const GREEN: Color32 = Color32::from_rgb(0x3F, 0xB9, 0x50);
#[allow(dead_code)]
const RED: Color32 = Color32::from_rgb(0xF8, 0x51, 0x49);
#[allow(dead_code)]
const SCROLLBAR: Color32 = Color32::from_rgb(0x25, 0x2A, 0x32);

#[allow(dead_code)]
fn card(fill: Color32) -> egui::Frame {
    egui::Frame::default()
        .fill(fill)
        .stroke(egui::Stroke::new(1.0, BORDER))
        .corner_radius(10)
        .inner_margin(egui::Margin::symmetric(12, 10))
}

#[allow(dead_code)]
fn section(ui: &mut egui::Ui, title: &str) {
    ui.add_space(4.0);
    ui.label(RichText::new(title).size(10.5).color(MUTED).strong());
    ui.add_space(2.0);
}

fn nav_item(ui: &mut egui::Ui, active: bool, label: &str, badge: Option<&str>) -> bool {
    let fill = if active { HOVER } else { Color32::TRANSPARENT };
    let text = if active { ACCENT } else { TEXT };
    let mut clicked = false;
    egui::Frame::default()
        .fill(fill)
        .corner_radius(7)
        .inner_margin(egui::Margin::symmetric(8, 4))
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                let resp = ui.add(
                    egui::Label::new(RichText::new(label).size(12.5).color(text))
                        .sense(egui::Sense::click()),
                );
                clicked = resp.clicked();
                if let Some(b) = badge {
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new(b).size(9.5).color(MUTED));
                    });
                }
            });
        });
    clicked
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tab {
    Chat,
    Models,
    Vault,
    Download,
    Engineer,
}

struct Msg {
    from_user: bool,
    text: String,
}

struct App {
    tab: Tab,
    role: Role,
    reasoning: ReasoningLevel,
    models: Vec<ModelEntry>,
    selected: usize,
    messages: Vec<Msg>,
    input: String,
    busy: bool,
    status: String,
    max_tokens: u32,
    worker: Worker,
    ev_rx: Receiver<Ev>,
    fullscreen: bool,
    hw: HardwareProfile,
    vault: Option<Vault>,
    vault_pass: String,
    vault_msg: String,
    vault_keys: Vec<String>,
    new_key: String,
    new_value: String,
    hf_query: String,
    hf_hits: Vec<HfHit>,
    hf_repo: String,
    hf_files: Vec<HfFile>,
    hf_progress: Vec<String>,
    dest_external: bool,
    eng_ws: String,
    eng_cmd: String,
    eng_out: String,
    skills: usize,
    mcps: usize,
    bwrap: bool,
    gpu_ptx: Option<String>,
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        install_fonts(&cc.egui_ctx);
        let (tx_ev, ev_rx) = std::sync::mpsc::channel::<Ev>();
        let worker = Worker::spawn(tx_ev);
        worker.send(Job::LoadModels);

        let mut vault_msg = String::new();
        let vault = match Vault::open_or_create(mark_core::paths::vault_file()) {
            Ok(v) => Some(v),
            Err(e) => {
                vault_msg = format!("cofre indisponivel: {e}");
                None
            }
        };
        let skills = mark_tools::load_skills(&mark_core::paths::hermes_skills_dir()).len();
        let mcps = mark_tools::mcp::load_mcp_servers(&mark_core::paths::hermes_config_file())
            .map(|v| v.len())
            .unwrap_or(0);

        Self {
            tab: Tab::Chat,
            role: Role::General,
            reasoning: ReasoningLevel::Medium,
            models: Vec::new(),
            selected: 0,
            messages: Vec::new(),
            input: String::new(),
            busy: false,
            status: "pronto".into(),
            max_tokens: 128,
            worker,
            ev_rx,
            fullscreen: false,
            hw: HardwareProfile::detect(),
            vault,
            vault_pass: String::new(),
            vault_msg,
            vault_keys: Vec::new(),
            new_key: String::new(),
            new_value: String::new(),
            hf_query: String::new(),
            hf_hits: Vec::new(),
            hf_repo: String::new(),
            hf_files: Vec::new(),
            hf_progress: Vec::new(),
            dest_external: mark_core::paths::external_volume("hd 1tb").is_some(),
            eng_ws: mark_core::paths::default_workspace().display().to_string(),
            eng_cmd: String::new(),
            eng_out: String::new(),
            skills,
            mcps,
            bwrap: mark_tools::sandbox::bwrap_available(),
            gpu_ptx: if mark_engine::gpu::gpu_available() {
                Some(mark_engine::gpu::device_name().unwrap_or_else(|| "CUDA PTX sm_75".to_string()))
            } else {
                None
            },
        }
    }

    fn drain_events(&mut self) {
        while let Ok(ev) = self.ev_rx.try_recv() {
            match ev {
                Ev::Models(m) => {
                    self.models = cinzelar_catalogo(m);
                    self.status = format!("{} modelos locais", self.models.len());
                }
                Ev::Delta(d) => {
                    if let Some(last) = self.messages.last_mut() {
                        if !last.from_user {
                            last.text.push_str(&d);
                        }
                    }
                }
                Ev::Done {
                    prompt_tokens,
                    completion_tokens,
                } => {
                    self.busy = false;
                    self.status = match (prompt_tokens, completion_tokens) {
                        (Some(p), Some(c)) => format!("concluido: {p} prompt / {c} gerados"),
                        (None, Some(c)) => format!("concluido: {c} tokens"),
                        _ => "concluido".into(),
                    };
                }
                Ev::Error(e) => {
                    self.busy = false;
                    self.status = format!("erro: {e}");
                    self.messages.push(Msg {
                        from_user: false,
                        text: format!("[erro] {e}"),
                    });
                }
                Ev::HfHits(h) => {
                    self.status = format!("{} repositorios encontrados", h.len());
                    self.hf_hits = h;
                }
                Ev::HfFiles(f) => {
                    self.status = format!("{} arquivos no repositorio", f.len());
                    self.hf_files = f;
                }
                Ev::Progress {
                    label,
                    done,
                    total,
                } => {
                    let pct = if total > 0 {
                        (done as f64 / total as f64) * 100.0
                    } else {
                        0.0
                    };
                    let line = format!(
                        "{}: {:.1} / {:.1} MiB ({pct:.1}%)",
                        label,
                        done as f64 / 1_048_576.0,
                        total as f64 / 1_048_576.0
                    );
                    let key = format!("{label}:");
                    match self.hf_progress.iter_mut().find(|l| l.starts_with(&key)) {
                        Some(slot) => *slot = line,
                        None => self.hf_progress.push(line),
                    }
                }
                Ev::Info(m) => {
                    if !m.is_empty() {
                        self.status = m;
                    }
                }
            }
        }
    }

    fn send(&mut self) {
        let text = self.input.trim().to_string();
        if text.is_empty() || self.busy || self.models.is_empty() {
            return;
        }
        let entry = self.models[self.selected.min(self.models.len() - 1)].clone();
        let system = match self.role {
            Role::General => "Voce e o MARK, assistente tecnico direto e preciso.",
            Role::Engineer => "Voce e o MARK Engineer: responda com codigo, diffs e comandos exatos.",
            Role::Professor => "Voce e o MARK Professor: explique passo a passo, com exemplos.",
            Role::Vision => "Voce e o MARK Vision: descreva imagens e dados visuais.",
        };
        let history: Vec<(String, String)> = self
            .messages
            .chunks(2)
            .filter_map(|c| {
                let u = c.first()?.text.clone();
                let a = c.get(1).map(|m| m.text.clone()).unwrap_or_default();
                Some((u, a))
            })
            .collect();
        self.messages.push(Msg {
            from_user: true,
            text: text.clone(),
        });
        self.messages.push(Msg {
            from_user: false,
            text: String::new(),
        });
        self.input.clear();
        self.busy = true;
        self.status = format!("gerando com {}", entry.name);
        self.worker.send(Job::Chat {
            entry,
            system: Some(system.to_string()),
            history,
            prompt: text,
            reasoning: self.reasoning,
            max_tokens: self.max_tokens,
        });
    }

    fn top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("MARK").color(ACCENT).size(20.0).strong());
            ui.label(RichText::new("Desktop").color(DIM).size(12.0));
            ui.add_space(18.0);
            for (tab, name) in [
                (Tab::Chat, "Conversa"),
                (Tab::Models, "Modelos & Papeis"),
                (Tab::Vault, "Cofre"),
                (Tab::Download, "Baixar do Hugging Face"),
                (Tab::Engineer, "Engineer"),
            ] {
                if ui
                    .selectable_label(self.tab == tab, RichText::new(name).size(13.0))
                    .clicked()
                {
                    self.tab = tab;
                }
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let label = if self.fullscreen {
                    "Sair da Tela Cheia"
                } else {
                    "Tela Cheia (F11)"
                };
                if ui.button(label).clicked() {
                    self.fullscreen = !self.fullscreen;
                    ui.ctx()
                        .send_viewport_cmd(egui::ViewportCommand::Fullscreen(self.fullscreen));
                }
            });
        });
    }

    fn sidebar(&mut self, ui: &mut egui::Ui) {
        ui.add_space(6.0);
        section(ui, "AGENTS & MODES");
        for role in Role::ALL {
            if nav_item(ui, self.role == role, role.label(), None) {
                self.role = role;
            }
        }
        ui.add_space(4.0);
        ui.label(RichText::new("Raciocinio").color(DIM).size(11.0));
        for level in [
            ReasoningLevel::Instant,
            ReasoningLevel::Medium,
            ReasoningLevel::High,
        ] {
            let badge = match level {
                ReasoningLevel::Instant => "1x",
                ReasoningLevel::Medium => "2x",
                ReasoningLevel::High => "3x",
            };
            if nav_item(ui, self.reasoning == level, level.label(), Some(badge)) {
                self.reasoning = level;
            }
        }

        ui.add_space(12.0);
        ui.separator();
        section(ui, "SPACE & SYSTEM");
        ui.label(
            RichText::new(format!(
                "RAM {:.1} GiB",
                self.hw.total_ram_bytes as f64 / 1_073_741_824.0
            ))
            .size(12.0),
        );
        match &self.gpu_ptx {
            Some(name) => {
                ui.label(RichText::new("GPU PTX sm_75").size(12.0).color(OK));
                ui.label(RichText::new(name).size(11.0).color(DIM));
            }
            None => {
                ui.label(
                    RichText::new("CPU AVX2+FMA+POPCNT")
                        .size(12.0)
                        .color(ACCENT),
                );
                ui.label(RichText::new("GPU indisponivel").size(11.0).color(DIM));
            }
        }
        ui.label(
            RichText::new(format!("{} nucleos", self.hw.cpu_cores))
                .size(11.0)
                .color(DIM),
        );
        ui.label(
            RichText::new(format!("skills {} | mcp {}", self.skills, self.mcps))
                .size(11.0)
                .color(DIM),
        );

        ui.add_space(12.0);
        ui.separator();
        section(ui, "RECENT CHATS");
        let mut open: Option<usize> = None;
        for (i, m) in self.messages.iter().enumerate() {
            if m.from_user {
                let snippet: String = m.text.chars().take(28).collect();
                if ui.selectable_label(false, snippet).clicked() {
                    open = Some(i);
                }
            }
        }
        if let Some(i) = open {
            self.messages.truncate(i + 1);
        }
        if ui.button("Nova conversa").clicked() {
            self.messages.clear();
            self.status = "conversa nova".into();
        }
    }

    fn chat_view(&mut self, ui: &mut egui::Ui) {
        let width = ui.available_width();
        egui::ScrollArea::vertical()
            .stick_to_bottom(true)
            .auto_shrink([false, false])
            .max_height(ui.available_height() - 132.0)
            .show(ui, |ui| {
                for m in &self.messages {
                    if m.from_user {
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Min), |ui| {
                            egui::Frame::default()
                                .fill(USER_BUBBLE)
                                .corner_radius(8)
                                .inner_margin(egui::Margin::symmetric(14, 10))
                                .show(ui, |ui| {
                                    ui.set_max_width((width * 0.72).max(240.0));
                                    ui.label(RichText::new(&m.text).size(13.0).color(TEXT));
                                });
                        });
                    } else {
                        ui.add_space(4.0);
                        ui.label(RichText::new("MARK").size(11.0).color(ACCENT).strong());
                        ui.add_space(2.0);
                        render_markdown(ui, &m.text);
                        ui.add_space(6.0);
                    }
                }
            });
        ui.add_space(6.0);
        egui::Frame::default()
            .fill(SURFACE)
            .stroke(egui::Stroke::new(1.0, BORDER))
            .corner_radius(10)
            .inner_margin(egui::Margin::symmetric(14, 10))
            .show(ui, |ui| {
                ui.add(
                    egui::TextEdit::multiline(&mut self.input)
                        .desired_rows(2)
                        .desired_width(f32::INFINITY)
                        .hint_text("Message MARK"),
                );
                ui.horizontal(|ui| {
                    let can = !self.busy && !self.input.trim().is_empty() && !self.models.is_empty();
                    if ui.add_enabled(can, egui::Button::new("Send")).clicked() {
                        self.send();
                    }
                    if ui.add_enabled(self.busy, egui::Button::new("Stop")).clicked() {
                        self.worker.stop();
                        self.busy = false;
                        self.status = "interrompido".into();
                    }
                    ui.add(egui::Slider::new(&mut self.max_tokens, 16..=512).text("max tokens"));
                    let mdl = self
                        .models
                        .get(self.selected)
                        .map(|m| m.name.clone())
                        .unwrap_or_else(|| "no model".into());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new(mdl).size(11.0).color(MUTED));
                        ui.label(RichText::new("·").size(11.0).color(MUTED));
                        ui.label(RichText::new(if self.gpu_ptx.is_some() { "GPU PTX sm_75" } else { "CPU AVX2" }).size(11.0).color(DIM));
                        ui.label(RichText::new("·").size(11.0).color(MUTED));
                        ui.label(RichText::new(self.reasoning.label()).size(11.0).color(DIM));
                    });
                });
            });
    }

    fn models_view(&mut self, ui: &mut egui::Ui) {
        ui.label(RichText::new("Modelos disponiveis").size(15.0).strong());
        ui.label(
            RichText::new("Somente modelos locais reais e da colecao Mark/DeepSeek.")
                .size(11.0)
                .color(DIM),
        );
        ui.add_space(6.0);
        if self.models.is_empty() {
            ui.label("Nenhum modelo local encontrado.");
        }
        egui::ScrollArea::vertical()
            .max_height(300.0)
            .show(ui, |ui| {
                for (i, m) in self.models.iter().enumerate() {
                    let fit = m
                        .size_bytes
                        .map(|s| format!("{:.1} GiB", s as f64 / 1_073_741_824.0))
                        .unwrap_or_else(|| "-".into());
                    let txt = format!("{}  [{}]  {}", m.name, m.backend.label(), fit);
                    if ui.selectable_label(self.selected == i, txt).clicked() {
                        self.selected = i;
                    }
                }
            });
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            if ui.button("Recarregar catalogo").clicked() {
                self.worker.send(Job::LoadModels);
            }
            if let Some(m) = self.models.get(self.selected) {
                ui.label(RichText::new(format!("ctx {} tokens", m.context_window)).color(DIM));
                if let Some(p) = &m.path {
                    ui.label(RichText::new(p).size(10.0).color(DIM));
                }
            }
        });
        ui.add_space(8.0);
        ui.separator();
        ui.label(RichText::new("Papel -> modelo primario").size(13.0).strong());
        let cfg = InferenceConfig::default();
        let app_cfg = mark_core::AppConfig::load().unwrap_or_default();
        for role in Role::ALL {
            let rc = app_cfg.role(role);
            let shown = if rc.primary_model.is_empty() {
                self.models
                    .get(self.selected)
                    .map(|m| m.name.clone())
                    .unwrap_or_else(|| "nao definido".into())
            } else {
                rc.primary_model
            };
            ui.horizontal(|ui| {
                ui.label(format!("{}:", role.label()));
                ui.label(RichText::new(shown).color(ACCENT));
            });
        }
        ui.label(
            RichText::new(format!(
                "threads {} | batch {} | ubatch {} | mmap {}",
                cfg.num_thread, cfg.num_batch, cfg.physical_batch_size, cfg.use_mmap
            ))
            .size(11.0)
            .color(DIM),
        );
    }

    fn vault_view(&mut self, ui: &mut egui::Ui) {
        ui.label(RichText::new("Cofre Argon2id + AES-256-GCM").size(15.0).strong());
        ui.label(
            RichText::new("Protege chaves de API, conversas e memoria persistida.")
                .size(11.0)
                .color(DIM),
        );
        ui.add_space(8.0);
        if !self.vault_msg.is_empty() {
            ui.label(RichText::new(&self.vault_msg).color(DIM).size(11.0));
        }
        let unlocked = self.vault.as_ref().map(|v| v.is_unlocked()).unwrap_or(false);
        ui.horizontal(|ui| {
            ui.add(
                egui::TextEdit::singleline(&mut self.vault_pass)
                    .password(true)
                    .hint_text("senha mestra")
                    .desired_width(220.0),
            );
            if ui.button("Destravar").clicked() {
                let pass = self.vault_pass.clone();
                self.vault_msg = match self.vault.as_mut() {
                    Some(v) => match v.unlock(&pass) {
                        Ok(()) => {
                            self.vault_keys = v.keys();
                            self.vault_pass.clear();
                            "cofre destravado".into()
                        }
                        Err(e) => format!("{e}"),
                    },
                    None => "cofre indisponivel".into(),
                };
            }
            if unlocked && ui.button("Bloquear").clicked() {
                if let Some(v) = self.vault.as_mut() {
                    v.lock();
                    self.vault_keys.clear();
                    self.vault_msg = "cofre bloqueado".into();
                }
            }
        });
        ui.add_space(8.0);
        if unlocked {
            ui.horizontal(|ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.new_key)
                        .hint_text("nome da chave")
                        .desired_width(180.0),
                );
                ui.add(
                    egui::TextEdit::singleline(&mut self.new_value)
                        .password(true)
                        .hint_text("valor")
                        .desired_width(240.0),
                );
                if ui.button("Gravar").clicked() {
                    let name = self.new_key.trim().to_string();
                    if !name.is_empty() && !self.new_value.is_empty() {
                        let value = self.new_value.clone();
                        self.vault_msg = match self.vault.as_mut() {
                            Some(v) => match v.put(&name, value.as_bytes()) {
                                Ok(()) => match v.save() {
                                    Ok(()) => {
                                        self.vault_keys = v.keys();
                                        self.new_key.clear();
                                        self.new_value.clear();
                                        "chave gravada".into()
                                    }
                                    Err(e) => format!("{e}"),
                                },
                                Err(e) => format!("{e}"),
                            },
                            None => "cofre indisponivel".into(),
                        };
                    }
                }
            });
            ui.add_space(6.0);
            ui.label(RichText::new("Chaves no cofre").size(12.0).strong());
            for k in self.vault_keys.clone() {
                ui.label(RichText::new(k).color(OK).size(12.0));
            }
        }
    }

    fn download_view(&mut self, ui: &mut egui::Ui) {
        ui.label(RichText::new("Baixar do Hugging Face").size(15.0).strong());
        ui.horizontal(|ui| {
            ui.add(
                egui::TextEdit::singleline(&mut self.hf_query)
                    .hint_text("buscar repositorio")
                    .desired_width(320.0),
            );
            if ui.button("Buscar").clicked() {
                self.worker.send(Job::HfSearch(self.hf_query.clone()));
            }
            if ui.button("Colecao Oficial Miceworks").clicked() {
                self.hf_query = "miceworks".into();
                self.worker.send(Job::HfSearch("miceworks".into()));
            }
        });
        ui.checkbox(&mut self.dest_external, "Gravar no HD 1TB (senao NVMe)");
        ui.add_space(6.0);
        egui::ScrollArea::vertical()
            .max_height(150.0)
            .show(ui, |ui| {
                let mut pick: Option<String> = None;
                for h in &self.hf_hits {
                    let label = format!("{}  ({} downloads)", h.id, h.downloads);
                    if ui.selectable_label(self.hf_repo == h.id, label).clicked() {
                        pick = Some(h.id.clone());
                    }
                }
                if let Some(id) = pick {
                    self.hf_repo = id.clone();
                    self.worker.send(Job::HfFiles(id));
                }
            });
        ui.separator();
        if !self.hf_repo.is_empty() {
            ui.label(RichText::new(&self.hf_repo).color(ACCENT).size(12.0));
        }
        let mut dl: Option<HfFile> = None;
        egui::ScrollArea::vertical()
            .max_height(200.0)
            .show(ui, |ui| {
                for f in &self.hf_files {
                    ui.horizontal(|ui| {
                        let mib = f.size as f64 / 1_048_576.0;
                        ui.label(format!("{}  {:.1} MiB", f.path, mib));
                        if ui.button("Baixar").clicked() {
                            dl = Some(f.clone());
                        }
                    });
                }
            });
        if let Some(f) = dl {
            let dest = download_dest(&f.path, self.dest_external);
            self.worker.send(Job::Download {
                repo: self.hf_repo.clone(),
                file: f.path.clone(),
                size: f.size,
                dest,
            });
        }
        for l in &self.hf_progress {
            ui.label(RichText::new(l).size(11.0).color(OK));
        }
    }

    fn engineer_view(&mut self, ui: &mut egui::Ui) {
        ui.label(RichText::new("Modo Engineer").size(15.0).strong());
        ui.label(
            RichText::new("Comandos isolados em sandbox bwrap, sem rede por padrao.")
                .size(11.0)
                .color(DIM),
        );
        ui.add(
            egui::TextEdit::singleline(&mut self.eng_ws)
                .hint_text("workspace")
                .desired_width(420.0),
        );
        ui.horizontal(|ui| {
            ui.add(
                egui::TextEdit::singleline(&mut self.eng_cmd)
                    .hint_text("comando")
                    .desired_width(420.0),
            );
            if ui.button("Executar").clicked() {
                let ws = PathBuf::from(self.eng_ws.clone());
                let cmd = self.eng_cmd.trim().to_string();
                if !cmd.is_empty() {
                    let mut s = EngineerSession::new(ws, ApprovalMode::FullAuto);
                    self.eng_out = match s.execute(mark_tools::Action {
                        kind: mark_tools::ActionKind::Shell,
                        path: None,
                        query: None,
                        content: None,
                        command: vec!["sh".into(), "-c".into(), cmd],
                    }) {
                        Ok(mark_tools::StepOutcome::Command(r)) => format!(
                            "status {:?} em {:.2}s\n{}\n{}",
                            r.status,
                            r.duration.as_secs_f64(),
                            r.stdout,
                            r.stderr
                        ),
                        Ok(other) => format!("{other:?}"),
                        Err(e) => format!("erro: {e:#}"),
                    };
                }
            }
        });
        ui.add_space(6.0);
        egui::ScrollArea::vertical().show(ui, |ui| {
            ui.label(RichText::new(&self.eng_out).monospace().size(12.0));
        });
    }

    fn status_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let (bwrap_txt, bwrap_col) = if self.bwrap {
                ("BWRAP ativo", GREEN)
            } else {
                ("BWRAP ausente", DIM)
            };
            ui.label(RichText::new(bwrap_txt).size(11.0).color(bwrap_col));
            ui.separator();
            let unlocked = self.vault.as_ref().map(|v| v.is_unlocked()).unwrap_or(false);
            let (c_txt, c_col) = if unlocked {
                ("CRYPTO destravado", OK)
            } else {
                ("CRYPTO bloqueado", DIM)
            };
            ui.label(RichText::new(c_txt).size(11.0).color(c_col));
            ui.separator();
            let ctx = self
                .models
                .get(self.selected)
                .map(|m| m.context_window)
                .unwrap_or(0);
            ui.label(RichText::new(format!("CTX {ctx}")).size(11.0).color(ACCENT));
            ui.separator();
            ui.label(RichText::new(&self.status).size(11.0).color(DIM));
        });
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.drain_events();
        let ctx = ui.ctx().clone();

        if ctx.input(|i| i.key_pressed(egui::Key::F11)) {
            self.fullscreen = !self.fullscreen;
            ctx.send_viewport_cmd(egui::ViewportCommand::Fullscreen(self.fullscreen));
        }
        let mut visuals = egui::Visuals::dark();
        visuals.panel_fill = BG;
        visuals.window_fill = SURFACE;
        visuals.extreme_bg_color = ELEVATED;
        visuals.faint_bg_color = SURFACE;
        visuals.override_text_color = Some(TEXT);
        visuals.selection.bg_fill = HOVER;
        visuals.selection.stroke = egui::Stroke::new(1.0, ACCENT);
        visuals.hyperlink_color = ACCENT;
        visuals.widgets.noninteractive.bg_stroke = egui::Stroke::new(1.0, BORDER);
        visuals.widgets.inactive.bg_fill = SURFACE;
        visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1.0, BORDER);
        visuals.widgets.hovered.bg_fill = HOVER;
        visuals.widgets.hovered.bg_stroke = egui::Stroke::new(1.0, ACCENT);
        visuals.widgets.active.bg_fill = ELEVATED;
        visuals.widgets.active.bg_stroke = egui::Stroke::new(1.0, ACCENT);
        visuals.window_corner_radius = egui::CornerRadius::same(10);
        visuals.widgets.inactive.corner_radius = egui::CornerRadius::same(6);
        visuals.widgets.hovered.corner_radius = egui::CornerRadius::same(6);
        visuals.widgets.active.corner_radius = egui::CornerRadius::same(6);
        ctx.set_visuals(visuals);

        egui::Panel::top("top")
            .exact_size(46.0)
            .frame(egui::Frame::default().fill(PANEL).inner_margin(egui::Margin::symmetric(12, 8)))
            .show(ui, |ui| self.top_bar(ui));

        egui::Panel::bottom("status")
            .exact_size(30.0)
            .frame(egui::Frame::default().fill(PANEL).inner_margin(egui::Margin::symmetric(12, 5)))
            .show(ui, |ui| self.status_bar(ui));

        egui::Panel::left("side")
            .exact_size(224.0)
            .resizable(false)
            .frame(egui::Frame::default().fill(PANEL).inner_margin(egui::Margin::symmetric(12, 10)))
            .show(ui, |ui| {
                egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| self.sidebar(ui));
            });

        egui::CentralPanel::default()
            .frame(egui::Frame::default().fill(BG).inner_margin(egui::Margin::symmetric(16, 12)))
            .show(ui, |ui| {
                ui.set_min_size(ui.available_size());
                match self.tab {
                    Tab::Chat => self.chat_view(ui),
                    Tab::Models => self.models_view(ui),
                    Tab::Vault => self.vault_view(ui),
                    Tab::Download => self.download_view(ui),
                    Tab::Engineer => self.engineer_view(ui),
                }
            });

        if self.busy {
            ctx.request_repaint_after(std::time::Duration::from_millis(80));
        }
    }
}


fn render_markdown(ui: &mut egui::Ui, text: &str) {
    let mut in_code = false;
    let mut code = String::new();
    let mut lang = String::new();
    for line in text.lines() {
        if line.trim_start().starts_with("```") {
            if in_code {
                code_block(ui, &lang, &code);
                code.clear();
                lang.clear();
                in_code = false;
            } else {
                lang = line.trim_start().trim_start_matches("```").trim().to_string();
                in_code = true;
            }
            continue;
        }
        if in_code {
            code.push_str(line);
            code.push('\n');
        } else if !line.trim().is_empty() {
            ui.label(RichText::new(line).size(13.0).color(TEXT));
        }
    }
    if in_code && !code.is_empty() {
        code_block(ui, &lang, &code);
    }
}

fn code_block(ui: &mut egui::Ui, lang: &str, code: &str) {
    egui::Frame::default()
        .fill(egui::Color32::from_rgb(0x0B, 0x0D, 0x0F))
        .stroke(egui::Stroke::new(1.0, BORDER))
        .corner_radius(8)
        .inner_margin(egui::Margin::symmetric(12, 8))
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new(if lang.is_empty() { "code" } else { lang }).size(11.0).color(DIM));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button(RichText::new("Copy").size(11.0).color(ACCENT)).clicked() {
                        ui.ctx().copy_text(code.to_string());
                    }
                });
            });
            ui.label(RichText::new(code.trim_end()).monospace().size(12.0).color(TEXT));
        });
}

fn cinzelar_catalogo(entries: Vec<ModelEntry>) -> Vec<ModelEntry> {
    let mut out: Vec<ModelEntry> = Vec::new();
    for e in entries {
        let n = e.name.to_ascii_lowercase();
        let auxiliar = n.starts_with("isometric_")
            || n.starts_with("calib_")
            || n.starts_with("mark_calibration")
            || n.starts_with("model-0000")
            || n.ends_with(".part");
        if auxiliar {
            continue;
        }
        if e.backend == mark_core::Backend::Ollama {
            let permitido = n.starts_with("mark")
                || n.contains("deepseek")
                || n.contains("coder-v2")
                || n.contains("v2-lite");
            if !permitido {
                continue;
            }
        }
        if out.iter().any(|x| x.name == e.name) {
            continue;
        }
        out.push(e);
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    out
}

fn download_dest(file: &str, external: bool) -> PathBuf {
    let name = file.rsplit('/').next().unwrap_or(file);
    if external {
        if let Some(vol) = mark_core::paths::external_volume("hd 1tb") {
            return vol.join("mark_checkpoints").join(name);
        }
    }
    mark_core::paths::models_dir().join(name)
}

fn install_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    for path in [
        "/usr/share/fonts/inter/InterVariable.ttf",
        "/usr/share/fonts/inter/Inter.ttc",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ] {
        if let Ok(bytes) = std::fs::read(path) {
            fonts.font_data.insert(
                "mark-sans".to_owned(),
                std::sync::Arc::new(egui::FontData::from_owned(bytes)),
            );
            if let Some(list) = fonts.families.get_mut(&egui::FontFamily::Proportional) {
                list.insert(0, "mark-sans".to_owned());
            }
            break;
        }
    }
    ctx.set_fonts(fonts);
}

fn main() -> eframe::Result<()> {
    std::env::set_var("WGPU_POWER_PREF", "high");
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1200.0, 780.0])
            .with_min_inner_size([880.0, 560.0])
            .with_title("MARK Desktop"),
        renderer: eframe::Renderer::Wgpu,
        ..Default::default()
    };
    eframe::run_native(
        "MARK Desktop",
        options,
        Box::new(|cc| Ok(Box::new(App::new(cc)))),
    )
}
