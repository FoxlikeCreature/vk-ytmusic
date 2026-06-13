# vk-ytmusic

Экспорт музыки из ВКонтакте в YouTube Music.

Треки, которые есть в YTM, получают лайк. Те, которых нет - скачиваются из ВК и загружаются в YTM как личные треки (раздел "Загрузки", затем автоматически добавляются в "Мне нравится").

**Все зависимости встроены в скрипт. pip install не нужен.**

---

## Требования

| | Linux | Windows |
|---|---|---|
| Python | 3.8+ | 3.8+ |
| ffmpeg | нужен для HLS-треков (большинство треков ВК) | нужен для HLS-треков |

### Установка Python

**Linux (Arch/Ubuntu/Debian):**
```bash
# Arch
sudo pacman -S python

# Ubuntu/Debian
sudo apt install python3
```

**Windows:** скачай с [python.org](https://www.python.org/downloads/), при установке поставь галку "Add Python to PATH".

### Установка ffmpeg

**Linux:**
```bash
# Arch
sudo pacman -S ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

**Windows:** скачай с [ffmpeg.org](https://ffmpeg.org/download.html), распакуй и добавь папку `bin` в PATH. Или через winget:
```cmd
winget install ffmpeg
```

---

## Опционально: автоматическое получение куков

Без этого тебе придётся вставлять куки YouTube вручную (инструкция выдаётся при первом запуске). С этим пакетом скрипт берёт куки из браузера сам.

**Linux:**
```bash
# Arch
yay -S python-browser-cookie3

# Ubuntu/Debian
pip install browser-cookie3
```

**Windows:**
```cmd
pip install browser-cookie3
```

---

## Запуск

**Linux:**
```bash
python vk_ytmusic.py
```

**Windows:**
```cmd
python vk_ytmusic.py
```

При первом запуске скрипт сам спросит всё необходимое: логин ВК, страницу с музыкой, авторизацию YouTube Music.

---

## Флаги

```
python vk_ytmusic.py              # обычный запуск
python vk_ytmusic.py --dry-run    # тест без изменений (не лайкает, не загружает)
python vk_ytmusic.py --reset      # сбросить прогресс и обработать всё заново
python vk_ytmusic.py --reauth-ytm # обновить авторизацию YTM (куки устарели)
```

---

## Как работает

1. Скрипт получает список треков со страницы ВКонтакте
2. Каждый трек ищется в YouTube Music по исполнителю и названию
3. Если нашёл - ставит лайк
4. Если не нашёл - скачивает MP3 из ВК и загружает в YTM
5. Прогресс сохраняется в `progress.json` - если прервать, продолжит с того же места

---

## Авторизация ВК

Скрипт использует логин и пароль для получения куков ВК (как обычный браузер). Двухфакторная аутентификация поддерживается - скрипт спросит код при необходимости.

VK API-токен не нужен.

---

## Авторизация YouTube Music

Если установлен `browser-cookie3`, скрипт предложит выбрать браузер и автоматически возьмёт куки. Для Chrome показывает список профилей, если их несколько.

Если куки взять не удалось, скрипт попросит выполнить одну команду в консоли браузера (`copy(document.cookie)` на music.youtube.com).

Куки хранятся локально в `browser.json` и не передаются никуда кроме YouTube.

Если куки протухли (ошибка 401), запусти с `--reauth-ytm`.
