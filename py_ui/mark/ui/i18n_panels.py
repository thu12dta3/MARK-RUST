"""Translation table for the side panels: Sentinel, voice, HF split view and Professor.

Row order matches ``i18n.LANGS``: en, pt-BR, zh, hi, es, fr, ar.
Keys are the exact English source literals used by ``tr()``.
"""

TRANSLATIONS: dict[str, tuple[str, str, str, str, str, str, str]] = {
    "(no README)": (
        "(no README)", "(sem README)", "（无 README）", "(कोई README नहीं)",
        "(sin README)", "(aucun README)", "(لا README)",
    ),
    "Antivirus & Threats · Sentinel": (
        "Antivirus & Threats · Sentinel", "Antivírus e ameaças · Sentinel",
        "杀毒与威胁 · Sentinel", "एंटीवायरस और खतरे · Sentinel",
        "Antivirus y amenazas · Sentinel", "Antivirus et menaces · Sentinel",
        "مكافحة الفيروسات والتهديدات · Sentinel",
    ),
    "Applied: {label}": (
        "Applied: {label}", "Aplicado: {label}", "已应用：{label}",
        "लागू किया गया: {label}", "Aplicado: {label}", "Appliqué : {label}",
        "تم التطبيق: {label}",
    ),
    "Authorize File Deletion": (
        "Authorize File Deletion", "Autorizar exclusão do arquivo",
        "授权删除文件", "फ़ाइल हटाने की अनुमति दें", "Autorizar la eliminación del archivo",
        "Autoriser la suppression du fichier", "السماح بحذف الملف",
    ),
    "ClamAV · read-only mode": (
        "ClamAV · read-only mode", "ClamAV · modo somente leitura",
        "ClamAV · 只读模式", "ClamAV · केवल पढ़ने का मोड", "ClamAV · modo de solo lectura",
        "ClamAV · mode lecture seule", "ClamAV · وضع القراءة فقط",
    ),
    "Connecting...": (
        "Connecting...", "Conectando...", "正在连接...", "कनेक्ट हो रहा है...",
        "Conectando...", "Connexion...", "جارٍ الاتصال...",
    ),
    "Delete this file permanently?\n\n{path}\n\nThis action is written to the audit log.": (
        "Delete this file permanently?\n\n{path}\n\nThis action is written to the audit log.",
        "Excluir este arquivo permanentemente?\\n\\n{path}\\n\\nEsta ação é gravada no log de auditoria.",
        "要永久删除此文件吗？\\n\\n{path}\\n\\n此操作会写入审计日志。",
        "क्या यह फ़ाइल स्थायी रूप से हटाएँ?\\n\\n{path}\\n\\nयह क्रिया ऑडिट लॉग में दर्ज होती है।",
        "¿Eliminar este archivo de forma permanente?\\n\\n{path}\\n\\nEsta acción queda registrada en el registro de auditoría.",
        "Supprimer définitivement ce fichier ?\\n\\n{path}\\n\\nCette action est inscrite dans le journal d'audit.",
        "هل تريد حذف هذا الملف نهائيًا؟\\n\\n{path}\\n\\nيُسجَّل هذا الإجراء في سجل التدقيق.",
    ),
    "Deletion refused: {detail}": (
        "Deletion refused: {detail}", "Exclusão recusada: {detail}", "删除被拒绝：{detail}",
        "हटाना अस्वीकार हुआ: {detail}", "Eliminación rechazada: {detail}",
        "Suppression refusée : {detail}", "رُفض الحذف: {detail}",
    ),
    "Deletion requires your explicit authorisation": (
        "Deletion requires your explicit authorisation",
        "A exclusão exige a sua autorização explícita",
        "删除需要您的明确授权", "हटाने के लिए आपकी स्पष्ट अनुमति आवश्यक है",
        "La eliminación requiere su autorización explícita",
        "La suppression exige votre autorisation explicite",
        "يتطلب الحذف إذنك الصريح",
    ),
    "Details failed: {detail}": (
        "Details failed: {detail}", "Falha nos detalhes: {detail}", "获取详情失败：{detail}",
        "विवरण विफल: {detail}", "Fallo en los detalles: {detail}",
        "Échec des détails : {detail}", "فشل جلب التفاصيل: {detail}",
    ),
    "Download": (
        "Download", "Baixar", "下载", "डाउनलोड", "Descargar", "Télécharger", "تنزيل",
    ),
    "End call": (
        "End call", "Encerrar chamada", "结束通话", "कॉल समाप्त करें", "Finalizar llamada",
        "Terminer l'appel", "إنهاء المكالمة",
    ),
    "File": (
        "File", "Arquivo", "文件", "फ़ाइल", "Archivo", "Fichier", "ملف",
    ),
    "File deleted after your authorisation · audit: {path}": (
        "File deleted after your authorisation · audit: {path}",
        "Arquivo excluído após a sua autorização · auditoria: {path}",
        "已按您的授权删除文件 · 审计：{path}",
        "आपकी अनुमति के बाद फ़ाइल हटाई गई · ऑडिट: {path}",
        "Archivo eliminado tras su autorización · auditoría: {path}",
        "Fichier supprimé après votre autorisation · audit : {path}",
        "حُذف الملف بعد إذنك · التدقيق: {path}",
    ),
    "Ignore / Keep": (
        "Ignore / Keep", "Ignorar / Manter", "忽略或保留", "अनदेखा करें या रखें",
        "Ignorar o conservar", "Ignorer ou conserver", "تجاهل أو احتفظ",
    ),
    "Live": (
        "Live", "Ao vivo", "实时", "लाइव", "En vivo", "En direct", "مباشر",
    ),
    "Loading files...": (
        "Loading files...", "Carregando arquivos...", "正在加载文件...",
        "फ़ाइलें लोड हो रही हैं...", "Cargando archivos...", "Chargement des fichiers...",
        "جارٍ تحميل الملفات...",
    ),
    "Loading the Hugging Face Hub...": (
        "Loading the Hugging Face Hub...", "Carregando o Hugging Face Hub...",
        "正在加载 Hugging Face Hub...", "Hugging Face Hub लोड हो रहा है...",
        "Cargando el Hugging Face Hub...", "Chargement du Hugging Face Hub...",
        "جارٍ تحميل Hugging Face Hub...",
    ),
    "Microphone": (
        "Microphone", "Microfone", "麦克风", "माइक्रोफ़ोन", "Micrófono",
        "Microphone", "الميكروفون",
    ),
    "Model Details & Download Options": (
        "Model Details & Download Options", "Detalhes do modelo e opções de download",
        "模型详情与下载选项", "मॉडल विवरण और डाउनलोड विकल्प",
        "Detalles del modelo y opciones de descarga",
        "Détails du modèle et options de téléchargement",
        "تفاصيل النموذج وخيارات التنزيل",
    ),
    "Mute": (
        "Mute", "Silenciar", "静音", "म्यूट करें", "Silenciar", "Couper le son", "كتم",
    ),
    "No TTS engine installed (piper, espeak-ng or spd-say).": (
        "No TTS engine installed (piper, espeak-ng or spd-say).",
        "Nenhum motor de voz instalado (piper, espeak-ng ou spd-say).",
        "未安装语音合成引擎（piper、espeak-ng 或 spd-say）。",
        "कोई वाक् संश्लेषण इंजन स्थापित नहीं है (piper, espeak-ng या spd-say)।",
        "No hay ningún motor de voz instalado (piper, espeak-ng o spd-say).",
        "Aucun moteur de synthèse vocale installé (piper, espeak-ng ou spd-say).",
        "لا يوجد محرك تحويل نص إلى كلام مثبت (piper أو espeak-ng أو spd-say).",
    ),
    "Nothing scanned yet. clamscan runs without --remove.": (
        "Nothing scanned yet. clamscan runs without --remove.",
        "Nada foi examinado ainda. O clamscan roda sem --remove.",
        "尚未扫描任何内容。clamscan 运行时不含 --remove。",
        "अभी कुछ भी स्कैन नहीं हुआ। clamscan बिना --remove के चलता है।",
        "Todavía no se analizó nada. clamscan se ejecuta sin --remove.",
        "Rien n'a encore été analysé. clamscan s'exécute sans --remove.",
        "لم يُفحص أي شيء بعد. يعمل clamscan بدون --remove.",
    ),
    "Nothing to speak yet.": (
        "Nothing to speak yet.", "Nada para falar ainda.", "还没有可朗读的内容。",
        "अभी बोलने के लिए कुछ नहीं है।", "Todavía no hay nada que leer en voz alta.",
        "Rien à énoncer pour le moment.", "لا يوجد ما يُنطق بعد.",
    ),
    "Pick a subject and an action": (
        "Pick a subject and an action", "Escolha uma matéria e uma ação",
        "选择学科和操作", "विषय और क्रिया चुनें", "Elige una materia y una acción",
        "Choisissez une matière et une action", "اختر مادة وإجراءً",
    ),
    "Querying the Hugging Face Hub...": (
        "Querying the Hugging Face Hub...", "Consultando o Hugging Face Hub...",
        "正在查询 Hugging Face Hub...", "Hugging Face Hub से पूछताछ हो रही है...",
        "Consultando el Hugging Face Hub...", "Interrogation du Hugging Face Hub...",
        "جارٍ الاستعلام من Hugging Face Hub...",
    ),
    "Scan (read-only)": (
        "Scan (read-only)", "Examinar (somente leitura)", "扫描（只读）",
        "स्कैन करें (केवल पढ़ें)", "Analizar (solo lectura)", "Analyser (lecture seule)",
        "افحص (قراءة فقط)",
    ),
    "Scan failed: {detail}": (
        "Scan failed: {detail}", "Falha no exame: {detail}", "扫描失败：{detail}",
        "स्कैन विफल: {detail}", "Falló el análisis: {detail}", "Échec de l'analyse : {detail}",
        "فشل الفحص: {detail}",
    ),
    "Scanning {path} with clamscan (no removal)...": (
        "Scanning {path} with clamscan (no removal)...",
        "Examinando {path} com clamscan (sem remoção)...",
        "正在用 clamscan 扫描 {path}（不删除）...",
        "clamscan से {path} स्कैन हो रहा है (कुछ हटाया नहीं जाएगा)...",
        "Analizando {path} con clamscan (sin eliminar)...",
        "Analyse de {path} avec clamscan (sans suppression)...",
        "جارٍ فحص {path} باستخدام clamscan (دون حذف)...",
    ),
    "Search models on Hugging Face...": (
        "Search models on Hugging Face...", "Buscar modelos no Hugging Face...",
        "在 Hugging Face 上搜索模型...", "Hugging Face पर मॉडल खोजें...",
        "Buscar modelos en Hugging Face...", "Rechercher des modèles sur Hugging Face...",
        "ابحث عن نماذج على Hugging Face...",
    ),
    "Select a folder to scan": (
        "Select a folder to scan", "Selecione uma pasta para examinar",
        "选择要扫描的文件夹", "स्कैन के लिए फ़ोल्डर चुनें", "Seleccione una carpeta para analizar",
        "Sélectionnez un dossier à analyser", "اختر مجلدًا لفحصه",
    ),
    "Size": (
        "Size", "Tamanho", "大小", "आकार", "Tamaño", "Taille", "الحجم",
    ),
    "Speak last reply": (
        "Speak last reply", "Falar a última resposta", "朗读上一条回复",
        "पिछला उत्तर बोलकर सुनाएँ", "Leer la última respuesta",
        "Énoncer la dernière réponse", "انطق الرد الأخير",
    ),
    "TTS failed: {detail}": (
        "TTS failed: {detail}", "Falha na síntese de voz: {detail}",
        "语音合成失败：{detail}", "वाक् संश्लेषण विफल: {detail}",
        "Falló la síntesis de voz: {detail}", "Échec de la synthèse vocale : {detail}",
        "فشل تحويل النص إلى كلام: {detail}",
    ),
    "This repository has no .gguf or .safetensors files.": (
        "This repository has no .gguf or .safetensors files.",
        "Este repositório não tem arquivos .gguf nem .safetensors.",
        "此仓库没有 .gguf 或 .safetensors 文件。",
        "इस रिपॉज़िटरी में .gguf या .safetensors फ़ाइलें नहीं हैं।",
        "Este repositorio no tiene archivos .gguf ni .safetensors.",
        "Ce dépôt ne contient aucun fichier .gguf ni .safetensors.",
        "لا يحتوي هذا المستودع على ملفات .gguf أو .safetensors.",
    ),
    "Threat": (
        "Threat", "Ameaça", "威胁", "खतरा", "Amenaza", "Menace", "تهديد",
    ),
    "Threat kept. MARK never deletes without your authorisation.": (
        "Threat kept. MARK never deletes without your authorisation.",
        "A ameaça foi mantida. O MARK nunca exclui sem a sua autorização.",
        "威胁已保留。MARK 绝不会未经您授权就删除。",
        "खतरा रखा गया। MARK आपकी अनुमति के बिना कभी नहीं हटाता।",
        "La amenaza se conservó. MARK nunca elimina sin su autorización.",
        "La menace est conservée. MARK ne supprime jamais sans votre autorisation.",
        "أُبقيت التهديدات. لا يحذف MARK أبدًا دون إذنك.",
    ),
    "Unmute": (
        "Unmute", "Reativar som", "取消静音", "अनम्यूट करें", "Activar sonido",
        "Rétablir le son", "إلغاء الكتم",
    ),
    "Voice Call": (
        "Voice Call", "Chamada de voz", "语音通话", "वॉइस कॉल", "Llamada de voz",
        "Appel vocal", "مكالمة صوتية",
    ),
    "failed": (
        "failed", "falhou", "失败", "विफल", "falló", "échec", "فشل",
    ),
    "no engine installed": (
        "no engine installed", "nenhum motor instalado", "未安装引擎",
        "कोई इंजन स्थापित नहीं", "ningún motor instalado", "aucun moteur installé",
        "لا محرك مثبت",
    ),
    "saved": (
        "saved", "salvo", "已保存", "सहेजा गया", "guardado", "enregistré", "تم الحفظ",
    ),
    "system default": (
        "system default", "padrão do sistema", "系统默认", "सिस्टम डिफ़ॉल्ट",
        "predeterminado del sistema", "valeur par défaut du système", "افتراضي النظام",
    ),
    "{count} repositories from the whole Hub": (
        "{count} repositories from the whole Hub", "{count} repositórios do Hub inteiro",
        "来自整个 Hub 的 {count} 个仓库", "पूरे Hub से {count} रिपॉज़िटरी",
        "{count} repositorios de todo el Hub", "{count} dépôts de tout le Hub",
        "{count} مستودعًا من كامل Hub",
    ),
    "{engine} scanned {count} files · {threats} threat(s) · read-only, nothing removed": (
        "{engine} scanned {count} files · {threats} threat(s) · read-only, nothing removed",
        "{engine} examinou {count} arquivos · {threats} ameaça(s) · somente leitura, nada foi removido",
        "{engine} 扫描了 {count} 个文件 · {threats} 个威胁 · 只读，未删除任何内容",
        "{engine} ने {count} फ़ाइलें स्कैन कीं · {threats} खतरा · केवल पढ़ें, कुछ नहीं हटाया",
        "{engine} analizó {count} archivos · {threats} amenaza(s) · solo lectura, nada se eliminó",
        "{engine} a analysé {count} fichiers · {threats} menace(s) · lecture seule, rien n'a été supprimé",
        "فحص {engine} عدد {count} ملفًا · {threats} تهديد · قراءة فقط، لم يُحذف شيء",
    ),
    "MARK plugins": (
        "MARK plugins", "Plugins do MARK", "MARK 插件", "MARK प्लगइन",
        "Plugins de MARK", "Plugins de MARK", "إضافات MARK",
    ),
    "Choose the integrations MARK may use. Each card lists the permissions it receives.": (
        "Choose the integrations MARK may use. Each card lists the permissions it receives.",
        "Escolha as integrações que o MARK pode usar. Cada cartão lista as permissões recebidas.",
        "选择 MARK 可使用的集成。每张卡片列出它获得的权限。",
        "चुनें कि MARK कौन से एकीकरण उपयोग कर सकता है। प्रत्येक कार्ड उसकी अनुमतियाँ दिखाता है।",
        "Elige las integraciones que MARK puede usar. Cada tarjeta lista los permisos que recibe.",
        "Choisissez les integrations que MARK peut utiliser. Chaque carte liste les permissions accordees.",
        "اختر التكاملات التي يستطيع MARK استخدامها. تعرض كل بطاقة الأذونات الممنوحة.",
    ),
    "Enabled": (
        "Enabled", "Ativo", "已启用", "सक्षम", "Activado", "Active", "مفعّل",
    ),
    "Enable plugin {name}": (
        "Enable plugin {name}", "Ativar plugin {name}", "启用插件 {name}",
        "प्लगइन {name} सक्षम करें", "Activar plugin {name}", "Activer le plugin {name}",
        "تفعيل الإضافة {name}",
    ),
    "Permissions: {list}": (
        "Permissions: {list}", "Permissoes: {list}", "权限：{list}",
        "अनुमतियाँ: {list}", "Permisos: {list}", "Permissions : {list}", "الأذونات: {list}",
    ),
    "External MCP servers ({count})": (
        "External MCP servers ({count})", "Servidores MCP externos ({count})",
        "外部 MCP 服务器（{count}）", "बाहरी MCP सर्वर ({count})",
        "Servidores MCP externos ({count})", "Serveurs MCP externes ({count})",
        "خوادم MCP الخارجية ({count})",
    ),
    "No MCP server configured. Add one under mcp_servers in the MARK config.": (
        "No MCP server configured. Add one under mcp_servers in the MARK config.",
        "Nenhum servidor MCP configurado. Adicione um em mcp_servers no config do MARK.",
        "未配置 MCP 服务器。请在 MARK 配置的 mcp_servers 下添加。",
        "कोई MCP सर्वर कॉन्फ़िगर नहीं है। MARK कॉन्फ़िग के mcp_servers में जोड़ें।",
        "No hay ningun servidor MCP configurado. Anade uno en mcp_servers del config de MARK.",
        "Aucun serveur MCP configure. Ajoutez-en un sous mcp_servers dans la config de MARK.",
        "لا يوجد خادم MCP مهيأ. أضف واحدًا تحت mcp_servers في إعداد MARK.",
    ),
    "Enable MCP server {name}": (
        "Enable MCP server {name}", "Ativar servidor MCP {name}", "启用 MCP 服务器 {name}",
        "MCP सर्वर {name} सक्षम करें", "Activar servidor MCP {name}",
        "Activer le serveur MCP {name}", "تفعيل خادم MCP {name}",
    ),
    "Enabled plugins and MCP servers are exposed to the Engineer sandbox tool registry.": (
        "Enabled plugins and MCP servers are exposed to the Engineer sandbox tool registry.",
        "Plugins e servidores MCP ativos sao expostos ao registro de ferramentas do sandbox do Engineer.",
        "已启用的插件和 MCP 服务器会注册到工程师沙箱的工具列表。",
        "सक्षम प्लगइन और MCP सर्वर इंजीनियर सैंडबॉक्स के टूल रजिस्ट्री में उपलब्ध होते हैं।",
        "Los plugins y servidores MCP activados se exponen al registro de herramientas del sandbox del Ingeniero.",
        "Les plugins et serveurs MCP actives sont exposes au registre d'outils du bac a sable Ingenieur.",
        "تُتاح الإضافات وخوادم MCP المفعّلة لسجل أدوات بيئة عزل المهندس.",
    ),
    "Done": (
        "Done", "Concluido", "完成", "पूर्ण", "Hecho", "Termine", "تم",
    ),
    "Thinking...": (
        "Thinking...", "Pensando...", "正在思考...", "सोच रहा है...",
        "Pensando...", "Reflexion...", "يفكر...",
    ),
    "Plugins": (
        "Plugins", "Plugins", "插件", "प्लगइन", "Plugins", "Plugins", "الإضافات",
    ),
    "Models discovered: {count}": (
        "Models discovered: {count}", "Modelos descobertos: {count}",
        "已发现模型：{count}", "खोजे गए मॉडल: {count}", "Modelos descubiertos: {count}",
        "Modeles decouverts : {count}", "النماذج المكتشفة: {count}",
    ),
    "Sync Models": (
        "Sync Models", "Sincronizar modelos", "同步模型", "मॉडल सिंक करें",
        "Sincronizar modelos", "Synchroniser les modeles", "مزامنة النماذج",
    ),
    "{files} files · {size} · VRAM budget {vram} GiB": (
        "{files} files · {size} · VRAM budget {vram} GiB",
        "{files} arquivos · {size} · orçamento de VRAM {vram} GiB",
        "{files} 个文件 · {size} · VRAM 预算 {vram} GiB",
        "{files} फ़ाइलें · {size} · VRAM बजट {vram} GiB",
        "{files} archivos · {size} · presupuesto de VRAM {vram} GiB",
        "{files} fichiers · {size} · budget VRAM {vram} GiB",
        "{files} ملفًا · {size} · ميزانية VRAM {vram} GiB",
    ),
}
