# PyInstaller build definition. Run it through scripts/build-exe.ps1, which
# builds the interface first -- this file assumes ui/dist already exists.
#
# onedir, not onefile, for two reasons. A onefile build re-extracts the whole
# archive to a temporary directory on every launch, which shows up as a delay
# before the window appears. More importantly, a self-extracting single binary
# that then spawns PowerShell and reads WMI is close to the platonic ideal of a
# heuristic antivirus detection, and Warden is unsigned. A folder is also more
# honest: everything shipped is visible.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

# Read-only assets, laid out inside the bundle exactly as they sit in the
# repository, so warden.paths.resource_path() needs no special cases.
datas = [
    (str(ROOT / "ui" / "dist"), "ui/dist"),
    (str(ROOT / "fixtures"), "fixtures"),
]

# The sensor DLL is gitignored and legitimately absent from a clean checkout.
# The thermal collector already falls back through OHM, ACPI and throttle
# inference without it, so a missing DLL costs a tier of accuracy rather than
# the build.
vendor = ROOT / "vendor"
if vendor.is_dir():
    datas.append((str(vendor), "vendor"))

# The model runtime: ollama.exe plus pre-pulled weights, staged by
# scripts/fetch-model.ps1. Bundling it is what makes a shared build behave the
# way it behaves here -- without it the header reads "rules engine" on every
# machine that has never installed Ollama, and the product looks like the
# scripted troubleshooter it exists to replace. Conditional, so a fresh
# checkout still builds; warden/reasoner/host.py degrades to a system Ollama
# and then to the rules engine.
runtime = ROOT / "runtime"
if runtime.is_dir():
    datas.append((str(runtime), "runtime"))

# uvicorn resolves its protocol, lifespan and logging implementations by string
# at runtime; PyInstaller's static analysis cannot see through that and the
# server dies on first request without them. pywebview picks its backend the
# same way -- edgechromium is the WebView2 one, which is what Windows 11 has.
hiddenimports = [
    *collect_submodules("uvicorn"),
    "webview.platforms.edgechromium",
]

a = Analysis(
    [str(ROOT / "warden" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    # Pulled in transitively by pythonnet and matplotlib-adjacent packages, and
    # worth about 40 MB of bundle each. Nothing in Warden imports them.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Warden",
    # Taskbar, Alt-Tab and File Explorer all read this from the executable
    # rather than from anything the application draws at runtime.
    icon=str(ROOT / "assets" / "warden.ico"),
    console=False,
    disable_windowed_traceback=False,
    upx=False,  # UPX-packed binaries are themselves an antivirus heuristic.
    # Deliberately *not* uac_admin. Requiring elevation to start would make
    # Warden unrunnable on a managed laptop where the user is not an
    # administrator -- and the machines most likely to have something quietly
    # misconfigured are exactly the managed ones. It runs for everyone, reports
    # honestly which actions it cannot perform, and offers to restart itself
    # elevated at the point the user hits that wall. See warden/winenv.py.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="Warden",
)
