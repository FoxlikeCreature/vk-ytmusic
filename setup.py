#!/usr/bin/env python3
"""
setup.py -- мастер первоначальной настройки vk_ytmusic.

Делает всё автоматически:
  1. Создаёт виртуальное окружение (venv)
  2. Устанавливает зависимости
  3. Помогает настроить авторизацию YouTube Music
  4. Создаёт config.json
"""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# ANSI цвета
class C:
    OK   = "\033[92m"
    WARN = "\033[93m"
    ERR  = "\033[91m"
    BOLD = "\033[1m"
    DIM  = "\033[2m"
    R    = "\033[0m"

def ok(msg):   print(f"{C.OK}  [+]{C.R} {msg}")
def warn(msg): print(f"{C.WARN}  [?]{C.R} {msg}")
def err(msg):  print(f"{C.ERR}  [!]{C.R} {msg}")
def step(msg): print(f"\n{C.BOLD}--- {msg} ---{C.R}")
def ask(prompt, default=''):
    val = input(f"  {prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return val or default

IS_ARCH   = Path('/etc/arch-release').exists()
IS_WIN    = platform.system() == 'Windows'
VENV_DIR  = HERE / '.venv'
VENV_PY   = VENV_DIR / ('Scripts/python.exe' if IS_WIN else 'bin/python')
VENV_PIP  = VENV_DIR / ('Scripts/pip.exe'    if IS_WIN else 'bin/pip')


# ---------------------------------------------------------------------------
# Установка зависимостей
# ---------------------------------------------------------------------------

PACMAN_PKGS = [
    'python-requests',
    'python-tqdm',
    'python-mutagen',
    'python-ytmusicapi',
]
# vk_api нет в официальных репозиториях, ставим через pip в venv
PIP_PKGS = ['vk_api']


def create_venv():
    step("Создание виртуального окружения")
    if VENV_DIR.exists():
        ok("Окружение уже существует, пропускаем")
        return
    print("  Создаю .venv...")
    result = subprocess.run([sys.executable, '-m', 'venv', str(VENV_DIR)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        err(f"Не удалось создать venv: {result.stderr}")
        sys.exit(1)
    ok("Виртуальное окружение создано")


def install_system_packages():
    if not IS_ARCH:
        return
    step("Установка системных пакетов (pacman)")
    print("  Пакеты:", ', '.join(PACMAN_PKGS))
    result = subprocess.run(
        ['sudo', 'pacman', '-S', '--needed', '--noconfirm'] + PACMAN_PKGS,
        text=True
    )
    if result.returncode != 0:
        warn("Не удалось установить все пакеты через pacman, продолжаем через pip в venv")


def install_pip_packages():
    step("Установка Python-библиотек в venv")

    # На Arch: основные пакеты уже через pacman, но venv изолирован.
    # Устанавливаем все через pip в venv чтобы всё точно работало.
    all_pkgs = (PACMAN_PKGS if not IS_ARCH else []) + PIP_PKGS

    if IS_ARCH:
        # На Arch ставим только то, чего нет в системе -- только vk_api
        all_pkgs = PIP_PKGS
        # Но нам нужен доступ к системным пакетам из venv
        # Пересоздаём venv с --system-site-packages если нужно
        if VENV_DIR.exists():
            # Проверяем есть ли флаг system-site-packages
            cfg = VENV_DIR / 'pyvenv.cfg'
            if cfg.exists() and 'include-system-site-packages = true' not in cfg.read_text():
                print("  Пересоздаю venv с доступом к системным пакетам...")
                shutil.rmtree(VENV_DIR)
                result = subprocess.run(
                    [sys.executable, '-m', 'venv', '--system-site-packages', str(VENV_DIR)],
                    capture_output=True, text=True)
                if result.returncode != 0:
                    err(f"Не удалось создать venv: {result.stderr}")
                    sys.exit(1)
        else:
            result = subprocess.run(
                [sys.executable, '-m', 'venv', '--system-site-packages', str(VENV_DIR)],
                capture_output=True, text=True)
            if result.returncode != 0:
                err(f"Не удалось создать venv: {result.stderr}")
                sys.exit(1)

    for pkg in all_pkgs:
        print(f"  Устанавливаю {pkg}...")
        result = subprocess.run(
            [str(VENV_PIP), 'install', pkg],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            err(f"Не удалось установить {pkg}:\n{result.stderr}")
            sys.exit(1)
        ok(f"{pkg} установлен")


# ---------------------------------------------------------------------------
# Авторизация YouTube Music
# ---------------------------------------------------------------------------

def setup_ytmusic_auth():
    step("Авторизация YouTube Music")

    oauth_path = HERE / 'oauth.json'
    if oauth_path.exists():
        ok("oauth.json уже существует, пропускаем")
        return

    print("""
  YouTube Music нужен доступ к твоему аккаунту Google.
  Сейчас откроется инструкция для входа через браузер.

  Что нужно сделать:
    1. Запустится команда ytmusicapi oauth
    2. В терминале появится ссылка -- открой её в браузере
    3. Войди в Google аккаунт
    4. Скопируй код обратно в терминал
""")
    input("  Нажми Enter чтобы начать...")

    # Ищем бинарник ytmusicapi: сначала в venv, потом в системе (pacman)
    ytmusicapi_bin = shutil.which('ytmusicapi', path=str(VENV_DIR / ('Scripts' if IS_WIN else 'bin')))
    if not ytmusicapi_bin:
        ytmusicapi_bin = shutil.which('ytmusicapi')

    if not ytmusicapi_bin:
        err("Не найден бинарник ytmusicapi. Убедись что пакет установлен:")
        err("  sudo pacman -S python-ytmusicapi")
        sys.exit(1)

    cmd = [ytmusicapi_bin, 'oauth', str(oauth_path)]

    result = subprocess.run(cmd)
    if result.returncode != 0 or not oauth_path.exists():
        err("Авторизация не прошла. Попробуй вручную:")
        err(f"  ytmusicapi oauth {oauth_path}")
        sys.exit(1)

    ok("YouTube Music авторизован")


# ---------------------------------------------------------------------------
# Создание конфига
# ---------------------------------------------------------------------------

def create_config():
    step("Настройка конфига")

    config_path = HERE / 'config.json'
    if config_path.exists():
        ans = ask("config.json уже существует. Перезаписать? (да/нет)", "нет")
        if ans.lower() not in ('да', 'y', 'yes', 'д'):
            ok("Оставляю существующий конфиг")
            return

    print("""
  Данные ВКонтакте нужны для доступа к музыке.
  Логин -- номер телефона или email.
""")
    vk_login    = ask("Логин ВК (телефон или email)")
    vk_password = ask("Пароль ВК")

    print("""
  Страница ВК из которой брать музыку.
  Можно указать:
    - домен: durov
    - ID: 123456789
    - группу: club123456
    - ссылку: vk.com/durov
""")
    vk_target = ask("Страница ВК")
    vk_target = vk_target.replace('https://vk.com/', '').replace('http://vk.com/', '').rstrip('/')

    print("""
  Насколько строго искать совпадения (0.0 - 1.0).
  0.65 -- рекомендуется: находит большинство треков,
  игнорируя небольшие различия в написании.
""")
    threshold = ask("Порог совпадения", "0.65")
    try:
        threshold = float(threshold)
        if not (0.0 <= threshold <= 1.0):
            raise ValueError
    except ValueError:
        warn("Некорректное значение, использую 0.65")
        threshold = 0.65

    config = {
        "vk": {
            "login":    vk_login,
            "password": vk_password,
            "target":   vk_target,
        },
        "ytmusic": {
            "auth_file": "oauth.json",
        },
        "options": {
            "match_threshold": threshold,
            "temp_dir":        None,
            "resume_file":     "progress.json",
        }
    }

    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    ok(f"Конфиг сохранён: {config_path}")


# ---------------------------------------------------------------------------
# Финальные инструкции
# ---------------------------------------------------------------------------

def print_final_instructions():
    step("Готово!")

    launcher = 'run.bat' if IS_WIN else 'run.sh'
    print(f"""
  Теперь можно запустить:

    {C.BOLD}./{launcher}{C.R}

  Или напрямую:

    {C.BOLD}{VENV_PY} vk_ytmusic.py{C.R}

  Полезные флаги:

    --dry-run   Проверить без реальных изменений
    --reset     Начать заново (сбросить прогресс)

  Треки которые нашлись на YouTube Music будут лайкнуты.
  Треки которых нет -- скачаются из ВК и загрузятся в
  "Моя музыка -> Загрузки" в YouTube Music.
""")


def create_launchers():
    sh = HERE / 'run.sh'
    sh.write_text(
        f'#!/bin/bash\ncd "$(dirname "$0")"\n{VENV_PY} vk_ytmusic.py "$@"\n',
        encoding='utf-8'
    )
    sh.chmod(0o755)

    bat = HERE / 'run.bat'
    bat.write_text(
        f'@echo off\ncd /d "%~dp0"\n{VENV_PY} vk_ytmusic.py %*\n',
        encoding='utf-8'
    )
    ok("Лаунчеры созданы (run.sh / run.bat)")


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main():
    if IS_WIN:
        os.system('')  # Включить ANSI на Windows

    print(f"""
{C.BOLD}==================================
  VK -> YouTube Music -- Настройка
=================================={C.R}
""")

    if IS_ARCH:
        print("  Обнаружена Arch Linux. Системные пакеты будут установлены")
        print("  через pacman. Только vk_api идёт через pip в изолированный venv.")
        print()

    if IS_WIN:
        print("  Обнаружена Windows. Все пакеты ставятся через pip в venv.")
        print()

    # Шаг 1: Системные пакеты (только Arch)
    if IS_ARCH:
        install_system_packages()
        create_venv()  # venv с --system-site-packages создаётся в install_pip_packages
    else:
        create_venv()

    # Шаг 2: pip пакеты в venv
    install_pip_packages()

    # Шаг 3: YouTube Music OAuth
    setup_ytmusic_auth()

    # Шаг 4: Конфиг
    create_config()

    # Шаг 5: Лаунчеры
    create_launchers()

    print_final_instructions()


if __name__ == '__main__':
    main()
