"""Complete display names and command examples after the package migration."""
from pathlib import Path
import re
import zipfile

root = Path(__file__).resolve().parents[1]
files = []
for name in ("imaging_scientist", "tests", "scripts", "docs", "webui/src", "webui/bin"):
    files.extend(p for p in (root / name).rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".ps1", ".tsx", ".ts", ".mjs", ".html"})
files.extend(root / n for n in ("README.md", "README.zh-CN.md", "onboard.bat"))
with zipfile.ZipFile(root / "artifacts/imaging-scientist-rename/display-originals.zip", "x", zipfile.ZIP_DEFLATED) as backup:
    for p in files:
        if p.name in {"rename-imaging-scientist.py", "finalize-imaging-name.py"}:
            continue
        old = p.read_bytes().decode("utf-8")
        new = re.sub(r"\bWitAISci\b", "ImagingSci", old)
        new = re.sub(r"(?<![-/\w])witaisci(?=[\s'\"`])", "imaging-sci", new)
        # Human-facing headings; package paths and identifiers retain underscores.
        for a, b in [("imaging_scientist Configuration", "Imaging Scientist Configuration"), ("imaging_scientist Agent", "Imaging Scientist Agent"), ("imaging_scientist sessions DB", "Imaging Scientist sessions DB"), ("imaging_scientist {_pkg_version", "Imaging Scientist {_pkg_version")]:
            new = new.replace(a, b)
        if p.suffix == ".md":
            new = re.sub(r"^(#+ )imaging_scientist\b", r"\1Imaging Scientist", new, flags=re.M)
        if p.suffix == ".tsx" and p.name not in {"page.tsx", "ActionGroup.test.tsx"}:
            new = new.replace("AIScientist", "Imaging Scientist")
        if p.name == "ProjectsHome.test.tsx":
            # These negative assertions refer to the previous branding.
            new = new.replace('queryByText("Imaging Scientist")', 'queryByText("WITAIScientist")')
        if p.name == "onboard.bat":
            new = new.replace("uv run ImagingSci onboard", '".venv\\Scripts\\python.exe" -m imaging_scientist onboard')
        if new != old:
            backup.writestr(p.relative_to(root).as_posix(), old.encode("utf-8"))
            p.write_bytes(new.encode("utf-8"))
print("Updated display names and command examples.")
