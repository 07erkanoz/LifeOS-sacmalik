#!/usr/bin/env python3
"""Saçmalık Odası: API ajanı. CLI'ı olmayan bir model (Groq, Gemini, Cloudflare, OpenRouter, yerel LM Studio/Ollama,
ücretli OpenAI/Anthropic…) odaya bu süreçle katılır: dosya okur, yazar, komut çalıştırır.

Hesaplar, model seçimi, kota kilitleri, bütçe ve araçlı döngü LifeOS'un modeller katmanından gelir
(lifeos_store.modeller: Ekip'in API işçisi aynı döngüyü kullanır). Anahtarlar anahtarlıkta durur; bu süreç onları
görmez, katman kullanır. Hesap eklemek: `lifeos modeller ekle` ya da LifeOS Asistan'ın Hesaplar'ı.

Çalıştırma: python3 api_ajan.py '<json>'   →  stdout'a satır satır olay (JSON):
  {"t": "session", "id", "model"} · {"t": "step", "text"} · {"t": "text", "text"} · {"t": "usage", ...}
  {"t": "result", "text", "status"} · {"t": "error", "text"}
python3 api_ajan.py --modeller   →  kullanılabilir modeller (Ayarlar'daki seçici için)
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

for _p in (os.environ.get("LIFEOS_LIB", ""), "/usr/lib/lifeos"):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

SYSTEM = (
    "Bir sohbet odasındasın: kullanıcı ve başka yapay zekâ ajanları seninle aynı odada konuşuyor. "
    "Dosya okuyabilir, yazabilir ve komut çalıştırabilirsin (araçlar). Yalnız sana düşen işi yap; başkasının "
    "alanına giren bir şey gerekiyorsa onu yapmak yerine odada iste. İşin ya da cevabın bitince finish aracını çağır: "
    "summary alanına odaya söyleyeceğin cevabı Türkçe ve kısa yaz (yaptığını, ürettiğin dosyaların yollarını, "
    "açık kalanı). Yalnız kendi adınla konuş; oda bilgisini ya da başkalarının sözlerini tekrarlama."
)


def out(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def usable_models():
    """Ayarlar için: araç çağırabilen, hesabı olan API modelleri (abonelikli CLI'lar hariç: onlar zaten odada)."""
    from lifeos_store.modeller import hesaplar, katalog
    providers = {a.get("saglayici") for a in hesaplar.accounts()}
    rows = []
    for key, m in katalog.models().items():
        prov = katalog.provider(m["saglayici"]) or {}
        if prov.get("tur") == "cli" or m["saglayici"] not in providers or not m.get("gorunur", True):
            continue
        if "arac" not in (m.get("yetenek") or []) and prov.get("tur") != "anthropic":
            continue
        free = bool(m.get("ucretsiz")) or prov.get("tur") in ("yerel", "local") or m["saglayici"] in ("ollama", "lmstudio")
        rows.append({"value": key, "label": f"{m.get('ad') or m['id']} · {prov.get('ad') or m['saglayici']}"
                     + (" · ücretsiz" if free else " · ücretli"), "free": free, "power": m.get("guc", 0)})
    rows.sort(key=lambda r: (not r["free"], -r["power"], r["label"]))
    return rows


def choose(work_class="standart"):
    """Otomatik: LifeOS'un kuralına göre (önce yerel ve ücretsiz) araç çağırabilen ilk uygun API modeli."""
    from lifeos_store.modeller import katalog, politika
    ok, _ = politika.candidates(work_class, needs=("arac",))
    for m, _account in ok:
        prov = katalog.provider(m["saglayici"]) or {}
        if prov.get("tur") != "cli":
            return f"{m['saglayici']}/{m['id']}"
    raise RuntimeError("Kullanılabilir API modeli yok: `lifeos modeller ekle` ile bir hesap ekleyin (ör. ücretsiz Groq).")


def worker_class():
    from lifeos_store.modeller import isci
    from lifeos_store.sources import SourceError

    class OdaWorker(isci.Worker):
        """Tartışma'da yalnız taslak/ yazılabilir (CLI ajanlarındaki kutuyla aynı sınır); Üretim'de proje klasörü."""

        def __init__(self, *args, drafts=None, **kw):
            self.drafts = Path(drafts).resolve() if drafts else None
            super().__init__(*args, **kw)

        def _run_tool(self, name, args):
            if self.drafts and name in ("write_file", "edit_file"):
                target = (self.root / (args.get("path") or ".")).resolve()
                if target != self.drafts and self.drafts not in target.parents:
                    raise SourceError(f"Tartışma modu: yalnız {self.drafts}/ klasörüne yazılabilir")
            return super()._run_tool(name, args)

        def _command(self, command, timeout, allowed=None):
            if not self.drafts or not shutil.which("bwrap"):
                return super()._command(command, timeout, allowed)
            reason = self.needs_permission(command)
            if reason and not allowed and not (allowed is None and self.permission and self.permission(command, reason)):
                return f"Refused: {reason}. Do work that does not depend on it, or explain in finish."
            self.drafts.mkdir(parents=True, exist_ok=True)
            wrapped = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                       "--ro-bind", str(self.root), str(self.root), "--bind", str(self.drafts), str(self.drafts),
                       *([] if isci.NETWORK.search(command) else ["--unshare-net"]),
                       "--die-with-parent", "--chdir", str(self.root), "bash", "-lc", command]
            try:
                done = self.runner(wrapped, cwd=self.root, capture_output=True, text=True, timeout=timeout,
                                   env={**os.environ, "CI": "1", "NO_COLOR": "1"})
            except subprocess.TimeoutExpired:
                return f"exit: timeout after {timeout} s"
            text = (done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")
            return f"exit {done.returncode}\n" + isci.cut(text, isci.SPILL_HEAD, isci.SPILL_TAIL)

    return OdaWorker


def main(cfg):
    model = cfg.get("model") or "auto"
    if model == "auto":
        model = choose()
    Worker = worker_class()
    w = Worker(model, cfg["root"], system=SYSTEM, effort=cfg.get("effort") or None, session=cfg.get("session") or None,
               permission=lambda command, reason: False, drafts=cfg.get("drafts") or None,
               max_steps=int(cfg.get("steps") or 40))
    out(t="session", id=w.session, model=model)
    for kind, text, data in w.run(cfg["prompt"]):
        if kind == "step":
            out(t="step", text=text)
        elif kind == "text" and text:
            out(t="text", text=text)
        elif kind == "usage":
            out(t="usage", **{k: v for k, v in (data or {}).items() if k in ("input", "output", "dollars", "model")})
        elif kind == "result":
            summary = text or ""
            extra = []
            if data.get("open_issues"):
                extra.append("Açık kalan: " + "; ".join(map(str, data["open_issues"])))
            if data.get("question"):
                extra.append(str(data["question"]))
            out(t="result", text="\n\n".join([summary] + extra).strip(), status=data.get("status", "done"))
        elif kind == "error":
            out(t="error", text=text, kind=(data or {}).get("kind", ""))


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--modeller"]:
            print(json.dumps(usable_models(), ensure_ascii=False))
        else:
            main(json.loads(sys.argv[1]))
    except Exception as error:      # odaya okunur bir hata: "modeller katmanı yok", "hesap yok"…
        out(t="error", text=f"{type(error).__name__}: {error}" if not isinstance(error, RuntimeError) else str(error))
        sys.exit(1)
