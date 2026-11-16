"""Translation table for the live window, Settings, Models Hub and plugins.

Row order matches ``i18n.LANGS``: en, pt-BR, zh, hi, es, fr, ar.
Every key is the exact English source literal used by ``tr()`` in the widgets.
"""

TRANSLATIONS: dict[str, tuple[str, str, str, str, str, str, str]] = {
    "(no output)": (
        "(no output)", "(sem saída)", "(无输出)", "(कोई आउटपुट नहीं)",
        "(sin salida)", "(aucune sortie)", "(لا خرج)",
    ),
    "(no sandbox output)": (
        "(no sandbox output)", "(sem saída do sandbox)", "(无沙箱输出)",
        "(कोई सैंडबॉक्स आउटपुट नहीं)", "(sin salida del sandbox)",
        "(aucune sortie du bac à sable)", "(لا خرج من بيئة العزل)",
    ),
    "Argon2id + AES-256-GCM (Rust)": (
        "Argon2id + AES-256-GCM (Rust)", "Argon2id + AES-256-GCM (núcleo Rust)",
        "Argon2id + AES-256-GCM（Rust 内核）", "Argon2id + AES-256-GCM (Rust कोर)",
        "Argon2id + AES-256-GCM (núcleo Rust)", "Argon2id + AES-256-GCM (cœur Rust)",
        "Argon2id + AES-256-GCM (نواة Rust)",
    ),
    "Attach an image to the composer to start.": (
        "Attach an image to the composer to start.",
        "Anexe uma imagem ao compositor para começar.",
        "先在输入区附加一张图片再开始。",
        "शुरू करने के लिए कंपोज़र में एक छवि संलग्न करें।",
        "Adjunta una imagen al compositor para empezar.",
        "Joignez une image au compositeur pour commencer.",
        "أرفق صورة بمحرر الرسالة للبدء.",
    ),
    "Autonomous engineering": (
        "Autonomous engineering", "Engenharia autônoma", "自主工程",
        "स्वायत्त इंजीनियरिंग", "Ingeniería autónoma", "Ingénierie autonome",
        "هندسة مستقلة",
    ),
    "Browse": (
        "Browse", "Procurar", "浏览", "ब्राउज़ करें", "Examinar", "Parcourir", "تصفح",
    ),
    "Choose project": (
        "Choose project", "Escolher projeto", "选择项目", "प्रोजेक्ट चुनें",
        "Elegir proyecto", "Choisir un projet", "اختر مشروعًا",
    ),
    "Click to expand/collapse": (
        "Click to expand/collapse", "Clique para expandir/recolher",
        "点击展开或折叠", "विस्तार या संकुचन के लिए क्लिक करें",
        "Haz clic para expandir o contraer", "Cliquez pour déplier ou replier",
        "انقر للتوسيع أو الطي",
    ),
    "Copied!": (
        "Copied!", "Copiado!", "已复制！", "कॉपी हो गया!", "¡Copiado!",
        "Copié !", "تم النسخ!",
    ),
    "Copy code": (
        "Copy code", "Copiar código", "复制代码", "कोड कॉपी करें", "Copiar código",
        "Copier le code", "انسخ الشيفرة",
    ),
    "Engine": (
        "Engine", "Motor", "引擎", "इंजन", "Motor", "Moteur", "المحرك",
    ),
    "Engine escolhida automaticamente pelo modelo": (
        "Engine chosen automatically for the model",
        "Motor escolhido automaticamente pelo modelo",
        "引擎由所选模型自动决定", "मॉडल के अनुसार इंजन स्वतः चुना गया",
        "Motor elegido automáticamente por el modelo",
        "Moteur choisi automatiquement pour le modèle",
        "يُختار المحرك تلقائيًا حسب النموذج",
    ),
    "Engine chosen automatically for the model": (
        "Engine chosen automatically for the model",
        "Motor escolhido automaticamente pelo modelo",
        "引擎由所选模型自动决定", "मॉडल के अनुसार इंजन स्वतः चुना गया",
        "Motor elegido automáticamente por el modelo",
        "Moteur choisi automatiquement pour le modèle",
        "يُختار المحرك تلقائيًا حسب النموذج",
    ),
    "Engine: resolved automatically": (
        "Engine: resolved automatically", "Motor: resolvido automaticamente",
        "引擎：自动判定", "इंजन: स्वतः निर्धारित", "Motor: resuelto automáticamente",
        "Moteur : déterminé automatiquement", "المحرك: يُحدد تلقائيًا",
    ),
    "Engineer uses its own model profile": (
        "Engineer uses its own model profile",
        "O Engineer usa o próprio perfil de modelo",
        "工程师模式使用专属模型配置", "इंजीनियर अपना मॉडल प्रोफ़ाइल उपयोग करता है",
        "El modo Ingeniero usa su propio perfil de modelo",
        "L'ingénieur utilise son propre profil de modèle",
        "يستخدم وضع المهندس ملف النموذج الخاص به",
    ),
    "Engineer uses the fixed Rust engine": (
        "Engineer uses the fixed Rust engine",
        "O Engineer usa o motor Rust fixo",
        "工程师模式固定使用 Rust 引擎", "इंजीनियर निश्चित Rust इंजन उपयोग करता है",
        "El modo Ingeniero usa el motor Rust fijo",
        "L'ingénieur utilise le moteur Rust fixe",
        "يستخدم وضع المهندس محرك Rust الثابت",
    ),
    "Processing failure": (
        "Processing failure", "Falha no processamento", "处理失败",
        "प्रोसेसिंग विफलता", "Fallo de procesamiento", "Échec du traitement",
        "فشل المعالجة",
    ),
    "Hardware scan failed: {detail}": (
        "Hardware scan failed: {detail}", "Falha ao examinar o hardware: {detail}",
        "硬件扫描失败：{detail}", "हार्डवेयर स्कैन विफल: {detail}",
        "Falló el análisis del hardware: {detail}",
        "Échec de l'analyse du matériel : {detail}",
        "فشل فحص العتاد: {detail}",
    ),
    "Internet Access": (
        "Internet Access", "Acesso à internet", "互联网访问", "इंटरनेट पहुँच",
        "Acceso a internet", "Accès Internet", "الوصول إلى الإنترنت",
    ),
    "Model ceiling: {ctx} tokens": (
        "Model ceiling: {ctx} tokens", "Teto do modelo: {ctx} tokens",
        "模型上限：{ctx} 个词元", "मॉडल सीमा: {ctx} टोकन",
        "Tope del modelo: {ctx} tokens", "Plafond du modèle : {ctx} jetons",
        "الحد الأقصى للنموذج: {ctx} رمزًا",
    ),
    "Model layers: {layers}": (
        "Model layers: {layers}", "Camadas do modelo: {layers}", "模型层数：{layers}",
        "मॉडल परतें: {layers}", "Capas del modelo: {layers}",
        "Couches du modèle : {layers}", "طبقات النموذج: {layers}",
    ),
    "Muted": (
        "Muted", "Silenciado", "已静音", "म्यूट", "Silenciado", "Sans son", "مكتوم",
    ),
    "No Codex step executed yet.": (
        "No Codex step executed yet.", "Nenhum passo do Codex foi executado ainda.",
        "尚未执行任何 Codex 步骤。", "अभी तक कोई Codex चरण नहीं चला।",
        "Todavía no se ejecutó ningún paso de Codex.",
        "Aucune étape Codex n'a encore été exécutée.",
        "لم تُنفَّذ أي خطوة من Codex بعد.",
    ),
    "No diff produced": (
        "No diff produced", "Nenhum diff foi produzido", "未生成差异",
        "कोई अंतर उत्पन्न नहीं हुआ", "No se generó ningún diff",
        "Aucun diff produit", "لم يُنتج أي فرق",
    ),
    "No project (Sandbox)": (
        "No project (Sandbox)", "Nenhum projeto (sandbox)", "无项目（沙箱）",
        "कोई प्रोजेक्ट नहीं (सैंडबॉक्स)", "Sin proyecto (sandbox)",
        "Aucun projet (bac à sable)", "لا مشروع (بيئة عزل)",
    ),
    "PC Profile Registered": (
        "PC Profile Registered", "Perfil do PC registrado", "已登记电脑配置",
        "पीसी प्रोफ़ाइल दर्ज है", "Perfil del equipo registrado",
        "Profil du PC enregistré", "ملف الحاسوب مسجل",
    ),
    "PC profile not registered yet": (
        "PC profile not registered yet", "Perfil do PC ainda não registrado",
        "尚未登记电脑配置", "पीसी प्रोफ़ाइल अभी दर्ज नहीं है",
        "El perfil del equipo aún no está registrado",
        "Profil du PC pas encore enregistré",
        "ملف الحاسوب غير مسجل بعد",
    ),
    "Path, pattern or shell command": (
        "Path, pattern or shell command", "Caminho, padrão ou comando de shell",
        "路径、匹配模式或 shell 命令", "पथ, पैटर्न या शेल कमांड",
        "Ruta, patrón o comando de shell", "Chemin, motif ou commande shell",
        "مسار أو نمط أو أمر صدفة",
    ),
    "Pick a subject and an action in the Professor bar.": (
        "Pick a subject and an action in the Professor bar.",
        "Escolha uma matéria e uma ação na barra do Professor.",
        "在教授栏中选择学科和操作。",
        "प्रोफ़ेसर बार में विषय और क्रिया चुनें।",
        "Elige una materia y una acción en la barra del Profesor.",
        "Choisissez une matière et une action dans la barre du Professeur.",
        "اختر مادة وإجراءً في شريط الأستاذ.",
    ),
    "Profile stored at {path}": (
        "Profile stored at {path}", "Perfil gravado em {path}", "配置已保存到 {path}",
        "प्रोफ़ाइल {path} में सहेजी गई", "Perfil guardado en {path}",
        "Profil enregistré dans {path}", "حُفظ الملف في {path}",
    ),
    "Re-scan PC": (
        "Re-scan PC", "Examinar o PC novamente", "重新扫描电脑", "पीसी फिर से स्कैन करें",
        "Volver a analizar el equipo", "Réanalyser le PC", "أعد فحص الحاسوب",
    ),
    "Ready": (
        "Ready", "Pronto", "就绪", "तैयार", "Listo", "Prêt", "جاهز",
    ),
    "Reload to apply the changes": (
        "Reload to apply the changes", "Recarregar para aplicar as mudanças",
        "重新加载以应用更改", "बदलाव लागू करने के लिए पुनः लोड करें",
        "Recargar para aplicar los cambios",
        "Recharger pour appliquer les changements",
        "أعد التحميل لتطبيق التغييرات",
    ),
    "Run step": (
        "Run step", "Executar passo", "运行步骤", "चरण चलाएँ", "Ejecutar paso",
        "Exécuter l'étape", "نفّذ الخطوة",
    ),
    "Running {action} in the sandbox...": (
        "Running {action} in the sandbox...", "Executando {action} no sandbox...",
        "正在沙箱中运行 {action}...", "सैंडबॉक्स में {action} चल रहा है...",
        "Ejecutando {action} en el sandbox...",
        "Exécution de {action} dans le bac à sable...",
        "جارٍ تنفيذ {action} في بيئة العزل...",
    ),
    "Scan PC Hardware": (
        "Scan PC Hardware", "Examinar o hardware do PC", "扫描电脑硬件",
        "पीसी हार्डवेयर स्कैन करें", "Analizar el hardware del equipo",
        "Analyser le matériel du PC", "افحص عتاد الحاسوب",
    ),
    "Scanning this PC...": (
        "Scanning this PC...", "Examinando este PC...", "正在扫描本机...",
        "इस पीसी को स्कैन किया जा रहा है...", "Analizando este equipo...",
        "Analyse de ce PC...", "جارٍ فحص هذا الحاسوب...",
    ),
    "Secondary model used if the primary fails": (
        "Secondary model used if the primary fails",
        "Modelo secundário usado se o primário falhar",
        "主模型失败时使用的备用模型", "प्राथमिक विफल होने पर उपयोग होने वाला द्वितीयक मॉडल",
        "Modelo secundario usado si falla el primario",
        "Modèle secondaire utilisé si le principal échoue",
        "نموذج ثانوي يُستخدم إذا فشل الأساسي",
    ),
    "Select the target file in the Engineer panel before running the sandbox.": (
        "Select the target file in the Engineer panel before running the sandbox.",
        "Selecione o arquivo alvo no painel do Engineer antes de rodar o sandbox.",
        "运行沙箱前，请先在工程师面板中选择目标文件。",
        "सैंडबॉक्स चलाने से पहले इंजीनियर पैनल में लक्ष्य फ़ाइल चुनें।",
        "Selecciona el archivo objetivo en el panel del Ingeniero antes de ejecutar el sandbox.",
        "Sélectionnez le fichier cible dans le panneau Ingénieur avant de lancer le bac à sable.",
        "اختر الملف الهدف في لوحة المهندس قبل تشغيل بيئة العزل.",
    ),
    "Select workspace": (
        "Select workspace", "Selecionar o workspace", "选择工作区", "वर्कस्पेस चुनें",
        "Seleccionar el espacio de trabajo", "Choisir l'espace de travail",
        "اختر مساحة العمل",
    ),
    "Step failed": (
        "Step failed", "O passo falhou", "步骤失败", "चरण विफल", "El paso falló",
        "Échec de l'étape", "فشل الخطوة",
    ),
    "Step finished": (
        "Step finished", "Passo concluído", "步骤已完成", "चरण पूरा हुआ",
        "Paso completado", "Étape terminée", "اكتملت الخطوة",
    ),
    "The Rust vault rejected the master password: {detail}": (
        "The Rust vault rejected the master password: {detail}",
        "O cofre Rust rejeitou a senha mestra: {detail}",
        "Rust 保险库拒绝了主密码：{detail}",
        "Rust तिजोरी ने मास्टर पासवर्ड अस्वीकार किया: {detail}",
        "La bóveda Rust rechazó la contraseña maestra: {detail}",
        "Le coffre Rust a refusé le mot de passe maître : {detail}",
        "رفض خزان Rust كلمة المرور الرئيسية: {detail}",
    ),
    "Thought Process": (
        "Thought Process", "Processo de raciocínio", "思考过程", "विचार प्रक्रिया",
        "Proceso de razonamiento", "Processus de réflexion", "عملية التفكير",
    ),
    "Unified Diff": (
        "Unified Diff", "Diff unificado", "统一差异", "एकीकृत अंतर", "Diff unificado",
        "Diff unifié", "فرق موحد",
    ),
    "Vault unlocked: {count} sealed entries opened by the Rust core.": (
        "Vault unlocked: {count} sealed entries opened by the Rust core.",
        "Cofre aberto: {count} entradas seladas abertas pelo núcleo Rust.",
        "保险库已解锁：Rust 内核打开了 {count} 条封存条目。",
        "तिजोरी खुल गई: Rust कोर ने {count} सीलबंद प्रविष्टियाँ खोलीं।",
        "Bóveda abierta: el núcleo Rust abrió {count} entradas selladas.",
        "Coffre déverrouillé : le cœur Rust a ouvert {count} entrées scellées.",
        "فُتح الخزان: فتحت نواة Rust {count} مدخلات مختومة.",
    ),
    "Web Access: OFF": (
        "Web Access: OFF", "Acesso web: desligado", "网页访问：关闭", "वेब पहुँच: बंद",
        "Acceso web: desactivado", "Accès web : désactivé", "الوصول للويب: متوقف",
    ),
    "Web Access: ON": (
        "Web Access: ON", "Acesso web: ligado", "网页访问：开启", "वेब पहुँच: चालू",
        "Acceso web: activado", "Accès web : activé", "الوصول للويب: مفعّل",
    ),
    "What shall we build?": (
        "What shall we build?", "O que vamos construir?", "我们要构建什么？",
        "हम क्या बनाएँ?", "¿Qué vamos a construir?", "Que allons-nous construire ?",
        "ماذا سنبني؟",
    ),
    "What shall we look at?": (
        "What shall we look at?", "O que vamos analisar?", "我们要看什么？",
        "हम क्या देखें?", "¿Qué vamos a mirar?", "Que allons-nous examiner ?",
        "إلى ماذا سننظر؟",
    ),
    "What shall we study?": (
        "What shall we study?", "O que vamos estudar?", "我们要学习什么？",
        "हम क्या अध्ययन करें?", "¿Qué vamos a estudiar ?", "Qu'allons-nous étudier ?",
        "ماذا سندرس؟",
    ),
    "VOICE CALL · IN-APP": (
        "VOICE CALL · IN-APP", "CHAMADA DE VOZ · IN-APP", "语音通话 · 应用内",
        "वॉइस कॉल · ऐप में", "LLAMADA DE VOZ · EN LA APP",
        "APPEL VOCAL · DANS L'APP", "مكالمة صوتية · داخل التطبيق",
    ),
    "Workspace": (
        "Workspace", "Workspace", "工作区", "वर्कस्पेस", "Espacio de trabajo",
        "Espace de travail", "مساحة العمل",
    ),
    "exit code": (
        "exit code", "código de saída", "退出码", "एग्ज़िट कोड", "código de salida",
        "code de sortie", "رمز الخروج",
    ),
    "mark-server binary missing: build the Rust workspace": (
        "mark-server binary missing: build the Rust workspace",
        "Binário do mark-server ausente: compile o workspace Rust",
        "缺少 mark-server 可执行文件：请构建 Rust 工作区",
        "mark-server बाइनरी अनुपस्थित है: Rust वर्कस्पेस बनाएँ",
        "Falta el ejecutable mark-server: compila el espacio de trabajo Rust",
        "Binaire mark-server manquant : compilez l'espace de travail Rust",
        "ملف mark-server التنفيذي مفقود: ابنِ مساحة عمل Rust",
    ),
    "no model selected": (
        "no model selected", "nenhum modelo selecionado", "未选择模型",
        "कोई मॉडल नहीं चुना गया", "ningún modelo seleccionado",
        "aucun modèle sélectionné", "لم يُحدد أي نموذج",
    ),
}


# Telas ativas: chamada de voz, navegacao, widgets, desktop e janela principal.
_SCREEN_TRANSLATIONS: dict[str, tuple[str, str, str, str, str, str, str]] = {
    " Toggle Menu": (
        " Toggle Menu", " Alternar Menu", " 切换菜单", " मेन्यू टॉगल करें", " Alternar menú", " Basculer le menu", " تبديل القائمة",
    ),
    " Verified Anchoring": (
        " Verified Anchoring", " Ancoragem Verificada", " 已验证锚定", " सत्यापित एंकरिंग", " Anclaje verificado", " Ancrage vérifié", " تثبيت موثّق",
    ),
    "+ New chat (Engineer)": (
        "+ New chat (Engineer)", "+ Nova conversa (Engineer)", "+ 新对话（工程师）", "+ नई चैट (इंजीनियर)", "+ Nuevo chat (Ingeniero)", "+ Nouveau chat (Ingénieur)", "+ دردشة جديدة (المهندس)",
    ),
    "--- LOCAL ENGINE & 1-BIT ---": (
        "--- LOCAL ENGINE & 1-BIT ---", "--- MOTOR LOCAL & 1-BIT ---", "--- 本地引擎与 1-BIT ---", "--- स्थानीय इंजन और 1-BIT ---", "--- MOTOR LOCAL Y 1-BIT ---", "--- MOTEUR LOCAL ET 1-BIT ---", "--- المحرك المحلي و1-BIT ---",
    ),
    "Action Confirmation · Human-in-the-Loop": (
        "Action Confirmation · Human-in-the-Loop", "Confirmação de Ação · Human-in-the-Loop", "操作确认 · 人在环路中", "क्रिया पुष्टि · ह्यूमन-इन-द-लूप", "Confirmación de acción · Human-in-the-Loop", "Confirmation d'action · Human-in-the-Loop", "تأكيد الإجراء · الإنسان في الحلقة",
    ),
    "Action Executed": (
        "Action Executed", "Ação Executada", "操作已执行", "क्रिया निष्पादित", "Acción ejecutada", "Action exécutée", "تم تنفيذ الإجراء",
    ),
    "Agentic Execution Permission": (
        "Agentic Execution Permission", "Permissão de Execução Agentizada", "代理执行权限", "एजेंटिक निष्पादन अनुमति", "Permiso de ejecución agéntica", "Autorisation d'exécution agentique", "إذن التنفيذ الوكيلي",
    ),
    "Anchored Original Excerpt:": (
        "Anchored Original Excerpt:", "Trecho Original Ancorado:", "已锚定的原始摘录：", "एंकर किया गया मूल अंश:", "Fragmento original anclado:", "Extrait original ancré :", "المقتطف الأصلي المثبَّت:",
    ),
    "Attach": (
        "Attach", "Anexar", "附加", "संलग्न करें", "Adjuntar", "Joindre", "إرفاق",
    ),
    "Audio output": (
        "Audio output", "Saída de áudio", "音频输出", "ऑडियो आउटपुट", "Salida de audio", "Sortie audio", "خرج الصوت",
    ),
    "Audio output:": (
        "Audio output:", "Saída de áudio:", "音频输出：", "ऑडियो आउटपुट:", "Salida de audio:", "Sortie audio :", "خرج الصوت:",
    ),
    "Authorize": (
        "Authorize", "Autorizar", "授权", "अनुमति दें", "Autorizar", "Autoriser", "السماح",
    ),
    "Back to Chat": (
        "Back to Chat", "Voltar para Conversa", "返回聊天", "चैट पर वापस जाएँ", "Volver al chat", "Retour au chat", "العودة إلى الدردشة",
    ),
    "Balanced reasoning": (
        "Balanced reasoning", "Raciocínio Balanceado", "均衡推理", "संतुलित तर्क", "Razonamiento equilibrado", "Raisonnement équilibré", "تفكير متوازن",
    ),
    "Browse...": (
        "Browse...", "Procurar...", "浏览...", "ब्राउज़ करें...", "Examinar...", "Parcourir...", "تصفح...",
    ),
    "CTX: -": (
        "CTX: -", "CTX: -", "CTX: -", "CTX: -", "CTX: -", "CTX: -", "CTX: -",
    ),
    "CTX: --": (
        "CTX: --", "CTX: --", "CTX: --", "CTX: --", "CTX: --", "CTX: --", "CTX: --",
    ),
    "Call ended": (
        "Call ended", "Chamada encerrada", "通话已结束", "कॉल समाप्त हुई", "Llamada finalizada", "Appel terminé", "انتهت المكالمة",
    ),
    "Call with MARK": (
        "Call with MARK", "Chamada com MARK", "与 MARK 通话", "MARK के साथ कॉल", "Llamada con MARK", "Appel avec MARK", "مكالمة مع MARK",
    ),
    "Cancel": (
        "Cancel", "Cancelar", "取消", "रद्द करें", "Cancelar", "Annuler", "إلغاء",
    ),
    "Cancel Task": (
        "Cancel Task", "Cancelar Tarefa", "取消任务", "कार्य रद्द करें", "Cancelar tarea", "Annuler la tâche", "إلغاء المهمة",
    ),
    "Cancelling task...": (
        "Cancelling task...", "Cancelando tarefa...", "正在取消任务...", "कार्य रद्द किया जा रहा है...", "Cancelando la tarea...", "Annulation de la tâche...", "جارٍ إلغاء المهمة...",
    ),
    "Chat unavailable": (
        "Chat unavailable", "Chat indisponível", "聊天不可用", "चैट उपलब्ध नहीं है", "Chat no disponible", "Chat indisponible", "الدردشة غير متاحة",
    ),
    "Checking connection...": (
        "Checking connection...", "Verificando conexão...", "正在检查连接...", "कनेक्शन जाँचा जा रहा है...", "Comprobando la conexión...", "Vérification de la connexion...", "جارٍ التحقق من الاتصال...",
    ),
    "Checking the configured model...": (
        "Checking the configured model...", "Verificando o modelo configurado...", "正在检查已配置的模型...", "कॉन्फ़िगर किया गया मॉडल जाँचा जा रहा है...", "Comprobando el modelo configurado...", "Vérification du modèle configuré...", "جارٍ التحقق من النموذج المهيأ...",
    ),
    "Checking the connection to MARK...": (
        "Checking the connection to MARK...", "Conferindo conexão com o MARK...", "正在检查与 MARK 的连接...", "MARK से कनेक्शन जाँचा जा रहा है...", "Comprobando la conexión con MARK...", "Vérification de la connexion à MARK...", "جارٍ التحقق من الاتصال بـ MARK...",
    ),
    "Checking the model configured in Ollama...": (
        "Checking the model configured in Ollama...", "Verificando o modelo configurado no Ollama...", "正在检查 Ollama 中配置的模型...", "Ollama में कॉन्फ़िगर किया गया मॉडल जाँचा जा रहा है...", "Comprobando el modelo configurado en Ollama...", "Vérification du modèle configuré dans Ollama...", "جارٍ التحقق من النموذج المهيأ في Ollama...",
    ),
    "Checking the routine status...": (
        "Checking the routine status...", "Consultando o estado da rotina...", "正在查询例行状态...", "रूटीन की स्थिति देखी जा रही है...", "Consultando el estado de la rutina...", "Consultation de l'état de la routine...", "جارٍ الاستعلام عن حالة الروتين...",
    ),
    "Choose where MARK plays the spoken answer": (
        "Choose where MARK plays the spoken answer", "Escolha onde o MARK reproduz a resposta falada", "选择 MARK 播放语音回答的位置", "चुनें कि MARK बोली जाने वाली प्रतिक्रिया कहाँ चलाए", "Elige dónde reproduce MARK la respuesta hablada", "Choisissez où MARK diffuse la réponse parlée", "اختر المكان الذي يشغّل فيه MARK الإجابة المنطوقة",
    ),
    "Close": (
        "Close", "Fechar", "关闭", "बंद करें", "Cerrar", "Fermer", "إغلاق",
    ),
    "Code self-evolution proposes changes and measures and verifies each cycle in isolation; only your review installs a proposal. QLoRA training is a separate process: it produces a candidate adapter and requires an evaluation of quality, VRAM and energy.": (
        "Code self-evolution proposes changes and measures and verifies each cycle in isolation; only your review installs a proposal. QLoRA training is a separate process: it produces a candidate adapter and requires an evaluation of quality, VRAM and energy.", "A Autoevolução de código propõe mudanças, mede e verifica cada ciclo isoladamente; só uma revisão sua instala uma proposta. O treino QLoRA é outro processo: produz um adaptador candidato e exige avaliação de qualidade, VRAM e energia.", "代码自进化会提出改动，并对每个循环单独测量和验证；只有经过你的审阅，才会安装某个提案。QLoRA 训练是另一个过程：它产出一个候选适配器，需要对质量、显存和能耗进行评估。", "कोड स्व-विकास बदलाव सुझाता है और हर चक्र को अलग से मापता और जाँचता है; किसी प्रस्ताव को केवल आपकी समीक्षा ही स्थापित करती है। QLoRA प्रशिक्षण अलग प्रक्रिया है: यह एक उम्मीदवार एडाप्टर बनाता है और गुणवत्ता, VRAM तथा ऊर्जा के मूल्यांकन की मांग करता है।", "La autoevolución de código propone cambios, mide y verifica cada ciclo por separado; solo tu revisión instala una propuesta. El entrenamiento QLoRA es otro proceso: produce un adaptador candidato y exige una evaluación de calidad, VRAM y energía.", "L'auto-évolution du code propose des changements, mesure et vérifie chaque cycle isolément ; seule votre relecture installe une proposition. L'entraînement QLoRA est un autre processus : il produit un adaptateur candidat et exige une évaluation de la qualité, de la VRAM et de l'énergie.", "يقترح التطور الذاتي للشيفرة تغييرات ويقيس ويثبت كل دورة بشكل منفصل؛ ولا تُثبَّت أي مقترحات إلا بمراجعتك. تدريب QLoRA عملية أخرى: ينتج محولًا مرشحًا ويتطلب تقييمًا للجودة وذاكرة الرسوميات والطاقة.",
    ),
    "Command Menu (Ctrl+K)": (
        "Command Menu (Ctrl+K)", "Menu de Comandos (Ctrl+K)", "命令菜单（Ctrl+K）", "कमांड मेन्यू (Ctrl+K)", "Menú de comandos (Ctrl+K)", "Menu des commandes (Ctrl+K)", "قائمة الأوامر (Ctrl+K)",
    ),
    "Complete current plan": (
        "Complete current plan", "Concluir plano atual", "完成当前计划", "मौजूदा योजना पूरी करें", "Completar el plan actual", "Terminer le plan en cours", "إكمال الخطة الحالية",
    ),
    "Configure models in Ollama or API keys in the vault.": (
        "Configure models in Ollama or API keys in the vault.", "Configure modelos no Ollama ou chaves de API no cofre.", "请在 Ollama 中配置模型，或在保险库中配置 API 密钥。", "Ollama में मॉडल या वॉल्ट में API कुंजियाँ कॉन्फ़िगर करें।", "Configura modelos en Ollama o claves de API en la caja fuerte.", "Configurez des modèles dans Ollama ou des clés d'API dans le coffre.", "قم بتهيئة النماذج في Ollama أو مفاتيح API في الخزنة.",
    ),
    "Copy answer": (
        "Copy answer", "Copiar resposta", "复制回答", "उत्तर कॉपी करें", "Copiar respuesta", "Copier la réponse", "نسخ الإجابة",
    ),
    "Could not play the answer": (
        "Could not play the answer", "Falha ao reproduzir a resposta", "无法播放回答", "उत्तर चलाया नहीं जा सका", "No se pudo reproducir la respuesta", "Impossible de lire la réponse", "تعذّر تشغيل الإجابة",
    ),
    "Deep reasoning": (
        "Deep reasoning", "Raciocínio Profundo", "深度推理", "गहन तर्क", "Razonamiento profundo", "Raisonnement approfondi", "تفكير عميق",
    ),
    "Delete progress...": (
        "Delete progress...", "Apagar progresso...", "删除进度...", "प्रगति हटाएँ...", "Borrar progreso...", "Effacer la progression...", "حذف التقدم...",
    ),
    "E.g.: Electronics handbook.pdf": (
        "E.g.: Electronics handbook.pdf", "Ex.: Manual de eletrônica.pdf", "例如：电子学手册.pdf", "जैसे: इलेक्ट्रॉनिक्स पुस्तिका.pdf", "Ej.: Manual de electrónica.pdf", "Ex. : Manuel d'électronique.pdf", "مثال: دليل الإلكترونيات.pdf",
    ),
    "E.g.: electrical circuits": (
        "E.g.: electrical circuits", "Ex.: circuitos elétricos", "例如：电路", "जैसे: विद्युत परिपथ", "Ej.: circuitos eléctricos", "Ex. : circuits électriques", "مثال: الدوائر الكهربائية",
    ),
    "ENGINEER · CODEX WORKFLOW": (
        "ENGINEER · CODEX WORKFLOW", "ENGENHEIRO · FLUXO CODEX", "工程师 · CODEX 工作流", "इंजीनियर · CODEX कार्यप्रवाह", "INGENIERO · FLUJO CODEX", "INGÉNIEUR · FLUX CODEX", "المهندس · سير عمل CODEX",
    ),
    "ENGINEER · MARK 1.5B": (
        "ENGINEER · MARK 1.5B", "ENGENHEIRO · MARK 1.5B", "工程师 · MARK 1.5B", "इंजीनियर · MARK 1.5B", "INGENIERO · MARK 1.5B", "INGÉNIEUR · MARK 1.5B", "المهندس · MARK 1.5B",
    ),
    "End and Go Back": (
        "End and Go Back", "Encerrar e Voltar", "结束并返回", "समाप्त करें और लौटें", "Terminar y volver", "Terminer et revenir", "إنهاء والعودة",
    ),
    "Ending the call...": (
        "Ending the call...", "Encerrando a chamada...", "正在结束通话...", "कॉल समाप्त हो रही है...", "Finalizando la llamada...", "Fin de l'appel...", "جارٍ إنهاء المكالمة...",
    ),
    "Engineer is analysing your request...": (
        "Engineer is analysing your request...", "Engineer está analisando sua solicitação...", "工程师正在分析你的请求...", "इंजीनियर आपका अनुरोध विश्लेषित कर रहा है...", "El ingeniero está analizando tu solicitud...", "L'ingénieur analyse votre demande...", "المهندس يحلل طلبك...",
    ),
    "Engineer profile": (
        "Engineer profile", "Perfil Engineer", "工程师配置", "इंजीनियर प्रोफ़ाइल", "Perfil de ingeniero", "Profil ingénieur", "ملف المهندس",
    ),
    "Engineer uses the configured code profile and the shared memory.": (
        "Engineer uses the configured code profile and the shared memory.", "O Engineer usa o perfil de código configurado e a memória compartilhada.", "工程师使用已配置的代码配置和共享记忆。", "इंजीनियर कॉन्फ़िगर की गई कोड प्रोफ़ाइल और साझा स्मृति का उपयोग करता है।", "El ingeniero usa el perfil de código configurado y la memoria compartida.", "L'ingénieur utilise le profil de code configuré et la mémoire partagée.", "يستخدم المهندس ملف الشيفرة المهيأ والذاكرة المشتركة.",
    ),
    "Enter sends · Shift+Enter for a new line": (
        "Enter sends · Shift+Enter for a new line", "Enter envia · Shift+Enter nova linha", "Enter 发送 · Shift+Enter 换行", "Enter भेजता है · Shift+Enter नई पंक्ति", "Enter envía · Shift+Enter para una línea nueva", "Entrée envoie · Maj+Entrée pour une nouvelle ligne", "Enter يرسل · Shift+Enter لسطر جديد",
    ),
    "Expand or collapse the sidebar": (
        "Expand or collapse the sidebar", "Expandir ou recolher barra lateral", "展开或收起侧边栏", "साइडबार फैलाएँ या समेटें", "Expandir o contraer la barra lateral", "Développer ou réduire la barre latérale", "توسيع الشريط الجانبي أو طيّه",
    ),
    "Filter conversations...": (
        "Filter conversations...", "Filtrar conversas...", "筛选对话...", "बातचीत फ़िल्टर करें...", "Filtrar conversaciones...", "Filtrer les conversations...", "تصفية المحادثات...",
    ),
    "GOD'S EYE VIEW · AGENTIC EXECUTION": (
        "GOD'S EYE VIEW · AGENTIC EXECUTION", "GOD'S EYE VIEW · EXECUÇÃO AGENTIZADA", "上帝视角 · 代理执行", "गॉड्स आई व्यू · एजेंटिक निष्पादन", "GOD'S EYE VIEW · EJECUCIÓN AGÉNTICA", "GOD'S EYE VIEW · EXÉCUTION AGENTIQUE", "عين الله · تنفيذ وكيلي",
    ),
    "Goal (optional)": (
        "Goal (optional)", "Objetivo (opcional)", "目标（可选）", "लक्ष्य (वैकल्पिक)", "Objetivo (opcional)", "Objectif (facultatif)", "الهدف (اختياري)",
    ),
    "Headphones": (
        "Headphones", "Fone de Ouvido", "耳机", "हेडफ़ोन", "Auriculares", "Casque", "سماعة رأس",
    ),
    "I could not finish speaking": (
        "I could not finish speaking", "Não consegui concluir a fala", "我没能说完", "मैं बोलना पूरा नहीं कर सका", "No pude terminar de hablar", "Je n'ai pas pu terminer de parler", "لم أتمكن من إكمال الكلام",
    ),
    "I could not refresh the local Engineer status.": (
        "I could not refresh the local Engineer status.", "Não consegui atualizar o estado local do Engineer.", "我无法更新工程师的本地状态。", "मैं इंजीनियर की स्थानीय स्थिति ताज़ा नहीं कर सका।", "No pude actualizar el estado local del ingeniero.", "Je n'ai pas pu actualiser l'état local de l'ingénieur.", "لم أتمكن من تحديث حالة المهندس المحلية.",
    ),
    "Images, PDFs, DOCX documents and text files": (
        "Images, PDFs, DOCX documents and text files", "Imagens, PDFs, documentos DOCX e arquivos de texto", "图片、PDF、DOCX 文档和文本文件", "चित्र, PDF, DOCX दस्तावेज़ और टेक्स्ट फ़ाइलें", "Imágenes, PDF, documentos DOCX y archivos de texto", "Images, PDF, documents DOCX et fichiers texte", "صور وملفات PDF ومستندات DOCX وملفات نصية",
    ),
    "Instant reasoning": (
        "Instant reasoning", "Raciocínio Instantâneo", "即时推理", "तत्काल तर्क", "Razonamiento instantáneo", "Raisonnement instantané", "تفكير فوري",
    ),
    "Instant: no extended reasoning, 4k context and up to 512 tokens.\nBalanced: 6k context and up to 2048 tokens.\nDeep: 8k context and up to 4096 tokens, with a deeper explanation.": (
        "Instant: no extended reasoning, 4k context and up to 512 tokens.\nBalanced: 6k context and up to 2048 tokens.\nDeep: 8k context and up to 4096 tokens, with a deeper explanation.", "Instantâneo: sem raciocínio estendido, contexto 4k e até 512 tokens.\nBalanceado: contexto 6k e até 2048 tokens.\nProfundo: contexto 8k e até 4096 tokens, com explicação mais aprofundada.", "即时：不使用扩展推理，4k 上下文，最多 512 个词元。\n均衡：6k 上下文，最多 2048 个词元。\n深度：8k 上下文，最多 4096 个词元，并提供更深入的解释。", "तत्काल: विस्तारित तर्क नहीं, 4k संदर्भ और अधिकतम 512 टोकन।\nसंतुलित: 6k संदर्भ और अधिकतम 2048 टोकन।\nगहन: 8k संदर्भ और अधिकतम 4096 टोकन, अधिक विस्तृत व्याख्या के साथ।", "Instantáneo: sin razonamiento extendido, contexto de 4k y hasta 512 tokens.\nEquilibrado: contexto de 6k y hasta 2048 tokens.\nProfundo: contexto de 8k y hasta 4096 tokens, con una explicación más detallada.", "Instantané : sans raisonnement étendu, contexte 4k et jusqu'à 512 jetons.\nÉquilibré : contexte 6k et jusqu'à 2048 jetons.\nProfond : contexte 8k et jusqu'à 4096 jetons, avec une explication plus approfondie.", "فوري: بدون تفكير موسّع، سياق 4k وحتى 512 رمزًا.\nمتوازن: سياق 6k وحتى 2048 رمزًا.\nعميق: سياق 8k وحتى 4096 رمزًا، مع شرح أعمق.",
    ),
    "Instant: no extended reasoning, 4k context and up to 512 tokens. Balanced: 6k context and up to 2048 tokens. Deep: 8k context and up to 4096 tokens, with a deeper explanation.": (
        "Instant: no extended reasoning, 4k context and up to 512 tokens. Balanced: 6k context and up to 2048 tokens. Deep: 8k context and up to 4096 tokens, with a deeper explanation.", "Instantâneo: sem raciocínio estendido, contexto 4k e até 512 tokens. Balanceado: contexto 6k e até 2048 tokens. Profundo: contexto 8k e até 4096 tokens, com explicação mais aprofundada.", "即时：不使用扩展推理，4k 上下文，最多 512 个词元。均衡：6k 上下文，最多 2048 个词元。深度：8k 上下文，最多 4096 个词元，并提供更深入的解释。", "तत्काल: विस्तारित तर्क नहीं, 4k संदर्भ और अधिकतम 512 टोकन। संतुलित: 6k संदर्भ और अधिकतम 2048 टोकन। गहन: 8k संदर्भ और अधिकतम 4096 टोकन, अधिक विस्तृत व्याख्या के साथ।", "Instantáneo: sin razonamiento extendido, contexto de 4k y hasta 512 tokens. Equilibrado: contexto de 6k y hasta 2048 tokens. Profundo: contexto de 8k y hasta 4096 tokens, con una explicación más detallada.", "Instantané : sans raisonnement étendu, contexte 4k et jusqu'à 512 jetons. Équilibré : contexte 6k et jusqu'à 2048 jetons. Profond : contexte 8k et jusqu'à 4096 jetons, avec une explication plus approfondie.", "فوري: بدون تفكير موسّع، سياق 4k وحتى 512 رمزًا. متوازن: سياق 6k وحتى 2048 رمزًا. عميق: سياق 8k وحتى 4096 رمزًا، مع شرح أعمق.",
    ),
    "Interrupt the answer and speak": (
        "Interrupt the answer and speak", "Interromper resposta e falar", "打断回答并说话", "उत्तर रोककर बोलें", "Interrumpir la respuesta y hablar", "Interrompre la réponse et parler", "قاطع الإجابة وتحدث",
    ),
    "Library source (optional; exact title)": (
        "Library source (optional; exact title)", "Fonte da Biblioteca (opcional; título exato)", "库来源（可选；精确标题）", "लाइब्रेरी स्रोत (वैकल्पिक; सटीक शीर्षक)", "Fuente de la biblioteca (opcional; título exacto)", "Source de la bibliothèque (facultatif ; titre exact)", "مصدر المكتبة (اختياري؛ العنوان الدقيق)",
    ),
    "Listening...": (
        "Listening...", "Ouvindo...", "正在聆听...", "सुन रहा है...", "Escuchando...", "Écoute...", "جارٍ الاستماع...",
    ),
    "Listening... (Voice active)": (
        "Listening... (Voice active)", "Ouvindo... (Voz ativa)", "正在聆听...（语音已启用）", "सुन रहा है... (आवाज़ सक्रिय)", "Escuchando... (Voz activa)", "Écoute... (voix active)", "جارٍ الاستماع... (الصوت مفعّل)",
    ),
    "Loading...": (
        "Loading...", "Carregando...", "正在加载...", "लोड हो रहा है...", "Cargando...", "Chargement...", "جارٍ التحميل...",
    ),
    "MARK": (
        "MARK", "MARK", "MARK", "MARK", "MARK", "MARK", "MARK",
    ),
    "MARK is speaking...": (
        "MARK is speaking...", "MARK está falando...", "MARK 正在说话...", "MARK बोल रहा है...", "MARK está hablando...", "MARK parle...", "MARK يتحدث...",
    ),
    "MARK operational · shared memory active": (
        "MARK operational · shared memory active", "MARK operacional · memória compartilhada ativa", "MARK 运行中 · 共享记忆已启用", "MARK संचालित · साझा स्मृति सक्रिय", "MARK operativo · memoria compartida activa", "MARK opérationnel · mémoire partagée active", "MARK قيد التشغيل · الذاكرة المشتركة مفعّلة",
    ),
    "MARK · Operational": (
        "MARK · Operational", "MARK · Operacional", "MARK · 运行中", "MARK · संचालित", "MARK · Operativo", "MARK · Opérationnel", "MARK · قيد التشغيل",
    ),
    "MARK · Personal Assistant": (
        "MARK · Personal Assistant", "MARK · Assistente Pessoal", "MARK · 个人助理", "MARK · व्यक्तिगत सहायक", "MARK · Asistente personal", "MARK · Assistant personnel", "MARK · المساعد الشخصي",
    ),
    "MARK · WORKSPACE": (
        "MARK · WORKSPACE", "MARK · ÁREA DE TRABALHO", "MARK · 工作区", "MARK · कार्यक्षेत्र", "MARK · ÁREA DE TRABAJO", "MARK · ESPACE DE TRAVAIL", "MARK · مساحة العمل",
    ),
    "Manage saved memories...": (
        "Manage saved memories...", "Gerenciar memórias salvas...", "管理已保存的记忆...", "सहेजी गई यादें प्रबंधित करें...", "Gestionar memorias guardadas...", "Gérer les souvenirs enregistrés...", "إدارة الذكريات المحفوظة...",
    ),
    "Models and APIs...": (
        "Models and APIs...", "Modelos e APIs...", "模型与 API...", "मॉडल और API...", "Modelos y APIs...", "Modèles et API...", "النماذج وواجهات API...",
    ),
    "No Ollama model installed": (
        "No Ollama model installed", "Nenhum modelo Ollama instalado", "未安装 Ollama 模型", "कोई Ollama मॉडल स्थापित नहीं", "Ningún modelo de Ollama instalado", "Aucun modèle Ollama installé", "لا يوجد نموذج Ollama مثبّت",
    ),
    "No active provider - configure the keys": (
        "No active provider - configure the keys", "Nenhum provedor ativo - Configure as Chaves", "没有启用的提供方 - 请配置密钥", "कोई सक्रिय प्रदाता नहीं - कुंजियाँ कॉन्फ़िगर करें", "Ningún proveedor activo - configura las claves", "Aucun fournisseur actif - configurez les clés", "لا مزوّد نشط - قم بتهيئة المفاتيح",
    ),
    "No active provider or model.": (
        "No active provider or model.", "Nenhum provedor ou modelo ativo.", "没有启用的提供方或模型。", "कोई सक्रिय प्रदाता या मॉडल नहीं।", "Ningún proveedor o modelo activo.", "Aucun fournisseur ni modèle actif.", "لا مزوّد أو نموذج نشط.",
    ),
    "No directory selected": (
        "No directory selected", "Nenhum diretório selecionado", "未选择目录", "कोई फ़ोल्डर चुना नहीं गया", "Ningún directorio seleccionado", "Aucun dossier sélectionné", "لم يتم اختيار مجلد",
    ),
    "No output available": (
        "No output available", "Nenhuma saída disponível", "没有可用的输出设备", "कोई आउटपुट उपलब्ध नहीं", "No hay salida disponible", "Aucune sortie disponible", "لا يوجد خرج متاح",
    ),
    "Open chat": (
        "Open chat", "Abrir conversa", "打开聊天", "चैट खोलें", "Abrir chat", "Ouvrir le chat", "فتح الدردشة",
    ),
    "Open evolution panel": (
        "Open evolution panel", "Abrir painel de evolução", "打开进化面板", "विकास पैनल खोलें", "Abrir panel de evolución", "Ouvrir le panneau d'évolution", "فتح لوحة التطور",
    ),
    "Open the call inside the app": (
        "Open the call inside the app", "Abrir chamada dentro do app", "在应用内打开通话", "ऐप के भीतर कॉल खोलें", "Abrir la llamada dentro de la aplicación", "Ouvrir l'appel dans l'application", "فتح المكالمة داخل التطبيق",
    ),
    "PC, phone and voice · one shared memory": (
        "PC, phone and voice · one shared memory", "PC, celular e voz · uma memória compartilhada", "电脑、手机和语音 · 一份共享记忆", "कंप्यूटर, फ़ोन और आवाज़ · एक साझा स्मृति", "PC, móvil y voz · una memoria compartilhada", "PC, téléphone et voix · une mémoire partagée", "الحاسوب والهاتف والصوت · ذاكرة مشتركة واحدة",
    ),
    "PERSONAL ASSISTANT": (
        "PERSONAL ASSISTANT", "ASSISTENTE PESSOAL", "个人助理", "व्यक्तिगत सहायक", "ASISTENTE PERSONAL", "ASSISTANT PERSONNEL", "المساعد الشخصي",
    ),
    "PROFESSOR · ASTRA": (
        "PROFESSOR · ASTRA", "PROFESSOR · ASTRA", "教授 · ASTRA", "प्रोफेसर · ASTRA", "PROFESOR · ASTRA", "PROFESSEUR · ASTRA", "الأستاذ · ASTRA",
    ),
    "Plan and progress": (
        "Plan and progress", "Plano e progresso", "计划与进度", "योजना और प्रगति", "Plan y progreso", "Plan et progression", "الخطة والتقدم",
    ),
    "Plan and progress ▾": (
        "Plan and progress ▾", "Plano e progresso ▾", "计划与进度 ▾", "योजना और प्रगति ▾", "Plan y progreso ▾", "Plan et progression ▾", "الخطة والتقدم ▾",
    ),
    "Prepare study": (
        "Prepare study", "Preparar estudo", "准备学习", "अध्ययन तैयार करें", "Preparar estudio", "Préparer l'étude", "تحضير الدراسة",
    ),
    "Project context": (
        "Project context", "Contexto do projeto", "项目上下文", "प्रोजेक्ट संदर्भ", "Contexto del proyecto", "Contexte du projet", "سياق المشروع",
    ),
    "RECENT CHATS": (
        "RECENT CHATS", "CONVERSAS RECENTES", "最近的对话", "हाल की चैट", "CHATS RECIENTES", "CONVERSATIONS RÉCENTES", "الدردشات الأخيرة",
    ),
    "Ready to talk": (
        "Ready to talk", "Pronto para conversar", "可以开始交谈", "बात करने के लिए तैयार", "Listo para conversar", "Prêt à parler", "جاهز للتحدث",
    ),
    "Refresh summary": (
        "Refresh summary", "Atualizar resumo", "刷新摘要", "सारांश ताज़ा करें", "Actualizar resumen", "Actualiser le résumé", "تحديث الملخص",
    ),
    "Refreshing routine status...": (
        "Refreshing routine status...", "Atualizando estado da rotina...", "正在更新例行状态...", "रूटीन स्थिति ताज़ा की जा रही है...", "Actualizando el estado de la rutina...", "Actualisation de l'état de la routine...", "جارٍ تحديث حالة الروتين...",
    ),
    "Remember this decision (always authorise this API)": (
        "Remember this decision (always authorise this API)", "Lembrar desta decisão (Autorizar sempre para esta API)", "记住此决定（始终授权此 API）", "यह निर्णय याद रखें (इस API को हमेशा अनुमति दें)", "Recordar esta decisión (autorizar siempre esta API)", "Mémoriser cette décision (toujours autoriser cette API)", "تذكّر هذا القرار (السماح دائمًا لهذه الواجهة)",
    ),
    "Requested Tool": (
        "Requested Tool", "Ferramenta Solicitada", "请求的工具", "अनुरोधित टूल", "Herramienta solicitada", "Outil demandé", "الأداة المطلوبة",
    ),
    "Requested parameters:": (
        "Requested parameters:", "Parâmetros solicitados:", "请求的参数：", "अनुरोधित पैरामीटर:", "Parámetros solicitados:", "Paramètres demandés :", "المعاملات المطلوبة:",
    ),
    "Resume last plan": (
        "Resume last plan", "Retomar último plano", "继续上一个计划", "पिछली योजना फिर शुरू करें", "Retomar el último plan", "Reprendre le dernier plan", "استئناف الخطة الأخيرة",
    ),
    "Routine status unavailable; open the panel to see the details.": (
        "Routine status unavailable; open the panel to see the details.", "Estado da rotina indisponível; abra o painel para consultar os detalhes.", "例行状态不可用；请打开面板查看详情。", "रूटीन स्थिति उपलब्ध नहीं; विवरण देखने के लिए पैनल खोलें।", "Estado de la rutina no disponible; abre el panel para consultar los detalles.", "État de la routine indisponible ; ouvrez le panneau pour consulter les détails.", "حالة الروتين غير متاحة؛ افتح اللوحة لعرض التفاصيل.",
    ),
    "Settings": (
        "Settings", "Configurações", "设置", "सेटिंग्स", "Ajustes", "Paramètres", "الإعدادات",
    ),
    "Shared chat, call and vision": (
        "Shared chat, call and vision", "Conversa compartilhada, chamada e visão", "共享聊天、通话与视觉", "साझा चैट, कॉल और विज़न", "Chat, llamada y visión compartidos", "Chat, appel et vision partagés", "دردشة ومكالمة ورؤية مشتركة",
    ),
    "Short optional ID, for example mark-core": (
        "Short optional ID, for example mark-core", "ID curto e opcional, por exemplo mark-core", "可选的简短 ID，例如 mark-core", "वैकल्पिक छोटा ID, जैसे mark-core", "ID corto y opcional, por ejemplo mark-core", "ID court et facultatif, par exemple mark-core", "معرّف قصير واختياري، مثل mark-core",
    ),
    "Speak naturally; MARK listens until you pause.": (
        "Speak naturally; MARK listens until you pause.", "Fale naturalmente; o MARK escuta até você fazer uma pausa.", "自然说话即可，MARK 会一直聆听到你停顿。", "स्वाभाविक बोलें; MARK तब तक सुनता है जब तक आप रुकें।", "Habla con naturalidad; MARK escucha hasta que hagas una pausa.", "Parlez naturellement ; MARK écoute jusqu'à ce que vous fassiez une pause.", "تحدث بعفوية؛ يستمع MARK حتى تتوقف.",
    ),
    "Speak normally. MARK answers directly by voice on the PC.": (
        "Speak normally. MARK answers directly by voice on the PC.", "Fale normalmente. O MARK responde diretamente por voz no PC.", "正常说话即可，MARK 会直接在电脑上用语音回答。", "सामान्य रूप से बोलें। MARK कंप्यूटर पर सीधे आवाज़ में उत्तर देता है।", "Habla con normalidad. MARK responde directamente por voz en el equipo.", "Parlez normalement. MARK répond directement par la voix sur l'ordinateur.", "تحدث بشكل طبيعي. يجيب MARK مباشرة بالصوت على الحاسوب.",
    ),
    "Speak normally. MARK answers through the headset or the PC speakers.": (
        "Speak normally. MARK answers through the headset or the PC speakers.", "Fale normalmente. O MARK responde pelo fone ou alto-falante do PC.", "正常说话即可，MARK 会通过耳机或电脑扬声器回答。", "सामान्य रूप से बोलें। MARK हेडसेट या कंप्यूटर के स्पीकर से उत्तर देता है।", "Habla con normalidad. MARK responde por los auriculares o los altavoces del equipo.", "Parlez normalement. MARK répond par le casque ou les haut-parleurs de l'ordinateur.", "تحدث بشكل طبيعي. يجيب MARK عبر سماعة الرأس أو مكبرات صوت الحاسوب.",
    ),
    "Start call": (
        "Start call", "Iniciar chamada", "开始通话", "कॉल शुरू करें", "Iniciar llamada", "Démarrer l'appel", "بدء المكالمة",
    ),
    "Start with": (
        "Start with", "Começar com", "从以下开始", "इससे शुरू करें", "Empezar con", "Commencer avec", "ابدأ بـ",
    ),
    "Step 1/3": (
        "Step 1/3", "Passo 1/3", "第 1/3 步", "चरण 1/3", "Paso 1/3", "Étape 1/3", "الخطوة 1/3",
    ),
    "Subject": (
        "Subject", "Assunto", "主题", "विषय", "Asunto", "Sujet", "الموضوع",
    ),
    "Success Confirmed": (
        "Success Confirmed", "Sucesso Confirmado", "已确认成功", "सफलता की पुष्टि", "Éxito confirmado", "Succès confirmé", "تم تأكيد النجاح",
    ),
    "System Default Speaker": (
        "System Default Speaker", "Alto-falante Padrão do Sistema", "系统默认扬声器", "सिस्टम का डिफ़ॉल्ट स्पीकर", "Altavoz predeterminado del sistema", "Haut-parleur par défaut du système", "مكبر الصوت الافتراضي للنظام",
    ),
    "Test camera": (
        "Test camera", "Testar câmera", "测试摄像头", "कैमरा जाँचें", "Probar cámara", "Tester la caméra", "اختبار الكاميرا",
    ),
    "Testing camera...": (
        "Testing camera...", "Testando câmera...", "正在测试摄像头...", "कैमरा जाँचा जा रहा है...", "Probando la cámara...", "Test de la caméra...", "جارٍ اختبار الكاميرا...",
    ),
    "The ID separates this project's context and memories. To allow reading, editing or testing files, open a Task and choose the working folder.": (
        "The ID separates this project's context and memories. To allow reading, editing or testing files, open a Task and choose the working folder.", "O ID separa o contexto e as memórias deste projeto. Para permitir leitura, edição ou testes em arquivos, abra uma Tarefa e escolha a pasta de trabalho.", "该 ID 用于区分本项目的上下文和记忆。若要允许读取、编辑或测试文件，请打开一个任务并选择工作文件夹。", "यह ID इस प्रोजेक्ट का संदर्भ और यादें अलग रखता है। फ़ाइलों को पढ़ने, बदलने या परखने की अनुमति देने के लिए एक कार्य खोलें और कार्य फ़ोल्डर चुनें।", "El ID separa el contexto y las memorias de este proyecto. Para permitir lectura, edición o pruebas de archivos, abre una Tarea y elige la carpeta de trabajo.", "L'ID sépare le contexte et les souvenirs de ce projet. Pour autoriser la lecture, la modification ou les tests de fichiers, ouvrez une Tâche et choisissez le dossier de travail.", "يفصل المعرّف سياق هذا المشروع وذكرياته. للسماح بقراءة الملفات أو تعديلها أو اختبارها، افتح مهمة واختر مجلد العمل.",
    ),
    "The microphone turns on only after the server answers.": (
        "The microphone turns on only after the server answers.", "O microfone só será ativado depois que o servidor responder.", "只有在服务器应答后才会启用麦克风。", "सर्वर के उत्तर देने के बाद ही माइक्रोफ़ोन चालू होगा।", "El micrófono solo se activa cuando el servidor responde.", "Le microphone ne s'active qu'après la réponse du serveur.", "لا يُفعَّل الميكروفون إلا بعد أن يجيب الخادم.",
    ),
    "This operation may change external files, create commits or trigger external calls that require consent.": (
        "This operation may change external files, create commits or trigger external calls that require consent.", "Esta operação pode alterar arquivos externos, realizar commits ou disparar chamadas externas que exigem consentimento.", "此操作可能修改外部文件、创建提交，或触发需要你同意的外部调用。", "यह क्रिया बाहरी फ़ाइलें बदल सकती है, कमिट बना सकती है, या ऐसी बाहरी कॉल शुरू कर सकती है जिनके लिए सहमति आवश्यक है।", "Esta operación puede modificar archivos externos, crear commits o lanzar llamadas externas que requieren consentimiento.", "Cette opération peut modifier des fichiers externes, créer des commits ou déclencher des appels externes nécessitant votre accord.", "قد يغيّر هذا الإجراء ملفات خارجية أو ينشئ التزامات أو يطلق استدعاءات خارجية تتطلب الموافقة.",
    ),
    "Try the call again": (
        "Try the call again", "Tentar chamada novamente", "重新尝试通话", "कॉल फिर से आज़माएँ", "Intentar la llamada de nuevo", "Réessayer l'appel", "أعد محاولة المكالمة",
    ),
    "Unavailable": (
        "Unavailable", "Indisponível", "不可用", "उपलब्ध नहीं", "No disponible", "Indisponible", "غير متاح",
    ),
    "VISION · MULTIMODAL": (
        "VISION · MULTIMODAL", "VISÃO · MULTIMODAL", "视觉 · 多模态", "विज़न · मल्टीमोडल", "VISIÓN · MULTIMODAL", "VISION · MULTIMODAL", "الرؤية · متعدد الوسائط",
    ),
    "View progress": (
        "View progress", "Ver progresso", "查看进度", "प्रगति देखें", "Ver progreso", "Voir la progression", "عرض التقدم",
    ),
    "Wait for the conversation answer.": (
        "Wait for the conversation answer.", "Aguarde a resposta da conversa.", "请等待对话回答。", "वार्तालाप के उत्तर की प्रतीक्षा करें।", "Espera la respuesta de la conversación.", "Attendez la réponse de la conversation.", "انتظر إجابة المحادثة.",
    ),
    "Waiting for Tool": (
        "Waiting for Tool", "Aguardando Ferramenta", "等待工具", "टूल की प्रतीक्षा", "Esperando herramienta", "En attente de l'outil", "في انتظار الأداة",
    ),
    "What do you want to be able to do?": (
        "What do you want to be able to do?", "O que você quer conseguir fazer?", "你希望做到什么？", "आप क्या कर पाना चाहते हैं?", "¿Qué quieres poder hacer?", "Que voulez-vous pouvoir faire ?", "ماذا تريد أن تكون قادرًا على فعله؟",
    ),
    "Workflow": (
        "Workflow", "Fluxo de trabalho", "工作流程", "कार्यप्रवाह", "Flujo de trabajo", "Flux de travail", "سير العمل",
    ),
    "Write to MARK or drop a file here...": (
        "Write to MARK or drop a file here...", "Escreva para o MARK ou arraste um arquivo aqui...", "给 MARK 写信，或将文件拖到这里...", "MARK को लिखें या यहाँ फ़ाइल छोड़ें...", "Escribe a MARK o arrastra un archivo aquí...", "Écrivez à MARK ou déposez un fichier ici...", "اكتب إلى MARK أو أفلت ملفًا هنا...",
    ),
    "You can interrupt to speak again.": (
        "You can interrupt to speak again.", "Você pode interromper para voltar a falar.", "你可以打断后继续说话。", "आप बीच में रोककर फिर बोल सकते हैं।", "Puedes interrumpir para volver a hablar.", "Vous pouvez interrompre pour reprendre la parole.", "يمكنك المقاطعة لتعود إلى الكلام.",
    ),
    "Your progress is saved only when you prepare a plan.": (
        "Your progress is saved only when you prepare a plan.", "Seu progresso só é guardado quando você prepara um plano.", "只有在你准备计划时才会保存进度。", "आपकी प्रगति केवल तब सहेजी जाती है जब आप योजना तैयार करते हैं।", "Tu progreso solo se guarda cuando preparas un plan.", "Votre progression n'est enregistrée que lorsque vous préparez un plan.", "لا يُحفظ تقدمك إلا عندما تحضّر خطة.",
    ),
    "← Back to Chat": (
        "← Back to Chat", "← Voltar para Conversa", "← 返回聊天", "← चैट पर वापस जाएँ", "← Volver al chat", "← Retour au chat", "← العودة إلى الدردشة",
    ),
    "⌘K Commands": (
        "⌘K Commands", "⌘K Comandos", "⌘K 命令", "⌘K कमांड", "⌘K Comandos", "⌘K Commandes", "⌘K أوامر",
    ),
}
TRANSLATIONS.update(_SCREEN_TRANSLATIONS)
