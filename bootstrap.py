#!/usr/bin/env python3
# Кроссплатформенный установщик и запускатор.
#   python bootstrap.py           — создать venv, поставить зависимости, запустить
#   python bootstrap.py --gpu     — то же + torch с CUDA (NVIDIA)
#   python bootstrap.py --setup   — только установить, без запуска
#   python bootstrap.py --check   — только проверить файлы, без установки/запуска
#   python bootstrap.py --recreate — пересоздать venv с нуля

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
VENV = ROOT / ".venv"
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LIN = platform.system() == "Linux"

PYEXE = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
PIPEXE = VENV / ("Scripts/pip.exe" if IS_WIN else "bin/pip")
REQUIREMENTS = ROOT / "requirements.txt"

REQUIRED_FILES = [
    "main.py", "requirements.txt",
    "app/__init__.py", "app/config.py", "app/models.py",
    "app/extractor.py", "app/builder.py", "app/page_view.py",
    "app/translator.py", "app/settings_dialog.py", "app/project.py",
    "app/models_manager.py", "app/wrap_check_dialog.py",
    "app/find_replace_dialog.py", "app/text_style.py",
    "app/main_window.py", "app/main_window_files.py",
    "app/main_window_edit.py", "app/main_window_translate.py",
]

def log(msg: str) -> None:
    print(msg, flush=True)

def run(cmd, **kwargs):
    log("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=False, **kwargs)

def find_system_python() -> str:
    """Найти системный Python 3.9+ (не из venv)."""
    for name in (sys.executable, shutil.which("python3") or "",
                 shutil.which("python") or "", "py" if IS_WIN else ""):
        if not name:
            continue
        try:
            out = subprocess.run(
                [name, "-c", "import sys;print(sys.version_info.major,"
                             "sys.version_info.minor)"],
                capture_output=True, text=True, check=False,
            )
            if out.returncode == 0:
                major, minor = out.stdout.split()
                if int(major) >= 3 and int(minor) >= 9:
                    return name
        except (OSError, ValueError):
            continue
    return sys.executable

def check_files() -> bool:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    if missing:
        log("[FAIL] Отсутствуют файлы:")
        for f in missing:
            log("   - " + f)
        log("\nЗапустите `python check_all.py` для диагностики. "
            "Перезапишите указанные файлы целиком из архива проекта.")
        return False
    log(f"[OK] Все {len(REQUIRED_FILES)} файлов на месте")
    return True

def ensure_venv(recreate: bool = False) -> bool:
    if recreate and VENV.exists():
        log(f"[..] Пересоздаю venv: {VENV}")
        shutil.rmtree(VENV, ignore_errors=True)
    if PYEXE.exists():
        log(f"[OK] venv найден: {VENV}")
        return True
    log(f"[..] Создаю venv: {VENV}")
    py = find_system_python()
    if py != sys.executable:
        log(f"    Системный Python: {py}")
    result = run([py, "-m", "venv", str(VENV)])
    if result.returncode != 0 or not PYEXE.exists():
        log("[FAIL] Не удалось создать venv")
        log(f"    Попробуйте вручную: {py} -m venv .venv")
        return False
    return True

def install_requirements() -> bool:
    if not REQUIREMENTS.exists():
        log("[SKIP] requirements.txt не найден")
        return True
    log("[..] Обновляю pip")
    run([str(PIPEXE), "install", "--upgrade", "pip", "setuptools", "wheel"])
    log("[..] Устанавливаю requirements.txt")
    return run([str(PIPEXE), "install", "-r", str(REQUIREMENTS)]).returncode == 0

def install_torch_gpu() -> bool:
    log("[..] Устанавливаю torch с GPU (CUDA 12.1)")
    if IS_MAC:
        # Apple Silicon: обычный torch использует Metal через MPS
        return run([str(PIPEXE), "install", "torch"]).returncode == 0
    return run([
        str(PIPEXE), "install", "torch",
        "--index-url", "https://download.pytorch.org/whl/cu121",
    ]).returncode == 0

def install_transformers_stack() -> bool:
    log("[..] Ставлю transformers/accelerate/sentencepiece")
    return run([
        str(PIPEXE), "install",
        "transformers", "accelerate", "sentencepiece",
    ]).returncode == 0

def launch_app() -> int:
    log("[..] Запускаю приложение")
    try:
        return subprocess.run([str(PYEXE), str(ROOT / "main.py")]).returncode
    except KeyboardInterrupt:
        return 130

def print_usage() -> None:
    log(__doc__ or "python bootstrap.py [--gpu|--setup|--check|--recreate]")

def main() -> int:
    log(f"ОС: {platform.system()} {platform.release()}")
    log(f"Python: {sys.version.split()[0]} ({sys.executable})")
    log(f"Каталог проекта: {ROOT}")
    log("")

    args = set(sys.argv[1:])
    if "--help" in args or "-h" in args:
        print_usage()
        return 0

    if not check_files():
        return 1

    if "--check" in args:
        return 0

    if not ensure_venv(recreate="--recreate" in args):
        return 1

    log("\n=== Шаг 1/2: основные зависимости ===")
    if not install_requirements():
        log("[WARN] Установка requirements завершилась с ошибками")

    log("\n=== Шаг 2/2: нейросетевой стек ===")
    if "--gpu" in args:
        install_torch_gpu()
    else:
        log("[SKIP] torch/CUDA не устанавливаю. "
            "Для GPU запустите: python bootstrap.py --gpu")
    install_transformers_stack()

    log("")
    if "--setup" in args:
        log("[OK] Установка завершена. Запуск: python bootstrap.py")
        return 0

    return launch_app()

if __name__ == "__main__":
    sys.exit(main())
