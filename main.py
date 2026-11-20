#!/usr/bin/env python3
"""Saçmalık Odası — 3 CLI ajan + sen, tek bir sohbet odasında.

Hiçbir ön prompt / rol / sistem talimatı yok. Her ajan yalnızca nerede
olduğunu, odada kimlerin bulunduğunu ve konuşulanları görür.

Söz alma: yeni bir mesaj geldiğinde ajanlar AYNI ANDA çağrılır; kimse
sıradan dolayı öne geçmez. Bir ajan işini bitirdiğinde, o sırada başkaları
yeni bir şey yazdıysa (ve izin varsa) onları da görüp devam eder.

Bağlam: her ajanın kendi CLI oturumu sürdürülür (claude --resume,
codex exec resume, agy --conversation); her çağrıda yalnızca kaçırdığı
yeni mesajlar gider. Ajanların o an ne yaptığı (dosya, komut) canlı izlenir.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
from pathlib import Path

from PySide6.QtCore import (QObject, QProcess, QProcessEnvironment, Property, Signal, Slot,
                            QTimer, QUrl)
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QTextDocument
from PySide6.QtQml import QQmlApplicationEngine

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "sacmalik"
CONFIG_FILE = CONFIG_DIR / "settings.json"
# Kullanıcı verisi program klasöründe değil: paketle kurulunca program /usr/lib altında, salt okunur durur.
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "sacmalik"
CHATS_DIR = DATA_DIR / "sohbetler"
MEDIA_DIR = DATA_DIR / "medya"          # mesaj içine yazılan SVG'lerin gösterim kopyası
ATTACH_DIR = DATA_DIR / "ekler"         # kullanıcının gönderdiği dosyaların kopyası (sohbet başına)
LOGS_DIR = DATA_DIR / "loglar"          # inceleme için olay kaydı (sohbet başına .jsonl)


def migrate_data():
    """Eski sürüm sohbetleri, kayıtları ve medyayı program klasörüne yazıyordu: bir kez DATA_DIR'e taşı."""
    for name in ("sohbetler", "loglar", "medya"):
        old, new = APP_DIR / name, DATA_DIR / name
        if old.is_dir() and not new.exists():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(new))
            except OSError:
                pass
SYSTEM_COLOR = "#6b7280"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
CODEX_SID_RE = re.compile(r"session id:\s*([0-9a-fA-F-]{36})")
USER_COLOR = "#8b5cf6"
INF = 10 ** 9
# Oda anlaşması: rol ya da görev değil, ortak çalışmanın trafik kuralı. Odaya görünür düşer (ayarlardan kapatılır).
PACT_TALK = ("Bir kararı ortak diye aktarırken kimin hangi öneriyi desteklediğini belirtin; "
             "sessiz kalan biri onay vermiş sayılmaz.")
PACT_PROD = ("Üretimde bir işe başlamadan hangi parçayı üstlendiğinizi odada kısaca söyleyin. "
             "Başkasının yazdığını silmeden ya da üzerine yazmadan önce onun açık onayını alın.")
# 19.11.2026: Claude görseli ve kodu tek başına, odadaki görselleri kullanmadan yazdı; diğerleri yalnız bekledi
PACT_HELP = ("Başkasının alanına giren bir şeye (görsel, kod, ses, veri) ihtiyacınız olursa onu yapmak yerine "
             "işin sahibinden isteyin. İşe başlarken hangi girdiyi (taslak, görsel, sözleşme) kullanacağınızı söyleyin. "
             "Birkaç dakikadan uzun süren işte arada kısa bir durum yazın.")
PACT_VER = 2      # anlaşma büyüyünce süren sohbetlere yalnız yenisi bir kez yazılır
# kota dolunca CLI'ların yazdığı hata (Ekip'teki desen)
# Yeni bilgi taşımayan kısa onay/bekleme mesajı ("Tamam.", "👍", "Claude'u bekliyorum."): boşta duran
# ajanı uyandırmaz, çalışan ajana araya yazılmaz; ajanlar onu bir sonraki çağrılarında dökümde görür.
ACK_RE = re.compile(r"\bbekl[ei]|\btamam(dır)?\b|\banlaşıldı|\banladım|👍|\bsürüyor|\bhazırı[mz]\b|\bsessiz", re.I)
ACK_NOT = re.compile(r"`|\]\(|https?://|\w\.(js|py|html|css|md|png|svg)\b|üstlen|tamamlandı|bitti|hazır\b|kaydedildi", re.I)


# itiraz ya da uyarı: kısa da olsa hemen ulaşmalı ("Tamam, koordinatlar ters", "Bekle, bu yanlış")
ACK_OBJ = re.compile(r"\b(ama|fakat|ancak|lakin|yanlış|ters|hata|hatalı|sorun|değil|olmadı|olmuyor|çalışmıyor|"
                     r"bozuk|eksik|boş|dur|durun|bekle|bekleyin|dikkat|uyarı)\b", re.I)
# "Tamam, ..." ile başlayıp ardından söz söyleyen mesaj onay değildir
ACK_HEAD = re.compile(r"^\W*(tamam(dır)?|anlaşıldı|anladım|👍)[\s,.:;!—–-]+(.*)$", re.I | re.S)


def is_ack(text):
    t = (text or "").strip()
    if len(t) > 160 or "?" in t or ACK_NOT.search(t) or ACK_OBJ.search(t):
        return False      # soru, itiraz, dosya, bağlantı, üstlenme ya da bitti haberi taşıyan mesaj bilgi sayılır
    m = ACK_HEAD.match(t)
    if m and len(m.group(3).split()) >= 3:
        return False
    return bool(ACK_RE.search(t))


LIMIT_ERROR = re.compile(r"rate.?limit|usage limit|quota|limit reached|hit your limit|resource.?exhausted|\b429\b|kota", re.I)
CLASH_SECS = 600    # aynı dosyaya bu süre içinde ikinci bir ajan yazarsa odaya uyarı düşer
HEADER_VER = 8      # oda bilgisi değişince sürmekte olan oturumlara da bir kez gönderilir
# Karar aç (20.11.2026, deniz navigasyonu deneyi): önemli bir kararda herkes ilk görüşünü ötekilerin cevabını
# görmeden yazar; cevaplar hepsi bitince birlikte açılır, sonra sohbet serbestçe sürer. Oy ya da atanmış itirazcı yok.
DECISION_ASK = ("Herkes önce kendi cevabını yazıyor: siz yazarken ötekilerin cevabı size gösterilmiyor, "
                "cevaplar hepsi bitince birlikte açılacak. İki şeyi yazın: 1) Önce hangi yolu denerdin, neden? "
                "2) Hangi bulgu ya da ölçüm fikrini değiştirirdi? Söyleyecek bir şeyin yoksa pas geçebilirsin.")
# Ajanın @ ile başlayan mesajı yalnız andığı ajana gider (20.11.2026, Erkan'ın isteği): diğerlerine iletilmez,
# onları uyandırmaz, dökümlerinde görünmez. Ortadaki @ ise yalnız iş devridir: anılan uyanır, mesaj herkese gider.
DIRECT_HINT = ("Yalnızca bir ajana yazmak istersen mesajını @adıyla başlat (ör. \"@{who} …\"): o mesaj yalnızca ona "
               "gider, diğerleri görmez ve uyanmaz; herkesin bilmesi gerekeni odaya yaz. Mesajın içinde bir ajanı @ ile "
               "anarsan o ajan hemen söz alır.")
# Ajanın mesajının başında oda bilgisinin kopyası ("**Konum:** … **Odadakiler:** …"): Gemini bunu rapor
# kalıbı sanıp her mesajına koyuyordu. Bu satırlar odaya düşmeden silinir.
ECHO_LINE = re.compile(r"^\s*(?:[-*>]\s*)?(?:\*\*|__)?(Konum|Odadakiler|Mod|Ekran|Çalışma klasörü)\s*:?\s*(?:\*\*|__)?\s*:?.*$", re.I)
# Roller (19.11.2026): ön tanımlı olarak kapalı; açılınca yetki değil sorumluluk alanıdır, ortak karar kuralı sürer.
ROLE_TEMPLATES = [
    {"id": "oyun", "name": "Oyun", "roles": [
        {"title": "Görsel ve sahne", "talk": "Önce görsel açıdan değerlendirir: sahne, ışık, kamera, taş ve arka plan kalitesi.",
         "prod": "Sahneyi, görselleri ve animasyon parçalarını üretir."},
        {"title": "Kurallar ve motor", "talk": "Oyun kurallarını, çözülebilirliği ve teknik riskleri tartar.",
         "prod": "Oyun motorunu, kuralları ve testlerini yazar."},
        {"title": "Eleştirmen", "talk": "Önerilerin zayıf yanlarını arar, oyuncu gözüyle sorar.",
         "prod": "Yapılanı dener, hataları ve tutarsızlıkları bildirir; kendi düzeltmesini sahibine önerir."}]},
    {"id": "resim", "name": "Resim", "roles": [
        {"title": "Sanat yönetmeni", "talk": "Konsepti, renk paletini, kompozisyonu ve üslubu belirlemeyi önerir.",
         "prod": "Kısa bir görsel yönerge yazar, üretilenleri bu yönergeye göre değerlendirir."},
        {"title": "Üretici", "talk": "Önerilen üslubun nasıl üretileceğini ve araçlarını tartar.",
         "prod": "Resimleri üretir ve dosya olarak kaydeder."},
        {"title": "Kalite denetçisi", "talk": "Tutarlılık, ışık, anatomi ve ayrıntı hatalarını arar.",
         "prod": "Her resmi kontrol eder, düzeltilecekleri tek tek yazar."}]},
    {"id": "animasyon", "name": "Animasyon", "roles": [
        {"title": "Hikâye ve storyboard", "talk": "Akışı, sahneleri ve zamanlamayı önerir.",
         "prod": "Storyboard ve sahne listesini hazırlar."},
        {"title": "Hareket ve zamanlama", "talk": "Hareketin, geçişlerin ve ritmin nasıl olacağını tartar.",
         "prod": "Animasyonları ve geçişleri üretir."},
        {"title": "Render ve son kontrol", "talk": "Çıktı biçimini, kaliteyi ve süreyi değerlendirir.",
         "prod": "Render alır, sonucu izler ve hataları bildirir."}]},
    {"id": "web", "name": "Web sitesi", "roles": [
        {"title": "Tasarım", "talk": "Sayfa yapısını, görünümü ve kullanıcı akışını önerir.",
         "prod": "Arayüzü ve stilleri yazar."},
        {"title": "Sunucu tarafı", "talk": "Veri, API ve güvenlik konularını tartar.",
         "prod": "Sunucu tarafını ve veri katmanını yazar."},
        {"title": "Test", "talk": "Kırılabilecek yerleri ve eksik durumları arar.",
         "prod": "Testleri yazar ve çalıştırır, sonuçları bildirir."}]},
    {"id": "arastirma", "name": "Araştırma", "roles": [
        {"title": "Savunan", "talk": "Önerinin lehindeki en güçlü gerekçeleri ve kanıtları getirir.",
         "prod": "Lehteki kaynakları ve verileri toplar."},
        {"title": "Karşı çıkan", "talk": "Önerinin aleyhindeki en güçlü gerekçeleri ve kanıtları getirir.",
         "prod": "Aleyhteki kaynakları ve verileri toplar."},
        {"title": "Hakem", "talk": "İki tarafı tartar, neyin kanıtlandığını neyin açık kaldığını söyler.",
         "prod": "Bulguları kaynaklarıyla bir özet belgede toplar."}]},
]
# İş bölümü: rollerin basit hâli. Açıklama yazılmazsa bu anlamlar kullanılır (Tartışma, Üretim).
TASKS = [
    {"title": "Plan", "talk": "Planın taslağını hazırlar; diğerleri itiraz edebilir, karar yine açık destekle alınır.",
     "prod": "Plan belgesini yazar ve günceller."},
    {"title": "Kod", "talk": "Teknik yaklaşımı ve kodun yapısını önerir.",
     "prod": "Kodu yazar; başkasının kodunu değiştirecekse önce sahibine önerir."},
    {"title": "Görsel", "talk": "Görsel yönü, üslubu ve kaliteyi önerir.", "prod": "Görselleri üretir."},
    {"title": "Ses", "talk": "Ses, efekt ve müzik yönünü önerir.", "prod": "Sesleri ve müziği üretir."},
    {"title": "Test", "talk": "Kırılabilecek yerleri ve eksik durumları arar.",
     "prod": "Yapılanı dener, testleri yazar ve sonuçları bildirir."},
    {"title": "Belge", "talk": "Belgelerin içeriğini ve düzenini önerir.", "prod": "Belgeleri yazar."},
    {"title": "Araştırma", "talk": "Kaynakları ve verileri araştırıp getirir.", "prod": "Bulguları kaynaklarıyla derler."},
]
TASK_BY_TITLE = {x["title"].lower(): x for x in TASKS}
# üretilen dosyalar: panelde türüne göre ayrılır
IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif", "mp4", "webm", "mov", "mkv", "ogv"}
VIDEO_EXT = {"mp4", "webm", "mov", "mkv", "ogv"}
AUDIO_EXT = {"mp3", "wav", "ogg", "oga", "flac", "m4a", "opus", "aac"}
CODE_EXT = {"py", "js", "mjs", "ts", "tsx", "jsx", "dart", "qml", "c", "cc", "cpp", "h", "hpp", "rs", "go", "java",
            "kt", "swift", "sh", "bash", "zsh", "css", "scss", "html", "htm", "vue", "svelte", "lua", "rb", "php",
            "sql", "glsl", "frag", "vert", "cs", "gd"}
DOC_EXT = {"md", "txt", "pdf", "json", "yaml", "yml", "toml", "csv", "tsv", "docx", "odt", "xlsx", "ods", "rtf",
           "udf", "xml"}
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
# panelde gösterilmeyen yollar: proje şablonlarının ve derlemenin ürettikleri (uygulama simgeleri, derleme çıktısı)
NOISE_RE = re.compile(r"/(?:build|\.dart_tool|node_modules|\.gradle|Pods|DerivedData|__pycache__|\.venv|venv|dist|"
                      r"mipmap-[^/]+|drawable[^/]*|[^/]+\.xcassets|web/icons|\.git)/")
STUCK_SECS = 240
# API ajanı (19.11.2026): CLI'ı olmayan modeller (Groq, Gemini, OpenRouter, yerel…) api_ajan.py süreciyle katılır;
# hesaplar, model seçimi, kota ve araçlı döngü LifeOS'un modeller katmanından (lifeos_store.modeller).
API_SCRIPT = Path(__file__).resolve().parent / "api_ajan.py"
API_AGENT = {"key": "api", "name": "API", "color": "#a78bfa", "enabled": True, "command": "", "timeout": 0,
             "model": "auto", "effort": "", "modelArg": "", "effortArg": "", "allowRules": "", "kind": "api"}


def api_ready():
    """LifeOS'un modeller katmanı bu bilgisayarda var mı (API ajanı onunla çalışır)."""
    return API_SCRIPT.is_file() and any(os.path.isdir(os.path.join(p, "lifeos_store", "modeller"))
                                        for p in (os.environ.get("LIFEOS_LIB", ""), "/usr/lib/lifeos") if p)
# Klasör ve dosya seçme: sistemin dosya seçme hizmetine (xdg-desktop-portal) sorulur; LifeOS'ta bu pencereyi
# LifeOS Dosyalar açar. Qt'nin kendi penceresi hizmeti kullanmıyordu (19.11.2026). Ayrı süreçte: sinyali beklerken
# arayüz donmasın.
PORTAL_PICK = r"""
import sys, json, uuid
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
mode, title = sys.argv[1], sys.argv[2]
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
token = "sacmalik" + uuid.uuid4().hex[:8]
sender = bus.get_unique_name()[1:].replace(".", "_")
path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)
loop = GLib.MainLoop()
out = {"ok": False, "uris": []}
def resp(conn, snd, obj, iface, sig, params):
    code, res = params.unpack()
    out["ok"] = code == 0
    out["uris"] = list(res.get("uris", []))
    loop.quit()
bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request", "Response", path, None,
                     Gio.DBusSignalFlags.NONE, resp)
opts = {"handle_token": GLib.Variant("s", token), "modal": GLib.Variant("b", True)}
if mode == "folder":
    opts["directory"] = GLib.Variant("b", True)
if mode == "files":
    opts["multiple"] = GLib.Variant("b", True)
bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.FileChooser",
              "OpenFile", GLib.Variant("(ssa{sv})", ("", title, opts)), None, Gio.DBusCallFlags.NONE, -1, None)
loop.run()
print(json.dumps(out))
"""        # bir komut bu kadar sürerse panel "takılmış olabilir" der
# sohbette gösterilecek ajan çıktıları: resimler önizlenir, diğerleri tıklayınca açılır
MEDIA_EXT = ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif",
             "mp4", "webm", "mov", "mkv", "ogv", "mp3", "wav", "ogg", "html", "htm", "pdf")
LINK_RE = re.compile(r"\]\((?:file://)?([^)\n]+)\)")       # markdown bağlantısı: [ad](yol)
PATH_RE = re.compile(r"(?:file://)?((?:~|\.{1,2})?/?[\w\-./~%]+\.(?:" + "|".join(MEDIA_EXT) + r"))\b", re.I)
# Tartışma modunda Antigravity'nin çalıştırabileceği okuma komutları
READ_CMDS = ["ls", "cat", "head", "tail", "find", "grep", "rg", "wc", "tree", "pwd", "file", "stat",
             "git status", "git log", "git diff", "git show"]

# Süreç koruması (20.11.2026): bir ajan "pkill" ile kullanıcının açtığı uygulama penceresini de kapatmıştı.
# Ajanların PATH'inin başına konan pkill ve killall, yalnızca odadaki ajanların başlattığı süreçlere dokunur
# (ajanların süreçleri SACMALIK_ODA=1 ortam değişkenini taşır); başkasına ait bir eşleşme varsa hiçbirini kapatmaz.
GUARD_DIR = DATA_DIR / "koruma"
GUARD_SCRIPT = r"""#!/usr/bin/env python3
# Saçmalık Odası süreç koruması: yalnız odadaki ajanların başlattığı süreçler kapatılır.
import os, re, shutil, subprocess, sys
name = os.path.basename(sys.argv[0])
here = os.path.dirname(os.path.abspath(sys.argv[0]))
path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if p and os.path.abspath(p) != here)
real = shutil.which(name, path=path)
if not real:
    sys.stderr.write(name + ": komut bulunamadı\n"); sys.exit(127)
mark = ("SACMALIK_ODA=" + os.environ.get("SACMALIK_ODA", "")).encode()
args = sys.argv[1:]
def ours(pid):
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            return mark != b"SACMALIK_ODA=" and mark in f.read().split(b"\0")
    except OSError:
        return False
def pname(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return "?"
pids = []
if name == "pkill":
    q, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("--signal", "-q", "--queue"):
            i += 2; continue
        if a.startswith("--signal=") or re.fullmatch(r"-(\d+|SIG[A-Z0-9+-]+|[A-Z][A-Z0-9+-]+)", a) or a in ("-e", "--echo"):
            i += 1; continue
        q.append(a); i += 1
    pg = shutil.which("pgrep", path=path)
    if pg:
        out = subprocess.run([pg] + q, capture_output=True, text=True).stdout
        pids = [int(x) for x in out.split() if x.isdigit()]
elif name == "killall":
    names, regex, i = [], False, 0
    while i < len(args):
        a = args[i]
        if a in ("-s", "--signal", "-u", "--user", "-o", "--older-than", "-y", "--younger-than", "-n", "--ns",
                 "-Z", "--context"):
            i += 2; continue
        if a in ("-r", "--regexp"):
            regex = True
        elif not a.startswith("-"):
            names.append(a)
        i += 1
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        n = pname(int(d))
        try:
            exe = os.path.basename(os.readlink("/proc/%s/exe" % d))
        except OSError:
            exe = ""
        if any((re.search(x, n) or re.search(x, exe)) if regex else x in (n, exe, n[:15]) for x in names):
            pids.append(int(d))
me = {os.getpid()}
foreign = [p for p in pids if p not in me and not ours(p)]
if foreign:
    sys.stderr.write("Saçmalık Odası: bu süreçleri odadaki ajanlar başlatmadı, hiçbiri kapatılmadı: "
                     + ", ".join("%d (%s)" % (p, pname(p)) for p in foreign[:8])
                     + ". Kapanmaları gerekiyorsa kullanıcıya söyleyin; yalnız kendi başlattığınızı kapatmak için "
                       "eşleşmeyi daraltın (ör. tam yol ya da PID).\n")
    sys.exit(1)
os.execv(real, [real] + args)
"""

_MD_CACHE = {}
# Markdown içindeki kod, tablo ve bağlantı renkleri; QML'deki Theme ile aynı iki palet
MD_PALETTE = {
    True:  {"CODE": "#d6dae6", "CODEBG": "#0e1016", "INLINE": "#f5c97a", "INLINEBG": "#232836",
            "LINE": "#2a2f3d", "LINK": "#8fb3ff"},
    False: {"CODE": "#2d3142", "CODEBG": "#f4f5f9", "INLINE": "#a64f0b", "INLINEBG": "#f3ede4",
            "LINE": "#dfe2ec", "LINK": "#3b6fe0"},
}
_SIZE_DOWN = {"xx-large": "x-large", "x-large": "large", "large": "medium"}


def md_html(md, dark=True, scale=1.0):
    """Markdown'u temaya uygun HTML'e çevir: yumuşak çizgili tablolar, zeminli kod, okunur bağlantı rengi.
    Qt'nin Markdown'ı tabloları kalın beyaz çizgiyle, kodu zeminsiz çiziyor."""
    key = (md, dark, scale)
    if key in _MD_CACHE:
        return _MD_CACHE[key]
    if len(_MD_CACHE) > 400:
        # akan cevabın her ara hâli ayrı girdi oluyordu: önbellek sınırsız büyüyordu (20.11.2026 donması)
        for k in list(_MD_CACHE)[:200]:
            del _MD_CACHE[k]
    doc = QTextDocument()
    doc.setMarkdown(md)
    h = doc.toHtml()
    h = re.sub(r"<body[^>]*>", "<body>", h, count=1)
    # başlıklar sohbet balonunda bir boy küçük
    h = re.sub(r"font-size:(xx-large|x-large|large);", lambda m: f"font-size:{_SIZE_DOWN[m.group(1)]};", h)
    # Qt sabit genişlikli yazı tipini sistemdekiyle yazar ('monospace', 'JetBrainsMono Nerd Font'…): adı ne olursa olsun
    mono = r"font-family:'[^']*';"
    # kod blokları: ardışık <pre> satırları tek, zeminli bir kutuda
    def block(m):
        lines = re.findall(r"<pre[^>]*>(.*?)</pre>", m.group(0), re.S)
        inner = "".join('<p style="white-space:pre; margin-top:0px; margin-bottom:0px;">'
                        '<span style="font-family:\'JetBrains Mono\',monospace; font-size:12px; color:@CODE@;">'
                        f'{re.sub(mono, "", ln)}</span></p>' for ln in lines)
        return ('<table width="100%" cellpadding="10" cellspacing="0" style="margin-top:6px; margin-bottom:6px;">'
                f'<tr><td bgcolor="@CODEBG@" style="border:1px solid @LINE@;">{inner}</td></tr></table>')
    h = re.sub(r"(?:<pre[^>]*>.*?</pre>\s*)+", block, h, flags=re.S)
    # satır içi kod: yalnız yazı tipi taşıyan span
    code = ("<span style=\"font-family:'JetBrains Mono',monospace; font-size:12px; color:@INLINE@;"
            " background-color:@INLINEBG@;\">&#8202;")
    h = re.sub("<span style=\" " + mono + "\">(.*?)</span>", lambda m: code + m.group(1) + "&#8202;</span>", h, flags=re.S)
    # tablolar: ince, temaya uyan çizgiler; ilk satır başlık zemini
    def table(m):
        t = m.group(0).replace('<table border="1" style=" border-collapse:collapse;" cellpadding="4">',
                               '<table border="1" width="100%" cellspacing="0" cellpadding="7" style="border-collapse:collapse;'
                               ' border-color:@LINE@; border-style:solid; margin-top:6px; margin-bottom:6px;">')
        return t
    h = re.sub(r"<table border=\"1\".*?</table>", table, h, flags=re.S)
    h = h.replace("color:#0000ff;", "color:@LINK@;")
    if len(_MD_CACHE) > 400:
        _MD_CACHE.clear()
    for k, v in MD_PALETTE[bool(dark)].items():
        h = h.replace(f"@{k}@", v)
    h = h.replace("font-size:12px;", f"font-size:{round(12 * scale)}px;")
    _MD_CACHE[key] = h
    return h


def default_user():
    """Varsayılan ad: sistemdeki kullanıcının tam adının ilk kelimesi, yoksa giriş adı."""
    try:
        import pwd
        e = pwd.getpwuid(os.getuid())
        return (e.pw_gecos.split(",")[0].split() or [e.pw_name])[0]
    except Exception:
        return os.environ.get("USER") or "Sen"


DEFAULTS = {
    "userName": default_user(),
    "autoRounds": 1,
    "autoMode": False,      # açıkken ajanlar kimse yeni bir şey söylemeyene dek konuşur
    "parallel": True,       # yeni mesajda üç ajan aynı anda çağrılır; konuşulanlar çalışanlara canlı iletilir
    "production": False,     # False = tartışma: CLI'lar salt-okunur çalışır (dosya yazamaz, komut çalıştıramaz)
    "defaultRules": "",     # yeni sohbetlerin oda kuralları (her sohbet kendi kurallarını değiştirebilir)
    "maxChars": 60000, "maxCalls": 12, "cmdTimeout": 180, "pact": True, "liveRelay": True,
    "leanTools": True,      # ajanlar kişisel bağlayıcı/MCP sunucuları olmadan açılır (gizlilik, daha az araç tanımı)
   
    "theme": "dark",
    "panelOpen": True,      # sağdaki durum paneli açık mı (hatırlanır)
    "roleTemplates": [],
    "recentDirs": [],       # son kullanılan proje klasörleri (en yenisi önce)    # kullanıcının kaydettiği rol şablonları: [{id, name, roles: [{title, talk, prod}]}]
    "fontScale": 1.0,       # yazı boyutu çarpanı (0.8–1.6)        # "dark" ya da "light"; üst çubuktaki düğmeyle değişir, hatırlanır
    "keepSessions": True,
    "workDir": str(DATA_DIR / "oda"),
    "agents": [
        {"key": "agy", "name": "Antigravity", "color": "#4f8cff", "enabled": True,
         "command": "agy --mode accept-edits -p {prompt}", "timeout": 0,
         "model": "", "effort": "", "modelArg": "--model {model}", "effortArg": "--effort {effort}",
         "allowRules": ""},
        {"key": "claude", "name": "Claude", "color": "#d97757", "enabled": True,
         "command": "claude -p --permission-mode auto", "timeout": 0,
         "model": "", "effort": "", "modelArg": "--model {model}", "effortArg": "--effort {effort}",
         "allowRules": ""},
        {"key": "codex", "name": "Codex", "color": "#10a37f", "enabled": True,
         "command": "codex exec --skip-git-repo-check -s workspace-write -", "timeout": 0,
         "model": "", "effort": "", "modelArg": "-m {model}",
         "effortArg": "-c model_reasoning_effort={effort}", "allowRules": ""},
    ],
}


def load_settings():
    data = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(CONFIG_FILE.read_text())
        data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        for a in data["agents"]:
            # eksik alanlar aynı CLI'ın varsayılanından: eklenen ikinci Claude, Antigravity'ninkini almasın
            for k, v in base_agent(a).items():
                a.setdefault(k, v if k not in ("model", "effort", "allowRules") else "")
    except (OSError, ValueError):
        pass
    return data


def exe_of(agent):
    try:
        parts = shlex.split(agent.get("command") or "")
    except ValueError:
        return ""
    return os.path.basename(parts[0]) if parts else ""


def kind_of(agent):
    """Ajanın türü: claude, codex, agy (CLI) ya da api. Aynı türden birden çok CLI ajanı aynı hesabı (ve kotayı) kullanır."""
    if agent.get("kind") == "api" or (agent.get("key") or "").split("-")[0] == "api":
        return "api"
    exe = exe_of(agent)
    if exe in ("agy", "antigravity"):
        return "agy"
    if exe in ("claude", "codex"):
        return exe
    key = (agent.get("key") or "").split("-")[0]
    return key if key in ("agy", "claude", "codex") else exe


def base_agent(agent):
    kind = kind_of(agent)
    if kind == "api":
        return API_AGENT
    return next((d for d in DEFAULTS["agents"] if d["key"] == kind),
                next((d for d in DEFAULTS["agents"] if d["key"] == agent.get("key")), DEFAULTS["agents"][0]))


def file_kind(path):
    ext = path.lower().rsplit(".", 1)[-1] if "." in os.path.basename(path) else ""
    return ("image" if ext in IMG_EXT else "audio" if ext in AUDIO_EXT else "code" if ext in CODE_EXT
            else "doc" if ext in DOC_EXT else "")


def strip_echo(text, me, others):
    """Ajanın mesajından oda bilgisi kopyasını ve kendi adıyla açılışını sil; başka ajanın adıyla açıyorsa notu döndür.
    → (temiz metin, not)"""
    lines = (text or "").split("\n")
    head = lines[:10]
    hits = [i for i, ln in enumerate(head) if ECHO_LINE.match(ln)]
    if len(hits) >= 2:
        lines = [ln for i, ln in enumerate(lines) if i not in hits]
        while len(lines) > 1 and not lines[0].strip() and not lines[1].strip():
            lines.pop(0)
        # başlık ile gövde arasında kalan boş satırlar ve "---" çizgisi
        i = 0
        while i < len(lines) and (not lines[i].strip() or lines[i].strip("-—*_ ") == ""):
            i += 1
        if i and i < len(lines):
            lines = lines[i:]
    text = "\n".join(lines).strip()
    note = ""
    m = re.match(r"^\s*(?:\*\*|__)?([^\n*_:]{2,40}?)(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*", text)
    if m:
        who = m.group(1).strip()
        if who.lower() == (me or "").lower():
            text = text[m.end():].lstrip()
        elif any(who.lower() == o.lower() for o in others):
            note = f"Bu mesajı {me} yazdı; {who} adıyla başlıyor"
    return text, note


def new_chat(workdir, rules=""):
    return {"id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
            "title": "", "created": time.time(), "updated": time.time(),
            "workDir": workdir, "messages": [], "sessions": {}, "seen": {}, "files": {},
            "rules": rules or "", "rulesRev": 0}


def short(s, n=90):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


class Room(QObject):
    # id, key, name, color, text, pending, time
    messageAdded = Signal(str, str, str, str, str, bool, str)
    messageUpdated = Signal(str, str)                       # id, text
    messageActivity = Signal(str, str)                      # id, satır satır yaptıkları
    messageDone = Signal(str, bool, float)                  # id, ok, seconds
    messageSilent = Signal(str)                             # id: ajan konuşmamayı seçti
    messageMedia = Signal(str, str)                         # id, dosya yolları (satır satır)
    messagePinned = Signal(str, bool)                       # id, sabit mi: yeni oturumda dökümden düşmez
    quotaChanged = Signal()                                 # ajanların 5 saatlik ve haftalık kota doluluğu
    roomReset = Signal()
    busyChanged = Signal()
    settingsChanged = Signal()
    speakingChanged = Signal()
    chatsChanged = Signal()
    statusText = Signal(str)
    testResult = Signal(str, bool, str)                     # key, ok, output
    modelsReady = Signal(str, "QVariantList", "QVariantList")  # key, models, efforts
    statusChanged = Signal()                                # ajanların anlık durumu (panel)
    filesChanged = Signal()                                 # bu sohbette üretilen dosyalar (panel)
    rolesChanged = Signal()
    rulesChanged = Signal()                                 # bu odanın kuralları
    decisionChanged = Signal()                              # açık karar ve alınan kararlar
    messageSealed = Signal(str, bool)                       # id, saklı mı: karar turunda cevap hepsi bitince açılır
    messageTo = Signal(str, str)                            # id, kime: yalnız anılan ajana giden mesaj
    picked = Signal(str, "QVariantList")                    # tür (folder/files), seçilen yollar
    pickFailed = Signal(str)                                # hizmet yok: arayüz kendi penceresini açar

    def __init__(self):
        super().__init__()
        self._s = load_settings()
        self._chat = new_chat(self._s["workDir"], self._s.get("defaultRules", ""))
        self._running = {}             # key -> çalışan çağrı
        self._budget = {}              # key -> kalan söz hakkı
        self._force = set()            # yeni mesaj olmasa da söz verilenler
        self._rr = 0                   # sıralı modda adalet için başlangıç noktası
        self._stopped = False
        self._calls = 0                # son kullanıcı hamlesinden beri başlatılan model çağrısı
        self._capped = False
        self._talk_mode()              # her yeni sohbet Tartışma ile açılır
        self._resume = set()           # bilerek durdurulup yeniden başlatılacaklar (çağrı sınırına takılmaz)
        self._handoff = set()          # başka bir ajanın @ ile andığı: bir kez, çağrı sınırına takılmadan söz alır
        self._write_guards()
        self._snap = None              # Üretimde proje dosyalarının son fotoğrafı
        self._snap_wd = ""
        self._watch = QTimer(self)     # takılan ajan komutlarının bekçisi
        self._watch.timeout.connect(self._watch_cmds)
        self._watch.start(10000)
        self._kota = {}          # CLI türü -> {pencere: {name, used, resets}}: aynı hesabı kullanan ajanlar ortak
        self._kota_told = set()  # (tür, pencere, sıfırlanma): aynı dolum için bir kez yazılır
        self._cmds = {}          # key -> {"cmd", "secs"}: ajanın şu an çalıştırdığı en eski komut
        self._probe_timer = QTimer(self)
        self._probe_timer.timeout.connect(self._probe)
        self._probe_timer.start(3000)
        self._kota_timer = QTimer(self)
        self._kota_timer.timeout.connect(self.refreshQuota)
        self._kota_timer.start(10 * 60 * 1000)
        QTimer.singleShot(1500, self.refreshQuota)

    # ================= properties =================
    @Property(bool, notify=busyChanged)
    def busy(self):
        return bool(self._running)

    @Property("QVariantList", notify=speakingChanged)
    def speaking(self):
        return list(self._running.keys())

    @Property("QVariantMap", notify=quotaChanged)
    def quota(self):
        """CLI'ların bildirdiği kota pencereleri: {ajan key: [{name, used, resets}]}; used yüzde, resets Unix zamanı.
        Aynı CLI'ı kullanan ajanlar (Opus ile Sonnet gibi) aynı hesabın kotasını paylaşır: hepsine aynısı gösterilir."""
        return {a["key"]: list(self._kota.get(kind_of(a), {}).values()) for a in self._s["agents"]}

    # ================= panel =================
    @Property("QVariantMap", notify=statusChanged)
    def agentStatus(self):
        """Panel için: {key: {state, since, act, cmd, cmdSecs, stuck, muted}}.
        state: running · idle · off (devre dışı) · missing (komut yok)."""
        out = {}
        muted = set(self._chat.get("muted", []))
        for a in self._s["agents"]:
            k = a["key"]
            cur = self._running.get(k)
            c = self._cmds.get(k) or {}
            act = ""
            if cur and cur.get("acts"):
                act = cur["acts"][-1]
            elif not cur:
                last = next((m for m in reversed(self._chat["messages"]) if m.get("key") == k), None)
                act = ("son söz " + last.get("time", "")) if last else ""
            act = re.sub(r"^[^\w`(]+", "", act).strip()
            exe = exe_of(a)
            out[k] = {"state": "running" if cur else "off" if not a.get("enabled") else
                      "missing" if not (api_ready() if kind_of(a) == "api" else exe and shutil.which(exe)) else "idle",
                      "since": cur["t0"] if cur else 0, "act": short(act, 120),
                      "cmd": short(c.get("cmd", ""), 90), "cmdSecs": int(c.get("secs", 0)),
                      "stuck": bool(cur) and c.get("secs", 0) >= STUCK_SECS, "muted": k in muted}
        return out

    @Property("QVariantList", notify=filesChanged)
    def producedFiles(self):
        """Bu sohbette ajanların ürettiği ya da değiştirdiği, hâlâ diskte duran dosyalar; en yenisi önce."""
        colors = {a["name"]: a["color"] for a in self._s["agents"]}
        wd = self._workdir()
        out = []
        for path, f in (self._chat.get("files") or {}).items():
            if not os.path.isfile(path) or NOISE_RE.search(path) or "/." in path.replace(wd, ""):
                continue
            kind = file_kind(path)
            if not kind:
                continue
            rel = os.path.relpath(path, wd) if path.startswith(wd + os.sep) else path
            ext = path.rsplit(".", 1)[-1].lower()
            out.append({"path": path, "name": os.path.basename(path), "video": ext in VIDEO_EXT,
                        "thumb": self._thumb(path) if ext in VIDEO_EXT else "", "size": os.path.getsize(path), "dir": os.path.dirname(rel) if rel != path else
                        os.path.dirname(path).replace(str(Path.home()), "~"), "inside": rel != path,
                        "kind": kind, "ext": path.rsplit(".", 1)[-1].lower(), "who": f.get("who", ""),
                        "color": colors.get(f.get("who", ""), SYSTEM_COLOR), "t": f.get("t", 0),
                        "change": f.get("change", "yeni")})
        out.sort(key=lambda x: x["t"], reverse=True)
        return out

    def _thumb(self, path):
        """Videonun küçük resmi (ilk saniyeden bir kare): yoksa arka planda ffmpeg ile üretilir, hazır olunca panel yenilenir."""
        import hashlib
        try:
            st = os.stat(path)
        except OSError:
            return ""
        d = MEDIA_DIR / "kucuk"
        f = d / (hashlib.sha1(f"{path}{st.st_mtime_ns}".encode()).hexdigest()[:16] + ".jpg")
        if f.exists():
            return str(f)
        busy = self.__dict__.setdefault("_thumbing", set())
        if str(f) not in busy and shutil.which("ffmpeg"):
            busy.add(str(f))
            d.mkdir(parents=True, exist_ok=True)
            p = QProcess(self)
            def done(*_):
                busy.discard(str(f))
                p.deleteLater()
                if f.exists():
                    self.filesChanged.emit()
            p.finished.connect(done)
            p.start("ffmpeg", ["-y", "-loglevel", "error", "-ss", "0.5", "-i", path, "-frames:v", "1",
                               "-vf", "scale=360:-2", str(f)])
        return ""

    def _note_file(self, path, who, change):
        files = self._chat.setdefault("files", {})
        if change == "silindi":
            if files.pop(path, None) is not None:
                self._files_changed()
            return
        old = files.get(path)
        files[path] = {"who": who if who and who != "?" else (old or {}).get("who", ""), "t": time.time(),
                       "change": "yeni" if not old and change == "yeni" else "değişti"}
        self._files_changed()

    def _files_changed(self):
        """Panelin dosya listesi bir kez yenilensin. Her dosya için ayrı yenileme, ajan yüzlerce dosya yazınca
        (466 dosyalık sürüm klasörü) listeyi yüzlerce kez baştan kurup odayı donduruyordu (20.11.2026)."""
        if not getattr(self, "_files_due", False):
            self._files_due = True
            QTimer.singleShot(200, self._emit_files)

    def _emit_files(self):
        self._files_due = False
        self.filesChanged.emit()

    def _rebuild_files(self):
        """Eski sohbetler: dosya listesini odadaki "📝 Projede …" satırlarından ve ajanların medyasından çıkar."""
        wd = self._chat.get("workDir") or self._s["workDir"]
        if "files" in self._chat:
            # sonradan eklenen kural: ajanın mesajında gösterdiği ama listede olmayan dosyalar (komutla üretilen ses, video)
            files = self._chat["files"]
            for m in self._chat["messages"]:
                if m.get("key") not in ("system", "user"):
                    for p in m.get("media") or []:
                        if not p.startswith((str(MEDIA_DIR), str(ATTACH_DIR))) and p not in files:
                            files[p] = {"who": m["name"], "t": m.get("ts") or 0, "change": "yeni"}
            self._backfill_media(files, wd)
            return
        files = {}
        for m in self._chat["messages"]:
            t = m.get("ts") or 0
            if m.get("key") == "system" and m["text"].startswith("📝 Projede"):
                for label, body in re.findall(r"(yeni|değişti|silindi):\s*(.*?)(?=;\s*(?:yeni|değişti|silindi):|\n|$)",
                                              m["text"]):
                    for rel, who in re.findall(r"`([^`]+)`\s*\(([^)]*)\)", body):
                        p = os.path.normpath(os.path.join(wd, rel))
                        if label == "silindi":
                            files.pop(p, None)
                        else:
                            files[p] = {"who": who if who != "?" else files.get(p, {}).get("who", ""), "t": t,
                                        "change": "yeni" if p not in files and label == "yeni" else "değişti"}
            elif m.get("key") not in ("system", "user"):
                for p in m.get("media") or []:
                    if not p.startswith(str(MEDIA_DIR)):
                        files.setdefault(p, {"who": m["name"], "t": t, "change": "yeni"})
        # zaman bilgisi olmayan eski kayıtlar: sıralama mesaj sırasından gelsin
        for i, f in enumerate(files.values()):
            f["t"] = f["t"] or i
        self._backfill_media(files, wd)
        self._chat["files"] = files

    def _backfill_media(self, files, wd):
        """Sohbet başladıktan sonra klasörde oluşan resim, ses ve videolar: ajan onları komutla üretip mesajında
        anmamış ya da uygulama o sırada eski sürümdeyken üretilmiş olabilir. Kimin ürettiği bilinmiyorsa boş kalır."""
        since = float(self._chat.get("created") or 0)
        if not since or not os.path.isdir(wd):
            return
        n = 0
        for d, dirs, names in os.walk(wd):
            dirs[:] = [x for x in dirs if x not in self.SNAP_SKIP and not x.startswith(".")]
            for f in names:
                n += 1
                if n > 20000:
                    return
                p = os.path.join(d, f)
                if p in files or file_kind(p) not in ("image", "audio") or NOISE_RE.search(p):
                    continue
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    continue
                if mt >= since:
                    # ajanlar dosyalarını çoğu zaman kendi adıyla başlatır (claude_…, codex_…)
                    rel = os.path.relpath(p, wd).lower()
                    who = next((a["name"] for a in self._s["agents"]
                                if any(part.startswith(a["name"].lower().split()[0]) for part in rel.split(os.sep))), "")
                    files[p] = {"who": who, "t": mt, "change": "yeni"}

    @Slot(str)
    def stopAgent(self, key):
        """Yalnız bu ajanı durdur: turu biter, kendiliğinden yeniden başlamaz; sen yazınca yine söz alır."""
        self._budget[key] = 0
        self._force.discard(key)
        self._resume.discard(key)
        cur = self._running.get(key)
        if cur:
            cur["stopped_one"] = True
            self._log("stop_one", agent=cur["agent"]["name"])
            cur["proc"].kill()

    def _shell_cmds(self, cur):
        """Ajanın çalıştırdığı komutlar: CLI'ın altındaki en üst kabuklar (MCP sunucuları kabuk değildir)."""
        import psutil
        try:
            root = psutil.Process(cur["proc"].processId())
            kids = root.children(recursive=True)
        except (psutil.Error, ValueError):
            return []
        def is_shell(p):
            try:
                return os.path.basename(p.name()) in SHELLS
            except psutil.Error:
                return False
        out = []
        for p in kids:
            try:
                parent = p.parent()
                if is_shell(p) and (parent is None or parent.pid == root.pid or not is_shell(parent)):
                    out.append(p)
            except psutil.Error:
                continue
        return out

    def _live_files(self):
        """Tur sürerken üretilenler: panel tur bitmesini beklemesin (Claude bir turda onlarca resim çizebiliyor).
        Klasör ~10 sn'de bir yoklanır; ilk fotoğraftan sonra oluşan ya da değişen dosyalar listeye girer. Kimin
        yazdığı tek ajan çalışıyorsa odur; tur sonundaki "📝 Projede…" satırı gerekirse düzeltir."""
        self._live_tick = getattr(self, "_live_tick", 0) + 1
        base = getattr(self, "_snap", None)
        if self._live_tick % 3 or base is None or self._snap_wd != self._workdir():
            return
        now = self._scan()
        if now is None:
            return
        wd = self._workdir()
        who = self._running[next(iter(self._running))]["agent"]["name"] if len(self._running) == 1 else ""
        files = self._chat.setdefault("files", {})
        seen = self.__dict__.setdefault("_live_seen", {})
        for rel, sig in now.items():
            if base.get(rel) == sig or seen.get(rel) == sig:
                continue
            seen[rel] = sig
            p = os.path.join(wd, rel)
            if not file_kind(p) or NOISE_RE.search(p):
                continue
            if p not in files or files[p].get("t", 0) < time.time() - 5:
                self._note_file(p, who or (files.get(p) or {}).get("who", ""), "yeni" if rel not in base else "değişti")

    @Slot(str)
    def cutCommand(self, key):
        """Ajanın takılan komutunu (ajanı değil) durdur: ajan komutun bittiğini görür ve devam eder."""
        import psutil
        cur = self._running.get(key)
        if not cur:
            return
        n = 0
        for p in self._shell_cmds(cur):
            try:
                name = " ".join(p.cmdline())[:80]
                for x in p.children(recursive=True) + [p]:
                    try:
                        x.kill()
                        n += 1
                    except psutil.Error:
                        pass
                self._act(cur, f"⏹ {self._s['userName']} komutu kesti: {name}")
                self._log("cmd_cut", agent=cur["agent"]["name"], cmd=name)
            except psutil.Error:
                continue
        self._cmds.pop(key, None)
        self.statusChanged.emit()
        self.statusText.emit(f"{cur['agent']['name']}: komut kesildi" if n else f"{cur['agent']['name']}: çalışan komut yok")

    @Slot(str)
    def toggleMute(self, key):
        """Sözü kapat/aç: kapalıyken bu ajan yeni turlara katılmaz; @ ile ya da adına tıklayınca yine konuşur."""
        muted = self._chat.setdefault("muted", [])
        if key in muted:
            muted.remove(key)
        else:
            muted.append(key)
            self._budget[key] = 0
            self._force.discard(key)
        self._save_chat()
        self.statusChanged.emit()

    def _probe(self):
        """Çalışan ajanların komutlarını yokla: panel ne yaptığını ve ne kadar sürdüğünü göstersin."""
        if not self._running:
            if self._cmds or getattr(self, "_was_running", False):
                self._cmds = {}
                self._was_running = False
                self.statusChanged.emit()
            return
        self._was_running = True
        now = time.time()
        self._live_files()
        cmds = {}
        for k, cur in self._running.items():
            shells = self._shell_cmds(cur)
            if shells:
                try:
                    p = min(shells, key=lambda x: x.create_time())
                    line = " ".join(p.cmdline())
                    line = re.sub(r"^.*?(?:\s-l?c\s+)", "", line)             # bash -lc '…' → komutun kendisi
                    line = re.sub(r"^source\s+\S+.*?&&\s*eval\s+", "", line)   # Claude'un kabuk ön eki
                    cmds[k] = {"cmd": line.strip("'\" "), "secs": now - p.create_time()}
                except Exception:
                    pass
        self._cmds = cmds
        self.statusChanged.emit()

    # ================= roller =================
    @Property("QVariantList", constant=True)
    def tasks(self):
        return TASKS

    @Property("QVariantList", notify=rolesChanged)
    def roleTemplates(self):
        """Hazır şablonlar ve kullanıcının kaydettikleri (own: true, silinebilir)."""
        mine = [dict(x, own=True) for x in self._s.get("roleTemplates") or []]
        return [dict(x, own=False) for x in ROLE_TEMPLATES] + mine

    @Slot(str, "QVariant", result=str)
    def saveRoleTemplate(self, name, roles):
        """Rolleri şablon olarak sakla: başka sohbetlerde de seçilsin. Aynı adlı şablonun üstüne yazar."""
        roles = roles.toVariant() if hasattr(roles, "toVariant") else roles
        name = " ".join(str(name or "").split())[:40]
        clean = [{k: " ".join(str(x.get(k) or "").split())[:300] for k in ("title", "talk", "prod")} for x in roles or []]
        clean = [x for x in clean if any(x.values())]
        if not name or not clean:
            return ""
        mine = [x for x in self._s.get("roleTemplates") or [] if x["name"].lower() != name.lower()]
        tid = "k-" + uuid.uuid4().hex[:6]
        mine.append({"id": tid, "name": name, "roles": clean})
        self._s["roleTemplates"] = mine
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self._s, indent=2, ensure_ascii=False))
        self.rolesChanged.emit()
        self.statusText.emit(f"Şablon kaydedildi: {name}")
        return tid

    @Slot(str)
    def deleteRoleTemplate(self, tid):
        self._s["roleTemplates"] = [x for x in self._s.get("roleTemplates") or [] if x["id"] != tid]
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self._s, indent=2, ensure_ascii=False))
        self.rolesChanged.emit()

    @Property("QVariantMap", notify=rolesChanged)
    def roles(self):
        """Bu sohbetin rolleri: {on, template, list: [{title, talk, prod, agents: [key]}]}. Ön tanımlı olarak kapalı.
        Bir role birden çok ajan atanabilir, bir ajan birden çok rol alabilir."""
        r = self._chat.get("roles") or {}
        lst = r.get("list")
        if lst is None:      # ilk biçim: ajan başına tek rol
            lst = [dict(x, agents=[k]) for k, x in (r.get("agents") or {}).items()]
        keys = {a["key"] for a in self._s["agents"]}
        lst = [dict(x, agents=[k for k in x.get("agents", []) if k in keys]) for x in lst]
        return {"on": bool(r.get("on")), "template": r.get("template", ""), "list": [x for x in lst if x["agents"]]}

    @Slot("QVariant")
    def setRoles(self, r):
        """Rolleri kaydet ve odaya görünür yaz. Kapatılınca da yazılır. Ajanlara oda bilgisiyle bir kez gider."""
        r = r.toVariant() if hasattr(r, "toVariant") else r
        keys = [a["key"] for a in self._s["agents"]]
        lst = []
        for x in r.get("list") or []:
            y = {k: " ".join(str(x.get(k) or "").split())[:300] for k in ("title", "talk", "prod")}
            y["agents"] = [k for k in keys if k in (x.get("agents") or [])]
            if y["agents"] and any(y[k] for k in ("title", "talk", "prod")):
                lst.append(y)
        on = bool(r.get("on")) and bool(lst)
        new = {"on": on, "template": r.get("template", "") if on else "", "list": lst if on else []}
        old = self.roles
        if old == new or (not on and not old["on"]):
            return
        self._chat["roles"] = new
        self._chat["rolesRev"] = int(self._chat.get("rolesRev", 0)) + 1
        who = self._s["userName"]
        if on:
            prod = bool(self._s.get("production"))
            if not any(x["talk"] or x["prod"] for x in lst):
                # yalnız iş bölümü: tek satır
                parts = "; ".join(f"{x['title']}: {self._names(x['agents'])}" for x in lst)
                text = (f"🎭 {who} iş bölümü yaptı. {parts}. İş bölümü yetki değil, sorumluluk alanıdır; "
                        "ortak karar kuralı aynen sürer.")
            else:
                parts = []
                for x in lst:
                    d = x["prod"] if prod and x["prod"] else x["talk"] or x["prod"]
                    parts.append(f"**{x['title'] or 'Rol'}** — {self._names(x['agents'])}" + (f": {d}" if d else ""))
                text = (f"🎭 {who} iş bölümü yaptı. İşler yetki değil, sorumluluk alanıdır; ortak karar kuralı aynen sürer.\n"
                        + "\n".join("- " + p for p in parts))
        else:
            text = f"🎭 {who} iş bölümünü kapattı: kimsenin işi ya da rolü yok."
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, text, True, 0, emit=True)
        self._save_chat()
        self.rolesChanged.emit()
        self.statusText.emit("İş bölümü kaydedildi" if on else "İş bölümü kapatıldı")

    # ================= oda kuralları =================
    @Property("QVariantMap", notify=rulesChanged)
    def rules(self):
        """Bu odanın kuralları. Ayarlardaki oda anlaşması bütün odalarındır; bunlar yalnız bu sohbetin."""
        text = self._chat.get("rules") or ""
        return {"text": text, "isDefault": bool(text) and text == (self._s.get("defaultRules") or ""),
                "defaultText": self._s.get("defaultRules") or ""}

    @Slot(str, bool)
    def setRules(self, text, as_default):
        """Kuralları kaydet ve odaya görünür yaz. Ajanlara oda bilgisiyle gider: yeni oturumda, yeni katılan ajana
        ve kurallar her değiştiğinde süren oturuma bir kez; döküm kırpılsa da düşmez."""
        text = "\n".join(ln.rstrip() for ln in (text or "").strip().splitlines())[:4000]
        if as_default != (bool(text) and text == (self._s.get("defaultRules") or "")):
            self._s["defaultRules"] = text if as_default else ""
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self._s, indent=2, ensure_ascii=False))
            self.settingsChanged.emit()
        old = self._chat.get("rules") or ""
        if text != old:
            self._chat["rules"] = text
            self._chat["rulesRev"] = int(self._chat.get("rulesRev", 0)) + 1
            who = self._s["userName"]
            if self._chat["messages"] or text:
                note = (f"📜 {who} oda kurallarını kaldırdı." if not text else
                        f"📜 {who} oda kurallarını {'değiştirdi' if old else 'koydu'}:\n\n{text}")
                self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, note, True, 0, emit=True)
                self._save_chat()
        self.rulesChanged.emit()
        self.statusText.emit("Oda kuralları kaydedildi" if text else "Oda kuralları kaldırıldı")

    # ================= karar aç =================
    def _decision_agents(self):
        d = self._chat.get("decision") or {}
        return set(d.get("agents") or []) if d.get("open") else set()

    @Property("QVariantMap", notify=decisionChanged)
    def decision(self):
        """Açık karar: {open, q, total, answered, agents: [{key, name, color, state}]}; state: bekliyor ·
        yazıyor · yazdı · pas. Ayrıca alınan son karar (last) ve kayıtlı kararlar (decisions)."""
        d = self._chat.get("decision") or {}
        sealed = {m["key"] for m in self._chat["messages"] if m.get("sealed")}
        done = set(d.get("done") or [])
        out = []
        for k in d.get("agents") or []:
            a = self._agent(k)
            if not a:
                continue
            state = ("yazıyor" if k in self._running else "yazdı" if k in sealed else
                     "hata" if k in (d.get("failed") or []) else "pas" if k in done else "bekliyor")
            out.append({"key": k, "name": a["name"], "color": a["color"], "state": state})
        decisions = self._chat.get("decisions") or []
        return {"open": bool(d.get("open")), "q": d.get("q", ""), "agents": out, "total": len(out),
                "answered": sum(1 for x in out if x["state"] in ("yazdı", "pas", "hata")),
                "revealed": bool(d) and not d.get("open"), "last": decisions[-1]["text"] if decisions else "",
                "decisions": decisions}

    @Slot(str, result=bool)
    def openDecision(self, q):
        """Önemli bir kararda bağımsız ilk görüş: herkes cevabını ötekilerinkini görmeden yazar, cevaplar hepsi
        bitince birlikte açılır. Sonra sohbet serbestçe sürer (oy, atanmış itirazcı yok)."""
        q = " ".join((q or "").split())[:600]
        if not q:
            self.statusText.emit("Kararın sorusunu yazın")
            return False
        if self._running:
            self.statusText.emit("Ajanlar çalışırken karar açılmaz: bitmelerini bekleyin ya da Durdur'a basın")
            return False
        muted = set(self._chat.get("muted", []))
        keys = [a["key"] for a in self._enabled() if a["key"] not in muted]
        if not keys:
            self.statusText.emit("Odada sözü açık ajan yok")
            return False
        who = self._s["userName"]
        self._post_pact("talk")
        mid = uuid.uuid4().hex
        self._append_msg(mid, "system", "Oda", SYSTEM_COLOR,
                         f"🗳 {who} karar açtı: **{q}**\n\n{DECISION_ASK}", True, 0, emit=True)
        if not self._chat.get("title"):
            self._chat["title"] = q[:70]
        self._chat["decision"] = {"q": q, "agents": keys, "open": True, "t": time.time(), "mid": mid, "done": []}
        self._log("decision_open", q=q, agents=keys)
        self._budget.clear()
        self._force.clear()
        for k in keys:
            self._budget[k] = 1
            self._force.add(k)
        self._stopped = False
        self._calls = 0
        self._capped = False
        self._save_chat()
        self.chatsChanged.emit()
        self.decisionChanged.emit()
        self._schedule()
        return True

    def _decision_check(self, key, answered, failed=False):
        """Karar turundaki bir ajan bitti: hepsi bittiyse cevapları aç."""
        d = self._chat.get("decision") or {}
        if not d.get("open") or key not in d.get("agents", []):
            return
        if answered and key not in d["done"]:
            d["done"].append(key)
        if failed and key not in d.setdefault("failed", []):
            d["failed"].append(key)
        self.decisionChanged.emit()
        if all(k in d["done"] for k in d["agents"]) and not any(k in self._running for k in d["agents"]):
            self._reveal()

    @Slot()
    def revealNow(self):
        """Bekleyenleri beklemeden cevapları aç: o an yazmakta olanın cevabı geldiğinde doğrudan odaya düşer."""
        if (self._chat.get("decision") or {}).get("open"):
            self._reveal(early=True)

    def _reveal(self, early=False):
        d = self._chat["decision"]
        d["open"] = False
        sealed = [m for m in self._chat["messages"] if m.get("sealed")]
        for m in sealed:
            self._chat["messages"].remove(m)
        names = self._names
        wrote = list(dict.fromkeys(m["key"] for m in sealed))
        failed = [k for k in d["agents"] if k not in wrote and k in d.get("failed", [])]
        passed = [k for k in d["agents"] if k not in wrote and k in d["done"] and k not in failed]
        waiting = [k for k in d["agents"] if k not in wrote and k not in d["done"]]
        text = f"🗳 Cevaplar açıldı: {names(wrote)} yazdı" if wrote else "🗳 Cevaplar açıldı: kimse cevap yazmadı"
        if passed:
            text += f"; {names(passed)} pas geçti"
        if failed:
            text += f"; {names(failed)} hata verdi"
        if waiting:
            text += f"; {names(waiting)} henüz yazmadı, cevabı gelince doğrudan odaya düşecek"
        text += ". Artık birbirinizin cevabını görüyorsunuz; sohbet serbest."
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, text, True, 0, emit=True)
        # cevaplar açıldıkları anda odaya düşer: sıra numaraları (kimin neyi gördüğü) bozulmasın
        for m in sealed:
            m.pop("sealed", None)
            m["ts"] = round(time.time(), 1)
            self._chat["messages"].append(m)
            self.messageSealed.emit(m["id"], False)
            self._broadcast(m)
        self._log("decision_reveal", early=early, wrote=wrote, passed=passed, waiting=waiting)
        n = INF if self._s.get("autoMode") else max(1, int(self._s["autoRounds"]))
        for a in self._enabled():
            if a["key"] not in self._chat.get("muted", []):
                self._budget[a["key"]] = n
        self._stopped = False
        self._calls = 0
        self._capped = False
        self._save_chat()
        self.decisionChanged.emit()
        QTimer.singleShot(0, self._schedule)

    @Slot(str)
    def recordDecision(self, text):
        """Alınan kararı tek cümleyle kaydet: odaya sabitlenmiş olarak düşer, ajanlara oda bilgisiyle gider."""
        text = " ".join((text or "").split())[:600]
        if not text:
            return
        d = self._chat.get("decision") or {}
        self._chat.setdefault("decisions", []).append({"q": d.get("q", ""), "text": text, "t": time.time()})
        self._chat["decisionsRev"] = int(self._chat.get("decisionsRev", 0)) + 1
        mid = uuid.uuid4().hex
        self._append_msg(mid, "system", "Oda", SYSTEM_COLOR, f"✅ {self._s['userName']} kararı yazdı: **{text}**",
                         True, 0, emit=True)
        self._chat["messages"][-1]["pinned"] = True
        self.messagePinned.emit(mid, True)
        self._save_chat()
        self.decisionChanged.emit()
        self.statusText.emit("Karar kaydedildi")

    @Slot(str)
    def startProduction(self, text):
        """Üretimi aç ve hangi kararın uygulandığını tek cümleyle odaya yaz (boşsa yalnız mod değişir)."""
        text = " ".join((text or "").split())[:600]
        if text != (self._chat.get("prodDecision") or ""):
            self._chat["prodDecision"] = text
            self._chat["decisionsRev"] = int(self._chat.get("decisionsRev", 0)) + 1
        self._prod_note = text
        s = json.loads(json.dumps(self._s))
        s["production"] = True
        self.saveSettings(s)

    @staticmethod
    def _with_meaning(x):
        """Açıklaması yazılmamış hazır iş (Plan, Kod…): varsayılan anlamıyla."""
        t = TASK_BY_TITLE.get((x.get("title") or "").strip().lower())
        if t and not (x.get("talk") or x.get("prod")):
            return dict(x, talk=t["talk"], prod=t["prod"])
        return x

    def _names(self, keys):
        ns = [a["name"] for a in self._s["agents"] if a["key"] in keys]
        return ns[0] if len(ns) == 1 else ", ".join(ns[:-1]) + " ve " + ns[-1] if ns else ""

    def _hdr_ver(self):
        """Oda bilgisinin sürümü: roller, kurallar ya da kararlar değişince süren oturumlara da bir kez yeniden gider."""
        c = self._chat
        return f"{HEADER_VER}.{c.get('rolesRev', 0)}.{c.get('rulesRev', 0)}.{c.get('decisionsRev', 0)}"

    def _role_lines(self, agent):
        r = self.roles
        if not r["on"]:
            return []
        prod = bool(self._s.get("production"))
        def desc(x):
            x = self._with_meaning(x)
            d = x.get("prod") if prod and x.get("prod") else x.get("talk") or x.get("prod") or ""
            return (x.get("title") or "rol") + (f" ({d})" if d else "")
        k = agent["key"]
        mine = [x for x in r["list"] if k in x["agents"]]
        out = [f"{self._s['userName']} bu sohbet için iş bölümü yaptı. İşler yetki değil sorumluluk alanıdır; "
               "kimse yönetici değildir, ortak karar yine açık destekle alınır."]
        for x in mine:
            mates = [a for a in x["agents"] if a != k]
            out.append("Senin işin: " + desc(x) + (f"; bu işi {self._names(mates)} ile paylaşıyorsun." if mates else "."))
        others = [f"{self._names([a for a in x['agents'] if a != k])}: {desc(x)}" for x in r["list"]
                  if x not in mine]
        if others:
            out.append("Diğerlerinin işleri: " + "; ".join(others) + ".")
        return out

    @Slot(str, bool, float, result=str)
    def renderMd(self, md, dark, scale):
        return md_html(md, dark, scale)

    @Property(bool, constant=True)
    def jailOk(self):
        """Tartışma kutusu bu makinede kurulabiliyor mu (açılışta bir kez denenir)."""
        return bool(self._jailed_ok())

    @Property(str, constant=True)
    def homeDir(self):
        return str(Path.home())

    @Property(str, notify=chatsChanged)
    def currentChat(self):
        return self._chat["id"]

    @Property("QVariantList", notify=chatsChanged)
    def chats(self):
        out = []
        for f in CHATS_DIR.glob("*.json") if CHATS_DIR.exists() else []:
            try:
                c = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            out.append({"id": c["id"], "title": c.get("title") or "(başlıksız)",
                        "dir": os.path.basename((c.get("workDir") or "").rstrip("/")),
                        "updated": c.get("updated", 0),
                        "count": len(c.get("messages", []))})
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    # ================= proje klasörü =================
    @Property(str, notify=chatsChanged)
    def chatDir(self):
        """Bu sohbetin proje klasörü: ajanlar burada çalışır, ürettiklerini buraya yazar."""
        return os.path.expanduser(self._chat.get("workDir") or self._s["workDir"])

    @Property("QVariantList", notify=settingsChanged)
    def recentDirs(self):
        return [{"path": d, "name": os.path.basename(d.rstrip("/")) or d} for d in self._s.get("recentDirs") or []
                if os.path.isdir(d)][:6]

    @Slot(str)
    def pick(self, mode):
        """Klasör ya da dosya seçtir: pencereyi sistemin dosya seçme hizmeti (LifeOS'ta LifeOS Dosyalar) açar."""
        title = "Proje klasörünü seç" if mode == "folder" else "Odaya dosya ekle"
        p = QProcess(self)
        p.setProcessEnvironment(QProcessEnvironment.systemEnvironment())
        def done(code, _s):
            try:
                out = json.loads(bytes(p.readAllStandardOutput()).decode() or "{}")
            except (ValueError, RuntimeError):
                out = None
            p.deleteLater()
            if code != 0 or out is None:
                self.pickFailed.emit(mode)
                return
            paths = [QUrl(u).toLocalFile() for u in out.get("uris", []) if u.startswith("file://")]
            if out.get("ok") and paths:
                self.picked.emit(mode, paths)
        p.finished.connect(done)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self.pickFailed.emit(mode))
        p.start(sys.executable, ["-c", PORTAL_PICK, mode, title])

    @Slot(str, str, result=str)
    def resolveFile(self, path, text):
        """Mesajdaki bağlantının gerçek yolu. Ajanlar çoğu zaman yalnız dosya adını yazar ("sayfa.png"), klasörünü
        aynı mesajda ayrıca anar ("taslak/tas_seti/"): önce o klasörlerde, sonra proje içinde (en yenisi) aranır."""
        wd = self.chatDir
        path = os.path.expanduser(path or "")
        if os.path.isabs(path) and os.path.exists(path):
            return path
        rel = path[len(wd):].lstrip("/") if path.startswith(wd + "/") else path.lstrip("./")
        tries = [os.path.join(wd, rel)]
        for d in re.findall(r"`?((?:~|/)?[\w.\-/]+/)`?", text or ""):
            d = os.path.expanduser(d)
            tries.append(os.path.join(d if os.path.isabs(d) else os.path.join(wd, d), os.path.basename(rel)))
        for c in tries:
            if os.path.isfile(c):
                return os.path.normpath(c)
        name, best, n = os.path.basename(rel), None, 0
        for d, dirs, files in os.walk(wd):
            dirs[:] = [x for x in dirs if x not in self.SNAP_SKIP and not x.startswith(".")]
            n += len(files)
            if n > 20000:
                break
            if name in files:
                f = os.path.join(d, name)
                if best is None or os.path.getmtime(f) > os.path.getmtime(best):
                    best = f
        return best or ""

    @Slot(str, result=bool)
    def isDir(self, path):
        return os.path.isdir(os.path.expanduser(path))

    @Slot(str)
    def setProjectDir(self, path):
        """Var olan bir projeyi odaya aç: bu sohbetin ve sonraki yeni sohbetlerin klasörü olur. Ajanların oturumları
        yeni klasörde baştan açılır (eski klasörde okuduklarını burada sanmasınlar); odaya görünür bir satır düşer."""
        path = os.path.normpath(os.path.expanduser(path or ""))
        if not os.path.isdir(path):
            self.statusText.emit("Klasör bulunamadı: " + path)
            return
        if self._running:
            self.statusText.emit("Ajanlar çalışırken klasör değişmez; önce durdurun")
            return
        old = self.chatDir
        recent = [path] + [d for d in self._s.get("recentDirs") or [] if d != path]
        self._s["recentDirs"] = recent[:8]
        self._s["workDir"] = path
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self._s, indent=2, ensure_ascii=False))
        if os.path.normpath(old) != path:
            self._chat["workDir"] = path
            self._chat["sessions"] = {}
            self._snap = None
            if self._chat["messages"]:
                self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR,
                                 f"📁 {self._s['userName']} proje klasörünü değiştirdi: `{path}`. Ajanlar bu klasörde çalışır.",
                                 True, 0, emit=True)
                self._save_chat()
        self.settingsChanged.emit()
        self.chatsChanged.emit()
        self.filesChanged.emit()
        self.statusText.emit("Proje klasörü: " + path)

    @Property("QVariant", notify=settingsChanged)
    def settings(self):
        s = json.loads(json.dumps(self._s))
        for a in s["agents"]:
            exe = shlex.split(a["command"])[0] if a["command"].strip() else ""
            a["found"] = api_ready() if kind_of(a) == "api" else bool(exe and shutil.which(exe))
        s["apiReady"] = api_ready()
        return s

    @Slot("QVariant")
    def saveSettings(self, s):
        s = s.toVariant() if hasattr(s, "toVariant") else s
        clean = {k: s.get(k, DEFAULTS[k]) for k in DEFAULTS}
        clean["agents"] = [{k: a.get(k, v) for k, v in base_agent(a).items()} for a in s["agents"] if a.get("key")]
        if not clean["agents"]:
            clean["agents"] = json.loads(json.dumps(self._s["agents"]))
        # ad ve anahtar tek olmalı: @ ile söz verme, "kim konuştu" ve oturumlar bunlarla bulunur
        keys, names = set(), set()
        for a in clean["agents"]:
            while a["key"] in keys:
                a["key"] = kind_of(a) + "-" + uuid.uuid4().hex[:4]
            keys.add(a["key"])
            base = " ".join(str(a.get("name") or base_agent(a)["name"]).split())[:40] or base_agent(a)["name"]
            name, n = base, 2
            while name.lower() in names or name.lower() == str(clean["userName"]).lower() or name.lower() == "oda":
                name, n = f"{base} {n}", n + 1
            a["name"] = name
            names.add(name.lower())
        clean["panelOpen"] = bool(clean.get("panelOpen", True))
        clean["roleTemplates"] = self._s.get("roleTemplates") or []      # şablonlar yalnız kendi düğmeleriyle değişir
        clean["recentDirs"] = self._s.get("recentDirs") or []
        clean["autoRounds"] = int(clean["autoRounds"])
        clean["maxChars"] = int(clean["maxChars"])
        clean["maxCalls"] = max(0, int(clean.get("maxCalls") or 0))
        clean["cmdTimeout"] = max(0, int(clean.get("cmdTimeout") or 0))
        clean["fontScale"] = min(1.6, max(0.8, round(float(clean.get("fontScale") or 1.0), 2)))
        for k in ("keepSessions", "autoMode", "parallel", "production", "liveRelay", "leanTools"):
            clean[k] = bool(clean[k])
        for a in clean["agents"]:
            a["timeout"] = max(0, int(a.get("timeout") or 0))   # 0 = sınırsız
        # klasör ya da komut değiştiyse eski CLI oturumları geçersiz: ajanlar dökümle yeniden başlar
        old = {a["key"]: a["command"] for a in self._s["agents"]}
        if clean["workDir"] != self._s["workDir"]:
            self._chat["workDir"] = clean["workDir"]
            self._chat["sessions"] = {}
        for a in clean["agents"]:
            if old.get(a["key"]) != a["command"]:
                self._chat["sessions"].pop(a["key"], None)
        was_auto = self._s.get("autoMode")
        was_prod = bool(self._s.get("production"))
        self._s = clean
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False))
        if clean["production"] != was_prod:
            self._log("mode", production=clean["production"])
            # çalışan süreçler eski izinlerle başlatıldı; izinler sonradan değişmez.
            # Bu süreçlere artık mesaj iletme: notu ve sonrasını yeni izinlerle açılan süreçte alsınlar.
            again = []
            for cur in self._running.values():
                cur["stale"] = True
                if bool(cur.get("prod")) != clean["production"]:
                    # Tartışma izniyle çalışan süreç üretemez; Üretim izniyle çalışan süreç ise
                    # Tartışma'da yazmayı sürdürmemeli: iki yönde de hemen durdur, yeni izinle yeniden başlasın
                    cur["restart"] = "prod" if clean["production"] else "talk"
                    cur["proc"].kill()
                    again.append(cur["agent"]["key"])
                    self._resume.add(cur["agent"]["key"])
            if self._chat["messages"]:
                # ajanlara nerede olduklarını söyleyen bir bilgi: konum ve odadakiler gibi
                who = clean["userName"]
                note = (f"{who} Üretim modunu açtı: artık dosya yazılabilir ve komut çalıştırılabilir."
                        if clean["production"] else
                        (f"{who} Tartışma moduna geçti: proje dosyaları yalnızca okunur; resim, belge ve taslaklar {self._drafts()} klasörüne yazılabilir. " + self._draft_rule()
                         if self._jailed_ok() else
                         f"{who} Tartışma moduna geçti: proje dosyaları yalnızca okunur. Bu makinede Tartışma kutusu kurulamadı; dosya üretimi kullanılamıyor."))
                self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, note, True, 0, emit=True)
                if clean["production"]:
                    note = getattr(self, "_prod_note", "")
                    self._prod_note = ""
                    if note:
                        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR,
                                         f"🎯 Üretim şu kararla açıldı: **{note}**", True, 0, emit=True)
                    self._post_pact("prod")
                    # üretimi açmak senin hamlen: her ajan notu yeni izinleriyle görsün
                    # (boştakiler hemen, çalışanlar mevcut turunu bitirince)
                    for a in self._enabled():
                        self._budget[a["key"]] = max(1, self._budget.get(a["key"], 0))
                        self._force.add(a["key"])
                    self._stopped = False
                    self._calls = 0
                    self._capped = False
                else:
                    # durdurulan Üretim süreçleri kutu içinde kaldıkları yerden sürsün
                    for k in again:
                        self._budget[k] = max(1, self._budget.get(k, 0))
                        self._force.add(k)
        self._save_chat()
        self.settingsChanged.emit()
        if clean["autoMode"] != was_auto:
            # oto açıldıysa çalışanlar için kalan hakkı sınırsız yap; kapandıysa yeni tur başlatma
            for k in self._budget:
                self._budget[k] = INF if clean["autoMode"] else 0
        self.statusText.emit("Ayarlar kaydedildi")
        if clean["production"] != was_prod and self._force:
            self._schedule()

    AGENT_COLORS = ["#4f8cff", "#d97757", "#10a37f", "#f59e0b", "#ec4899", "#06b6d4", "#eab308", "#a3e635", "#f472b6"]

    @Slot(str, "QVariant", result="QVariant")
    def newAgent(self, kind, agents):
        """Ayarlarda "Ajan ekle": aynı CLI'dan bir ajan daha (başka model, başka çaba). Ad ve renk boşta olandan."""
        agents = agents.toVariant() if hasattr(agents, "toVariant") else (agents or [])
        base = API_AGENT if kind == "api" else next((d for d in DEFAULTS["agents"] if d["key"] == kind), DEFAULTS["agents"][0])
        a = json.loads(json.dumps(base))
        keys = {x.get("key") for x in agents}
        a["key"] = kind + "-" + uuid.uuid4().hex[:4]
        while a["key"] in keys:
            a["key"] = kind + "-" + uuid.uuid4().hex[:4]
        names = {str(x.get("name", "")).lower() for x in agents}
        n = 2
        a["name"] = base["name"]
        while a["name"].lower() in names:
            a["name"], n = f"{base['name']} {n}", n + 1
        used = {x.get("color") for x in agents}
        a["color"] = next((c for c in self.AGENT_COLORS if c not in used), base["color"])
        a["enabled"] = True
        exe = exe_of(a)
        a["found"] = api_ready() if kind == "api" else bool(exe and shutil.which(exe))
        return a

    @Slot(str, str)
    def fetchModelsFor(self, key, command):
        """Henüz kaydedilmemiş (yeni eklenen) ajanın modelleri: komutuna bakarak."""
        self._models_for(key, {"key": key, "command": command})

    @Slot()
    def resetSettings(self):
        self.saveSettings(json.loads(json.dumps(DEFAULTS)))

    # ================= sohbetler =================
    @Slot()
    def newChat(self):
        self.stop()
        self._chat = new_chat(self._s["workDir"], self._s.get("defaultRules", ""))
        self._talk_mode()
        self.roomReset.emit()
        self.filesChanged.emit()
        self.rolesChanged.emit()
        self.rulesChanged.emit()
        self.decisionChanged.emit()
        self.statusChanged.emit()
        self.chatsChanged.emit()
        self.statusText.emit("Yeni sohbet — bir konu aç")

    def _talk_mode(self):
        """Yeni sohbet: karar konuşarak alınsın diye Tartışma modunda başla."""
        if self._s.get("production"):
            self._s["production"] = False
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self._s, indent=2, ensure_ascii=False))
            self.settingsChanged.emit()

    @Slot(str)
    def openChat(self, cid):
        try:
            c = json.loads((CHATS_DIR / f"{cid}.json").read_text())
        except (OSError, ValueError):
            return
        self.stop()
        c.setdefault("seen", {})
        for k, v in c.get("sessions", {}).items():   # eski kayıtlar: seen oturumun içindeydi
            if "seen" in v:
                c["seen"].setdefault(k, v["seen"])
        self._chat = c
        self._rebuild_files()
        self.roomReset.emit()
        self.filesChanged.emit()
        self.rolesChanged.emit()
        self.rulesChanged.emit()
        self.decisionChanged.emit()
        self.statusChanged.emit()
        ids = [m.get("id") for m in c["messages"]]
        for m in c["messages"]:
            # kayıtlı kimlik tekse onu kullan: sabitleme gibi işlemler mesajı bununla bulur
            mid = m["id"] if m.get("id") and ids.count(m["id"]) == 1 else uuid.uuid4().hex
            shown = m["text"] + (f"\n\n_⚠ {m['note']}_" if m.get("note") else "")
            self.messageAdded.emit(mid, m["key"], m["name"], m["color"], shown, False, m.get("time", ""))
            if m.get("acts"):
                self.messageActivity.emit(mid, "\n".join(m["acts"]))
            if m.get("media"):
                self.messageMedia.emit(mid, "\n".join(f for f in m["media"] if os.path.isfile(f)))
            self.messageDone.emit(mid, m.get("ok", True), m.get("secs", 0))
            if m.get("pinned"):
                self.messagePinned.emit(mid, True)
            if m.get("to"):
                self.messageTo.emit(mid, self._names(m["to"]))
            if m.get("sealed"):
                self.messageSealed.emit(mid, True)
        self.chatsChanged.emit()
        self.statusText.emit(f"Sohbet açıldı · {c.get('workDir') or self._s['workDir']}")

    @Slot(str)
    def togglePin(self, mid):
        """Mesajı sabitle ya da bırak. Sabit mesaj, ajana yeni oturum açılırken döküm kırpılsa da gider."""
        m = next((m for m in reversed(self._chat["messages"]) if m.get("id") == mid), None)
        if not m:
            return
        if m.get("pinned"):
            m.pop("pinned")
        else:
            m["pinned"] = True
        self._log("pin", id=mid, pinned=bool(m.get("pinned")))
        self._save_chat()
        self.messagePinned.emit(mid, bool(m.get("pinned")))

    @Slot(str)
    @Slot(str, str)
    def renameChat(self, cid, title):
        """Sohbetin geçmişteki adını değiştir (ajanlara gitmez, yalnızca listede görünür)."""
        title = " ".join(title.split())[:120]
        if not title:
            return
        if cid == self._chat["id"]:
            self._chat["title"] = title
            self._save_chat()
        else:
            f = CHATS_DIR / f"{cid}.json"
            try:
                c = json.loads(f.read_text())
                c["title"] = title
                f.write_text(json.dumps(c, ensure_ascii=False, indent=1))
            except (OSError, ValueError):
                return
        self.chatsChanged.emit()

    def deleteChat(self, cid):
        try:
            (CHATS_DIR / f"{cid}.json").unlink()
        except OSError:
            pass
        if cid == self._chat["id"]:
            self.newChat()
        self.chatsChanged.emit()

    def _log(self, ev, **data):
        """İnceleme kaydı: loglar/<sohbet>.jsonl — her satır bir olay."""
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": round(time.time(), 3), "ev": ev, **data}
            with open(LOGS_DIR / f"{self._chat['id']}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _save_chat(self):
        if not self._chat["messages"]:
            return
        self._chat["updated"] = time.time()
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        (CHATS_DIR / f"{self._chat['id']}.json").write_text(
            json.dumps(self._chat, indent=1, ensure_ascii=False))

    def _transcript(self):
        """Ajanlara giden döküm. Karar turunda saklanan cevaplar hepsi bitince açılır, o zamana dek burada yoktur."""
        return [m for m in self._chat["messages"] if m.get("ok", True) and not m.get("sealed")]

    @staticmethod
    def _for(m, a):
        """Bu mesaj bu ajana gider mi: @ ile başlayan ajan mesajı yalnız andığı ajana (ve yazana) gider."""
        to = m.get("to")
        return not to or a["key"] in to or m.get("key") == a["key"]

    @staticmethod
    def _noise(m):
        """Yeni bilgi taşımayan mesaj: kısa onay ya da aynı ajanın az önce söylediğinin tekrarı."""
        return is_ack(m.get("text")) or bool(m.get("repeat"))

    # ================= söz alma =================
    def _enabled(self):
        return [a for a in self._s["agents"] if a["enabled"]]

    @Slot(result="QVariantList")
    def pasteFromClipboard(self):
        """Panodaki dosyalar ya da resim: ek olarak eklenecek yollar. Resim geçici bir PNG'ye yazılır."""
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return []
        if md.hasUrls():
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
            if paths:
                return paths
        if md.hasImage():
            img = QGuiApplication.clipboard().image()
            if not img.isNull():
                d = ATTACH_DIR / "_pano"
                d.mkdir(parents=True, exist_ok=True)
                f = d / time.strftime("yapistirilan-%Y%m%d-%H%M%S.png")
                if img.save(str(f), "PNG"):
                    return [str(f)]
        return []

    def _store_attachments(self, files):
        """Gönderilen dosyaları sohbetin ek klasörüne kopyala: asılları taşınsa ya da silinse de mesaj geçerli kalsın."""
        out = []
        d = ATTACH_DIR / self._chat["id"]
        for f in files or []:
            f = str(f)
            if f.startswith("file://"):
                f = QUrl(f).toLocalFile()
            if not os.path.isfile(f):
                continue
            d.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"\s+", "-", Path(f).name)      # boşluksuz: mesajdaki yol bölünmeden tanınsın
            dst = d / name
            n = 1
            while dst.exists():
                dst = d / f"{Path(name).stem}-{n}{Path(name).suffix}"
                n += 1
            try:
                if Path(f).parent == ATTACH_DIR / "_pano":
                    shutil.move(f, dst)
                else:
                    shutil.copy2(f, dst)
                out.append(str(dst))
            except OSError:
                continue
        return out

    @Slot(str, "QVariantList")
    def sendWith(self, text, files):
        """Mesaj ve ekleri: ekler sohbet klasörüne kopyalanır, yolları mesajın sonuna yazılır (ajanlar okuyup açar)."""
        paths = self._store_attachments(files)
        text = text.strip()
        if paths:
            text += ("\n\n" if text else "") + "**Ekler:**\n" + "\n".join(f"- `{p}`" for p in paths)
        self._attached = paths          # balonda kart olarak gösterilsin (resim olmayanlar da)
        try:
            self.send(text)
        finally:
            self._attached = []

    @Slot(str)
    def send(self, text):
        text = text.strip()
        if not text:
            return
        first = not self._chat.get("title")
        self._post_pact("talk")
        if self._s.get("production"):
            self._post_pact("prod")      # Üretim açıkken anlaşmaya eklenen kural süren sohbete de bir kez düşer
        mid = uuid.uuid4().hex
        self._append_msg(mid, "user", self._s["userName"], USER_COLOR, text, True, 0, emit=True)
        media = list(getattr(self, "_attached", []) or [])
        media += [f for f in self._media({}, text) if f not in media]
        if media:
            self._chat["messages"][-1]["media"] = media     # sohbet yeniden açılınca da görünsün
            self.messageMedia.emit(mid, "\n".join(media))
        if first:
            self._chat["title"] = text.replace("\n", " ")[:70]
        self._save_chat()
        self.chatsChanged.emit()
        targets = self._mentions(text)
        for k in targets:
            self._force.add(k)      # @ ile anılan, sözü kapalı olsa da konuşur
        n = INF if self._s.get("autoMode") and not targets else max(1, int(self._s["autoRounds"]))
        for a in self._enabled():
            if targets:
                self._budget[a["key"]] = 1 if a["key"] in targets else 0
            else:
                self._budget[a["key"]] = n
        self._stopped = False
        self._calls = 0
        self._capped = False
        self._schedule()

    @Slot()
    def nextRound(self):
        for a in self._enabled():
            self._budget[a["key"]] = max(1, self._budget.get(a["key"], 0))
            self._force.add(a["key"])
        self._stopped = False
        self._calls = 0
        self._capped = False
        self._schedule()

    @Property(bool, notify=busyChanged)
    def capped(self):
        """Elle modda çağrı sınırı doldu: odada "Devam et" görünür."""
        return bool(self._capped) and not self._s.get("autoMode")

    @Slot()
    def goOn(self):
        """Çağrı sınırında kalınan yerden sür: kalan söz hakları aynen, sayaç sıfırdan."""
        self._calls = 0
        self._capped = False
        self._stopped = False
        self._log("go_on")
        self._schedule()

    @Slot(str)
    def poke(self, key):
        """Belirli bir ajana söz ver (yeni mesaj olmasa bile)."""
        self._budget[key] = max(1, self._budget.get(key, 0))
        self._force.add(key)
        self._stopped = False
        self._calls = 0
        self._capped = False
        self._schedule()

    @Slot()
    def stop(self):
        if self._running:
            self._log("stop", running=[c["agent"]["name"] for c in self._running.values()])
        self._stopped = True
        self._budget.clear()
        self._force.clear()
        for cur in list(self._running.values()):
            cur["proc"].kill()

    def _seen(self, key):
        return self._chat.setdefault("seen", {}).get(key, 0)

    def _has_unseen(self, a):
        user = self._s["userName"]
        return any(m["name"] != a["name"] and m["key"] != "system" and self._for(m, a)
                   and (m["name"] == user or not self._noise(m))
                   for m in self._transcript()[self._seen(a["key"]):])

    def _schedule(self):
        """Boşta olan, söz hakkı olan ve görmediği yeni mesaj bulunan ajanları başlat."""
        if not self._stopped:
            agents = self._enabled()
            limit = len(agents) if self._s.get("parallel", True) else 1
            n = len(agents)
            for j in range(n):
                if len(self._running) >= limit:
                    break
                a = agents[(self._rr + j) % n] if n else None
                k = a["key"]
                if k in self._running or self._budget.get(k, 0) <= 0:
                    continue
                if k in self._chat.get("muted", []) and k not in self._force:
                    continue      # sözü kapalı: yalnız adına tıklayınca ya da @ ile konuşur
                if k not in self._force and not self._has_unseen(a):
                    continue
                # Oto'da sayı sınırı yok: Oto "sen durdurana kadar" demek (20.11.2026). Boşa dönmeyi onay ve tekrar
                # süzgeci önler: yeni bilgi taşımayan mesaj kimseyi uyandırmaz. Elle modda sınır sürer; yarıda
                # kesilen ve başka bir ajanın @ ile iş devrettiği ajan sınıra takılmaz.
                cap = 0 if self._s.get("autoMode") else int(self._s.get("maxCalls") or 0)
                if cap > 0 and self._calls >= cap and k not in self._resume and k not in self._handoff:
                    if not self._capped:
                        self._log("cap", calls=self._calls)
                    self._capped = True
                    break
                self._calls += 1
                self._force.discard(k)
                self._resume.discard(k)
                self._handoff.discard(k)
                self._budget[k] -= 1
                if limit == 1:
                    self._rr = (self._rr + j + 1) % n
                self._start(a)
        self.busyChanged.emit()
        self.speakingChanged.emit()
        self.statusChanged.emit()
        if not self._running:
            if self._capped:
                self.statusText.emit(f"Çağrı sınırı doldu ({self._calls}) — sürdürmek için Devam et")
            else:
                self.statusText.emit("Oda sessiz — sıra sende")
        else:
            names = [c["agent"]["name"] for c in self._running.values()]
            self.statusText.emit(" · ".join(names) + (" düşünüyor…" if len(names) == 1 else " çalışıyor…"))

    # ================= test / modeller =================
    @Slot(str)
    def test(self, key):
        a = self._agent(key)
        if not a:
            return
        proc = QProcess(self)
        if kind_of(a) == "api":
            cfg = {"model": a.get("model") or "auto", "root": self._drafts(), "drafts": self._drafts(), "steps": 3,
                   "prompt": "Merhaba. Araç kullanmadan, finish ile tek cümlelik bir selam ver."}
            args, stdin = [sys.executable, str(API_SCRIPT), json.dumps(cfg, ensure_ascii=False)], None
        else:
            args, stdin = self._build_cmd(dict(a), "Merhaba", False, plain=True)
        proc.setProcessEnvironment(self._env())
        proc.setWorkingDirectory(self._workdir())
        proc.setProcessChannelMode(QProcess.MergedChannels)

        def done(code, _status):
            out = ANSI_RE.sub("", bytes(proc.readAll()).decode(errors="replace")).strip()
            self.testResult.emit(key, code == 0, out[-1500:] or "(boş çıktı)")
            proc.deleteLater()

        proc.finished.connect(done)
        proc.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and
                                   self.testResult.emit(key, False, "Başlatılamadı: " + args[0]))
        proc.start(args[0], args[1:])
        if stdin is not None:
            proc.write(stdin.encode())
        proc.closeWriteChannel()

    @Slot(str)
    def fetchModels(self, key):
        """CLI'ın sunduğu modelleri ve effort seviyelerini getir."""
        a = self._agent(key)
        if a:
            self._models_for(key, a)

    def _models_for(self, key, a):
        if kind_of(a) == "api":
            p = QProcess(self)
            def done(*_):
                try:
                    rows = json.loads(bytes(p.readAllStandardOutput()).decode() or "[]")
                except (ValueError, RuntimeError):
                    rows = []
                if isinstance(rows, dict):
                    rows = []
                p.deleteLater()
                self.modelsReady.emit(key, [{"value": "auto", "label": "Otomatik: önce yerel ve ücretsiz"}]
                                      + [{"value": r["value"], "label": r["label"]} for r in rows],
                                      ["low", "medium", "high"])
            p.finished.connect(done)
            p.start(sys.executable, [str(API_SCRIPT), "--modeller"])
            return
        exe = exe_of(a)
        efforts = ["low", "medium", "high", "xhigh", "max"]
        if exe == "claude":
            self.modelsReady.emit(key, [
                {"value": "claude-opus-5-5", "label": "Claude Opus 5.5"},
                {"value": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
                {"value": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},
                {"value": "claude-fable-5-2", "label": "Claude Fable 5.2"},
            ], efforts)
        elif exe == "codex":
            models, efforts = [], efforts + ["ultra"]
            try:
                d = json.loads((Path.home() / ".codex" / "models_cache.json").read_text())
                for m in d.get("models", []):
                    if m.get("visibility") == "list":
                        models.append({"value": m["slug"],
                                       "label": m.get("display_name") or m["slug"]})
            except (OSError, ValueError, KeyError):
                pass
            self.modelsReady.emit(key, models, efforts)
        elif exe in ("agy", "antigravity"):
            p = QProcess(self)

            def done(*_):
                try:
                    out = bytes(p.readAllStandardOutput()).decode(errors="replace")
                except RuntimeError:        # uygulama kapanırken süreç nesnesi çoktan silinmiş
                    return
                ms = [{"value": ln.split("\t")[0], "label": ln.split("\t", 1)[1].strip()}
                      for ln in out.splitlines() if "\t" in ln]
                self.modelsReady.emit(key, ms, efforts)
                p.deleteLater()

            p.finished.connect(done)
            p.start("agy", ["models"])
        else:
            self.modelsReady.emit(key, [], efforts)

    # ================= internals =================
    def _agent(self, key):
        return next((a for a in self._s["agents"] if a["key"] == key), None)

    def _mentions(self, text):
        low = text.lower()
        def said(w):
            return re.search("@" + re.escape(w.lower()) + r"(?![\w-])", low) is not None
        return [a["key"] for a in self._enabled() if said(a["key"]) or said(a["name"])]

    def _post_pact(self, kind):
        """Oda anlaşmasını sohbette bir kez göster: Tartışma'da ilk mesajla, Üretim ilk açılınca.
        Anlaşmaya sonradan eklenen kural (PACT_VER) Üretim'i çoktan açılmış sohbete yalnız bir kez yazılır."""
        done = self._chat.setdefault("pact", [])
        if not self._s.get("pact", True):
            return
        if kind in done:
            if kind == "prod" and int(self._chat.get("pactVer", 1)) < PACT_VER:
                self._chat["pactVer"] = PACT_VER
                self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR,
                                 "🤝 Oda anlaşmasına eklendi: " + PACT_HELP, True, 0, emit=True)
            return
        if kind == "prod":
            self._chat["pactVer"] = PACT_VER
        if kind == "prod" and "talk" not in done:
            text, done[:] = PACT_TALK + " " + PACT_PROD + " " + PACT_HELP, ["talk", "prod"]
        else:
            text = PACT_TALK if kind == "talk" else PACT_PROD + " " + PACT_HELP
            done.append(kind)
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, "🤝 Oda anlaşması: " + text, True, 0, emit=True)

    def _append_msg(self, mid, key, name, color, text, ok, secs, emit=False, acts=None):
        t = time.strftime("%H:%M")
        m = {"id": mid, "key": key, "name": name, "color": color, "text": text,
             "ok": ok, "secs": round(secs, 1), "time": t, "ts": round(time.time(), 1)}
        if acts:
            m["acts"] = acts
        agent_msg = ok and key not in ("system", "user")
        if agent_msg:
            to = self._directed(text, key)
            if to:
                m["to"] = to
            if self._repeats(key, text):
                m["repeat"] = True
            if key in self._decision_agents():
                m["sealed"] = True
        self._chat["messages"].append(m)
        self._log("message", id=mid, author=name, key=key, ok=ok, secs=round(secs, 1), text=text,
                  acts=acts or [], to=m.get("to") or [], sealed=bool(m.get("sealed")), repeat=bool(m.get("repeat")))
        if emit:
            self.messageAdded.emit(mid, key, name, color, text, False, t)
        if m.get("to"):
            self.messageTo.emit(mid, self._names(m["to"]))
        if m.get("sealed"):
            self.messageSealed.emit(mid, True)
            self.decisionChanged.emit()
        elif ok:
            self._broadcast(m)
            if agent_msg:
                self._pass_on(m)

    def _directed(self, text, me):
        """Mesaj @ ile başlıyorsa andığı ajanlar (yazan hariç): mesaj yalnız onlara gider."""
        t = re.sub(r"^[\s*_>]+", "", text or "")
        out, agents = [], sorted(self._enabled(), key=lambda a: -len(a["name"]))
        while t.startswith("@"):
            low, hit = t.lower(), None
            for a in agents:
                for w in ("@" + a["name"].lower(), "@" + a["key"].lower()):
                    if low.startswith(w) and not re.match(r"[\w-]", low[len(w):len(w) + 1]):
                        hit = (a["key"], len(w))
                        break
                if hit:
                    break
            if not hit:
                break
            if hit[0] != me and hit[0] not in out:
                out.append(hit[0])
            t = re.sub(r"^\W*?(?:ve\s+|,\s*)?(?=@)|^[\s,;:]+", "", t[hit[1]:])
        return out

    def _repeats(self, key, text):
        """Aynı ajan az önce neredeyse aynısını söylediyse ("raporu bekliyorum" tekrarı): yeni bilgi sayılmaz."""
        import difflib
        t = (text or "")[:1500]
        if len(t) < 20:
            return False
        prev = [m["text"][:1500] for m in reversed(self._chat["messages"])
                if m.get("key") == key and m.get("ok", True)][:3]
        for p in prev:
            sm = difflib.SequenceMatcher(None, t, p, autojunk=False)
            if sm.quick_ratio() > 0.85 and sm.ratio() > 0.85:
                return True
        return False

    def _pass_on(self, m):
        """İş devri: ajanın @ ile andığı ajan (sözü kapalı değilse) hemen bir kez söz alır, çağrı sınırı dolmuş olsa
        bile. 20.11.2026: araştırma geldiğinde planı yazacak ajanı çağıracak hak kalmamıştı, oda 18 dakika bekledi."""
        if m.get("repeat"):
            return
        muted = set(self._chat.get("muted", []))
        keys = [k for k in dict.fromkeys((m.get("to") or []) + self._mentions(m["text"]))
                if k != m["key"] and k not in muted]
        if not keys:
            return
        for k in keys:
            self._budget[k] = max(1, self._budget.get(k, 0))
            self._handoff.add(k)
        self._log("handoff", by=m["name"], to=[self._agent(k)["name"] for k in keys if self._agent(k)])
        if not self._stopped:
            QTimer.singleShot(0, self._schedule)

    def _line(self, m):
        """Dökümdeki ve canlı iletimdeki satır: özel mesajda kime gittiği de yazar."""
        to = m.get("to")
        who = m["name"] + (f" → {self._names(to)} (yalnız {'sana' if len(to) == 1 else 'size'})" if to else "")
        return f"{who}: {m['text']}"

    def _broadcast(self, m):
        """Odaya yeni düşen bir mesajı, o an çalışan ve canlı girdi alan ajanlara hemen yaz."""
        author, text = m["name"], m["text"]
        line = self._line(m)
        n = len(self._transcript())
        cap = 0 if self._s.get("autoMode") else int(self._s.get("maxCalls") or 0)
        if cap > 0 and self._calls >= cap and author != self._s["userName"] and not m.get("to"):
            return     # sınır doldu: ajanlar arası canlı iletim de durur; sen yazınca kaldıkları yerden alırlar
        if not self._s.get("liveRelay", True) and author != self._s["userName"]:
            return     # canlı iletim kapalı: ajanlar birbirini sıraları gelince toplu okur (kota için); senin sözün yine anında gider
        if author != self._s["userName"] and self._noise(m):
            return     # kısa onay/bekleme ya da tekrar: çalışanı bölmeye değmez, sonraki çağrıda dökümde görülür
        for cur in self._running.values():
            if not cur.get("live_in") or cur.get("in_closed") or cur.get("stale") or cur["agent"]["name"] == author:
                continue
            if not self._for(m, cur["agent"]):
                continue     # özel mesaj: yalnız anılan ajana
            if cur["proc"].state() != QProcess.Running:
                continue
            if cur["fmt"] == "cxs":
                # codex app-server: çalışan tura turn/steer ile ekle
                if not cur.get("turn") or cur.get("turn_done"):
                    continue
                rid = self._rpc(cur, "turn/steer", {"threadId": cur["new_sid"], "expectedTurnId": cur["turn"],
                                                    "input": [{"type": "text", "text": line}]})
                cur["steers"][rid] = (line, n)
            elif cur["fmt"] == "agy":
                # agy stream-json girdi: aynı süreçte, mevcut tur bitince işlenir
                cur["proc"].write(self._agy_line(line).encode())
                cur["sent"] += 1
                cur["agy_q"].append(n)
            else:
                cur["proc"].write(self._user_line(line).encode())
                cur["pending_inj"].append(line)
                cur["inj_n"][line] = n
            self._log("inject", to=cur["agent"]["name"], via=cur["fmt"], text=line)
            # seen burada ilerlemez: CLI mesajı aldığını bildirince ilerler (_delivered).
            # Teyit gelmezse ajan mesajı bir sonraki çağrısında alır.

    def _delivered(self, cur, n):
        """CLI araya yazılan mesajı aldığını teyit etti: o noktaya kadar görmüş say."""
        cur["seen"] = max(cur["seen"], n)
        self._log("delivered", to=cur["agent"]["name"], seen=n)

    def _header(self, agent):
        """Ajana giden oda bilgisi. "Konum: …" gibi başlıklı satırlar yerine düz cümle: başlıklı biçimi Gemini her
        mesajında rapor kalıbı olarak tekrarlıyordu (19.11.2026)."""
        others = [self._s["userName"]] + [a["name"] for a in self._enabled() if a["name"] != agent["name"]]
        mode = ("Şu an Üretim modundayız: dosya yazılabilir, komut çalıştırılabilir." if self._s.get("production")
                else f"Şu an Tartışma modundayız: proje dosyaları yalnızca okunur, komutlar çalıştırılabilir; resim, belge ve taslaklar {self._drafts()} klasörüne yazılabilir. " + self._draft_rule()
                if self._jailed_ok() else
                "Şu an Tartışma modundayız: proje dosyaları yalnızca okunur; bu makinede Tartışma kutusu kurulamadığı için dosya üretimi kullanılamıyor.")
        lines = [f"(Oda bilgisi, yalnız senin için. Odaya yazarken bunu tekrarlama; mesajını konum, katılımcı listesi "
                 f"ya da rapor başlığıyla açma. Yalnız kendi adınla konuş.)",
                 f"Bu bir sohbet odası ve sen {agent['name']} olarak buradasın. Odada ayrıca {', '.join(others)} var.",
                 f"Çalışma klasörü {self._workdir()}. {mode}",
                 "Mesajda yolu geçen ya da yazılan resim (png, jpg, gif, webp, svg), video (mp4, webm, mov), "
                 "ses (mp3, wav, ogg), html ve pdf dosyaları odada herkese gösterilir.",
                 DIRECT_HINT.replace("{who}", next((a["name"] for a in self._enabled() if a["key"] != agent["key"]),
                                                   "Ad"))]
        if self._s.get("production"):
            lines.append(f"Odadaki ajanların başlatmadığı süreçleri (örneğin {self._s['userName']} tarafından açılmış "
                         f"pencere ve uygulamaları) kapatma; kapanması gerekiyorsa bunu {self._s['userName']} ile konuş.")
        return "\n".join(lines + self._rule_lines() + self._role_lines(agent))

    def _rule_lines(self):
        """Odaya özel kurallar ve alınan kararlar: her yeni oturumda ve değiştiklerinde gider, dökümle kırpılmaz."""
        out, user = [], self._s["userName"]
        rules = (self._chat.get("rules") or "").strip()
        if rules:
            out.append(f"{user} bu oda için şu kuralları koydu; sohbet boyunca geçerlidir:\n{rules}")
        done = [d for d in self._chat.get("decisions") or [] if d.get("text")]
        if done:
            out.append("Bu odada alınan kararlar (en yenisi sonda):\n" + "\n".join(f"- {d['text']}" for d in done[-6:]))
        if self._s.get("production") and self._chat.get("prodDecision"):
            out.append(f"Üretim şu kararla açıldı: {self._chat['prodDecision']}")
        return out

    def _fmt(self, msgs):
        return "\n\n".join(self._line(m) for m in msgs)

    def _prompt_for(self, agent, resumed):
        """Oturum sürüyorsa yalnızca ajanın kaçırdıkları; yoksa konum + odadakiler + tüm döküm."""
        tr = self._transcript()
        mine = [m for m in tr if self._for(m, agent)]      # başkasına özel mesajlar bu ajana gitmez
        if resumed:
            new = [m for m in tr[self._seen(agent["key"]):] if m["name"] != agent["name"] and self._for(m, agent)]
            body = self._fmt(new or mine[-1:])
            if self._chat.get("hdr", {}).get(agent["key"], 0) != self._hdr_ver():
                body = self._header(agent) + "\n\n" + body     # oturum eski oda bilgisiyle açılmıştı
            return body
        body = self._fmt(mine)
        mx = int(self._s["maxChars"])
        if len(body) > mx:
            body = body[-mx:]
        # sabitlenen mesajlar kırpmada düşmesin: dökümde kalmadıysa başa, olduğu gibi eklenir
        lost = [m for m in mine if m.get("pinned") and self._fmt([m]) not in body]
        if lost:
            body = (f"Sabitlenen mesajlar ({self._s['userName']} sabitledi; döküm uzun olduğu için "
                    f"aşağıda yer almıyor olabilirler):\n\n" + self._fmt(lost) + "\n\n---\n\n" + body)
        return self._header(agent) + "\n\n" + body

    def _codex_lean(self):
        """Yalın oda profili (Codex): ~/.codex/config.toml'daki MCP sunucuları kapatılır; tarayıcı/REPL
        sunucuları kalır, çünkü Codex sayfayı açıp kontrol etmek için onları kullanıyor."""
        if not self._s.get("leanTools", True):
            return []
        try:
            cfg = tomllib.loads((Path.home() / ".codex" / "config.toml").read_text())
        except (OSError, ValueError):
            return []
        out = []
        for name in cfg.get("mcp_servers") or {}:
            if re.fullmatch(r"[A-Za-z0-9_-]+", name) and not re.search(r"repl|browser|chrome", name, re.I):
                out += ["-c", f"mcp_servers.{name}.enabled=false"]
        return out

    def _build_cmd(self, agent, prompt, sid, plain=False):
        """Komutu kur: model/effort + (varsa) oturum sürdürme + canlı olay akışı."""
        args = shlex.split(agent["command"])
        exe = exe_of(agent)
        extra = []
        effort = agent.get("effort")
        if exe in ("agy", "antigravity") and re.search(r"-(low|medium|high|xhigh|max)$", agent.get("model") or ""):
            effort = ""     # Gemini model adı seviyeyi zaten içeriyor; --effort ile çakışıyor
        for val, tpl in ((agent.get("model"), agent.get("modelArg")),
                         (effort, agent.get("effortArg"))):
            if val and tpl:
                extra += [x.replace("{model}", val).replace("{effort}", val) for x in shlex.split(tpl)]
        has_fmt = "--output-format" in args or "--json" in args
        sess = self._s.get("keepSessions", True) and sid is not False
        talk = not self._s.get("production", True)
        # Tartışma kutusu: ajan Üretim'deki yetkilerle çalışır ama bubblewrap içinde proje salt okunur,
        # yalnızca taslak/ yazılabilir. bwrap yoksa eski araç kısıtlamalarına düşülür.
        jail = talk and not plain and self._jailed()
        if jail:
            talk = False

        def set_opt(names, value):
            """args içindeki seçeneğin değerini değiştir; yoksa extra'ya ekle."""
            for j, x in enumerate(args):
                if x in names and j + 1 < len(args):
                    args[j + 1] = value
                    return
            extra.extend([names[0], value])

        if talk:
            # tartışma: konuşabilir, okuyabilir; yazamaz, komut çalıştıramaz
            if exe == "claude":
                # yalnızca taslak/ klasörüne yazabilir; başka yere yazma onay ister, başsız modda reddedilir
                tas = self._drafts()
                set_opt(["--permission-mode"], "default")
                extra += ["--disallowedTools=Bash", "--allowedTools", "Read", "Glob", "Grep",
                          f"Edit(/{tas}/**)", f"Write(/{tas}/**)"]
            elif exe == "codex":
                set_opt(["-s", "--sandbox"], "read-only")
            elif exe in ("agy", "antigravity"):
                # --disable-slash-commands ile plan modu etkisiz; düzenlemeleri otomatik kabul eden modu kaldır,
                # böylece yalnızca izin kuralının açtığı yere yazabilir
                for j, x in enumerate(args):
                    if x == "--mode" and j + 1 < len(args) and args[j + 1] == "accept-edits":
                        del args[j:j + 2]
                        break
                # okuma komutları serbest (kural önek eşleşmesidir)
                # okuma komutları serbest (kural önek eşleşmesidir); dosya yazma yalnızca taslak/ klasörüne
                extra += ["--settings", json.dumps({"permissions": {"allow": [f"command({c})" for c in READ_CMDS]
                                                                     + [f"write_file({self._drafts()})"]}})]
        if exe in ("agy", "antigravity"):
            extra.append("--disable-slash-commands")
            if not talk:
                # LifeosArch/ekip (surucu.py AgyDriver) ile aynı: agy'nin kendi sandbox'ı yazmayı çalışma
                # klasörü ve /tmp ile sınırlar; içinde her komut serbest. Başsız modda onay soramadığı için
                # kural olmadan her komut reddediliyordu.
                rules = [r.strip() for r in re.split(r"[,\n]", agent.get("allowRules") or "") if r.strip()]
                if jail:
                    # Tartışma kutusunda sınırı bubblewrap çiziyor: agy'nin kendi sandbox'ı kutu içinde
                    # kurulamıyor (komutlar salt okunur hatası alıyor). Yazma izni de kutuya bırakılır;
                    # izinsiz yere yazmaya kalkarsa başsız modda sessizce düşmek yerine dosya sisteminden hata görür.
                    args = [x for x in args if x != "--sandbox"]
                    rules = (rules or ["command(*)"]) + ["write_file(/)"]
                elif "--sandbox" not in args:
                    extra.append("--sandbox")
                extra += ["--settings", json.dumps({"permissions": {"allow": rules or ["command(*)"]}})]
        if exe == "claude":
            if self._s.get("leanTools", True) and "--strict-mcp-config" not in args:
                # yalın oda profili: kişisel bağlayıcılar (Gmail, Takvim, Drive…), MCP sunucuları ve kullanıcı
                # eklentileri yüklenmez; yerleşik araçlar (Bash, Read, Write, Edit, WebSearch) aynen kalır.
                # İzinler komut satırından verildiği için kullanıcı ayarlarını atlamak onları etkilemez.
                extra += ["--strict-mcp-config", "--setting-sources", "project,local"]
            if not plain and not has_fmt:
                # çift yönlü akış: çalışırken odaya düşen mesajlar Claude'a anında yazılır
                extra += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                          "--replay-user-messages"]
            if sess:
                extra += ["--resume", sid] if sid else ["--session-id", agent["_newsid"]]
        elif exe in ("agy", "antigravity"):
            if not plain and not has_fmt:
                extra += ["--output-format", "stream-json", "--input-format", "stream-json"]
            if sess and sid:
                extra += ["--conversation", sid]
        elif exe == "codex" and len(args) > 1 and args[1] == "exec":
            if not plain and not has_fmt:
                extra += ["--json"]
            if sess and sid:
                # codex exec resume <sid> — resume -s desteklemez, sandbox'ı -c ile ver
                rest, conv, i = args[2:], [], 0
                while i < len(rest):
                    if rest[i] in ("-s", "--sandbox") and i + 1 < len(rest):
                        conv += ["-c", f'sandbox_mode="{rest[i + 1]}"']
                        i += 2
                        continue
                    if rest[i] != "-" and "{prompt}" not in rest[i]:
                        conv.append(rest[i])
                    i += 1
                tail = [x for x in rest if x == "-" or "{prompt}" in x] or ["-"]
                args = [args[0], "exec", "resume"] + conv + [sid] + tail

        i = 1
        while i < len(args) and not args[i].startswith("-") and "{prompt}" not in args[i] \
                and not (sid and args[i] == sid):
            i += 1
        args = args[:i] + extra + args[i:]
        if jail:
            args = self._jail_prefix() + args
        live = "--input-format" in args and "stream-json" in args
        if exe in ("agy", "antigravity") and live:
            return [x.replace("{prompt}", "") for x in args], self._agy_line(prompt)
        if "{prompt}" in agent["command"]:
            return [x.replace("{prompt}", prompt) for x in args], None
        if live:
            return args, self._user_line(prompt)
        return args, prompt

    @staticmethod
    def _agy_line(text):
        return json.dumps({"event": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n"

    @staticmethod
    def _user_line(text):
        return json.dumps({"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n"

    _shell_path = None

    @classmethod
    def _user_path(cls):
        """Kullanıcının terminalde gördüğü PATH. Uygulama menüden açılınca ~/.bashrc okunmaz; oraya eklenen araçlar
        (Flutter, Cargo, Go…) ajanlara görünmüyordu: "Flutter bu makinede kurulu değil" (19.11.2026)."""
        if cls._shell_path is None:
            found = []
            shell = os.environ.get("SHELL") or "/bin/bash"
            try:
                out = subprocess.run([shell, "-ilc", 'printf "\\n__PATH__%s\\n" "$PATH"'], capture_output=True,
                                     text=True, timeout=5, stdin=subprocess.DEVNULL).stdout
                m = re.search(r"__PATH__(.*)", out)
                found = [p for p in (m.group(1).split(":") if m else []) if p]
            except (OSError, subprocess.SubprocessError):
                pass
            home = Path.home()
            for d in ("flutter/bin", ".pub-cache/bin", ".cargo/bin", "go/bin", ".npm-global/bin", ".bun/bin",
                      ".deno/bin", ".local/bin"):
                if (home / d).is_dir():
                    found.append(str(home / d))
            cls._shell_path = found
        return cls._shell_path

    @staticmethod
    def _write_guards():
        try:
            GUARD_DIR.mkdir(parents=True, exist_ok=True)
            for n in ("pkill", "killall"):
                f = GUARD_DIR / n
                if not f.exists() or f.read_text() != GUARD_SCRIPT:
                    f.write_text(GUARD_SCRIPT)
                    f.chmod(0o755)
        except OSError:
            pass

    def _env(self):
        env = QProcessEnvironment.systemEnvironment()
        for k in list(env.keys()):
            if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_"):
                env.remove(k)
        env.insert("NO_COLOR", "1")
        env.insert("SACMALIK_ODA", "1")     # süreç koruması: ajanların başlattığı süreçler bu işareti taşır
        path = [p for p in env.value("PATH", "").split(":") if p]
        if (GUARD_DIR / "pkill").exists():
            path = [str(GUARD_DIR)] + [p for p in path if p != str(GUARD_DIR)]
        for p in self._user_path():
            if p not in path:
                path.append(p)
        env.insert("PATH", ":".join(path))
        return env

    def _workdir(self):
        raw = self._chat.get("workDir") or self._s["workDir"] or str(DATA_DIR / "oda")
        d = Path(os.path.expanduser(raw))
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    # CLI'ların kendi oturum, kimlik ve önbellek yerleri: kutuda yalnızca bunlar ve taslak/ yazılabilir
    STATE_PATHS = (".claude", ".claude.json", ".codex", ".gemini", ".cache", ".npm",
                   ".local/share/claude", ".local/state/claude", ".local/state/codex")

    @classmethod
    def _jail_args(cls, wd, tas):
        """Tartışma kutusu: tüm sistem salt okunur, ajana özel boş /tmp; yazılabilir yerler taslak/ ve CLI durumları."""
        args = ["bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--tmpfs", "/tmp",
                "--die-with-parent"]
        run = f"/run/user/{os.getuid()}"
        if os.path.isdir(run):
            args += ["--bind", run, run]
        for rel in cls.STATE_PATHS:
            p = Path.home() / rel
            if p.exists():
                args += ["--bind", str(p), str(p)]
        # kullanıcının gönderdiği ekler okunabilsin (veri klasörü /tmp'de olsa bile)
        ATTACH_DIR.mkdir(parents=True, exist_ok=True)
        args += ["--ro-bind", str(ATTACH_DIR), str(ATTACH_DIR)]
        # /tmp boşaltıldı: proje oradaysa onu da salt okunur geri bağla
        return args + ["--ro-bind", wd, wd, "--bind", tas, tas, "--chdir", wd, "--"]

    _jail_state = None   # None: denenmedi, True/False: öz-denetim sonucu

    @classmethod
    def _jailed_ok(cls):
        """bwrap'ın var olması yetmez: kutunun gerçekten kurulup sınırı uyguladığını bir kez dene."""
        if cls._jail_state is None:
            cls._jail_state = False
            if shutil.which("bwrap"):
                import tempfile
                with tempfile.TemporaryDirectory(dir=Path.home()) as d:
                    wd, tas = Path(d) / "proje", Path(d) / "proje" / "taslak"
                    tas.mkdir(parents=True)
                    sh = (f'touch "{tas}/a" && ! touch "{wd}/b" 2>/dev/null && ! touch "{d}/c" 2>/dev/null'
                          ' && touch /tmp/d')
                    try:
                        r = subprocess.run(cls._jail_args(str(wd), str(tas)) + ["sh", "-c", sh],
                                           capture_output=True, timeout=10)
                        cls._jail_state = r.returncode == 0 and (tas / "a").exists() \
                            and not (wd / "b").exists() and not (Path(d) / "c").exists()
                    except Exception:
                        pass
        return cls._jail_state

    def _jailed(self):
        return not self._s.get("production", True) and self._jailed_ok()

    def _jail_prefix(self):
        return self._jail_args(self._workdir(), self._drafts())

    def _draft_rule(self):
        """Kullanıcının koyduğu kural: Tartışma'da taslak resimdir, kodlanmış sayfa ancak o isterse."""
        return (f"Taslaklar resim olarak çizilir (png, svg); kodlanmış site ya da html taslağı yalnızca "
                f"{self._s['userName']} açıkça isterse yazılır.")

    def _drafts(self):
        """Tartışma modunda ajanların yazabildiği tek yer: proje içindeki taslak/ klasörü."""
        d = Path(self._workdir()) / "taslak"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def _rel(self, path):
        try:
            return os.path.relpath(str(path), self._workdir()) if os.path.isabs(str(path)) else str(path)
        except ValueError:
            return str(path)

    # ---------- bir ajanı çalıştır ----------
    def _start(self, a):
        key = a["key"]
        a = dict(a)
        sid = self._chat["sessions"].get(key, {}).get("sid") if self._s.get("keepSessions", True) else False
        a["_newsid"] = str(uuid.uuid4())
        prompt = self._prompt_for(a, bool(sid))
        if kind_of(a) == "api":
            # API ajanı kendi kutusunu kurar (api_ajan.py): Tartışma'da yalnız taslak/ yazılabilir
            cfg = {"model": a.get("model") or "auto", "effort": a.get("effort") or "", "root": self._workdir(),
                   "drafts": "" if self._s.get("production") else self._drafts(), "session": sid or "",
                   "prompt": prompt, "steps": 40}
            args, stdin = [sys.executable, str(API_SCRIPT), json.dumps(cfg, ensure_ascii=False)], None
        else:
            args, stdin = self._build_cmd(a, prompt, sid)
        exe = exe_of(a)
        fmt = ("claude" if exe == "claude" and "stream-json" in args else
               "codex" if exe == "codex" and "--json" in args else
               "agy" if exe in ("agy", "antigravity") and "stream-json" in args else "text")
        pre = []
        if args and args[0] == "bwrap" and "--" in args:
            k = args.index("--") + 1
            pre, args = args[:k], args[k:]
        fmt = ("claude" if exe == "claude" and "stream-json" in args else
               "codex" if exe == "codex" and "--json" in args else
               "agy" if exe in ("agy", "antigravity") and "stream-json" in args else "text")
        if kind_of(a) == "api":
            fmt = "api"
        if fmt == "codex" and args[1:2] == ["exec"]:
            # codex app-server: tur sürerken gelen mesajlar turn/steer ile aynı tura eklenir
            fmt, args, stdin = "cxs", [args[0], "app-server"] + self._codex_lean(), None
        args = pre + args

        self._chat.setdefault("hdr", {})[key] = self._hdr_ver()
        prod_now = bool(self._s.get("production"))
        mid = uuid.uuid4().hex
        self._log("start", id=mid, agent=a["name"], model=a.get("model") or "", effort=a.get("effort") or "",
                  production=bool(self._s.get("production")), resumed=bool(sid), session=sid or "",
                  call=self._calls, seen=len(self._transcript()), prompt=prompt, argv=args)
        self.messageAdded.emit(mid, key, a["name"], a["color"], "", True, time.strftime("%H:%M"))
        if key in self._decision_agents():
            self.messageSealed.emit(mid, True)      # karar turu: cevap yazılırken de saklı
            self.decisionChanged.emit()
        p = QProcess(self)
        p.setProcessEnvironment(self._env())
        p.setWorkingDirectory(self._workdir())
        cur = {"id": mid, "agent": a, "proc": p, "t0": time.time(), "out": b"", "err": b"",
               "sid": sid, "fmt": fmt, "seen": len(self._transcript()), "buf": b"",
               "texts": [], "live": "", "acts": [], "final": None, "new_sid": None,
               "denied": [], "error": "", "prompt": prompt, "sent": 1, "steers": {}, "rid": 0,
               "turn": None, "turn_done": False, "in_closed": False, "inj_n": {}, "agy_q": [],
               "prod": prod_now}
        self._snap_start()
        self._running[key] = cur
        p.readyReadStandardOutput.connect(lambda k=key: self._on_out(k))
        p.readyReadStandardError.connect(lambda k=key: self._on_err(k))
        p.finished.connect(lambda code, _s, k=key: self._on_finished(k, code))
        p.errorOccurred.connect(lambda e, k=key: self._on_error(k, e))
        p.start(args[0], args[1:])
        cur["live_in"] = fmt == "cxs" or ("--input-format" in args and "stream-json" in args)
        cur["pending_inj"] = []
        cur["results"] = []
        if fmt == "cxs":
            self._rpc(cur, "initialize", {"clientInfo": {"name": "sacmalik", "version": "1"}})
        elif stdin is not None:
            p.write(stdin.encode())
        if not cur["live_in"]:
            self._close_in(cur)

        # zaman aşımı yalnızca kullanıcı bir süre verdiyse (varsayılan 0 = sınırsız)
        cur["timer"] = None
        limit = int(a.get("timeout") or 0)
        if limit > 0:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda pp=p: pp.state() != QProcess.NotRunning and pp.kill())
            t.start(limit * 1000)
            cur["timer"] = t

    def _close_in(self, cur):
        if not cur["in_closed"]:
            cur["in_closed"] = True
            cur["proc"].closeWriteChannel()

    def _rpc(self, cur, method, params=None, notify=False):
        m = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            m["params"] = params
        if not notify:
            cur["rid"] += 1
            m["id"] = cur["rid"]
        cur["proc"].write((json.dumps(m, ensure_ascii=False) + "\n").encode())
        return m.get("id")

    def _file(self, cur, path):
        """Ajanın yazdığı/ürettiği dosya: resim, html, pdf ise sohbette gösterilecek."""
        if isinstance(path, str) and path:
            full = path if os.path.isabs(path) else os.path.join(self._workdir(), path)
            cur.setdefault("wrote", set()).add(os.path.normpath(full))
        if isinstance(path, str) and path.lower().rsplit(".", 1)[-1] in MEDIA_EXT:
            full = path if os.path.isabs(path) else os.path.join(self._workdir(), path)
            if full not in cur.setdefault("files", []):
                cur["files"].append(full)

    def _media(self, cur, text):
        """Mesajda anılan ya da ajanın yazdığı, diskte gerçekten var olan medya dosyaları."""
        found = []
        links = [x for x in LINK_RE.findall(text or "") if x.lower().rsplit(".", 1)[-1] in MEDIA_EXT]
        for raw in links + PATH_RE.findall(LINK_RE.sub("", text or "")):
            path = os.path.expanduser(raw.replace("%20", " "))
            found.append(path if os.path.isabs(path) else os.path.normpath(os.path.join(self._workdir(), path)))
        out = []
        for f in found + cur.get("files", []):
            if f not in out and os.path.isfile(f):
                out.append(f)
        return out[:12]

    def _attach_media(self, cur, mid, text):
        media = self._media(cur, text)
        # mesajın içine kod olarak yazılmış SVG: gösterim için dosyaya çıkar
        for i, svg in enumerate(re.findall(r"<svg\b[\s\S]*?</svg>", text or "", re.I)[:4]):
            try:
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                f = MEDIA_DIR / f"{mid}-{i}.svg"
                f.write_text(svg, encoding="utf-8")
                media.append(str(f))
            except OSError:
                pass
        if media:
            self._chat["messages"][-1]["media"] = media
            self.messageMedia.emit(mid, "\n".join(media))
            for f in media:
                # ajanın gösterdiği dosya: araçla ya da komutla üretmiş olabilir (ses, video çoğu zaman komutla)
                if not f.startswith((str(MEDIA_DIR), str(ATTACH_DIR))) and f not in (self._chat.get("files") or {}):
                    self._note_file(f, cur["agent"]["name"], "yeni")
        cur["files"] = []

    def _watch_cmds(self):
        """Antigravity'nin komutlarında zaman aşımı yok (~5 dk sonra kendisi bırakıyor): pencere açan ya da
        hiç bitmeyen bir komut ajanı ve odayı kilitler. Süreyi aşan komutu (ajanı değil) durdur;
        ajan hatayı görüp devam eder. Claude ve Codex'in kendi komut zaman aşımları var."""
        limit = int(self._s.get("cmdTimeout") or 0)
        if limit <= 0 or not self._running:
            return
        import psutil
        now = time.time()
        for cur in list(self._running.values()):
            if cur.get("fmt") != "agy":
                continue
            try:
                root = psutil.Process(cur["proc"].processId())
                cli = []
                for x in [root] + root.children(recursive=True):
                    try:
                        if os.path.basename(x.exe()) == "antigravity":   # süreç adı "exe" olabiliyor; yoluna bak
                            cli.append(x)
                    except psutil.Error:
                        pass
                if not cli:
                    continue
                main_pid = cli[0].pid            # agy'nin kendisi; MCP sunucuları onun doğrudan çocukları
                cmds = [c for r in cli[1:] for c in r.children()]
                idle = now - cur.get("last_out", cur["t0"])
                if not cmds and idle > limit and not cur.get("restart"):
                    # komut çalışmıyor ama ajan da susmuş: çoğunlukla "schedule" ile kendine bekleme kurmuş
                    # olur ve tur bitmediği için gelen mesajları okumaz. Aynı oturumla yeniden başlat.
                    cur["restart"] = "stall"
                    self._act(cur, f"⏱ {int(idle)} sn'dir yanıt yok, aynı oturumla yeniden başlatılıyor")
                    self._log("stall", id=cur["id"], agent=cur["agent"]["name"], secs=int(idle))
                    k = cur["agent"]["key"]
                    self._budget[k] = max(1, self._budget.get(k, 0))
                    self._force.add(k)
                    self._resume.add(k)
                    cur["proc"].kill()
                    continue
                for runner in cli[1:]:           # komut yürütücüsü: altındakiler ajanın çalıştırdığı komutlar
                    for c in runner.children():
                        if runner.pid != main_pid and now - c.create_time() > limit:
                            name = " ".join(c.cmdline())[:80]
                            for x in c.children(recursive=True) + [c]:
                                try:
                                    x.kill()
                                except psutil.Error:
                                    pass
                            self._act(cur, f"⏱ komut {limit} sn'yi aştı, durduruldu: {name}")
                            self._log("cmd_timeout", id=cur["id"], agent=cur["agent"]["name"], cmd=name, secs=limit)
            except psutil.Error:
                continue

    def _live_text(self, cur, text):
        """Akan cevap ekrana saniyede en çok dört kez yazılsın. Antigravity cevabı parça parça gönderiyor; her
        parçada bütün metin yeniden biçimleniyordu, uzun cevapta oda donuyordu (20.11.2026)."""
        cur["live_shown"] = text
        if not cur.get("live_due"):
            cur["live_due"] = True
            QTimer.singleShot(250, lambda c=cur: self._flush_live(c))

    def _flush_live(self, cur):
        cur["live_due"] = False
        text = cur.pop("live_shown", None)
        if text is not None and not cur.get("finished"):
            self.messageUpdated.emit(cur["id"], text)

    def _act(self, cur, line):
        cur["acts"].append(line)
        self.messageActivity.emit(cur["id"], "\n".join(cur["acts"]))

    def _on_err(self, key):
        cur = self._running.get(key)
        if cur:
            cur["err"] += bytes(cur["proc"].readAllStandardError())

    def _on_out(self, key):
        cur = self._running.get(key)
        if not cur:
            return
        data = bytes(cur["proc"].readAllStandardOutput())
        cur["out"] += data
        cur["last_out"] = time.time()
        if cur["fmt"] == "text":
            text = ANSI_RE.sub("", cur["out"].decode(errors="replace"))
            self.messageUpdated.emit(cur["id"], text.strip())
            return
        cur["buf"] += data
        *lines, cur["buf"] = cur["buf"].split(b"\n")
        for ln in lines:
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            getattr(self, "_ev_" + cur["fmt"])(cur, ev)

    # --- claude stream-json ---
    def _ev_claude(self, cur, ev):
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            cur["new_sid"] = ev.get("session_id")
        elif t == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    cur["texts"].append(c["text"].strip())
                    self.messageUpdated.emit(cur["id"], "\n\n".join(cur["texts"]))
                    if cur.pop("reply_due", False):
                        # iş sürerken araya yazılan mesaja verdiği cevap: tur sonunu beklemeden odaya düşsün,
                        # yoksa yalnızca son metin kalır ve diğerleri bu cevabı hiç görmez
                        cur["published"] = cur["texts"][-1]
                        self._publish_turn(cur, cur["texts"][-1], count=False)
                elif c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    what = (inp.get("file_path") or inp.get("path") or inp.get("command")
                            or inp.get("pattern") or inp.get("url") or inp.get("query")
                            or inp.get("description") or "")
                    if inp.get("file_path") or inp.get("path"):
                        what = self._rel(what)
                    if c.get("name") in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                        self._file(cur, inp.get("file_path") or inp.get("notebook_path"))
                    icon = {"Write": "✎", "Edit": "✎", "MultiEdit": "✎", "Read": "👁",
                            "Bash": "$", "Glob": "⌕", "Grep": "⌕"}.get(c.get("name"), "⚙")
                    self._act(cur, f"{icon} {c.get('name')}  {short(what)}")
        elif t == "user" and isinstance((ev.get("message") or {}).get("content"), str):
            # --replay-user-messages: araya yazdığımız mesajı Claude aldı
            c = ev["message"]["content"]
            # Claude art arda gelen mesajları tek mesajda birleştirebilir: içerilen her biri teslim edildi
            for line in [x for x in cur.get("pending_inj", []) if x in c]:
                cur["pending_inj"].remove(line)
                self._delivered(cur, cur["inj_n"].pop(line, cur["seen"]))
                if not line.startswith("Oda: "):
                    cur["reply_due"] = True
                self._act(cur, "↩ " + short(line, 80))
        elif t == "rate_limit_event":
            info = ev.get("rate_limit_info") or {}
            ws = []
            for k, name in (("five_hour", "5h"), ("seven_day", "week")):
                w = (info.get("unifiedWindows") or {}).get(k)
                if w and w.get("utilization") is not None:
                    full = w.get("status") == "rejected"
                    ws.append({"name": name, "used": 100 if full else round(float(w["utilization"]) * 100),
                               "resets": w.get("resetsAt")})
            if ws:
                self._quota(cur["agent"], ws)
        elif t == "result" or "result" in ev:
            cur["new_sid"] = ev.get("session_id") or cur["new_sid"]
            r = (ev.get("result") or "").strip()
            if ev.get("is_error"):
                cur["error"] = r or "hata"
            elif r and r == cur.pop("published", None):
                r = ""      # bu metin ara cevap olarak zaten odaya düştü
            for d in ev.get("permission_denials") or []:
                cur["denied"].append(d.get("tool_name", "?"))
            if cur.get("live_in") and cur.get("pending_inj") and not ev.get("is_error"):
                # süreç araya yazılan mesajlar için yeni tura geçecek: bu turun cevabı şimdi odaya düşsün
                self._publish_turn(cur, r)
            else:
                cur["final"] = r
                # araya yazılan her şey alındıysa bitir
                if cur.get("live_in"):
                    self._close_in(cur)

    # --- codex --json ---
    def _ev_codex(self, cur, ev):
        t = ev.get("type")
        it = ev.get("item") or {}
        if t == "thread.started":
            cur["new_sid"] = ev.get("thread_id")
        elif t == "item.started" and it.get("type") == "command_execution":
            cmd = it.get("command", "")
            m = re.match(r"^/bin/(?:ba)?sh -lc '(.*)'$", cmd, re.S)
            self._act(cur, "$ " + short(m.group(1) if m else cmd))
        elif t == "item.completed":
            ty = it.get("type")
            if ty == "agent_message" and it.get("text", "").strip():
                cur["texts"].append(it["text"].strip())
                self.messageUpdated.emit(cur["id"], "\n\n".join(cur["texts"]))
            elif ty == "file_change":
                for ch in it.get("changes", []):
                    self._file(cur, ch.get("path"))
                    self._act(cur, f"✎ {ch.get('kind', 'değişiklik')}  {self._rel(ch.get('path', ''))}")
            elif ty in ("mcp_tool_call", "web_search"):
                self._act(cur, f"⚙ {ty}  {short(it.get('query') or it.get('tool') or '')}")
        elif t in ("turn.failed", "error"):
            cur["error"] = short(json.dumps(ev.get("error") or ev.get("message") or ev, ensure_ascii=False), 400)

    # --- codex app-server (JSON-RPC) ---
    def _cx_thread_params(self, cur):
        a = cur["agent"]
        args = shlex.split(a["command"])
        sandbox = "workspace-write"
        for j, x in enumerate(args):
            if x in ("-s", "--sandbox") and j + 1 < len(args):
                sandbox = args[j + 1]
        cwd = self._workdir()
        if self._jailed():
            # kutunun içinde: korumayı bubblewrap yapıyor; Codex'in kendi sandbox'ı iç içe açılamıyor
            sandbox = "danger-full-access"
        elif not self._s.get("production", True):
            # kutu yok: çalışma klasörü taslak/ — Codex yalnızca orayı yazabilir, projeyi okuyabilir
            sandbox, cwd = "workspace-write", self._drafts()
        return {"cwd": cwd, "sandbox": sandbox, "approvalPolicy": "never"}

    def _cx_policy(self, prm):
        sb = prm["sandbox"]
        if sb == "read-only":
            return {"type": "readOnly"}
        if sb == "danger-full-access":
            return {"type": "dangerFullAccess"}
        pol = {"type": "workspaceWrite"}
        if self._s.get("production", True):
            # Codex'in korumasında ağ varsayılan kapalı; aynı filtre ekran sunucusuna (Wayland/X) bağlanmayı da
            # kesiyor. Üretimde diğerleri gibi internete çıkabilsin, pencere açabilsin; yazma sınırı yine geçerli.
            pol["networkAccess"] = True
        if not self._s.get("production", True) and prm["cwd"].startswith("/tmp"):
            pol.update(excludeSlashTmp=True, excludeTmpdirEnvVar=True)   # /tmp'deki proje korunsun
        return pol

    def _cx_turn(self, cur):
        a = cur["agent"]
        tp = self._cx_thread_params(cur)
        # sürdürülen konuşmada da güncel mod geçerli olsun
        prm = {"threadId": cur["new_sid"], "input": [{"type": "text", "text": cur["prompt"]}],
               "cwd": tp["cwd"], "sandboxPolicy": self._cx_policy(tp)}
        if a.get("model"):
            prm["model"] = a["model"]
        if a.get("effort"):
            prm["effort"] = a["effort"]
        cur["turn_rid"] = self._rpc(cur, "turn/start", prm)

    def _ev_cxs(self, cur, j):
        rid, res, err, m = j.get("id"), j.get("result"), j.get("error"), j.get("method")
        if rid is not None and m:
            # sunucudan istek (onay vb.) — onay politikası "never", gelirse reddet
            cur["proc"].write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32601, "message": "desteklenmiyor"}}) + "\n").encode())
            return
        if rid is not None:
            if rid == 1:
                self._rpc(cur, "initialized", notify=True)
                prm = self._cx_thread_params(cur)
                if cur["sid"]:
                    cur["thread_rid"] = self._rpc(cur, "thread/resume", dict(prm, threadId=cur["sid"]))
                else:
                    cur["thread_rid"] = self._rpc(cur, "thread/start", prm)
            elif rid == cur.get("thread_rid"):
                if err:
                    if cur["sid"]:
                        # oturum açılamadı: dökümle temiz başla
                        cur["sid"] = None
                        cur["prompt"] = self._prompt_for(cur["agent"], False)
                        cur["thread_rid"] = self._rpc(cur, "thread/start", self._cx_thread_params(cur))
                    else:
                        cur["error"] = short(err.get("message", str(err)), 400)
                        self._close_in(cur)
                    return
                cur["new_sid"] = res["thread"]["id"]
                self._cx_turn(cur)
            elif rid == cur.get("turn_rid"):
                if err:
                    cur["error"] = short(err.get("message", str(err)), 400)
                    self._close_in(cur)
                else:
                    cur["turn"] = res["turn"]["id"]
            elif rid in cur["steers"]:
                line, n = cur["steers"].pop(rid)
                if not err:          # hata: tur bitmişti; mesajı bir sonraki çağrıda alır
                    self._delivered(cur, n)
                    self._act(cur, "↩ " + short(line, 80))
            return
        prm = j.get("params") or {}
        it = prm.get("item") or {}
        ty = it.get("type")
        if m == "item/started" and ty == "commandExecution":
            cmd = it.get("command", "")
            mm = re.match(r"^/bin/(?:ba)?sh -lc '(.*)'$", cmd, re.S)
            self._act(cur, "$ " + short(mm.group(1) if mm else cmd))
        elif m == "item/completed":
            if ty == "agentMessage" and (it.get("text") or "").strip():
                cur["texts"].append(it["text"].strip())
                if it.get("phase") == "final_answer":
                    cur["results"].append(it["text"].strip())
                self.messageUpdated.emit(cur["id"], "\n\n".join(cur["texts"]))
            elif ty == "fileChange":
                for ch in it.get("changes") or []:
                    kind = ch.get("kind")
                    kind = kind.get("type") if isinstance(kind, dict) else kind
                    self._file(cur, ch.get("path"))
                    self._act(cur, f"✎ {kind or 'değişiklik'}  {self._rel(ch.get('path', ''))}")
            elif ty == "mcpToolCall":
                self._act(cur, f"⚙ {it.get('server')}.{it.get('tool')}")
            elif ty == "webSearch":
                self._act(cur, f"⌕ {short(it.get('query') or '')}")
            elif ty == "imageGeneration" and it.get("savedPath"):
                self._file(cur, it["savedPath"])
                self._act(cur, f"🖼 resim üretti  {self._rel(it['savedPath'])}")
        elif m == "account/rateLimits/updated":
            lim, ws = prm.get("rateLimits") or {}, []
            for k in ("primary", "secondary"):
                w = lim.get(k)
                if w and w.get("usedPercent") is not None:
                    mins = w.get("windowDurationMins") or 0
                    ws.append({"name": {300: "5h", 10080: "week"}.get(mins, f"{mins // 60}h"),
                               "used": round(w["usedPercent"]), "resets": w.get("resetsAt")})
            if ws:
                self._quota(cur["agent"], ws)
        elif m == "error" and not prm.get("willRetry"):
            cur["error"] = short((prm.get("error") or {}).get("message", ""), 400)
        elif m == "turn/completed":
            t = prm.get("turn") or {}
            if t.get("status") == "failed":
                cur["error"] = short(((t.get("error") or {}).get("message")) or "tur başarısız", 400)
            cur["turn_done"] = True
            self._close_in(cur)
            QTimer.singleShot(3000, lambda c=cur: self._reap(c))

    @staticmethod
    def _reap(cur):
        """Tur bittiği halde kapanmayan sunucuyu sonlandır."""
        if not cur.get("finished"):
            cur["proc"].kill()

    # --- antigravity stream-json ---
    # --- API ajanı (api_ajan.py) ---
    def _ev_api(self, cur, ev):
        t = ev.get("t")
        if t == "session":
            cur["new_sid"] = ev.get("id")
            if ev.get("model") and ev["model"] != cur["agent"].get("model"):
                self._act(cur, "◇ model: " + ev["model"])
        elif t == "step":
            name, _, rest = (ev.get("text") or "").partition(" ")
            try:
                args = json.loads(rest) if rest else {}
            except ValueError:
                args = {}
            shown = args.get("path") or args.get("command") or args.get("pattern") or rest
            icon = {"write_file": "✎", "edit_file": "✎", "read_file": "📖", "run": "⚙", "list_dir": "📂", "search": "🔍"}.get(name, "•")
            self._act(cur, f"{icon} {name}  {short(shown, 140)}")
            if name in ("write_file", "edit_file") and args.get("path"):
                self._file(cur, args["path"])
        elif t == "text" and ev.get("text"):
            cur["texts"].append(ev["text"])
        elif t == "result":
            cur["final"] = ev.get("text") or ""
        elif t == "error":
            cur["error"] = ev.get("text") or "hata"

    def _ev_agy(self, cur, ev):
        e = ev.get("event")
        if e == "init":
            cur["new_sid"] = ev.get("conversation_id")
        elif e == "step_update":
            st = ev.get("step_update") or {}
            if st.get("step_type") == "tool" and st.get("state") == "ACTIVE":
                prm = (st.get("tool_info") or {}).get("parameters") or {}
                what = next((v for k, v in prm.items() if isinstance(v, str) and k in
                             ("Path", "TargetFile", "AbsolutePath", "CommandLine", "Command",
                              "Query", "Url", "SearchPath", "DirectoryPath")), "")
                if what.startswith("/"):
                    what = self._rel(what)
                tool = (st.get("tool_name") or "").lower()
                if "write" in tool or "edit" in tool or "image" in tool or "replace" in tool:
                    for v in prm.values():
                        self._file(cur, v)
                self._act(cur, f"⚙ {st.get('tool_name')}  {short(what)}")
            elif st.get("step_type") == "user_input" and st.get("state") == "DONE" and cur.get("turns"):
                if cur["agy_q"]:
                    self._delivered(cur, cur["agy_q"].pop(0))
                self._act(cur, "↩ yeni mesajı aldı")
            elif st.get("step_type") == "agent_response" and st.get("text_delta"):
                cur["live"] += st["text_delta"]
                self._live_text(cur, cur["live"].strip())
        elif e == "result":
            r = ev.get("result") or {}
            cur["new_sid"] = r.get("conversation_id") or cur["new_sid"]
            resp = (r.get("response") or "").strip()
            if r.get("status") not in (None, "SUCCESS"):
                why = str(r.get("error") or r.get("status"))
                # agy, oturumda bir kez yaşanmış hatayı (ör. bağlantı kopması) sonraki her turda yeniden
                # bildiriyor; aynı oturumda zaten bildirilmiş hata cevapla birlikte gelirse yok sayılır
                seen = self._chat.setdefault("agyErrors", {})
                sid = cur["new_sid"] or cur["sid"] or ""
                if not (resp and seen.get(sid) == why):
                    cur["error"] = why
                seen[sid] = why
            for d in r.get("denied_actions") or []:
                cur["denied"].append(d.get("display_name") or d.get("action") or "?")
            cur["turns"] = cur.get("turns", 0) + 1
            if cur["turns"] >= cur["sent"]:
                cur["final"] = resp
                self._close_in(cur)     # araya yazılanların hepsi işlendi
            elif not cur["error"]:
                # sırada araya yazılmış mesaj var: bu turun cevabı şimdi odaya düşsün
                self._publish_turn(cur, resp)

    SNAP_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", "dist", "build", ".mypy_cache"}

    def _scan(self):
        """Proje dosyalarının (yol -> değişiklik zamanı, boyut) fotoğrafı; çok büyük projede vazgeçer."""
        root, out = self._workdir(), {}
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in self.SNAP_SKIP and not x.startswith(".")]
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out[os.path.relpath(p, root)] = (st.st_mtime_ns, st.st_size)
                if len(out) > 20000:
                    return None
        return out

    def _snap_start(self):
        """İlk ajan başlarken projenin fotoğrafını çek (karşılaştırma noktası). Tartışma'da da: ajanlar taslak/
        klasörüne resim, ses, video üretir; panel onları da göstersin (19.11.2026)."""
        if getattr(self, "_snap", None) is None:
            self._snap = self._scan()
            self._snap_wd = self._workdir()

    def _report_changes(self, cur):
        """Bir ajanın turu bitince projede neyin değiştiğini odaya bilgi olarak düş: diğerleri eski
        hâlin üstüne yazmasın diye. Kim yazdı belli değilse (aynı anda başkası da çalışıyorsa) öyle söylenir."""
        old = getattr(self, "_snap", None)
        if old is None or self._snap_wd != self._workdir():
            self._snap = None
            self._writers = {}
            return
        new = self._scan()
        self._snap = new
        if new is None:
            return
        added = [p for p in new if p not in old]
        changed = [p for p in new if p in old and new[p] != old[p]]
        removed = [p for p in old if p not in new]
        if not (added or changed or removed):
            return
        wd = self._workdir()
        # kim yazdı: ajanların dosya araçlarından bildiğimiz yollar (komutla yazılanlar bilinmez)
        writers = {}      # yol -> o aralıkta dosya aracıyla yazan ajanlar (sırayla)
        for c in [cur] + [c for c in self._running.values() if c is not cur]:
            for p in c.get("wrote", ()):
                ns = writers.setdefault(os.path.relpath(p, wd), [])
                if c["agent"]["name"] not in ns:
                    ns.append(c["agent"]["name"])
        owners = {p: ns[0] for p, ns in writers.items()}
        cur["wrote"] = set()
        others = [c["agent"]["name"] for c in self._running.values() if c is not cur]
        everything = set(added) | set(changed) | set(removed)
        for c in self._running.values():
            c["wrote"] = {p for p in c.get("wrote", ()) if os.path.relpath(p, wd) not in everything}

        def who(p):
            if p in owners:
                return owners[p]
            # aracı bilinmiyorsa: tek çalışan bu ajansa odur, değilse belirsiz
            return cur["agent"]["name"] if not others else "?"

        def fmt(paths):
            paths = sorted(paths)
            s = ", ".join(f"`{p}` ({who(p)})" for p in paths[:8])
            return s + (f" ve {len(paths) - 8} dosya daha" if len(paths) > 8 else "")
        parts = []
        for label, ps in (("yeni", added), ("değişti", changed), ("silindi", removed)):
            if ps:
                parts.append(f"{label}: {fmt(ps)}")
            for p in ps:
                self._note_file(os.path.normpath(os.path.join(wd, p)), who(p), label)
        text = "📝 Projede " + "; ".join(parts)

        # aynı dosyaya kısa aralıkla birden fazla ajan yazdıysa görünür olsun (engellemez, yalnızca bildirir)
        now, hist, clash = time.time(), self.__dict__.setdefault("_writers", {}), []
        for p in sorted(everything):
            names = writers.get(p) or ([who(p)] if who(p) != "?" else [])
            if not names:
                continue
            prev = hist.get(p)
            seq = ([prev[0]] if prev and now - prev[1] <= CLASH_SECS and prev[0] not in names else []) + names
            if len(seq) > 1:
                clash.append(f"`{p}` ({', '.join(seq)})")
            hist[p] = (names[-1], now)
        if clash:
            text += ("\n⚠ Aynı dosyaya kısa aralıkla birden fazla ajan yazdı: " + ", ".join(clash[:6])
                     + (f" ve {len(clash) - 6} dosya daha" if len(clash) > 6 else ""))
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, text, True, 0, emit=True)

    # ================= kota =================
    MAIN_WINDOWS = ("5h", "week")     # aboneliğin asıl pencereleri; "week:Fable" gibi alt pencereler ipucunda

    def _quota(self, a, windows, fresh=False):
        """CLI'ın bildirdiği kota pencereleri. Asıl pencerelerden biri dolduysa odaya bir kez yazılır: herkes görür.
        fresh: /usage raporunun tamamı, eskisinin yerine geçer; tur olayları ise yalnızca kendi pencerelerini günceller."""
        key = kind_of(a)
        mine = {} if fresh else dict(self._kota.get(key) or {})
        for w in windows:
            mine[w["name"]] = w
        self._kota[key] = mine
        self.quotaChanged.emit()
        for w in windows:
            if w["name"] not in self.MAIN_WINDOWS:
                continue
            if w.get("used", 0) >= 100:
                self._quota_full(a, w)
            else:     # açıldı: bir sonraki dolum yine yazılsın
                self._kota_told = {t for t in self._kota_told if not (t[0] == key and t[1] in (w["name"], None))}

    # --- model çağırmadan kota okuma (Ekip'teki yöntem) ---
    CLAUDE_LINE = re.compile(r"^Current (session|week \(([^)]+)\)):\s*(\d+)% used(?:\s*·\s*resets (.+))?$")
    MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}

    @classmethod
    def _claude_reset(cls, text):
        """"Nov 24, 4pm (Europe/Istanbul)" → Unix zamanı (yerel saat); okunamazsa None."""
        m = re.match(r"([A-Za-z]{3})\w*\s+(\d+),?\s+(\d+)(?::(\d+))?\s*(am|pm)", text or "", re.I)
        if not m:
            return None
        mon, day, hh, mm, ap = m.groups()
        h = int(hh) % 12 + (12 if ap.lower() == "pm" else 0)
        now = time.localtime()
        try:
            t = time.mktime((now.tm_year, cls.MONTHS[mon.lower()], int(day), h, int(mm or 0), 0, 0, 0, -1))
        except (KeyError, OverflowError, ValueError):
            return None
        return t + (365 * 86400 if t < time.time() - 30 * 86400 else 0)    # yıl dönümü

    @classmethod
    def _parse_claude_usage(cls, text):
        out = []
        for line in (text or "").splitlines():
            m = cls.CLAUDE_LINE.match(line.strip())
            if m:
                which, model, used, resets = m.groups()
                name = "5h" if which == "session" else "week" if model == "all models" else f"week:{model}"
                out.append({"name": name, "used": int(used), "resets": cls._claude_reset(resets)})
        return out

    @staticmethod
    def _parse_agy_usage(data):
        from datetime import datetime
        tags = {"Gemini Models": "", "Claude and GPT models": "Claude/GPT", "Gemini 4 Argon": "Argon"}
        out = []
        for g in (((data or {}).get("command") or {}).get("data") or {}).get("groups") or []:
            tag = tags.get(g.get("name"), g.get("name") or "?")
            for b in g.get("buckets") or []:
                win = {"weekly": "week", "5h": "5h"}.get(b.get("window"))
                if not win or b.get("remaining_fraction") is None:
                    continue
                try:
                    r = datetime.fromisoformat(b["reset_time"].replace("Z", "+00:00")).timestamp() if b.get("reset_time") else None
                except ValueError:
                    r = None
                out.append({"name": win + (f":{tag}" if tag else ""), "resets": r,
                            # Antigravity kalanı aşağı yuvarlar (0,9658 → %96): aynısı görünsün
                            "used": max(0, min(100, 100 - int(float(b["remaining_fraction"]) * 100)))})
        return out

    @staticmethod
    def _parse_codex_limits(lim):
        out = []
        for k in ("primary", "secondary"):
            w = (lim or {}).get(k)
            if w and w.get("usedPercent") is not None:
                mins = w.get("windowDurationMins") or 0
                out.append({"name": {300: "5h", 10080: "week"}.get(mins, f"{mins // 60}h"),
                            "used": round(w["usedPercent"]), "resets": w.get("resetsAt")})
        if (lim or {}).get("rateLimitReachedType") and out:
            # Codex dolduğunu açıkça söylüyor: en dolu pencere dolmuş sayılır
            max(out, key=lambda w: w["used"])["used"] = 100
        return out

    @Slot()
    def refreshQuota(self):
        seen = set()
        for a in self._enabled():
            if kind_of(a) not in seen:       # aynı hesabı kullananlar için bir kez sor
                seen.add(kind_of(a))
                self._read_quota(a)

    def _read_quota(self, a):
        """Ajanın kendi CLI'ına kotayı sor; model çağrısı yok, bir şey harcanmaz. Boş bir klasörde çalışır."""
        exe = Path(shlex.split(a.get("command") or "x")[0]).name
        if exe not in ("claude", "codex", "agy", "antigravity") or not shutil.which(exe):
            return
        procs = self.__dict__.setdefault("_quota_procs", {})
        if kind_of(a) in procs:
            return
        folder = DATA_DIR / "kota"
        folder.mkdir(parents=True, exist_ok=True)
        p = QProcess(self)
        p.setWorkingDirectory(str(folder))
        procs[kind_of(a)] = p
        buf = bytearray()

        def finish(windows):
            procs.pop(kind_of(a), None)
            if windows:
                self._quota(a, windows, fresh=True)
            try:
                p.deleteLater()
            except RuntimeError:     # uygulama kapanırken nesne çoktan silinmiş
                pass

        if exe == "codex":
            def out():
                try:
                    buf.extend(bytes(p.readAllStandardOutput()))
                except RuntimeError:     # uygulama kapanırken nesne çoktan silinmiş
                    return
                *lines, rest = bytes(buf).split(b"\n")
                buf[:] = rest
                for ln in lines:
                    try:
                        j = json.loads(ln)
                    except ValueError:
                        continue
                    if j.get("id") == 2:
                        p.kill()
                        ws = self._parse_codex_limits((j.get("result") or {}).get("rateLimits"))
                        if ws:
                            self._quota(a, ws, fresh=True)
            p.readyReadStandardOutput.connect(out)
            p.finished.connect(lambda *_: finish([]))
            p.start("codex", ["app-server"])
            for m in ({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"clientInfo": {"name": "sacmalik", "version": "0.1"}}},
                      {"jsonrpc": "2.0", "method": "initialized"},
                      {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}}):
                p.write((json.dumps(m) + "\n").encode())
        else:
            def done(*_):
                try:
                    text = bytes(p.readAllStandardOutput()).decode(errors="replace")
                except RuntimeError:
                    return
                try:
                    ws = (self._parse_claude_usage(text) if exe == "claude"
                          else self._parse_agy_usage(json.loads(text or "{}")))
                except ValueError:
                    ws = []
                finish(ws)
            p.finished.connect(done)
            if exe == "claude":
                p.start("claude", ["-p", "/usage", "--setting-sources", "project"])
            else:
                p.start(exe, ["-p", "/usage", "--output-format", "json"])
        QTimer.singleShot(60000, lambda: p.state() != QProcess.NotRunning and p.kill())

    def _quota_full(self, a, w=None, why=""):
        kind = kind_of(a)
        tag = (kind, (w or {}).get("name"), (w or {}).get("resets"))
        if tag in self._kota_told or (not w and any(t[0] == kind for t in self._kota_told)):
            return
        self._kota_told.add(tag)
        names = {"5h": "5 saatlik pencere", "week": "haftalık pencere"}
        parts = []
        if w:
            parts.append(names.get(w["name"], w["name"]))
            if w.get("resets"):
                r = float(w["resets"])
                parts.append(time.strftime("%H:%M" if r - time.time() < 86400 else "%d.%m %H:%M", time.localtime(r))
                             + " civarı açılır")
        elif why:
            parts.append(short(why, 160))
        same = [x["name"] for x in self._enabled() if kind_of(x) == kind] or [a["name"]]
        who = same[0] if len(same) == 1 else ", ".join(same[:-1]) + " ve " + same[-1]
        text = (f"⛔ {who} kullanım kotası doldu" + (f" ({', '.join(parts)})" if parts else "")
                + (". Kota açılana kadar yanıt veremez." if len(same) == 1 else
                   ". Aynı hesabı kullandıkları için kota açılana kadar yanıt veremezler."))
        self._log("quota_full", agent=a["name"], window=(w or {}).get("name"), why=why)
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, text, True, 0, emit=True)
        self._save_chat()

    def _publish_turn(self, cur, text, count=True):
        """Açık kalan süreçte bir tur bitti: cevabı odaya koy, sonraki tur için yeni balon aç."""
        a, key = cur["agent"], cur["agent"]["key"]
        dt = time.time() - cur["t0"]
        text, echo_note = strip_echo(text, a["name"], [x["name"] for x in self._s["agents"]] + [self._s["userName"]])
        if text:
            self._append_msg(cur["id"], key, a["name"], a["color"], text, True, dt, acts=cur["acts"])
            if echo_note:
                self._chat["messages"][-1]["note"] = echo_note
            self._attach_media(cur, cur["id"], text)
            self.messageUpdated.emit(cur["id"], text + (f"\n\n_⚠ {echo_note}_" if echo_note else ""))
            self.messageDone.emit(cur["id"], True, dt)
            cur.pop("live_shown", None)     # bekleyen ara görüntü yeni balona yazılmasın
            if count:
                self._calls += 1      # açık süreçteki her yeni tur da bir çağrı sayılır
            self._log("turn", id=cur["id"], agent=a["name"], secs=round(dt, 1), call=self._calls)
            cur["id"] = uuid.uuid4().hex
            self.messageAdded.emit(cur["id"], key, a["name"], a["color"], "", True, time.strftime("%H:%M"))
            if key in self._decision_agents():
                self.messageSealed.emit(cur["id"], True)
            cur["acts"], cur["t0"] = [], time.time()
        self._report_changes(cur)
        # oturum ve görülen konum şimdiden kayda geçsin
        if self._s.get("keepSessions", True) and cur["new_sid"]:
            self._chat["sessions"][key] = {"sid": cur["new_sid"]}
        self._chat.setdefault("seen", {})[key] = cur["seen"]
        cur["texts"], cur["results"], cur["live"], cur["final"] = [], [], "", None
        self._save_chat()
        self.chatsChanged.emit()

    def _on_error(self, key, err):
        cur = self._running.get(key)
        if err == QProcess.FailedToStart and cur:
            cur["err"] += b"Komut baslatilamadi. Ayarlardan yolu kontrol et."
            self._on_finished(key, -1)

    def _on_finished(self, key, code):
        cur = self._running.pop(key, None)
        if not cur:
            return
        cur["finished"] = True
        if cur["timer"]:
            cur["timer"].stop()
        cur["err"] += bytes(cur["proc"].readAllStandardError())
        if cur["buf"]:
            cur["out"] += b""
            self._on_out_tail(cur)
        dt = time.time() - cur["t0"]
        a = cur["agent"]
        err = ANSI_RE.sub("", cur["err"].decode(errors="replace")).strip()

        if cur["fmt"] == "text":
            text = ANSI_RE.sub("", cur["out"].decode(errors="replace")).strip()
            if exe_of(a) == "claude":
                cur["new_sid"] = cur["sid"] or a["_newsid"]
            elif exe_of(a) == "codex":
                m = CODEX_SID_RE.search(err)
                cur["new_sid"] = m.group(1) if m else cur["sid"]
        elif cur["fmt"] == "codex":
            text = cur["texts"][-1] if cur["texts"] else ""
        elif cur["fmt"] == "cxs":
            text = "\n\n".join(cur["results"]) or (cur["texts"][-1] if cur["texts"] else "")
            if cur["turn_done"] and not cur["error"]:
                code = 0          # tur bitti; sunucuyu biz kapattık
        elif cur["fmt"] == "agy":
            text = cur["final"] if cur["final"] is not None else cur["live"].strip()
        else:
            text = cur["final"] if cur["final"] is not None else "\n\n".join(cur["texts"])
        if cur["fmt"] == "claude" and not cur["new_sid"]:
            cur["new_sid"] = cur["sid"] or a["_newsid"]
        if cur["fmt"] in ("codex", "cxs") and not cur["new_sid"]:
            cur["new_sid"] = cur["sid"]

        stopped = self._stopped or bool(cur.get("stopped_one"))
        text, echo_note = strip_echo(text, a["name"], [x["name"] for x in self._s["agents"]] + [self._s["userName"]])
        restart = cur.get("restart") and not stopped
        if restart:
            code, cur["error"] = 0, ""        # bilerek durdurduk: hata değil
        denied = sorted(set(cur["denied"]))
        # Ajan bir şey söylediyse, süreç nasıl biterse bitsin söyledikleri odada kalır: diğerleri görür.
        spoke = bool(text)
        failed = not spoke and (bool(cur["error"]) or code != 0 or bool(denied))
        ok = spoke
        silent = not spoke and not failed and not stopped and not restart

        self._log("finish", id=cur["id"], agent=a["name"], code=code, secs=round(dt, 1),
                  result="spoke" if ok else "silent" if silent else "stopped" if stopped else "failed",
                  session=cur["new_sid"] or "", seen=cur["seen"], denied=denied, error=cur["error"],
                  stderr=err[-1500:] if not ok else "")
        if (ok or silent) and self._s.get("keepSessions", True) and cur["new_sid"]:
            self._chat["sessions"][key] = {"sid": cur["new_sid"]}
        if restart and not ok and self._s.get("keepSessions", True) and cur["new_sid"]:
            self._chat["sessions"][key] = {"sid": cur["new_sid"]}
        if ok or silent:
            self._chat.setdefault("seen", {})[key] = cur["seen"]

        if ok:
            notes = []
            if denied:
                notes.append(f"izin verilmedi: {', '.join(denied)}")
            if echo_note:
                notes.append(echo_note)
            if stopped:
                notes.append("durduruldu")
            elif code != 0 or cur["error"]:
                notes.append(f"süreç yarıda kesildi (çıkış kodu {code})")
            shown = text + (f"\n\n_⚠ {' · '.join(notes)}_" if notes else "")
            # dökümde yalnızca ajanın kendi sözü durur; uygulamanın notu ekranda kalır
            self._append_msg(cur["id"], key, a["name"], a["color"], text, True, dt, acts=cur["acts"])
            self._chat["messages"][-1]["note"] = " · ".join(notes)
            self._attach_media(cur, cur["id"], text)
            self.messageUpdated.emit(cur["id"], shown)
        elif silent:
            self.messageSilent.emit(cur["id"])
        elif restart:
            self.messageUpdated.emit(cur["id"], {
                "prod": "_↻ Üretim açıldı — yazma izniyle yeniden başlıyor_",
                "talk": "_↻ Tartışma'ya geçildi — yazma yetkisi kapatıldı, kutu içinde yeniden başlıyor_",
                "stall": "_↻ uzun süre yanıt vermedi — aynı oturumla yeniden başlatıldı_"}.get(restart, "_↻ yeniden başlıyor_"))
        else:
            if stopped:
                msg = "**■ durduruldu**"
            else:
                if cur["sid"] and not denied:
                    # oturum sürdürülemediyse bir dahakine dökümle temiz başla
                    self._chat["sessions"].pop(key, None)
                if denied:
                    msg = f"**⚠ {a['name']} şu izni istedi ama yetkisi yok: {', '.join(denied)}**"
                else:
                    tail = cur["error"] or "  \n".join(err.splitlines()[-6:])[-600:]
                    msg = f"**⚠ hata (çıkış kodu {code})**" + ("\n\n" + tail if tail else "")
            self._append_msg(cur["id"], key, a["name"], a["color"], msg, False, dt, acts=cur["acts"])
            self._budget[key] = 0     # hata veren ajan kendiliğinden yeniden başlamasın; sen yazınca tekrar dener
            self.messageUpdated.emit(cur["id"], msg)
        if ok:      # konuşabildi: kota yeniden açılmış, bir sonraki dolum yine yazılsın
            self._kota_told = {t for t in self._kota_told if t[0] != kind_of(a)}
        if not ok and not stopped and not restart:
            why = cur["error"] or err[-600:]
            if LIMIT_ERROR.search(why or ""):
                self._quota_full(a, None, why)
                QTimer.singleShot(1000, lambda a=a: self._read_quota(a))   # hangi pencere, ne zaman açılır
        if cur["fmt"] == "agy" and (ok or silent):
            QTimer.singleShot(1000, lambda a=a: self._read_quota(a))       # agy tur içinde kota bildirmez
        self.messageDone.emit(cur["id"], ok or silent or bool(restart), dt)
        self._report_changes(cur)
        if not self._running:
            self._snap = None     # oda boşaldı: senin aradaki değişikliklerin bir ajana yazılmasın
        if not ok:
            self.messageSealed.emit(cur["id"], False)     # hata, pas ya da durdurma notu saklanmaz
        self._decision_check(key, not stopped and not restart, failed)
        self._save_chat()
        self.chatsChanged.emit()
        cur["proc"].deleteLater()
        self._schedule()

    def _on_out_tail(self, cur):
        """Satır sonu olmadan biten son JSON olayını işle."""
        ln, cur["buf"] = cur["buf"], b""
        try:
            getattr(self, "_ev_" + cur["fmt"])(cur, json.loads(ln))
        except (ValueError, AttributeError):
            pass


def main():
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Saçmalık Odası")
    f = QFont("Inter")                  # kurulu değilse Qt sistem yazı tipine düşer
    f.setPixelSize(13)
    f.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(f)
    app.setDesktopFileName("tr.com.lifeos.Sacmalik")   # pencere, masaüstü dosyasının simgesini alsın
    # kurulu tema simgesi yoksa (doğrudan klasörden çalışırken) depodaki SVG
    app.setWindowIcon(QIcon.fromTheme("tr.com.lifeos.Sacmalik", QIcon(str(APP_DIR / "tr.com.lifeos.Sacmalik.svg"))))
    migrate_data()
    room = Room()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("room", room)
    engine.load(QUrl.fromLocalFile(str(APP_DIR / "qml" / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
