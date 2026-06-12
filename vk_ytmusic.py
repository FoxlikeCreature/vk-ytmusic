#!/usr/bin/env python3
"""
vk_ytmusic.py -- экспорт музыки из ВКонтакте в YouTube Music.

Найденные треки лайкаются. Ненайденные -- скачиваются из ВК и загружаются
как личные треки в раздел "Мои загрузки" YouTube Music.
"""

import argparse
import json
import re
import sys
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

# Цвета ANSI (работают на Linux и Windows 10+)
class C:
    OK    = "\033[92m"  # зелёный
    WARN  = "\033[93m"  # жёлтый
    ERR   = "\033[91m"  # красный
    DIM   = "\033[2m"
    BOLD  = "\033[1m"
    RESET = "\033[0m"

def ok(msg):   print(f"{C.OK}  v  {C.RESET}{msg}")
def warn(msg): print(f"{C.WARN}  ?  {C.RESET}{msg}")
def err(msg):  print(f"{C.ERR}  !  {C.RESET}{msg}")
def up(msg):   print(f"\033[94m  ^  {C.RESET}{msg}")
def info(msg): print(f"{C.DIM}     {msg}{C.RESET}")


# ---------------------------------------------------------------------------
# Нечёткое совпадение
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    s = s.lower()
    # Убираем типичные суффиксы в скобках которые не меняют суть трека
    noise = r'feat\.|ft\.|explicit|official|video|audio|lyric|live|remaster|remix|radio.edit|hd|hq'
    s = re.sub(r'[\(\[][^\)\]]*(?:' + noise + r')[^\)\]]*[\)\]]', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()

def _is_match(q_artist: str, q_title: str, r_artist: str, r_title: str, threshold: float) -> bool:
    return _sim(q_artist, r_artist) >= threshold and _sim(q_title, r_title) >= threshold


# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------

def vk_login(login: str, password: str):
    try:
        import vk_api
    except ImportError:
        err("Библиотека vk_api не установлена.")
        err("Запусти: python setup.py")
        sys.exit(1)

    import vk_api as vk_mod
    session = vk_mod.VkApi(login=login, password=password)
    try:
        session.auth()
    except vk_mod.AuthError as e:
        err(f"Не удалось войти в ВК: {e}")
        err("Проверь логин и пароль в config.json")
        sys.exit(1)
    return session


def _resolve_owner_id(session, target: str) -> int:
    import vk_api as vk_mod
    vk = session.get_api()

    try:
        return int(target)
    except ValueError:
        pass

    target = target.lstrip('@').lstrip('https://vk.com/').rstrip('/')

    try:
        result = vk.utils.resolveScreenName(screen_name=target)
    except vk_mod.ApiError as e:
        err(f"Не удалось найти страницу '{target}': {e}")
        sys.exit(1)

    if not result:
        err(f"Страница '{target}' не найдена. Проверь поле 'target' в config.json")
        sys.exit(1)

    obj_id = result.get('object_id', 0)
    if result.get('type') == 'group':
        return -obj_id
    return obj_id


def _get_thumb_url(item: dict) -> str:
    album = item.get('album') or {}
    thumb = album.get('thumb') or {}
    for size in ('photo_600', 'photo_300', 'photo_270', 'photo_135'):
        if thumb.get(size):
            return thumb[size]
    return ''


def get_vk_tracks(session, owner_id: int) -> List[Dict]:
    try:
        from vk_api.audio import VkAudio
    except ImportError:
        err("Библиотека vk_api не установлена. Запусти: python setup.py")
        sys.exit(1)

    audio = VkAudio(session)
    tracks = []
    try:
        for item in audio.get_iter(owner_id=owner_id):
            tracks.append({
                'id':       f"{item.get('owner_id')}_{item.get('id')}",
                'artist':   (item.get('artist') or '').strip(),
                'title':    (item.get('title') or '').strip(),
                'url':      item.get('url') or '',
                'duration': item.get('duration') or 0,
                'thumb':    _get_thumb_url(item),
            })
    except Exception as e:
        err(f"Ошибка при получении треков из ВК: {e}")
        sys.exit(1)
    return tracks


# ---------------------------------------------------------------------------
# YouTube Music
# ---------------------------------------------------------------------------

def ytm_login(auth_file: str):
    try:
        from ytmusicapi import YTMusic
    except ImportError:
        err("Библиотека ytmusicapi не установлена. Запусти: python setup.py")
        sys.exit(1)

    path = Path(auth_file)
    if not path.is_absolute():
        path = Path(__file__).parent / path

    if not path.exists():
        err(f"Файл авторизации YouTube Music не найден: {path}")
        err("Создай его командой: ytmusicapi oauth oauth.json")
        sys.exit(1)

    from ytmusicapi import YTMusic
    return YTMusic(str(path))


def search_ytmusic(ytm, artist: str, title: str, threshold: float) -> Optional[Dict]:
    query = f"{artist} - {title}"
    try:
        results = ytm.search(query, filter='songs', limit=5)
        for r in results:
            artists = r.get('artists') or []
            r_artist = artists[0].get('name', '') if artists else ''
            r_title  = r.get('title', '')
            if _is_match(artist, title, r_artist, r_title, threshold):
                return r
    except Exception:
        pass

    # Fallback: поиск по видео (иногда треки есть только как видео)
    try:
        results2 = ytm.search(query, filter='videos', limit=3)
        for r in results2:
            r_title = r.get('title', '')
            if _sim(title, r_title) >= threshold:
                return r
    except Exception:
        pass

    return None


def like_track(ytm, video_id: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        ytm.rate_song(video_id, 'LIKE')
        return True
    except Exception as e:
        warn(f"Не удалось поставить лайк {video_id}: {e}")
        return False


def upload_track(ytm, mp3_path: Path, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        status = ytm.upload_song(str(mp3_path))
        if status is None or (isinstance(status, str) and 'SUCCEEDED' in status):
            return True
        if status == 200:
            return True
        warn(f"Неожиданный ответ при загрузке: {status}")
        return False
    except Exception as e:
        warn(f"Ошибка загрузки {mp3_path.name}: {e}")
        return False


# ---------------------------------------------------------------------------
# Загрузка из ВК
# ---------------------------------------------------------------------------

def _download_bytes(url: str, timeout: int = 30) -> Optional[bytes]:
    try:
        import requests as req
        resp = req.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        chunks = []
        for chunk in resp.iter_content(chunk_size=65536):
            chunks.append(chunk)
        return b''.join(chunks)
    except Exception as e:
        warn(f"Ошибка загрузки: {e}")
        return None


def _tag_mp3(path: Path, artist: str, title: str, thumb_data: Optional[bytes]):
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, APIC, ID3NoHeaderError
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags['TIT2'] = TIT2(encoding=3, text=title)
        tags['TPE1'] = TPE1(encoding=3, text=artist)
        if thumb_data:
            tags['APIC'] = APIC(encoding=3, mime='image/jpeg',
                                type=3, desc='Cover', data=thumb_data)
        tags.save(str(path))
    except Exception as e:
        info(f"Предупреждение: теги не записаны: {e}")


# ---------------------------------------------------------------------------
# Прогресс (resume)
# ---------------------------------------------------------------------------

def _load_progress(path: Path) -> set:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            return set()
    return set()


def _save_progress(path: Path, done: set):
    path.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=2),
                    encoding='utf-8')


# ---------------------------------------------------------------------------
# Главный цикл
# ---------------------------------------------------------------------------

def run(config: dict, dry_run: bool, reset: bool):
    vk_cfg  = config['vk']
    ytm_cfg = config['ytmusic']
    opts    = config.get('options', {})

    threshold   = float(opts.get('match_threshold', 0.65))
    tmp_root    = Path(opts['temp_dir']) if opts.get('temp_dir') else \
                  Path(tempfile.gettempdir()) / 'vk_ytmusic'
    tmp_root.mkdir(parents=True, exist_ok=True)

    script_dir  = Path(__file__).parent
    resume_path = script_dir / opts.get('resume_file', 'progress.json')

    if reset and resume_path.exists():
        resume_path.unlink()
        print("Прогресс сброшен.")

    done_ids = _load_progress(resume_path)

    print(f"\n{C.BOLD}=== VK -> YouTube Music ==={C.RESET}")
    if dry_run:
        print(f"{C.WARN}Режим dry-run: треки не лайкаются и не загружаются{C.RESET}\n")

    print("Авторизация в ВКонтакте...")
    vk_session = vk_login(vk_cfg['login'], vk_cfg['password'])

    print("Авторизация в YouTube Music...")
    ytm = ytm_login(ytm_cfg['auth_file'])

    print(f"Определяем ID страницы '{vk_cfg['target']}'...")
    owner_id = _resolve_owner_id(vk_session, vk_cfg['target'])
    info(f"owner_id = {owner_id}")

    print("Загружаем список треков из ВК...")
    tracks = get_vk_tracks(vk_session, owner_id)
    total  = len(tracks)
    print(f"Найдено треков: {C.BOLD}{total}{C.RESET}\n")

    stats = {'found': 0, 'uploaded': 0, 'skipped': 0, 'errors': 0}

    try:
        from tqdm import tqdm
        use_tqdm = True
    except ImportError:
        use_tqdm = False

    pbar = tqdm(tracks, unit='трек', dynamic_ncols=True) if use_tqdm else tracks

    for i, track in enumerate(pbar):
        track_id = track['id']
        label    = f"{track['artist']} - {track['title']}"

        if use_tqdm:
            pbar.set_description(label[:55])
        else:
            print(f"[{i+1}/{total}] {label}")

        if track_id in done_ids:
            stats['skipped'] += 1
            continue

        if not track['artist'] and not track['title']:
            info(f"Пустой трек {track_id}, пропускаем")
            done_ids.add(track_id)
            _save_progress(resume_path, done_ids)
            stats['errors'] += 1
            continue

        try:
            result = search_ytmusic(ytm, track['artist'], track['title'], threshold)

            if result:
                video_id = result.get('videoId', '')
                if video_id and like_track(ytm, video_id, dry_run):
                    (tqdm.write if use_tqdm else print)(f"{C.OK}  v{C.RESET}  {label}")
                    stats['found'] += 1
                else:
                    (tqdm.write if use_tqdm else print)(f"{C.WARN}  ?{C.RESET}  Найден, но лайк не прошёл: {label}")
                    stats['errors'] += 1
                    continue

            else:
                if not track['url']:
                    (tqdm.write if use_tqdm else print)(
                        f"{C.DIM}  -  Нет URL (трек удалён в ВК): {label}{C.RESET}")
                    stats['errors'] += 1
                    done_ids.add(track_id)
                    _save_progress(resume_path, done_ids)
                    continue

                # Скачать из ВК
                audio_data = _download_bytes(track['url'])
                if not audio_data:
                    stats['errors'] += 1
                    continue

                safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label)[:100]
                mp3_path  = tmp_root / f"{safe_name}.mp3"
                mp3_path.write_bytes(audio_data)

                thumb_data = _download_bytes(track['thumb']) if track['thumb'] else None
                _tag_mp3(mp3_path, track['artist'], track['title'], thumb_data)

                if upload_track(ytm, mp3_path, dry_run):
                    (tqdm.write if use_tqdm else print)(
                        f"\033[94m  ^{C.RESET}  Загружен из ВК: {label}")
                    stats['uploaded'] += 1
                    time.sleep(1)  # не спамим API
                else:
                    stats['errors'] += 1
                    continue

                try:
                    mp3_path.unlink()
                except Exception:
                    pass

        except Exception as e:
            (tqdm.write if use_tqdm else print)(
                f"{C.ERR}  !{C.RESET}  Ошибка '{label}': {e}")
            stats['errors'] += 1
            continue

        done_ids.add(track_id)
        _save_progress(resume_path, done_ids)

    print(f"\n{C.BOLD}{'=' * 40}{C.RESET}")
    if dry_run:
        print(f"{C.WARN}[dry-run, реальных изменений нет]{C.RESET}")
    print(f"  Найдено и лайкнуто:  {C.OK}{stats['found']}{C.RESET}")
    print(f"  Загружено из ВК:     \033[94m{stats['uploaded']}{C.RESET}")
    print(f"  Пропущено (resume):  {stats['skipped']}")
    print(f"  Ошибки/без URL:      {C.ERR}{stats['errors']}{C.RESET}")
    print(f"{C.BOLD}{'=' * 40}{C.RESET}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Включаем ANSI на Windows
    if sys.platform == 'win32':
        import os
        os.system('')

    parser = argparse.ArgumentParser(
        description='Экспорт музыки из ВКонтакте в YouTube Music',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python vk_ytmusic.py --config config.json\n"
            "  python vk_ytmusic.py --config config.json --dry-run\n"
            "  python vk_ytmusic.py --config config.json --reset\n"
        )
    )
    parser.add_argument('--config',  default='config.json',
                        help='Путь к конфигу (по умолчанию: config.json)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Тест без реальных изменений')
    parser.add_argument('--reset',   action='store_true',
                        help='Начать заново (сбросить прогресс)')
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).parent / config_path

    if not config_path.exists():
        err(f"Конфиг не найден: {config_path}")
        err("Запусти python setup.py чтобы создать его")
        sys.exit(1)

    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        err(f"Ошибка в config.json: {e}")
        sys.exit(1)

    run(config, dry_run=args.dry_run, reset=args.reset)


if __name__ == '__main__':
    main()
