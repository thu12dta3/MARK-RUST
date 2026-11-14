//! MARK Desktop: GUI egui/eframe sobre wgpu (Vulkan) com inferencia em thread separada.

mod worker;

use std::path::PathBuf;
use std::sync::mpsc::Receiver;

use egui::{Color32, RichText};
use worker::{Ev, HfFile, HfHit, Job, Worker};

use mark_core::{HardwareProfile, InferenceConfig, ModelEntry, ReasoningLevel, Role, Vault};
use mark_tools::engineer::{ApprovalMode, EngineerSession};

const BG: Color32 = Color32::from_rgb(0x0D, 0x11, 0x17);
const PANEL: Color32 = Color32::from_rgb(0x16, 0x1B, 0x22);
const ACCENT: Color32 = Color32::from_rgb(0x00, 0xD4, 0xFF);
const OK: Color32 = Color32::from_rgb(0x22, 0xC5, 0x5E);
const DIM: Color32 = Color32::from_rgb(0x8B, 0x94, 0x9E);

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
        ui.label(RichText::new("AGENTES & MODOS").color(DIM).size(11.0).strong());
        for role in Role::ALL {
            if ui
                .selectable_label(self.role == role, RichText::new(role.label()).size(13.0))
                .clicked()
            {
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
            if ui
                .selectable_label(self.reasoning == level, level.label())
                .clicked()
            {
                self.reasoning = level;
            }
        }

        ui.add_space(12.0);
        ui.separator();
        ui.label(RichText::new("ESPACO & SISTEMA").color(DIM).size(11.0).strong());
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
        ui.label(RichText::new("CONVERSAS RECENTES").color(DIM).size(11.0).strong());
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
        egui::ScrollArea::vertical()
            .stick_to_bottom(true)
            .auto_shrink([false, false])
            .max_height(480.0)
            .show(ui, |ui| {
                for m in &self.messages {
                    let (who, color) = if m.from_user {
                        ("voce", ACCENT)
                    } else {
                        ("mark", OK)
                    };
                    ui.label(RichText::new(who).color(color).size(11.0).strong());
                    ui.label(RichText::new(&m.text).size(14.0));
                    ui.add_space(6.0);
                }
            });
        ui.separator();
        ui.add(
            egui::TextEdit::multiline(&mut self.input)
                .desired_rows(2)
                .desired_width(f32::INFINITY)
                .hint_text("Escreva a mensagem para o MARK"),
        );
        ui.horizontal(|ui| {
            let can = !self.busy && !self.input.trim().is_empty() && !self.models.is_empty();
            if ui.add_enabled(can, egui::Button::new("Enviar")).clicked() {
                self.send();
            }
            if ui.add_enabled(self.busy, egui::Button::new("Parar")).clicked() {
                self.worker.stop();
                self.busy = false;
                self.status = "interrompido".into();
            }
            ui.add(egui::Slider::new(&mut self.max_tokens, 16..=512).text("max tokens"));
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
                ("BWRAP ativo", OK)
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
        visuals.window_fill = PANEL;
        visuals.override_text_color = Some(Color32::from_rgb(0xC9, 0xD1, 0xD9));
        ctx.set_visuals(visuals);

        ui.vertical(|ui| {
            egui::Frame::default()
                .fill(PANEL)
                .inner_margin(egui::Margin::symmetric(10, 8))
                .show(ui, |ui| self.top_bar(ui));

            let body_h = (ui.available_height() - 34.0).max(200.0);
            ui.horizontal_top(|ui| {
                egui::Frame::default()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::symmetric(10, 8))
                    .show(ui, |ui| {
                        ui.allocate_ui_with_layout(
                            egui::vec2(216.0, body_h),
                            egui::Layout::top_down(egui::Align::Min),
                            |ui| self.sidebar(ui),
                        );
                    });
                ui.add_space(8.0);
                egui::Frame::default().fill(BG).show(ui, |ui| {
                    ui.allocate_ui_with_layout(
                        egui::vec2(ui.available_width(), body_h),
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| match self.tab {
                            Tab::Chat => self.chat_view(ui),
                            Tab::Models => self.models_view(ui),
                            Tab::Vault => self.vault_view(ui),
                            Tab::Download => self.download_view(ui),
                            Tab::Engineer => self.engineer_view(ui),
                        },
                    );
                });
            });

            egui::Frame::default()
                .fill(PANEL)
                .inner_margin(egui::Margin::symmetric(10, 6))
                .show(ui, |ui| self.status_bar(ui));
        });

        if self.busy {
            ctx.request_repaint_after(std::time::Duration::from_millis(80));
        }
    }
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
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
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
