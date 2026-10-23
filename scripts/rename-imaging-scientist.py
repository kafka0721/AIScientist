"""One-time, backed-up source package migration (run from repository root)."""
from pathlib import Path
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"node_modules", ".next", "dist", "__pycache__", ".git", ".webui-state"}
EXT = {".py", ".toml", ".json", ".yaml", ".yml", ".md", ".ps1", ".bat", ".ts", ".tsx", ".js", ".mjs", ".css", ".svg", ".lock"}
paths = [p for p in ROOT.iterdir() if p.is_file()]
for name in ("WitAIScientist", "tests", "scripts", "webui", "docs"):
    paths.extend(p for p in (ROOT / name).rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP))
changes = {}
for p in paths:
    if p == Path(__file__).resolve() or p.suffix not in EXT:
        continue
    try:
        original = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        continue
    # Preserve real upstream URLs and provenance; do not invent renamed repos.
    urls = []
    def save_url(match):
        urls.append(match.group())
        return f"__PRESERVED_URL_{len(urls)-1}__"
    text = re.sub(r"https?://[^\s\"'<>`)]+", save_url, original)
    text = text.replace("WitAIScientistConfig", "ImagingScientistConfig")
    text = text.replace("WitAIScientist_agent", "imaging_scientist_agent")
    text = text.replace("WitAIScientist", "imaging_scientist")
    text = text.replace("WITAIScientist", "Imaging Scientist")
    for i, url in enumerate(urls):
        text = text.replace(f"__PRESERVED_URL_{i}__", url)
    if p.name == "pyproject.toml":
        text = text.replace('name = "imaging_scientist"', 'name = "imaging-scientist"')
        text = text.replace('description = "imaging_scientist:', 'description = "Imaging Scientist:')
        text = text.replace('witaiscientist = ', 'imaging-scientist = ')
        text = text.replace('witaisci = ', 'imaging-sci = ').replace('WitAISci = ', 'ImagingSci = ')
    if p.name == "uv.lock":
        text = text.replace('name = "witaiscientist"', 'name = "imaging-scientist"')
    if p.name in {"package.json", "package-lock.json"}:
        text = text.replace('@witaiscientist/webui', '@imaging-scientist/webui')
        text = text.replace('"witaiscientist-webui":', '"imaging-scientist-webui":')
    if p.suffix in {".bat", ".ps1"}:
        text = re.sub(r'(title |Write-Host "[^"\r\n]*|throw "[^"\r\n]*)imaging_scientist', lambda m: m.group().replace('imaging_scientist', 'Imaging Scientist'), text)
    if p.name in {"layout.tsx", "ProjectsHome.tsx"}:
        text = text.replace('AIScientist', 'Imaging Scientist')
    if p.name == "page.tsx":
        text = text.replace('alt="AIScientist"', 'alt="Imaging Scientist"').replace('                AIScientist', '                Imaging Scientist').replace('Connecting to AIScientist', 'Connecting to Imaging Scientist').replace('Welcome to AIScientist', 'Welcome to Imaging Scientist')
    if p.name == "stop-webui.py":
        text = text.replace('"-m witaiscientist deploy" in command', '("-m witaiscientist deploy" in command or "-m imaging_scientist deploy" in command)')
    if text != original:
        changes[p] = (original, text)

backup = ROOT / "artifacts" / "imaging-scientist-rename"
backup.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(backup / "original-sources.zip", "x", zipfile.ZIP_DEFLATED) as z:
    for p, (original, _) in changes.items():
        z.writestr(p.relative_to(ROOT).as_posix(), original.encode("utf-8"))
for p, (_, text) in changes.items():
    p.write_bytes(text.encode("utf-8"))
(ROOT / "WitAIScientist" / "WitAIScientist.py").rename(ROOT / "WitAIScientist" / "imaging_scientist.py")
print(json.dumps({"changed_files": len(changes), "backup": str(backup)}, indent=2))
