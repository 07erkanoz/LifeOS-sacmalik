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
import uuid
from pathlib import Path

from PySide6.QtCore import (QObject, QProcess, QProcessEnvironment, Property, Signal, Slot,
                            QTimer, QUrl)
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QTextDocument
from PySide6.QtQml import QQmlApplicationEngine

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "sacmalik"
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
# kota dolunca CLI'ların yazdığı hata (Ekip'teki desen)
LIMIT_ERROR = re.compile(r"rate.?limit|usage limit|quota|limit reached|hit your limit|resource.?exhausted|\b429\b|kota", re.I)
HEADER_VER = 6      # oda bilgisi değişince sürmekte olan oturumlara da bir kez gönderilir
# sohbette gösterilecek ajan çıktıları: resimler önizlenir, diğerleri tıklayınca açılır
MEDIA_EXT = ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif",
             "mp4", "webm", "mov", "mkv", "ogv", "mp3", "wav", "ogg", "html", "htm", "pdf")
LINK_RE = re.compile(r"\]\((?:file://)?([^)\n]+)\)")       # markdown bağlantısı: [ad](yol)
PATH_RE = re.compile(r"(?:file://)?((?:~|\.{1,2})?/?[\w\-./~%]+\.(?:" + "|".join(MEDIA_EXT) + r"))\b", re.I)
# Tartışma modunda Antigravity'nin çalıştırabileceği okuma komutları
READ_CMDS = ["ls", "cat", "head", "tail", "find", "grep", "rg", "wc", "tree", "pwd", "file", "stat",
             "git status", "git log", "git diff", "git show"]

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
    "maxChars": 60000, "maxCalls": 12, "cmdTimeout": 180, "pact": True, "liveRelay": True,
    "theme": "dark",
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
        base = {a["key"]: a for a in DEFAULTS["agents"]}
        for a in data["agents"]:
            for k, v in base.get(a.get("key"), DEFAULTS["agents"][0]).items():
                a.setdefault(k, v if k not in ("model", "effort", "allowRules") else "")
    except (OSError, ValueError):
        pass
    return data


def exe_of(agent):
    parts = shlex.split(agent.get("command") or "")
    return os.path.basename(parts[0]) if parts else ""


def new_chat(workdir):
    return {"id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
            "title": "", "created": time.time(), "updated": time.time(),
            "workDir": workdir, "messages": [], "sessions": {}, "seen": {}}


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
    quotaChanged = Signal()                                 # ajanların 5 saatlik ve haftalık kota doluluğu
    roomReset = Signal()
    busyChanged = Signal()
    settingsChanged = Signal()
    speakingChanged = Signal()
    chatsChanged = Signal()
    statusText = Signal(str)
    testResult = Signal(str, bool, str)                     # key, ok, output
    modelsReady = Signal(str, "QVariantList", "QVariantList")  # key, models, efforts

    def __init__(self):
        super().__init__()
        self._s = load_settings()
        self._chat = new_chat(self._s["workDir"])
        self._running = {}             # key -> çalışan çağrı
        self._budget = {}              # key -> kalan söz hakkı
        self._force = set()            # yeni mesaj olmasa da söz verilenler
        self._rr = 0                   # sıralı modda adalet için başlangıç noktası
        self._stopped = False
        self._calls = 0                # son kullanıcı hamlesinden beri başlatılan model çağrısı
        self._capped = False
        self._talk_mode()              # her yeni sohbet Tartışma ile açılır
        self._resume = set()           # bilerek durdurulup yeniden başlatılacaklar (çağrı sınırına takılmaz)
        self._snap = None              # Üretimde proje dosyalarının son fotoğrafı
        self._snap_wd = ""
        self._watch = QTimer(self)     # takılan ajan komutlarının bekçisi
        self._watch.timeout.connect(self._watch_cmds)
        self._watch.start(10000)
        self._kota = {}          # key -> {pencere: {name, used, resets}}
        self._kota_told = set()  # (key, pencere, sıfırlanma): aynı dolum için bir kez yazılır
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
        """CLI'ların bildirdiği kota pencereleri: {key: [{name, used, resets}]}; used yüzde, resets Unix zamanı."""
        return {k: list(v.values()) for k, v in self._kota.items()}

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
                        "updated": c.get("updated", 0),
                        "count": len(c.get("messages", []))})
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    @Property("QVariant", notify=settingsChanged)
    def settings(self):
        s = json.loads(json.dumps(self._s))
        for a in s["agents"]:
            exe = shlex.split(a["command"])[0] if a["command"].strip() else ""
            a["found"] = bool(exe and shutil.which(exe))
        return s

    @Slot("QVariant")
    def saveSettings(self, s):
        s = s.toVariant() if hasattr(s, "toVariant") else s
        clean = {k: s.get(k, DEFAULTS[k]) for k in DEFAULTS}
        clean["agents"] = [{k: a.get(k) for k in DEFAULTS["agents"][0]} for a in s["agents"]]
        clean["autoRounds"] = int(clean["autoRounds"])
        clean["maxChars"] = int(clean["maxChars"])
        clean["maxCalls"] = max(0, int(clean.get("maxCalls") or 0))
        clean["cmdTimeout"] = max(0, int(clean.get("cmdTimeout") or 0))
        clean["fontScale"] = min(1.6, max(0.8, round(float(clean.get("fontScale") or 1.0), 2)))
        for k in ("keepSessions", "autoMode", "parallel", "production", "liveRelay"):
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

    @Slot()
    def resetSettings(self):
        self.saveSettings(json.loads(json.dumps(DEFAULTS)))

    # ================= sohbetler =================
    @Slot()
    def newChat(self):
        self.stop()
        self._chat = new_chat(self._s["workDir"])
        self._talk_mode()
        self.roomReset.emit()
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
        self.roomReset.emit()
        for m in c["messages"]:
            mid = uuid.uuid4().hex
            shown = m["text"] + (f"\n\n_⚠ {m['note']}_" if m.get("note") else "")
            self.messageAdded.emit(mid, m["key"], m["name"], m["color"], shown, False, m.get("time", ""))
            if m.get("acts"):
                self.messageActivity.emit(mid, "\n".join(m["acts"]))
            if m.get("media"):
                self.messageMedia.emit(mid, "\n".join(f for f in m["media"] if os.path.isfile(f)))
            self.messageDone.emit(mid, m.get("ok", True), m.get("secs", 0))
        self.chatsChanged.emit()
        self.statusText.emit(f"Sohbet açıldı · {c.get('workDir') or self._s['workDir']}")

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
        return [m for m in self._chat["messages"] if m.get("ok", True)]

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
        return any(m["name"] != a["name"] and m["key"] != "system"
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
                if k not in self._force and not self._has_unseen(a):
                    continue
                cap = int(self._s.get("maxCalls") or 0)
                if cap > 0 and self._calls >= cap and k not in self._resume:   # yarıda kesileni sınır engellemez
                    if not self._capped:
                        self._log("cap", calls=self._calls)
                    self._capped = True
                    break
                self._calls += 1
                self._force.discard(k)
                self._resume.discard(k)
                self._budget[k] -= 1
                if limit == 1:
                    self._rr = (self._rr + j + 1) % n
                self._start(a)
        self.busyChanged.emit()
        self.speakingChanged.emit()
        if not self._running:
            if self._capped:
                self.statusText.emit(f"Çağrı sınırı doldu ({self._calls}) — sıra sende")
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
        if not a:
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
        return [a["key"] for a in self._enabled()
                if "@" + a["key"].lower() in low or "@" + a["name"].lower() in low]

    def _post_pact(self, kind):
        """Oda anlaşmasını sohbette bir kez göster: Tartışma'da ilk mesajla, Üretim ilk açılınca."""
        done = self._chat.setdefault("pact", [])
        if not self._s.get("pact", True) or kind in done:
            return
        if kind == "prod" and "talk" not in done:
            text, done[:] = PACT_TALK + " " + PACT_PROD, ["talk", "prod"]
        else:
            text = PACT_TALK if kind == "talk" else PACT_PROD
            done.append(kind)
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, "🤝 Oda anlaşması: " + text, True, 0, emit=True)

    def _append_msg(self, mid, key, name, color, text, ok, secs, emit=False, acts=None):
        t = time.strftime("%H:%M")
        m = {"id": mid, "key": key, "name": name, "color": color, "text": text,
             "ok": ok, "secs": round(secs, 1), "time": t}
        if acts:
            m["acts"] = acts
        self._chat["messages"].append(m)
        self._log("message", id=mid, author=name, key=key, ok=ok, secs=round(secs, 1), text=text,
                  acts=acts or [])
        if emit:
            self.messageAdded.emit(mid, key, name, color, text, False, t)
        if ok:
            self._broadcast(name, text)

    def _broadcast(self, author, text):
        """Odaya yeni düşen bir mesajı, o an çalışan ve canlı girdi alan ajanlara hemen yaz."""
        line = f"{author}: {text}"
        n = len(self._transcript())
        cap = int(self._s.get("maxCalls") or 0)
        if cap > 0 and self._calls >= cap and author != self._s["userName"]:
            return     # sınır doldu: ajanlar arası canlı iletim de durur; sen yazınca kaldıkları yerden alırlar
        if not self._s.get("liveRelay", True) and author != self._s["userName"]:
            return     # canlı iletim kapalı: ajanlar birbirini sıraları gelince toplu okur (kota için); senin sözün yine anında gider
        for cur in self._running.values():
            if not cur.get("live_in") or cur.get("in_closed") or cur.get("stale") or cur["agent"]["name"] == author:
                continue
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
        people = [self._s["userName"]] + [a["name"] for a in self._enabled()]
        people = [p + " (sen)" if p == agent["name"] else p for p in people]
        mode = ("Üretim — dosya yazılabilir, komut çalıştırılabilir" if self._s.get("production")
                else f"Tartışma — proje dosyaları yalnızca okunur; komutlar çalıştırılabilir; resim, belge ve taslaklar {self._drafts()} klasörüne yazılabilir. " + self._draft_rule()
                if self._jailed_ok() else
                "Tartışma — proje dosyaları yalnızca okunur; bu makinede Tartışma kutusu kurulamadığı için dosya üretimi kullanılamıyor")
        return (f"Konum: {self._workdir()}\nOdadakiler: {', '.join(people)}\nMod: {mode}\n"
                "Ekran: Mesajda yolu geçen ya da yazılan resim (png, jpg, gif, webp, svg), video (mp4, webm, mov), "
                "ses (mp3, wav, ogg), html ve pdf dosyaları odada herkese gösterilir.")

    @staticmethod
    def _fmt(msgs):
        return "\n\n".join(f"{m['name']}: {m['text']}" for m in msgs)

    def _prompt_for(self, agent, resumed):
        """Oturum sürüyorsa yalnızca ajanın kaçırdıkları; yoksa konum + odadakiler + tüm döküm."""
        tr = self._transcript()
        if resumed:
            new = [m for m in tr[self._seen(agent["key"]):] if m["name"] != agent["name"]]
            body = self._fmt(new or tr[-1:])
            if self._chat.get("hdr", {}).get(agent["key"], 0) < HEADER_VER:
                body = self._header(agent) + "\n\n" + body     # oturum eski oda bilgisiyle açılmıştı
            return body
        body = self._fmt(tr)
        mx = int(self._s["maxChars"])
        if len(body) > mx:
            body = body[-mx:]
        return self._header(agent) + "\n\n" + body

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

    def _env(self):
        env = QProcessEnvironment.systemEnvironment()
        for k in list(env.keys()):
            if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_"):
                env.remove(k)
        env.insert("NO_COLOR", "1")
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
        if fmt == "codex" and args[1:2] == ["exec"]:
            # codex app-server: tur sürerken gelen mesajlar turn/steer ile aynı tura eklenir
            fmt, args, stdin = "cxs", [args[0], "app-server"], None
        args = pre + args

        self._chat.setdefault("hdr", {})[key] = HEADER_VER
        prod_now = bool(self._s.get("production"))
        mid = uuid.uuid4().hex
        self._log("start", id=mid, agent=a["name"], model=a.get("model") or "", effort=a.get("effort") or "",
                  production=bool(self._s.get("production")), resumed=bool(sid), session=sid or "",
                  call=self._calls, seen=len(self._transcript()), prompt=prompt, argv=args)
        self.messageAdded.emit(mid, key, a["name"], a["color"], "", True, time.strftime("%H:%M"))
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
                self.messageUpdated.emit(cur["id"], cur["live"].strip())
        elif e == "result":
            r = ev.get("result") or {}
            cur["new_sid"] = r.get("conversation_id") or cur["new_sid"]
            resp = (r.get("response") or "").strip()
            if r.get("status") not in (None, "SUCCESS"):
                cur["error"] = str(r.get("error") or r.get("status"))
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
        """Üretimde ilk ajan başlarken projenin fotoğrafını çek (karşılaştırma noktası)."""
        if self._s.get("production") and getattr(self, "_snap", None) is None:
            self._snap = self._scan()
            self._snap_wd = self._workdir()

    def _report_changes(self, cur):
        """Bir ajanın turu bitince projede neyin değiştiğini odaya bilgi olarak düş: diğerleri eski
        hâlin üstüne yazmasın diye. Kim yazdı belli değilse (aynı anda başkası da çalışıyorsa) öyle söylenir."""
        old = getattr(self, "_snap", None)
        if old is None or self._snap_wd != self._workdir():
            self._snap = None
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
        owners = {}
        for c in [cur] + [c for c in self._running.values() if c is not cur]:
            for p in c.get("wrote", ()):
                owners.setdefault(os.path.relpath(p, wd), c["agent"]["name"])
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
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR,
                         "📝 Projede " + "; ".join(parts), True, 0, emit=True)

    # ================= kota =================
    MAIN_WINDOWS = ("5h", "week")     # aboneliğin asıl pencereleri; "week:Fable" gibi alt pencereler ipucunda

    def _quota(self, a, windows, fresh=False):
        """CLI'ın bildirdiği kota pencereleri. Asıl pencerelerden biri dolduysa odaya bir kez yazılır: herkes görür.
        fresh: /usage raporunun tamamı, eskisinin yerine geçer; tur olayları ise yalnızca kendi pencerelerini günceller."""
        key = a["key"]
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
                            "used": max(0, min(100, round((1 - float(b["remaining_fraction"])) * 100)))})
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
        for a in self._enabled():
            self._read_quota(a)

    def _read_quota(self, a):
        """Ajanın kendi CLI'ına kotayı sor; model çağrısı yok, bir şey harcanmaz. Boş bir klasörde çalışır."""
        exe = Path(shlex.split(a.get("command") or "x")[0]).name
        if exe not in ("claude", "codex", "agy", "antigravity") or not shutil.which(exe):
            return
        procs = self.__dict__.setdefault("_quota_procs", {})
        if a["key"] in procs:
            return
        folder = DATA_DIR / "kota"
        folder.mkdir(parents=True, exist_ok=True)
        p = QProcess(self)
        p.setWorkingDirectory(str(folder))
        procs[a["key"]] = p
        buf = bytearray()

        def finish(windows):
            procs.pop(a["key"], None)
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
        tag = (a["key"], (w or {}).get("name"), (w or {}).get("resets"))
        if tag in self._kota_told or (not w and any(t[0] == a["key"] for t in self._kota_told)):
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
        text = (f"⛔ {a['name']} kullanım kotası doldu" + (f" ({', '.join(parts)})" if parts else "")
                + ". Kota açılana kadar yanıt veremez.")
        self._log("quota_full", agent=a["name"], window=(w or {}).get("name"), why=why)
        self._append_msg(uuid.uuid4().hex, "system", "Oda", SYSTEM_COLOR, text, True, 0, emit=True)
        self._save_chat()

    def _publish_turn(self, cur, text):
        """Açık kalan süreçte bir tur bitti: cevabı odaya koy, sonraki tur için yeni balon aç."""
        a, key = cur["agent"], cur["agent"]["key"]
        dt = time.time() - cur["t0"]
        if text:
            self._append_msg(cur["id"], key, a["name"], a["color"], text, True, dt, acts=cur["acts"])
            self._attach_media(cur, cur["id"], text)
            self.messageUpdated.emit(cur["id"], text)
            self.messageDone.emit(cur["id"], True, dt)
            self._calls += 1      # açık süreçteki her yeni tur da bir çağrı sayılır
            self._log("turn", id=cur["id"], agent=a["name"], secs=round(dt, 1), call=self._calls)
            cur["id"] = uuid.uuid4().hex
            self.messageAdded.emit(cur["id"], key, a["name"], a["color"], "", True, time.strftime("%H:%M"))
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

        stopped = self._stopped
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
            self._kota_told = {t for t in self._kota_told if t[0] != key}
        if not ok and not stopped and not restart:
            why = cur["error"] or err[-600:]
            if LIMIT_ERROR.search(why or ""):
                self._quota_full(a, None, why)
                QTimer.singleShot(1000, lambda a=a: self._read_quota(a))   # hangi pencere, ne zaman açılır
        if cur["fmt"] == "agy" and (ok or silent):
            QTimer.singleShot(1000, lambda a=a: self._read_quota(a))       # agy tur içinde kota bildirmez
        self.messageDone.emit(cur["id"], ok or silent or bool(restart), dt)
        if cur.get("prod"):
            self._report_changes(cur)
        if not self._running:
            self._snap = None     # oda boşaldı: senin aradaki değişikliklerin bir ajana yazılmasın
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
