#!/usr/bin/env python3
"""
vk_ytmusic.py -- экспорт музыки из ВКонтакте в YouTube Music.

Первый запуск: скрипт сам установит зависимости и настроит всё необходимое.
Повторные запуски: сразу работает.
"""

# =============================================================================
# BOOTSTRAP -- работает только на stdlib, никаких внешних зависимостей
# =============================================================================
import os
import sys
from pathlib import Path

HERE    = Path(__file__).parent
IS_WIN  = sys.platform == 'win32'
IS_ARCH = Path('/etc/arch-release').exists()

VENV_DIR    = HERE / '.venv'
VENV_PY     = VENV_DIR / ('Scripts' if IS_WIN else 'bin') / ('python.exe' if IS_WIN else 'python')
VENV_PIP    = VENV_DIR / ('Scripts' if IS_WIN else 'bin') / ('pip.exe' if IS_WIN else 'pip')
VENV_MARKER = VENV_DIR / '.packages'  # хранит список установленных пакетов

# Пакеты которые ставятся через pip в venv
ARCH_PIP  = ['vk_api', 'browser_cookie3']
ALL_PIP   = ['vk_api', 'ytmusicapi', 'mutagen', 'requests', 'tqdm', 'browser_cookie3']

def _required_pip():
    return ARCH_PIP if IS_ARCH else ALL_PIP


def _in_our_venv() -> bool:
    try:
        return VENV_PY.resolve() == Path(sys.executable).resolve()
    except Exception:
        return False


def _reexec():
    """Перезапустить этот же скрипт внутри venv."""
    args = [str(VENV_PY)] + sys.argv
    if IS_WIN:
        import subprocess
        sys.exit(subprocess.run(args).returncode)
    else:
        os.execv(str(VENV_PY), args)


def _run(*cmd, check=True, show=True):
    import subprocess
    if show:
        print(f"  > {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, text=True, capture_output=not show)
    if check and result.returncode != 0:
        if not show:
            print(result.stderr or result.stdout)
        print(f"\nОшибка при выполнении команды. Код: {result.returncode}")
        sys.exit(result.returncode)
    return result


def _installed_pip() -> list:
    """Читает список уже установленных пакетов из маркера."""
    try:
        import json as _json
        return _json.loads(VENV_MARKER.read_text())
    except Exception:
        return []


def _mark_installed(pkgs: list):
    import json as _json
    VENV_MARKER.write_text(_json.dumps(sorted(pkgs)))


def _install_pip(pkgs: list):
    if not pkgs:
        return
    print(f"  Устанавливаю: {', '.join(pkgs)}")
    _run(str(VENV_PIP), 'install', '--quiet', *pkgs)


def _bootstrap():
    required = sorted(_required_pip())

    if _in_our_venv():
        # Проверяем нет ли новых пакетов добавленных после создания venv
        installed = _installed_pip()
        missing = [p for p in required if p not in installed]
        if missing:
            print(f"\nДоустанавливаю новые зависимости: {', '.join(missing)}")
            _install_pip(missing)
            _mark_installed(required)
        return

    if VENV_MARKER.exists():
        # Venv существует -- проверить нет ли новых пакетов
        installed = _installed_pip()
        missing = [p for p in required if p not in installed]
        if missing:
            print(f"\nОбновляю зависимости: {', '.join(missing)}")
            _install_pip(missing)
            _mark_installed(required)
        _reexec()

    # --- Первый запуск: полная установка ---
    print("\n\033[1m=== Первый запуск: устанавливаю зависимости ===\033[0m\n")

    if IS_ARCH:
        print("Arch Linux -- ставлю системные пакеты через pacman...")
        sys_pkgs = ['python-requests', 'python-tqdm', 'python-mutagen', 'python-ytmusicapi']
        _run('sudo', 'pacman', '-S', '--needed', '--noconfirm', *sys_pkgs)
        print()
        print("Создаю виртуальное окружение (с доступом к системным пакетам)...")
        _run(sys.executable, '-m', 'venv', '--system-site-packages', str(VENV_DIR))
        print()
        _install_pip(required)
    else:
        print("Создаю виртуальное окружение...")
        _run(sys.executable, '-m', 'venv', str(VENV_DIR))
        print()
        _install_pip(required)

    _mark_installed(required)
    print("\n\033[92mЗависимости установлены.\033[0m Перезапускаю...\n")
    _reexec()


_bootstrap()

# =============================================================================
# Всё что ниже выполняется уже внутри venv, все зависимости доступны
# =============================================================================

import json
import re
import shutil
import subprocess
import tempfile
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional


# ANSI цвета (Linux и Windows 10+)
class C:
    OK   = "\033[92m"
    WARN = "\033[93m"
    ERR  = "\033[91m"
    UP   = "\033[94m"
    BOLD = "\033[1m"
    DIM  = "\033[2m"
    R    = "\033[0m"


def _ok(msg):   print(f"{C.OK}  v  {C.R}{msg}")
def _warn(msg): print(f"{C.WARN}  ?  {C.R}{msg}")
def _err(msg):  print(f"{C.ERR}  !  {C.R}{msg}")
def _up(msg):   print(f"{C.UP}  ^  {C.R}{msg}")
def _info(msg): print(f"{C.DIM}     {msg}{C.R}")


# =============================================================================
# Мастер первоначальной настройки
# =============================================================================

def _ask(prompt: str, default: str = '') -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"  {prompt}{hint}: ").strip()
    return val or default


def _wizard_config():
    """Интерактивное создание config.json если его нет."""
    config_path = HERE / 'config.json'
    if config_path.exists():
        return

    print(f"\n{C.BOLD}=== Первоначальная настройка ==={C.R}\n")
    print("Конфиг не найден. Сейчас настроим всё вместе.\n")

    print("  1/3  Данные ВКонтакте")
    print("       Логин -- номер телефона или email аккаунта ВК.\n")
    vk_login    = _ask("Логин ВК")
    vk_password = _ask("Пароль ВК")

    print()
    print("  2/3  Откуда брать музыку")
    print("       Укажи страницу ВК: домен (например durov),")
    print("       числовой ID (123456789) или ссылку (vk.com/durov).\n")
    vk_target = _ask("Страница ВК")
    vk_target = vk_target.replace('https://vk.com/', '').replace('http://vk.com/', '').rstrip('/')

    print()
    print("  3/3  Точность поиска")
    print("       Насколько строго искать совпадения (0.0-1.0).")
    print("       0.65 -- оптимально для большинства случаев.\n")
    threshold = _ask("Порог совпадения", "0.65")
    try:
        threshold = float(threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError
    except ValueError:
        _warn("Некорректное значение, использую 0.65")
        threshold = 0.65

    config = {
        "vk": {
            "login":    vk_login,
            "password": vk_password,
            "target":   vk_target,
        },
        "ytmusic": {
            "auth_file": "browser.json",
        },
        "options": {
            "match_threshold": threshold,
            "temp_dir":        None,
            "resume_file":     "progress.json",
        }
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    _ok(f"Конфиг сохранён: {config_path.name}")


def _try_auto_cookie_extract() -> Optional[str]:
    """Пробует автоматически достать куки YouTube из установленных браузеров."""
    try:
        import browser_cookie3
    except ImportError:
        return None

    extractors = [
        ('Chrome',    browser_cookie3.chrome),
        ('Chromium',  browser_cookie3.chromium),
        ('Firefox',   browser_cookie3.firefox),
        ('Brave',     browser_cookie3.brave),
        ('Edge',      browser_cookie3.edge),
        ('Opera',     browser_cookie3.opera),
        ('Vivaldi',   browser_cookie3.vivaldi),
    ]

    for name, extractor in extractors:
        try:
            jar = extractor(domain_name='.youtube.com')
            cookies = {c.name: c.value for c in jar}
            if 'SAPISID' in cookies:
                _ok(f"Куки найдены в {name}")
                return '; '.join(f'{k}={v}' for k, v in cookies.items())
        except Exception:
            continue

    return None


def _save_ytm_auth(auth_path: Path, cookie_str: str):
    """Создаёт browser.json для ytmusicapi из строки куки."""
    from ytmusicapi import YTMusic
    headers_raw = f"cookie: {cookie_str}\nx-goog-authuser: 0\n"
    try:
        YTMusic.setup(filepath=str(auth_path), headers_raw=headers_raw)
        return
    except Exception:
        pass
    # Fallback: сохранить напрямую в нужном формате
    auth_path.write_text(json.dumps({
        "accept": "*/*",
        "accept-encoding": "gzip, deflate",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "cookie": cookie_str,
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-goog-authuser": "0",
        "x-youtube-client-name": "67",
        "x-youtube-client-version": "1.20240101.00.00",
    }, indent=2), encoding='utf-8')


def _wizard_ytmusic_auth(auth_file: str):
    """Авторизация YouTube Music: сначала авто, потом 1 команда в браузере."""
    auth_path = HERE / auth_file
    if auth_path.exists():
        return

    print(f"\n{C.BOLD}=== Авторизация YouTube Music ==={C.R}\n")
    print("  Пробую получить куки автоматически из браузера...")

    cookie_str = _try_auto_cookie_extract()
    if cookie_str:
        _save_ytm_auth(auth_path, cookie_str)
        _ok("YouTube Music авторизован автоматически!")
        return

    # Ручной метод: одна команда в консоли браузера
    _warn("Автоматически не вышло (возможно браузер закрыт или куки недоступны).\n")
    print("  Нужно выполнить одну команду в браузере. Это займёт минуту.\n")
    print(f"  1. Открой любой браузер, перейди на  {C.BOLD}music.youtube.com{C.R}")
    print(f"     Убедись что ты залогинен в нужный Google аккаунт.\n")
    print(f"  2. Нажми  {C.BOLD}F12{C.R}  -- откроется панель разработчика.\n")
    print(f"  3. Перейди на вкладку  {C.BOLD}Console{C.R}  (Консоль).\n")
    print(f"  4. Вставь туда эту команду и нажми Enter:\n")
    print(f"       {C.BOLD}copy(document.cookie){C.R}\n")
    print(f"     {C.DIM}Ничего не отобразится -- это нормально.")
    print(f"     Куки уже скопированы в буфер обмена.{C.R}\n")
    input("  Выполнил? Нажми Enter...")
    print(f"  Теперь вставь сюда (Ctrl+V) и нажми Enter:")
    cookie_str = input("  > ").strip()

    if len(cookie_str) < 20:
        _err("Строка слишком короткая. Убедись что выполнил команду на music.youtube.com")
        sys.exit(1)

    if 'SAPISID' not in cookie_str and 'VISITOR_INFO' not in cookie_str:
        _warn("Не найдены ожидаемые куки YouTube. Продолжаю, но авторизация может не работать.")

    _save_ytm_auth(auth_path, cookie_str)
    _ok("YouTube Music авторизован!")


# =============================================================================
# Нечёткое совпадение
# =============================================================================

def _normalize(s: str) -> str:
    s = s.lower()
    noise = r'feat\.|ft\.|explicit|official|video|audio|lyric|live|remaster|remix|radio.edit|hd|hq'
    s = re.sub(r'[\(\[][^\)\]]*(?:' + noise + r')[^\)\]]*[\)\]]', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _is_match(qa: str, qt: str, ra: str, rt: str, threshold: float) -> bool:
    return _sim(qa, ra) >= threshold and _sim(qt, rt) >= threshold


# =============================================================================
# VK
# =============================================================================

def _vk_login(login: str, password: str):
    import vk_api as vk_mod
    session = vk_mod.VkApi(login=login, password=password)
    try:
        session.auth()
    except vk_mod.AuthError as e:
        _err(f"Не удалось войти в ВК: {e}")
        _err("Проверь логин и пароль в config.json")
        sys.exit(1)
    return session


def _resolve_owner_id(session, target: str) -> int:
    import vk_api as vk_mod
    vk = session.get_api()
    try:
        return int(target)
    except ValueError:
        pass
    target = target.lstrip('@').replace('https://vk.com/', '').replace('http://vk.com/', '').rstrip('/')
    try:
        result = vk.utils.resolveScreenName(screen_name=target)
    except vk_mod.ApiError as e:
        _err(f"Страница '{target}' не найдена: {e}")
        sys.exit(1)
    if not result:
        _err(f"Страница '{target}' не найдена. Проверь поле 'target' в config.json")
        sys.exit(1)
    obj_id = result.get('object_id', 0)
    return -obj_id if result.get('type') == 'group' else obj_id


def _get_thumb_url(item: dict) -> str:
    album = item.get('album') or {}
    thumb = (album.get('thumb') or {})
    for size in ('photo_600', 'photo_300', 'photo_270', 'photo_135'):
        if thumb.get(size):
            return thumb[size]
    return ''


def _get_vk_tracks(session, owner_id: int) -> List[Dict]:
    from vk_api.audio import VkAudio
    audio = VkAudio(session)
    tracks = []
    try:
        for item in audio.get_iter(owner_id=owner_id):
            tracks.append({
                'id':       f"{item.get('owner_id')}_{item.get('id')}",
                'artist':   (item.get('artist') or '').strip(),
                'title':    (item.get('title') or '').strip(),
                'url':      item.get('url') or '',
                'thumb':    _get_thumb_url(item),
            })
    except Exception as e:
        _err(f"Ошибка при получении треков из ВК: {e}")
        sys.exit(1)
    return tracks


# =============================================================================
# YouTube Music
# =============================================================================

def _ytm_login(auth_file: str):
    from ytmusicapi import YTMusic
    path = HERE / auth_file
    if not path.exists():
        _err(f"Файл авторизации не найден: {path}")
        sys.exit(1)
    return YTMusic(str(path))


def _search_ytmusic(ytm, artist: str, title: str, threshold: float) -> Optional[Dict]:
    query = f"{artist} - {title}"
    try:
        for r in ytm.search(query, filter='songs', limit=5):
            artists = r.get('artists') or []
            ra = artists[0].get('name', '') if artists else ''
            if _is_match(artist, title, ra, r.get('title', ''), threshold):
                return r
    except Exception:
        pass
    try:
        for r in ytm.search(query, filter='videos', limit=3):
            if _sim(title, r.get('title', '')) >= threshold:
                return r
    except Exception:
        pass
    return None


def _like(ytm, video_id: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        ytm.rate_song(video_id, 'LIKE')
        return True
    except Exception as e:
        _warn(f"Не удалось поставить лайк: {e}")
        return False


def _upload(ytm, mp3_path: Path, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        status = ytm.upload_song(str(mp3_path))
        return status is None or status == 200 or (isinstance(status, str) and 'SUCCEEDED' in status)
    except Exception as e:
        _warn(f"Ошибка загрузки {mp3_path.name}: {e}")
        return False


# =============================================================================
# Загрузка из ВК
# =============================================================================

def _download(url: str) -> Optional[bytes]:
    import requests as req
    try:
        r = req.get(url, stream=True, timeout=30)
        r.raise_for_status()
        return b''.join(r.iter_content(65536))
    except Exception as e:
        _warn(f"Ошибка скачивания: {e}")
        return None


def _tag(path: Path, artist: str, title: str, thumb: Optional[bytes]):
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, APIC, ID3NoHeaderError
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags['TIT2'] = TIT2(encoding=3, text=title)
        tags['TPE1'] = TPE1(encoding=3, text=artist)
        if thumb:
            tags['APIC'] = APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=thumb)
        tags.save(str(path))
    except Exception:
        pass


# =============================================================================
# Прогресс
# =============================================================================

def _load_progress(path: Path) -> set:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def _save_progress(path: Path, done: set):
    path.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=2), encoding='utf-8')


# =============================================================================
# Главный цикл
# =============================================================================

def run(config: dict, dry_run: bool, reset: bool):
    vk_cfg  = config['vk']
    ytm_cfg = config['ytmusic']
    opts    = config.get('options', {})

    threshold   = float(opts.get('match_threshold', 0.65))
    tmp_root    = Path(opts['temp_dir']) if opts.get('temp_dir') else \
                  Path(tempfile.gettempdir()) / 'vk_ytmusic'
    tmp_root.mkdir(parents=True, exist_ok=True)
    resume_path = HERE / opts.get('resume_file', 'progress.json')

    if reset and resume_path.exists():
        resume_path.unlink()
        print("Прогресс сброшен.\n")

    done_ids = _load_progress(resume_path)

    print(f"\n{C.BOLD}=== VK -> YouTube Music ==={C.R}")
    if dry_run:
        print(f"{C.WARN}Режим dry-run: треки не лайкаются и не загружаются{C.R}\n")

    print("Авторизация в ВКонтакте...")
    vk_session = _vk_login(vk_cfg['login'], vk_cfg['password'])

    print("Авторизация в YouTube Music...")
    ytm = _ytm_login(ytm_cfg['auth_file'])

    print(f"Ищем страницу '{vk_cfg['target']}'...")
    owner_id = _resolve_owner_id(vk_session, vk_cfg['target'])
    _info(f"owner_id = {owner_id}")

    print("Загружаем треки из ВК...")
    tracks = _get_vk_tracks(vk_session, owner_id)
    total  = len(tracks)
    print(f"Найдено треков: {C.BOLD}{total}{C.R}\n")

    stats = {'found': 0, 'uploaded': 0, 'skipped': 0, 'errors': 0}

    try:
        from tqdm import tqdm
        pbar     = tqdm(tracks, unit='трек', dynamic_ncols=True)
        tprint   = tqdm.write
    except ImportError:
        pbar     = tracks
        tprint   = print

    for i, track in enumerate(pbar):
        track_id = track['id']
        label    = f"{track['artist']} - {track['title']}"

        if hasattr(pbar, 'set_description'):
            pbar.set_description(label[:55])
        else:
            print(f"[{i+1}/{total}] {label}")

        if track_id in done_ids:
            stats['skipped'] += 1
            continue

        if not track['artist'] and not track['title']:
            done_ids.add(track_id)
            _save_progress(resume_path, done_ids)
            stats['errors'] += 1
            continue

        try:
            result = _search_ytmusic(ytm, track['artist'], track['title'], threshold)

            if result:
                vid = result.get('videoId', '')
                if vid and _like(ytm, vid, dry_run):
                    tprint(f"{C.OK}  v{C.R}  {label}")
                    stats['found'] += 1
                else:
                    tprint(f"{C.WARN}  ?{C.R}  Лайк не прошёл: {label}")
                    stats['errors'] += 1
                    continue
            else:
                if not track['url']:
                    tprint(f"{C.DIM}  -  Нет URL (удалён в ВК): {label}{C.R}")
                    done_ids.add(track_id)
                    _save_progress(resume_path, done_ids)
                    stats['errors'] += 1
                    continue

                audio = _download(track['url'])
                if not audio:
                    stats['errors'] += 1
                    continue

                safe   = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label)[:100]
                mp3    = tmp_root / f"{safe}.mp3"
                mp3.write_bytes(audio)

                thumb_data = _download(track['thumb']) if track['thumb'] else None
                _tag(mp3, track['artist'], track['title'], thumb_data)

                if _upload(ytm, mp3, dry_run):
                    tprint(f"{C.UP}  ^{C.R}  Загружен из ВК: {label}")
                    stats['uploaded'] += 1
                    time.sleep(1)
                else:
                    stats['errors'] += 1
                    continue

                try:
                    mp3.unlink()
                except Exception:
                    pass

        except Exception as e:
            tprint(f"{C.ERR}  !{C.R}  Ошибка '{label}': {e}")
            stats['errors'] += 1
            continue

        done_ids.add(track_id)
        _save_progress(resume_path, done_ids)

    print(f"\n{C.BOLD}{'=' * 40}{C.R}")
    if dry_run:
        print(f"{C.WARN}[dry-run]{C.R}")
    print(f"  Лайкнуто:        {C.OK}{stats['found']}{C.R}")
    print(f"  Загружено из ВК: {C.UP}{stats['uploaded']}{C.R}")
    print(f"  Пропущено:       {stats['skipped']}")
    print(f"  Ошибки:          {C.ERR}{stats['errors']}{C.R}")
    print(f"{C.BOLD}{'=' * 40}{C.R}\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    if IS_WIN:
        os.system('')  # ANSI на Windows

    import argparse
    parser = argparse.ArgumentParser(
        description='Экспорт музыки из ВКонтакте в YouTube Music',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python vk_ytmusic.py\n"
            "  python vk_ytmusic.py --dry-run\n"
            "  python vk_ytmusic.py --reset\n"
            "  python vk_ytmusic.py --config /path/to/config.json\n"
        )
    )
    parser.add_argument('--config',  default='config.json',
                        help='Путь к конфигу (по умолчанию: config.json рядом со скриптом)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Тест без реальных изменений')
    parser.add_argument('--reset',   action='store_true',
                        help='Начать заново, сбросив прогресс')
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = HERE / config_path

    # Мастер настройки (запускается автоматически при первом запуске)
    _wizard_config()

    # Загрузить конфиг
    if not config_path.exists():
        _err(f"Конфиг не найден: {config_path}")
        sys.exit(1)
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        _err(f"Ошибка в config.json: {e}")
        sys.exit(1)

    # Авторизация YT Music (запускается автоматически если нет oauth.json)
    _wizard_ytmusic_auth(config['ytmusic']['auth_file'])

    run(config, dry_run=args.dry_run, reset=args.reset)


if __name__ == '__main__':
    main()
