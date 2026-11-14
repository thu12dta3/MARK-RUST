"""Translation table for the main window, menus and composer.

Row order matches ``i18n.LANGS``: en, pt-BR, zh, hi, es, fr, ar.
The key is the literal that appears in the widget code.
"""

TRANSLATIONS: dict[str, tuple[str, str, str, str, str, str, str]] = {
    # ------------------------------------------------------------- sidebar
    "ASSISTENTE PESSOAL": (
        "PERSONAL ASSISTANT", "ASSISTENTE PESSOAL", "个人助理",
        "व्यक्तिगत सहायक", "ASISTENTE PERSONAL", "ASSISTANT PERSONNEL", "المساعد الشخصي",
    ),
    "+  Nova conversa (Engineer)": (
        "+  New chat (Engineer)", "+  Nova conversa (Engineer)", "+  新建对话（工程师）",
        "+  नई चैट (इंजीनियर)", "+  Nueva conversación (Ingeniero)",
        "+  Nouvelle conversation (Ingénieur)", "+  محادثة جديدة (المهندس)",
    ),
    "Filtrar conversas...": (
        "Filter conversations...", "Filtrar conversas...", "筛选对话...",
        "बातचीत फ़िल्टर करें...", "Filtrar conversaciones...",
        "Filtrer les conversations...", "تصفية المحادثات...",
    ),
    "AGENTES & MODOS": (
        "AGENTS & MODES", "AGENTES & MODOS", "智能体与模式",
        "एजेंट और मोड", "AGENTES Y MODOS", "AGENTS ET MODES", "الوكلاء والأوضاع",
    ),
    "Geral": ("General", "Geral", "通用", "सामान्य", "General", "Général", "عام"),
    "Engenheiro": ("Engineer", "Engenheiro", "工程师", "इंजीनियर", "Ingeniero", "Ingénieur", "مهندس"),
    "Professor": ("Professor", "Professor", "教授", "प्रोफेसर", "Profesor", "Professeur", "أستاذ"),
    "ESPAÇO & SISTEMA": (
        "SPACE & SYSTEM", "ESPAÇO & SISTEMA", "空间与系统",
        "स्थान और सिस्टम", "ESPACIO Y SISTEMA", "ESPACE ET SYSTÈME", "الفضاء والنظام",
    ),
    "Biblioteca": ("Library", "Biblioteca", "资料库", "लाइब्रेरी", "Biblioteca", "Bibliothèque", "المكتبة"),
    "Evolução": ("Evolution", "Evolução", "进化", "विकास", "Evolución", "Évolution", "التطور"),
    "Chamada de Voz": (
        "Voice Call", "Chamada de Voz", "语音通话", "वॉइस कॉल",
        "Llamada de voz", "Appel vocal", "مكالمة صوتية",
    ),
    "Dispositivos": ("Devices", "Dispositivos", "设备", "उपकरण", "Dispositivos", "Appareils", "الأجهزة"),
    "Ferramentas": ("Tools", "Ferramentas", "工具", "औज़ार", "Herramientas", "Outils", "الأدوات"),
    "CONVERSAS RECENTES": (
        "RECENT CHATS", "CONVERSAS RECENTES", "最近对话", "हाल की चैट",
        "CONVERSACIONES RECIENTES", "CONVERSATIONS RÉCENTES", "المحادثات الأخيرة",
    ),
    "Configurações": ("Settings", "Configurações", "设置", "सेटिंग्स", "Configuración", "Paramètres", "الإعدادات"),
    "MARK · Operacional": (
        "MARK · Operational", "MARK · Operacional", "MARK · 运行中", "MARK · चालू",
        "MARK · Operativo", "MARK · Opérationnel", "MARK · يعمل",
    ),
    "Verificando...": (
        "Checking...", "Verificando...", "正在检查...", "जाँच हो रही है...",
        "Comprobando...", "Vérification...", "جارٍ التحقق...",
    ),
    "Microfone": ("Microphone", "Microfone", "麦克风", "माइक्रोफ़ोन", "Micrófono", "Microphone", "الميكروفون"),
    "Pronto": ("Ready", "Pronto", "就绪", "तैयार", "Listo", "Prêt", "جاهز"),
    "Criar uma nova sessão de conversa dedicada no modo Engenheiro": (
        "Create a dedicated conversation in Engineer mode",
        "Criar uma nova sessão de conversa dedicada no modo Engenheiro",
        "在工程师模式下创建专用对话",
        "इंजीनियर मोड में समर्पित बातचीत बनाएँ",
        "Crear una conversación dedicada en modo Ingeniero",
        "Créer une conversation dédiée en mode Ingénieur",
        "إنشاء محادثة مخصصة في وضع المهندس",
    ),
    "Abrir ferramentas do MARK": (
        "Open MARK tools", "Abrir ferramentas do MARK", "打开 MARK 工具",
        "MARK उपकरण खोलें", "Abrir herramientas de MARK", "Ouvrir les outils MARK", "فتح أدوات MARK",
    ),
    # -------------------------------------------------------------- header
    "Conversa": ("Chat", "Conversa", "对话", "चैट", "Conversación", "Conversation", "محادثة"),
    "MARK operacional · memória compartilhada ativa": (
        "MARK operational · shared memory active",
        "MARK operacional · memória compartilhada ativa",
        "MARK 运行中 · 共享记忆已启用",
        "MARK चालू · साझा मेमोरी सक्रिय",
        "MARK operativo · memoria compartida activa",
        "MARK opérationnel · mémoire partagée active",
        "MARK يعمل · الذاكرة المشتركة مفعّلة",
    ),
    "Chamada": ("Call", "Chamada", "通话", "कॉल", "Llamada", "Appel", "مكالمة"),
    "Nova conversa": (
        "New chat", "Nova conversa", "新建对话", "नई चैट",
        "Nueva conversación", "Nouvelle conversation", "محادثة جديدة",
    ),
    "Excluir conversa atual": (
        "Delete current conversation", "Excluir conversa atual", "删除当前对话",
        "वर्तमान बातचीत हटाएँ", "Eliminar conversación actual",
        "Supprimer la conversation actuelle", "حذف المحادثة الحالية",
    ),
    "Iniciar chamada de voz in-app": (
        "Start in-app voice call", "Iniciar chamada de voz in-app", "开始应用内语音通话",
        "ऐप में वॉइस कॉल शुरू करें", "Iniciar llamada de voz en la app",
        "Démarrer un appel vocal intégré", "بدء مكالمة صوتية داخل التطبيق",
    ),
    "Abrir painel de configurações": (
        "Open settings panel", "Abrir painel de configurações", "打开设置面板",
        "सेटिंग्स पैनल खोलें", "Abrir panel de configuración",
        "Ouvrir le panneau de paramètres", "فتح لوحة الإعدادات",
    ),
    "Atualizar estado do MARK": (
        "Refresh MARK status", "Atualizar estado do MARK", "刷新 MARK 状态",
        "MARK स्थिति रीफ़्रेश करें", "Actualizar estado de MARK",
        "Actualiser l'état de MARK", "تحديث حالة MARK",
    ),
    "Tela Cheia (F11)": (
        "Fullscreen (F11)", "Tela Cheia (F11)", "全屏（F11）", "पूर्ण स्क्रीन (F11)",
        "Pantalla completa (F11)", "Plein écran (F11)", "ملء الشاشة (F11)",
    ),
    "Sair da Tela Cheia (F11)": (
        "Exit Fullscreen (F11)", "Sair da Tela Cheia (F11)", "退出全屏（F11）",
        "पूर्ण स्क्रीन से बाहर (F11)", "Salir de pantalla completa (F11)",
        "Quitter le plein écran (F11)", "الخروج من ملء الشاشة (F11)",
    ),
    "Alternar tela cheia com F11": (
        "Toggle fullscreen with F11", "Alternar tela cheia com F11", "用 F11 切换全屏",
        "F11 से पूर्ण स्क्रीन बदलें", "Alternar pantalla completa con F11",
        "Basculer le plein écran avec F11", "تبديل ملء الشاشة بـ F11",
    ),
    "Voltar a janela": (
        "Back to window", "Voltar a janela", "返回窗口", "विंडो पर लौटें",
        "Volver a la ventana", "Revenir à la fenêtre", "العودة إلى النافذة",
    ),
    "Idioma da interface": (
        "Interface language", "Idioma da interface", "界面语言", "इंटरफ़ेस भाषा",
        "Idioma de la interfaz", "Langue de l'interface", "لغة الواجهة",
    ),
    # ------------------------------------------------------------ welcome
    "UM ASSISTENTE. TODOS OS SEUS DISPOSITIVOS.": (
        "ONE ASSISTANT. ALL YOUR DEVICES.", "UM ASSISTENTE. TODOS OS SEUS DISPOSITIVOS.",
        "一个助手，连接你的所有设备。", "एक सहायक। आपके सभी उपकरण।",
        "UN ASISTENTE. TODOS TUS DISPOSITIVOS.", "UN ASSISTANT. TOUS VOS APPAREILS.",
        "مساعد واحد. كل أجهزتك.",
    ),
    "O que vamos fazer hoje?": (
        "What shall we do today?", "O que vamos fazer hoje?", "今天我们要做什么？",
        "आज हम क्या करें?", "¿Qué hacemos hoy?", "Que faisons-nous aujourd'hui ?",
        "ماذا سنفعل اليوم؟",
    ),
    "Converse, planeje ou explore uma ideia com o MARK.": (
        "Chat, plan, or explore an idea with MARK.",
        "Converse, planeje ou explore uma ideia com o MARK.",
        "与 MARK 对话、规划或探索想法。",
        "MARK के साथ बात करें, योजना बनाएँ या विचार खोजें।",
        "Conversa, planifica o explora una idea con MARK.",
        "Discutez, planifiez ou explorez une idée avec MARK.",
        "تحدّث أو خطّط أو استكشف فكرة مع MARK.",
    ),
    "Organizar meu dia": (
        "Plan my day", "Organizar meu dia", "规划我的一天", "मेरा दिन व्यवस्थित करें",
        "Organizar mi día", "Organiser ma journée", "تنظيم يومي",
    ),
    "Explorar uma ideia": (
        "Explore an idea", "Explorar uma ideia", "探索一个想法", "एक विचार खोजें",
        "Explorar una idea", "Explorer une idée", "استكشاف فكرة",
    ),
    "Entender um arquivo": (
        "Understand a file", "Entender um arquivo", "理解文件", "फ़ाइल समझें",
        "Entender un archivo", "Comprendre un fichier", "فهم ملف",
    ),
    "Resolver um problema": (
        "Solve a problem", "Resolver um problema", "解决问题", "समस्या हल करें",
        "Resolver un problema", "Résoudre un problème", "حل مشكلة",
    ),
    # ----------------------------------------------------------- composer
    "Escreva para o MARK ou arraste um arquivo aqui... (Shift+Enter nova linha)": (
        "Write to MARK or drop a file here... (Shift+Enter for a new line)",
        "Escreva para o MARK ou arraste um arquivo aqui... (Shift+Enter nova linha)",
        "向 MARK 输入消息或拖入文件...（Shift+Enter 换行）",
        "MARK को लिखें या फ़ाइल यहाँ छोड़ें... (नई पंक्ति के लिए Shift+Enter)",
        "Escribe a MARK o arrastra un archivo aquí... (Shift+Enter nueva línea)",
        "Écrivez à MARK ou déposez un fichier ici... (Maj+Entrée nouvelle ligne)",
        "اكتب إلى MARK أو أفلت ملفاً هنا... (Shift+Enter لسطر جديد)",
    ),
    "Anexar arquivos (imagens, documentos, código)": (
        "Attach files (images, documents, code)", "Anexar arquivos (imagens, documentos, código)",
        "附加文件（图片、文档、代码）", "फ़ाइलें संलग्न करें (चित्र, दस्तावेज़, कोड)",
        "Adjuntar archivos (imágenes, documentos, código)",
        "Joindre des fichiers (images, documents, code)", "إرفاق ملفات (صور، مستندات، شيفرة)",
    ),
    "Raciocínio Instantâneo": (
        "Instant reasoning", "Raciocínio Instantâneo", "即时推理", "तात्कालिक तर्क",
        "Razonamiento instantáneo", "Raisonnement instantané", "استدلال فوري",
    ),
    "Raciocínio Balanceado": (
        "Balanced reasoning", "Raciocínio Balanceado", "均衡推理", "संतुलित तर्क",
        "Razonamiento equilibrado", "Raisonnement équilibré", "استدلال متوازن",
    ),
    "Raciocínio Profundo": (
        "Deep reasoning", "Raciocínio Profundo", "深度推理", "गहन तर्क",
        "Razonamiento profundo", "Raisonnement approfondi", "استدلال عميق",
    ),
    "Enviar mensagem": (
        "Send message", "Enviar mensagem", "发送消息", "संदेश भेजें",
        "Enviar mensaje", "Envoyer le message", "إرسال الرسالة",
    ),
    "Remover o arquivo selecionado": (
        "Remove selected file", "Remover o arquivo selecionado", "移除所选文件",
        "चयनित फ़ाइल हटाएँ", "Quitar archivo seleccionado", "Retirer le fichier sélectionné",
        "إزالة الملف المحدد",
    ),
    "Enter envia · Shift+Enter nova linha": (
        "Enter sends · Shift+Enter new line", "Enter envia · Shift+Enter nova linha",
        "Enter 发送 · Shift+Enter 换行", "Enter भेजता है · Shift+Enter नई पंक्ति",
        "Enter envía · Shift+Enter nueva línea", "Entrée envoie · Maj+Entrée nouvelle ligne",
        "Enter يرسل · Shift+Enter سطر جديد",
    ),
    "⌘K Comandos": ("⌘K Commands", "⌘K Comandos", "⌘K 命令", "⌘K कमांड", "⌘K Comandos", "⌘K Commandes", "⌘K أوامر"),
    "Abrir Menu de Comandos (Ctrl+K / Cmd+K)": (
        "Open command menu (Ctrl+K / Cmd+K)", "Abrir Menu de Comandos (Ctrl+K / Cmd+K)",
        "打开命令菜单（Ctrl+K / Cmd+K）", "कमांड मेन्यू खोलें (Ctrl+K / Cmd+K)",
        "Abrir menú de comandos (Ctrl+K / Cmd+K)", "Ouvrir le menu de commandes (Ctrl+K / Cmd+K)",
        "فتح قائمة الأوامر (Ctrl+K / Cmd+K)",
    ),
    "ATIVO": ("ACTIVE", "ATIVO", "已启用", "सक्रिय", "ACTIVO", "ACTIF", "مُفعّل"),
    "INATIVO": ("INACTIVE", "INATIVO", "未启用", "निष्क्रिय", "INACTIVO", "INACTIF", "غير مفعّل"),
    "Multi-idioma ativo. Pt-BR é o idioma padrão do aplicativo.": (
        "Multi-language enabled. English is the default application language.",
        "Multi-idioma ativo. Inglês é o idioma padrão do aplicativo.",
        "多语言已启用。默认语言为英语。", "बहुभाषा सक्रिय। डिफ़ॉल्ट भाषा अंग्रेज़ी है।",
        "Multi-idioma activo. El idioma predeterminado es el inglés.",
        "Multilingue actif. L'anglais est la langue par défaut.",
        "تعدد اللغات مفعّل. اللغة الافتراضية هي الإنجليزية.",
    ),
    # -------------------------------------------------------------- menus
    "--- SEGURANÇA E AGENTES ---": (
        "--- SECURITY AND AGENTS ---", "--- SEGURANÇA E AGENTES ---", "--- 安全与智能体 ---",
        "--- सुरक्षा और एजेंट ---", "--- SEGURIDAD Y AGENTES ---",
        "--- SÉCURITÉ ET AGENTS ---", "--- الأمان والوكلاء ---",
    ),
    "Antivírus e ameaças · Sentinel": (
        "Antivirus and threats · Sentinel", "Antivírus e ameaças · Sentinel",
        "防病毒与威胁 · Sentinel", "एंटीवायरस और खतरे · Sentinel",
        "Antivirus y amenazas · Sentinel", "Antivirus et menaces · Sentinel",
        "مكافحة الفيروسات والتهديدات · Sentinel",
    ),
    "Dispositivos e segurança": (
        "Devices and security", "Dispositivos e segurança", "设备与安全", "उपकरण और सुरक्षा",
        "Dispositivos y seguridad", "Appareils et sécurité", "الأجهزة والأمان",
    ),
    "--- ENGENHARIA E CÓDIGO ---": (
        "--- ENGINEERING AND CODE ---", "--- ENGENHARIA E CÓDIGO ---", "--- 工程与代码 ---",
        "--- अभियांत्रिकी और कोड ---", "--- INGENIERÍA Y CÓDIGO ---",
        "--- INGÉNIERIE ET CODE ---", "--- الهندسة والشيفرة ---",
    ),
    "Tarefas do Engineer": (
        "Engineer tasks", "Tarefas do Engineer", "工程师任务", "इंजीनियर कार्य",
        "Tareas del Ingeniero", "Tâches de l'Ingénieur", "مهام المهندس",
    ),
    "Engenharia Autônoma · Sandbox": (
        "Autonomous engineering · Sandbox", "Engenharia Autônoma · Sandbox",
        "自主工程 · 沙盒", "स्वायत्त अभियांत्रिकी · सैंडबॉक्स",
        "Ingeniería autónoma · Sandbox", "Ingénierie autonome · Sandbox",
        "هندسة ذاتية · صندوق رمل",
    ),
    "Código · GitHub": (
        "Code · GitHub", "Código · GitHub", "代码 · GitHub", "कोड · GitHub",
        "Código · GitHub", "Code · GitHub", "الشيفرة · GitHub",
    ),
    "--- UTILITÁRIOS E MÍDIA ---": (
        "--- UTILITIES AND MEDIA ---", "--- UTILITÁRIOS E MÍDIA ---", "--- 实用工具与媒体 ---",
        "--- उपयोगिताएँ और मीडिया ---", "--- UTILIDADES Y MEDIOS ---",
        "--- UTILITAIRES ET MÉDIAS ---", "--- الأدوات والوسائط ---",
    ),
    "Agenda e lembretes": (
        "Calendar and reminders", "Agenda e lembretes", "日程与提醒", "कैलेंडर और अनुस्मारक",
        "Agenda y recordatorios", "Agenda et rappels", "التقويم والتذكيرات",
    ),
    "E-mail · Tuta": ("Email · Tuta", "E-mail · Tuta", "电子邮件 · Tuta", "ईमेल · Tuta", "Correo · Tuta", "E-mail · Tuta", "البريد · Tuta"),
    "Visão ao vivo / Câmera": (
        "Live vision / Camera", "Visão ao vivo / Câmera", "实时视觉 / 摄像头",
        "लाइव दृष्टि / कैमरा", "Visión en vivo / Cámara", "Vision en direct / Caméra",
        "رؤية مباشرة / الكاميرا",
    ),
    "Escuta por voz": (
        "Voice listening", "Escuta por voz", "语音聆听", "वॉइस सुनना",
        "Escucha por voz", "Écoute vocale", "الاستماع الصوتي",
    ),
    "Alternar escuta por voz": (
        "Toggle voice listening", "Alternar escuta por voz", "切换语音聆听",
        "वॉइस सुनना बदलें", "Alternar escucha por voz", "Basculer l'écoute vocale",
        "تبديل الاستماع الصوتي",
    ),
    "--- SISTEMA ---": (
        "--- SYSTEM ---", "--- SISTEMA ---", "--- 系统 ---", "--- सिस्टम ---",
        "--- SISTEMA ---", "--- SYSTÈME ---", "--- النظام ---",
    ),
    "Plugins...": ("Plugins...", "Plugins...", "插件...", "प्लगइन...", "Complementos...", "Extensions...", "الإضافات..."),
    "Iniciar MARK": ("Start MARK", "Iniciar MARK", "启动 MARK", "MARK शुरू करें", "Iniciar MARK", "Démarrer MARK", "تشغيل MARK"),
    "Limpar conversa": (
        "Clear conversation", "Limpar conversa", "清除对话", "बातचीत साफ़ करें",
        "Limpiar conversación", "Effacer la conversation", "مسح المحادثة",
    ),
    "Biblioteca de Memórias": (
        "Memory library", "Biblioteca de Memórias", "记忆库", "स्मृति लाइब्रेरी",
        "Biblioteca de memorias", "Bibliothèque de mémoires", "مكتبة الذاكرة",
    ),
    "Evolução do MARK": (
        "MARK evolution", "Evolução do MARK", "MARK 进化", "MARK विकास",
        "Evolución de MARK", "Évolution de MARK", "تطور MARK",
    ),
    "Clique para ver detalhes de segurança BWRAP": (
        "Click to see BWRAP security details", "Clique para ver detalhes de segurança BWRAP",
        "点击查看 BWRAP 安全详情", "BWRAP सुरक्षा विवरण देखने के लिए क्लिक करें",
        "Clic para ver detalles de seguridad BWRAP", "Cliquez pour les détails de sécurité BWRAP",
        "انقر لعرض تفاصيل أمان BWRAP",
    ),
    "Clique para ver detalhes de segurança mTLS": (
        "Click to see mTLS security details", "Clique para ver detalhes de segurança mTLS",
        "点击查看 mTLS 安全详情", "mTLS सुरक्षा विवरण देखने के लिए क्लिक करें",
        "Clic para ver detalles de seguridad mTLS", "Cliquez pour les détails de sécurité mTLS",
        "انقر لعرض تفاصيل أمان mTLS",
    ),
    "Clique para ver detalhes de janela de contexto": (
        "Click to see context window details", "Clique para ver detalhes de janela de contexto",
        "点击查看上下文窗口详情", "कॉन्टेक्स्ट विंडो विवरण देखने के लिए क्लिक करें",
        "Clic para ver detalles de la ventana de contexto", "Cliquez pour les détails de la fenêtre de contexte",
        "انقر لعرض تفاصيل نافذة السياق",
    ),
    "Expandir ou recolher barra lateral": (
        "Expand or collapse sidebar", "Expandir ou recolher barra lateral", "展开或收起侧边栏",
        "साइडबार विस्तृत या संक्षिप्त करें", "Expandir o contraer la barra lateral",
        "Développer ou réduire la barre latérale", "توسيع أو طي الشريط الجانبي",
    ),
    "Conversas separadas por perfil; memórias salvas continuam compartilhadas": (
        "Conversations separated by profile; saved memories stay shared",
        "Conversas separadas por perfil; memórias salvas continuam compartilhadas",
        "按配置分离的对话；已保存的记忆仍共享",
        "प्रोफ़ाइल के अनुसार अलग बातचीत; सहेजी गई स्मृति साझा रहती है",
        "Conversaciones separadas por perfil; las memorias guardadas se comparten",
        "Conversations séparées par profil ; les mémoires enregistrées restent partagées",
        "محادثات منفصلة حسب الملف؛ الذاكرة المحفوظة تبقى مشتركة",
    ),
    "Secundário": ("Secondary", "Secundário", "次级", "द्वितीयक", "Secundario", "Secondaire", "ثانوي"),
    "Primário": ("Primary", "Primário", "主级", "प्राथमिक", "Primario", "Principal", "أساسي"),
    "Local Secundário": (
        "Local Secondary", "Local Secundário", "本地次级", "स्थानीय द्वितीयक",
        "Secundario local", "Secondaire local", "ثانوي محلي",
    ),
    "Local Primário": (
        "Local Primary", "Local Primário", "本地主级", "स्थानीय प्राथमिक",
        "Primario local", "Principal local", "أساسي محلي",
    ),
    "Conectado": (
        "Connected", "Conectado", "已连接", "कनेक्टेड", "Conectado", "Connecté", "متصل",
    ),
    "Desligada": (
        "Off", "Desligada", "关闭", "बंद", "Apagado", "Désactivé", "متوقف",
    ),
}
