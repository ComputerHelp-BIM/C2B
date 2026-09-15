"""Optional DWG to DXF conversion.

DWG is a closed format, so C2B never reads it directly. When one of the usual converters is
installed the conversion is done for you; otherwise you are told exactly what to install or
to save the DXF by hand.

Supported, in order of preference:

* **ODA File Converter** (free, Open Design Alliance) - batch converts a folder of DWGs.
* **AutoCAD accoreconsole.exe** - ships with AutoCAD, scripted headless conversion.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

ODA_NAMES = ("ODAFileConverter", "ODAFileConverter.exe")
ODA_HINTS = [
    r"C:\Program Files\ODA",
    r"C:\Program Files (x86)\ODA",
    "/usr/bin",
    "/opt",
    "/Applications",
]
ACCORE_HINTS = [r"C:\Program Files\Autodesk"]
DXF_VERSION = "ACAD2018"


def find_oda() -> Path | None:
    for name in ODA_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    for hint in ODA_HINTS:
        root = Path(hint)
        if not root.exists():
            continue
        for name in ODA_NAMES:
            for candidate in sorted(root.glob(f"**/{name}"))[:1]:
                return candidate
    return None


def find_accoreconsole() -> Path | None:
    found = shutil.which("accoreconsole.exe") or shutil.which("accoreconsole")
    if found:
        return Path(found)
    for hint in ACCORE_HINTS:
        root = Path(hint)
        if root.exists():
            for candidate in sorted(root.glob("**/accoreconsole.exe"), reverse=True)[:1]:
                return candidate
    return None


def converter_status() -> dict[str, str | None]:
    oda, acc = find_oda(), find_accoreconsole()
    return {"oda_file_converter": str(oda) if oda else None, "accoreconsole": str(acc) if acc else None}


def convert_dwg(path: str | Path, out_dir: str | Path | None = None, timeout: int = 900) -> Path:
    """Convert one DWG to DXF and return the DXF path. Raises RuntimeError when no converter exists."""
    path = Path(path).resolve()
    out_dir = Path(out_dir).resolve() if out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (path.stem + ".dxf")

    oda = find_oda()
    if oda:
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / path.name
            shutil.copy2(path, staged)
            # ODAFileConverter <in dir> <out dir> <version> <type> <recurse> <audit> [filter]
            subprocess.run([str(oda), str(Path(tmp)), str(out_dir), DXF_VERSION, "DXF", "0", "1", "*.DWG"],
                           check=False, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        if target.exists():
            return target

    acc = find_accoreconsole()
    if acc:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "to_dxf.scr"
            script.write_text(f'_.DXFOUT\n"{target}"\nV\n2018\n16\n_.QUIT\nY\n', encoding="utf-8")
            subprocess.run([str(acc), "/i", str(path), "/s", str(script)], check=False, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if target.exists():
            return target

    raise RuntimeError(
        "No DWG converter found. Either save the drawing as DXF (AutoCAD: Save As, "
        "'AutoCAD 2018 DXF'), or install the free ODA File Converter from "
        "https://www.opendesign.com/guestfiles/oda_file_converter and run C2B again."
    )


def ensure_dxf(path: str | Path, work_dir: str | Path | None = None) -> tuple[Path, bool]:
    """Return (dxf_path, converted). A .dxf passes through untouched."""
    path = Path(path)
    if path.suffix.lower() == ".dwg":
        return convert_dwg(path, work_dir), True
    return path, False


def is_windows() -> bool:
    return platform.system().lower().startswith("win")
