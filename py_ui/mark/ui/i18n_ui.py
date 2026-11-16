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
