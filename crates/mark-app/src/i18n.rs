//! Traducoes da interface. Ingles e o idioma padrao.

/// Idiomas suportados.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lang {
    En,
    PtBr,
    Zh,
    Hi,
    Es,
    Fr,
    Ar,
}

impl Lang {
    /// Todos os idiomas na ordem exibida.
    pub const ALL: [Lang; 7] = [
        Lang::En,
        Lang::PtBr,
        Lang::Zh,
        Lang::Hi,
        Lang::Es,
        Lang::Fr,
        Lang::Ar,
    ];

    /// Codigo estavel persistido.
    pub fn code(self) -> &'static str {
        match self {
            Lang::En => "en",
            Lang::PtBr => "pt-BR",
            Lang::Zh => "zh",
            Lang::Hi => "hi",
            Lang::Es => "es",
            Lang::Fr => "fr",
            Lang::Ar => "ar",
        }
    }

    /// Nome nativo do idioma.
    pub fn label(self) -> &'static str {
        match self {
            Lang::En => "English",
            Lang::PtBr => "Portugues",
            Lang::Zh => "中文",
            Lang::Hi => "हिन्दी",
            Lang::Es => "Espanol",
            Lang::Fr => "Francais",
            Lang::Ar => "العربية",
        }
    }

    /// Converte do codigo persistido; ingles como default.
    pub fn from_code(s: &str) -> Self {
        match s.trim() {
            "pt-BR" | "pt" => Lang::PtBr,
            "zh" => Lang::Zh,
            "hi" => Lang::Hi,
            "es" => Lang::Es,
            "fr" => Lang::Fr,
            "ar" => Lang::Ar,
            _ => Lang::En,
        }
    }

    /// Texto de uma chave.
    pub fn t(self, key: Key) -> &'static str {
        use Lang::*;
        match key {
            Key::AgentsModes => match self {
                En => "AGENTS & MODES",
                PtBr => "AGENTES & MODOS",
                Zh => "代理与模式",
                Hi => "एजेंट और मोड",
                Es => "AGENTES Y MODOS",
                Fr => "AGENTS ET MODES",
                Ar => "الوكلاء والاوضاع",
            },
            Key::SpaceSystem => match self {
                En => "SPACE & SYSTEM",
                PtBr => "ESPACO & SISTEMA",
                Zh => "空间与系统",
                Hi => "स्थान और सिस्टम",
                Es => "ESPACIO Y SISTEMA",
                Fr => "ESPACE ET SYSTEME",
                Ar => "المساحة والنظام",
            },
            Key::Tools => match self {
                En => "TOOLS",
                PtBr => "FERRAMENTAS",
                Zh => "工具",
                Hi => "उपकरण",
                Es => "HERRAMIENTAS",
                Fr => "OUTILS",
                Ar => "الادوات",
            },
            Key::RecentChats => match self {
                En => "RECENT CHATS",
                PtBr => "CONVERSAS RECENTES",
                Zh => "最近对话",
                Hi => "हाल की चैट",
                Es => "CONVERSACIONES",
                Fr => "CONVERSATIONS",
                Ar => "المحادثات الاخيرة",
            },
            Key::NewChat => match self {
                En => "New chat",
                PtBr => "Nova conversa",
                Zh => "新对话",
                Hi => "नई चैट",
                Es => "Nueva conversacion",
                Fr => "Nouvelle conversation",
                Ar => "محادثة جديدة",
            },
            Key::Settings => match self {
                En => "Settings",
                PtBr => "Configuracoes",
                Zh => "设置",
                Hi => "सेटिंग्स",
                Es => "Ajustes",
                Fr => "Parametres",
                Ar => "الاعدادات",
            },
            Key::General => match self {
                En => "General",
                PtBr => "Geral",
                Zh => "通用",
                Hi => "सामान्य",
                Es => "General",
                Fr => "General",
                Ar => "عام",
            },
            Key::Engineer => "Engineer",
            Key::Professor => "Professor",
            Key::Vision => "Vision",
            Key::Reasoning => match self {
                En => "Reasoning",
                PtBr => "Raciocinio",
                Zh => "推理",
                Hi => "तर्क",
                Es => "Razonamiento",
                Fr => "Raisonnement",
                Ar => "الاستدلال",
            },
            Key::Instant => match self {
                En => "Instant",
                PtBr => "Instantaneo",
                Zh => "即时",
                Hi => "तुरंत",
                Es => "Instantaneo",
                Fr => "Instantane",
                Ar => "فوري",
            },
            Key::Medium => match self {
                En => "Medium",
                PtBr => "Medio",
                Zh => "中等",
                Hi => "मध्यम",
                Es => "Medio",
                Fr => "Moyen",
                Ar => "متوسط",
            },
            Key::Deep => match self {
                En => "Deep",
                PtBr => "Profundo",
                Zh => "深度",
                Hi => "गहरा",
                Es => "Profundo",
                Fr => "Profond",
                Ar => "عميق",
            },
            Key::Library => match self {
                En => "Library",
                PtBr => "Biblioteca",
                Zh => "文库",
                Hi => "लाइब्रेरी",
                Es => "Biblioteca",
                Fr => "Bibliotheque",
                Ar => "المكتبة",
            },
            Key::Evolution => match self {
                En => "Evolution",
                PtBr => "Evolucao",
                Zh => "进化",
                Hi => "विकास",
                Es => "Evolucion",
                Fr => "Evolution",
                Ar => "التطور",
            },
            Key::VoiceCall => match self {
                En => "Voice call",
                PtBr => "Chamada de voz",
                Zh => "语音通话",
                Hi => "वॉइस कॉल",
                Es => "Llamada de voz",
                Fr => "Appel vocal",
                Ar => "مكالمة صوتية",
            },
            Key::Devices => match self {
                En => "Devices",
                PtBr => "Dispositivos",
                Zh => "设备",
                Hi => "उपकरण",
                Es => "Dispositivos",
                Fr => "Appareils",
                Ar => "الاجهزة",
            },
            Key::Sentinel => "Sentinel",
            Key::Missions => match self {
                En => "Missions",
                PtBr => "Missoes",
                Zh => "任务",
                Hi => "मिशन",
                Es => "Misiones",
                Fr => "Missions",
                Ar => "المهام",
            },
            Key::Sandbox => "Sandbox",
            Key::GitHub => "GitHub",
            Key::Calendar => match self {
                En => "Calendar",
                PtBr => "Agenda",
                Zh => "日历",
                Hi => "कैलेंडर",
                Es => "Agenda",
                Fr => "Agenda",
                Ar => "التقويم",
            },
            Key::Email => match self {
                En => "Email",
                PtBr => "E-mail",
                Zh => "邮件",
                Hi => "ईमेल",
                Es => "Correo",
                Fr => "E-mail",
                Ar => "البريد",
            },
            Key::Attachments => match self {
                En => "Vision / Attachments",
                PtBr => "Visao / Anexos",
                Zh => "视觉/附件",
                Hi => "विज़न/अटैचमेंट",
                Es => "Vision / Adjuntos",
                Fr => "Vision / Pieces",
                Ar => "الرؤية والمرفقات",
            },
            Key::HomeAssistant => "Home Assistant",
            Key::Plugins => match self {
                En => "Plugins & Skills",
                PtBr => "Plugins e Skills",
                Zh => "插件与技能",
                Hi => "प्लगइन और कौशल",
                Es => "Plugins y Skills",
                Fr => "Plugins et Skills",
                Ar => "الاضافات والمهارات",
            },
            Key::ClearChat => match self {
                En => "Clear chat",
                PtBr => "Limpar conversa",
                Zh => "清空对话",
                Hi => "चैट साफ करें",
                Es => "Limpiar conversacion",
                Fr => "Effacer la conversation",
                Ar => "مسح المحادثة",
            },
            Key::Chat => match self {
                En => "Chat",
                PtBr => "Conversa",
                Zh => "对话",
                Hi => "चैट",
                Es => "Chat",
                Fr => "Discussion",
                Ar => "محادثة",
            },
            Key::ModelsRoles => match self {
                En => "Models & Roles",
                PtBr => "Modelos & Papeis",
                Zh => "模型与角色",
                Hi => "मॉडल और भूमिकाएँ",
                Es => "Modelos y Roles",
                Fr => "Modeles et Roles",
                Ar => "النماذج والادوار",
            },
            Key::Vault => match self {
                En => "Vault",
                PtBr => "Cofre",
                Zh => "保险库",
                Hi => "वॉल्ट",
                Es => "Caja fuerte",
                Fr => "Coffre",
                Ar => "الخزنة",
            },
            Key::HfDownload => match self {
                En => "Hugging Face",
                PtBr => "Baixar do Hugging Face",
                Zh => "Hugging Face",
                Hi => "Hugging Face",
                Es => "Hugging Face",
                Fr => "Hugging Face",
                Ar => "Hugging Face",
            },
            Key::Fullscreen => match self {
                En => "Fullscreen (F11)",
                PtBr => "Tela cheia (F11)",
                Zh => "全屏 (F11)",
                Hi => "फुलस्क्रीन (F11)",
                Es => "Pantalla completa (F11)",
                Fr => "Plein ecran (F11)",
                Ar => "شاشة كاملة (F11)",
            },
            Key::ExitFullscreen => match self {
                En => "Exit fullscreen",
                PtBr => "Sair da tela cheia",
                Zh => "退出全屏",
                Hi => "फुलस्क्रीन से बाहर",
                Es => "Salir de pantalla completa",
                Fr => "Quitter le plein ecran",
                Ar => "الخروج من الشاشة الكاملة",
            },
            Key::Send => match self {
                En => "Send",
                PtBr => "Enviar",
                Zh => "发送",
                Hi => "भेजें",
                Es => "Enviar",
                Fr => "Envoyer",
                Ar => "ارسال",
            },
            Key::Stop => match self {
                En => "Stop",
                PtBr => "Parar",
                Zh => "停止",
                Hi => "रोकें",
                Es => "Detener",
                Fr => "Arreter",
                Ar => "ايقاف",
            },
            Key::ComposerHint => match self {
                En => "Message MARK",
                PtBr => "Escreva a mensagem para o MARK",
                Zh => "给 MARK 发送消息",
                Hi => "MARK को संदेश भेजें",
                Es => "Escribe a MARK",
                Fr => "Ecrire a MARK",
                Ar => "اكتب الى MARK",
            },
            Key::Copy => match self {
                En => "Copy",
                PtBr => "Copiar",
                Zh => "复制",
                Hi => "कॉपी",
                Es => "Copiar",
                Fr => "Copier",
                Ar => "نسخ",
            },
            Key::Commands => match self {
                En => "Ctrl+K Commands",
                PtBr => "Ctrl+K Comandos",
                Zh => "Ctrl+K 命令",
                Hi => "Ctrl+K कमांड",
                Es => "Ctrl+K Comandos",
                Fr => "Ctrl+K Commandes",
                Ar => "Ctrl+K اوامر",
            },
            Key::Language => match self {
                En => "Language",
                PtBr => "Idioma",
                Zh => "语言",
                Hi => "भाषा",
                Es => "Idioma",
                Fr => "Langue",
                Ar => "اللغة",
            },
            Key::Connected => match self {
                En => "Connected",
                PtBr => "Conectado",
                Zh => "已连接",
                Hi => "कनेक्टेड",
                Es => "Conectado",
                Fr => "Connecte",
                Ar => "متصل",
            },
        }
    }
}

/// Chaves de traducao usadas pela interface.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    AgentsModes,
    SpaceSystem,
    Tools,
    RecentChats,
    NewChat,
    Settings,
    General,
    Engineer,
    Professor,
    Vision,
    Reasoning,
    Instant,
    Medium,
    Deep,
    Library,
    Evolution,
    VoiceCall,
    Devices,
    Sentinel,
    Missions,
    Sandbox,
    GitHub,
    Calendar,
    Email,
    Attachments,
    HomeAssistant,
    Plugins,
    ClearChat,
    Chat,
    ModelsRoles,
    Vault,
    HfDownload,
    Fullscreen,
    ExitFullscreen,
    Send,
    Stop,
    ComposerHint,
    Copy,
    Commands,
    Language,
    Connected,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn english_is_the_default() {
        assert_eq!(Lang::from_code("xx"), Lang::En);
        assert_eq!(Lang::from_code(""), Lang::En);
        assert_eq!(Lang::En.code(), "en");
    }

    #[test]
    fn all_languages_have_labels() {
        for l in Lang::ALL {
            assert!(!l.label().is_empty());
            assert!(!l.t(Key::AgentsModes).is_empty());
            assert!(!l.t(Key::Send).is_empty());
            assert!(!l.t(Key::Vault).is_empty());
        }
    }

    #[test]
    fn pt_br_and_en_differ() {
        assert_eq!(Lang::En.t(Key::AgentsModes), "AGENTS & MODES");
        assert_eq!(Lang::PtBr.t(Key::AgentsModes), "AGENTES & MODOS");
        assert_eq!(Lang::Zh.t(Key::Vault), "保险库");
        assert_eq!(Lang::Hi.t(Key::Send), "भेजें");
    }

    #[test]
    fn codes_roundtrip() {
        for l in Lang::ALL {
            assert_eq!(Lang::from_code(l.code()), l);
        }
    }
}
