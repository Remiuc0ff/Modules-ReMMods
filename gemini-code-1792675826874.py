# meta developer: @DmitriReMM, @space_modules
# Name: RemakeVoiceMod
# meta banner: https://raw.githubusercontent.com/Hshdhr1/my-modules-heroku/main/banner_voicemod.jpg
# meta pic: https://raw.githubusercontent.com/Hshdhr1/my-modules-heroku/main/banner_voicemod.jpg
# meta fhsdesc: voicemod, voice, music, audio, video, player, radio, stream, стрим, музыка, видео, голосовой чат, войс, плейлист
# meta tags: voice, music, audio, video, player, стрим, музыка
# meta license: AGPL-3.0
# scope: heroku
# packages: ffmpeg
# requires: yt-dlp py-tgcalls

__version__ = (6, 9)

import asyncio
import builtins
import contextlib
import importlib
import importlib.machinery
import importlib.util
import inspect
import logging
import os
import re
import shutil
import site
import sys
import tempfile
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional, Tuple

from telethon.tl import functions, types
from telethon.tl.types import Message

from .. import loader, utils
from ..inline.types import InlineCall

logger = logging.getLogger(__name__)

def _ensure_site_packages():
    home = os.path.expanduser("~")
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        f"/root/.local/lib/{py_ver}/site-packages",
        f"/root/.local/lib/python3/site-packages",
        os.path.join(home, ".local", "lib", py_ver, "site-packages"),
        os.path.join(home, ".local", "lib", "python3", "site-packages"),
        f"/usr/local/lib/{py_ver}/site-packages",
        f"/usr/local/lib/{py_ver}/dist-packages",
        f"/usr/lib/{py_ver}/site-packages",
        f"/usr/lib/{py_ver}/dist-packages",
    ]

    try:
        user_site = site.getusersitepackages()
        if user_site and user_site not in candidates:
            candidates.insert(0, user_site)
    except Exception:
        pass

    for base in (home, "/root", "/var/root"):
        local_lib = os.path.join(base, ".local", "lib")
        if os.path.isdir(local_lib):
            try:
                for entry in os.scandir(local_lib):
                    if entry.is_dir() and entry.name.startswith("python"):
                        sp = os.path.join(entry.path, "site-packages")
                        if os.path.isdir(sp) and sp not in candidates:
                            candidates.insert(0, sp)
            except Exception:
                pass

    for p in candidates:
        if os.path.isdir(p):
            with contextlib.suppress(Exception):
                site.addsitedir(p)
            if p not in sys.path:
                sys.path.insert(0, p)

_ensure_site_packages()

HAS_PYTGCALLS = False
HAS_GROUP_CALL_FACTORY = False
PyTgCallsClass = None
GroupCallFactoryClass = None
MediaStreamClass = None
AudioPipedClass = None
AudioVideoPipedClass = None
RecordStreamClass = None
HighQualityAudioClass = None
HighQualityVideoClass = None
AudioQualityClass = None
VideoQualityClass = None
StreamTypeClass = None
PYTGCALLS_VERSION = "unknown"
PYTGCALLS_IMPORT_ERROR: Optional[str] = None


def _fix_heroku_import_hook():
    orig_import = builtins.__import__
    if getattr(orig_import, "_voicemod_fixed", False):
        return

    loader_mod = sys.modules.get("heroku.loader") or sys.modules.get("loader")
    native_import = getattr(loader_mod, "native_import", None) or importlib.__import__

    def _fixed_import(name, *args, **kwargs):
        level = kwargs.get("level", args[3] if len(args) >= 4 else 0)
        if (level > 0 and name.startswith("telethon")) or (
            name.startswith("telethon") and name != "telethon" and not name.startswith("telethon.")
        ):
            return native_import(name, *args, **kwargs)
        return orig_import(name, *args, **kwargs)

    _fixed_import._voicemod_fixed = True
    builtins.__import__ = _fixed_import

    if loader_mod and hasattr(loader_mod, "patched_import"):
        with contextlib.suppress(Exception):
            loader_mod_orig_native = getattr(loader_mod, "native_import", importlib.__import__)
            orig_patched = loader_mod.patched_import
            if not getattr(orig_patched, "_voicemod_fixed", False):
                def _loader_fixed_import(name, *args, **kwargs):
                    level = kwargs.get("level", args[3] if len(args) >= 4 else 0)
                    if (level > 0 and name.startswith("telethon")) or (
                        name.startswith("telethon") and name != "telethon" and not name.startswith("telethon.")
                    ):
                        return loader_mod_orig_native(name, *args, **kwargs)
                    return orig_patched(name, *args, **kwargs)

                _loader_fixed_import._voicemod_fixed = True
                loader_mod.patched_import = _loader_fixed_import


def _alias_pytgcalls_telethon_client():
    _fix_heroku_import_hook()
    try:
        import pytgcalls.mtproto.telethon_client as tc_mod
        sys.modules["pytgcalls.mtproto.herokutl_client"] = tc_mod
        mt_mod = sys.modules.get("pytgcalls.mtproto")
        if mt_mod:
            setattr(mt_mod, "herokutl_client", tc_mod)
    except Exception:
        pass


_fix_heroku_import_hook()


def _setup_telethon_alias():
    _fix_heroku_import_hook()
    _alias_pytgcalls_telethon_client()
    try:
        class _TelethonAliasLoader:
            def __init__(self, mod):
                self._mod = mod

            def create_module(self, spec):
                return self._mod

            def exec_module(self, module):
                pass

        class _TelethonAliasFinder:
            @classmethod
            def find_spec(cls, fullname: str, path=None, target=None):
                if fullname == "telethon" or fullname.startswith("telethon."):
                    alt_name = "herokutl" + fullname[8:]
                    try:
                        alt_mod = importlib.import_module(alt_name)
                        is_pkg = hasattr(alt_mod, "__path__")
                        loader = _TelethonAliasLoader(alt_mod)
                        spec = importlib.machinery.ModuleSpec(fullname, loader, is_package=is_pkg)
                        if is_pkg:
                            spec.submodule_search_locations = list(alt_mod.__path__)
                        return spec
                    except Exception:
                        pass
                return None

        if not any(getattr(f, "__name__", "") == "_TelethonAliasFinder" for f in sys.meta_path):
            sys.meta_path.insert(0, _TelethonAliasFinder)

        target_base = None
        for b in ("herokutl", "telethon"):
            if b in sys.modules:
                target_base = sys.modules[b]
                break
        if not target_base:
            with contextlib.suppress(Exception):
                target_base = importlib.import_module("herokutl")
        if target_base:
            base_name = getattr(target_base, "__name__", "herokutl")
            sys.modules.setdefault("telethon", target_base)
            for m_name, mod in list(sys.modules.items()):
                if m_name.startswith(f"{base_name}."):
                    alias = "telethon" + m_name[len(base_name):]
                    sys.modules.setdefault(alias, mod)
    except Exception as e:
        logger.debug(f"[RemakeVoiceMod] telethon alias error: {e}")


def _patch_bridged_client():
    patched = False

    bc_mod = sys.modules.get("pytgcalls.mtproto.bridged_client")
    if bc_mod and hasattr(bc_mod, "BridgedClient"):
        bc_mod.BridgedClient.package_name = staticmethod(lambda obj: "telethon")
        patched = True
        logger.debug("[RemakeVoiceMod] BridgedClient patched via sys.modules")

    mc_mod = sys.modules.get("pytgcalls.mtproto.mtproto_client")
    if mc_mod and hasattr(mc_mod, "BridgedClient"):
        mc_mod.BridgedClient.package_name = staticmethod(lambda obj: "telethon")
        patched = True
        logger.debug("[RemakeVoiceMod] BridgedClient patched via mtproto_client module")

    if not patched:
        try:
            from pytgcalls.mtproto.bridged_client import BridgedClient
            BridgedClient.package_name = staticmethod(lambda obj: "telethon")
            patched = True
            logger.debug("[RemakeVoiceMod] BridgedClient patched via direct import")
        except Exception as e:
            logger.warning(f"[RemakeVoiceMod] BridgedClient patch FAILED: {e}")

    try:
        env_mod = sys.modules.get("pytgcalls.environment")
        if env_mod and hasattr(env_mod, "Environment"):
            env_mod.Environment.check_environment = lambda self: None
        else:
            from pytgcalls.environment import Environment
            Environment.check_environment = lambda self: None
    except Exception as e:
        logger.debug(f"[RemakeVoiceMod] Environment patch error: {e}")

    _alias_pytgcalls_telethon_client()
    return patched


def _patch_telethon_client():
    try:
        tc_mod = sys.modules.get("pytgcalls.mtproto.telethon_client")
        if not tc_mod or not hasattr(tc_mod, "TelethonClient"):
            logger.debug("[RemakeVoiceMod] TelethonClient not in sys.modules, skipping patch")
            return
        TelethonClientCls = tc_mod.TelethonClient

        async def _patched_start(self):
            pass
        TelethonClientCls.start = _patched_start
        logger.debug("[RemakeVoiceMod] TelethonClient.start patched (no-op)")

        async def _patched_resolve_peer(self, user_id):
            try:
                return await self._app.get_input_entity(user_id)
            except Exception:
                with contextlib.suppress(Exception):
                    me = await self._app.get_me()
                    me_id = getattr(me, "id", None)
                    if me_id and (user_id == me_id or user_id in ("me", "self")):
                        from telethon.tl.types import InputPeerSelf
                        return InputPeerSelf()
                raise
        TelethonClientCls.resolve_peer = _patched_resolve_peer
        logger.debug("[RemakeVoiceMod] TelethonClient.resolve_peer patched")
    except Exception as e:
        logger.debug(f"[RemakeVoiceMod] TelethonClient patch error: {e}")


def _try_import_pytgcalls() -> Tuple[bool, Optional[str]]:
    global HAS_PYTGCALLS, PyTgCallsClass, PYTGCALLS_VERSION, PYTGCALLS_IMPORT_ERROR
    global GroupCallFactoryClass, HAS_GROUP_CALL_FACTORY
    global MediaStreamClass, AudioPipedClass, AudioVideoPipedClass, RecordStreamClass
    global HighQualityAudioClass, HighQualityVideoClass, AudioQualityClass, VideoQualityClass, StreamTypeClass

    _ensure_site_packages()
    _setup_telethon_alias()
    importlib.invalidate_caches()

    try:
        import pytgcalls
        HAS_PYTGCALLS = True
        PYTGCALLS_VERSION = getattr(pytgcalls, "__version__", "unknown")
    except Exception as e:
        HAS_PYTGCALLS = False
        PyTgCallsClass = None
        tb = traceback.format_exc()
        PYTGCALLS_IMPORT_ERROR = f"{e.__class__.__name__}: {e}\n{tb[-300:]}".strip()
        return False, PYTGCALLS_IMPORT_ERROR

    _patch_bridged_client()
    _alias_pytgcalls_telethon_client()

    try:
        from pytgcalls import PyTgCalls
        PyTgCallsClass = PyTgCalls
    except Exception as e:
        HAS_PYTGCALLS = False
        PyTgCallsClass = None
        tb = traceback.format_exc()
        PYTGCALLS_IMPORT_ERROR = f"PyTgCalls import: {e}\n{tb[-300:]}".strip()
        return False, PYTGCALLS_IMPORT_ERROR

    for mod_name in (
        "pytgcalls.types",
        "pytgcalls.types.stream",
        "pytgcalls.types.input_stream",
        "pytgcalls",
    ):
        try:
            m = importlib.import_module(mod_name)
            if hasattr(m, "MediaStream") and MediaStreamClass is None:
                MediaStreamClass = getattr(m, "MediaStream")
            if hasattr(m, "RecordStream") and RecordStreamClass is None:
                RecordStreamClass = getattr(m, "RecordStream")
            if hasattr(m, "AudioPiped") and AudioPipedClass is None:
                AudioPipedClass = getattr(m, "AudioPiped")
            if hasattr(m, "AudioVideoPiped") and AudioVideoPipedClass is None:
                AudioVideoPipedClass = getattr(m, "AudioVideoPiped")
            if hasattr(m, "AudioQuality") and AudioQualityClass is None:
                AudioQualityClass = getattr(m, "AudioQuality")
            if hasattr(m, "VideoQuality") and VideoQualityClass is None:
                VideoQualityClass = getattr(m, "VideoQuality")
            if hasattr(m, "StreamType") and StreamTypeClass is None:
                StreamTypeClass = getattr(m, "StreamType")
        except Exception:
            pass

    if AudioPipedClass is None and MediaStreamClass is not None:
        AudioPipedClass = MediaStreamClass

    for mod_name in (
        "pytgcalls.types.input_stream.quality",
        "pytgcalls.types.stream.quality",
        "pytgcalls.types.quality",
        "pytgcalls.types",
    ):
        try:
            m = importlib.import_module(mod_name)
            if hasattr(m, "HighQualityAudio") and HighQualityAudioClass is None:
                HighQualityAudioClass = getattr(m, "HighQualityAudio")
            if hasattr(m, "HighQualityVideo") and HighQualityVideoClass is None:
                HighQualityVideoClass = getattr(m, "HighQualityVideo")
        except Exception:
            pass

    try:
        from pytgcalls import GroupCallFactory
        GroupCallFactoryClass = GroupCallFactory
        HAS_GROUP_CALL_FACTORY = True
    except Exception:
        pass

    PYTGCALLS_IMPORT_ERROR = None
    return True, None


_try_import_pytgcalls()


@loader.tds
class RemakeVoiceMod(loader.Module):
    """Модуль для воспроизведения музыки, аудио и видео в голосовых чатах Telegram."""

    strings = {
        "name": "RemakeVoiceMod",
        "no_args": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Укажите ссылку, поисковый запрос или ответьте на аудио/видео!",
        "searching": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408834714523959238\">👁</tg-emoji> Поиск и обработка трека...",
        "downloading": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5411426838956248880\">📁</tg-emoji> Загрузка аудио...",
        "converting": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5411236022149219263\">⚙️</tg-emoji> Конвертация...",
        "playing": (
            "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5408850846421124323\">🎵</tg-emoji> Сейчас играет:</b>\n"
            "<tg-emoji emoji-id=\"5411614357228390551\">📌</tg-emoji> <b>Трек:</b> <code>{title}</code>\n"
            "<tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> <b>Длительность:</b> <code>{duration}</code>\n"
            "<tg-emoji emoji-id=\"5404796002156711053\">👨‍💻</tg-emoji> <b>Запросил:</b> {requester}\n"
            "<tg-emoji emoji-id=\"5411252368794746740\">📈</tg-emoji> <b>В очереди:</b> <code>{queue_len}</code>"
        ),
        "playing_video": (
            "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5332480894764614680\">🖥</tg-emoji> Сейчас транслируется видео:</b>\n"
            "<tg-emoji emoji-id=\"5411614357228390551\">📌</tg-emoji> <b>Видео:</b> <code>{title}</code>\n"
            "<tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> <b>Длительность:</b> <code>{duration}</code>\n"
            "<tg-emoji emoji-id=\"5404796002156711053\">👨‍💻</tg-emoji> <b>Запросил:</b> {requester}\n"
            "<tg-emoji emoji-id=\"5411252368794746740\">📈</tg-emoji> <b>В очереди:</b> <code>{queue_len}</code>"
        ),
        "queued": (
            "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5404723589008101395\">📦</tg-emoji> Добавлено в очередь (№{pos}):</b>\n"
            "{icon} <code>{title}</code> (<tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> {duration})"
        ),
        "paused": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5409328197676334300\">⏹</tg-emoji> Воспроизведение приостановлено.",
        "resumed": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5411341373402025345\">⏩</tg-emoji> Воспроизведение возобновлено.",
        "muted": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5409003906170651374\">🔇</tg-emoji> Микрофон заглушен.",
        "unmuted": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408901642999335517\">🔔</tg-emoji> Микрофон включен.",
        "skipped": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5411341373402025345\">⏩</tg-emoji> Трек пропущен.",
        "stopped": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5409328197676334300\">⏹</tg-emoji> Воспроизведение остановлено, очередь очищена.",
        "joined": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5407016517428610262\">🎤</tg-emoji> Подключился к голосовому чату.",
        "left": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5411397341120857044\">👣</tg-emoji> Покинул голосовой чат.",
        "not_joined": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Бот не находится в голосовом чате (используйте {p}vplay или {p}vjoin).",
        "empty_queue": "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5409105409132757277\">🫗</tg-emoji> Очередь пуста.",
        "queue_title": "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5332510792031959942\">📄</tg-emoji> Очередь воспроизведения ({count}):</b>\n\n{items}",
        "error": "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5409235172979672859\">⚠️</tg-emoji> Ошибка:</b> <code>{err}</code>",
        "no_pytgcalls": (
            "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Библиотека py-tgcalls не установлена или не может запуститься!</b>\n"
            "<tg-emoji emoji-id=\"5409235172979672859\">⚠️</tg-emoji> <b>Ошибка:</b> <code>{err}</code>\n\n"
            "Установите её через терминал: <code>{p}terminal pip install py-tgcalls yt-dlp</code>\n"
            "После установки перезапустите юзербота: <code>{p}restart</code>"
        ),
        "no_active_vc": (
            "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> В этом чате нет активного голосового чата!</b>\n"
            "Сначала включите голосовой чат в группе перед подключением."
        ),
        "ffmpeg_missing": (
            "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> FFmpeg не найден в системе!</b>\n\n"
            "FFmpeg необходим для трансляции звука и конвертации медиа.\n"
            "Установите его через пакетный менеджер вашего сервера."
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "auto_leave",
                True,
                lambda: "Автоматически выходить из голосового чата, когда очередь закончится",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "video_quality",
                "720p",
                lambda: "Качество видео стрима (360p / 480p / 720p / 1080p)",
                validator=loader.validators.Choice(["360p", "480p", "720p", "1080p"]),
            ),
            loader.ConfigValue(
                "auto_reconnect",
                True,
                lambda: "Автоматически переподключаться при неожиданном обрыве стрима",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "max_cache_mb",
                500,
                lambda: "Максимальный размер кеша временных файлов в МБ",
                validator=loader.validators.Integer(minimum=50, maximum=5000),
            ),
        )
        self._temp_dir: Optional[str] = None
        self._queue: Dict[int, List[Dict[str, Any]]] = {}
        self._current: Dict[int, Dict[str, Any]] = {}
        self._calls: Dict[int, Any] = {}
        self._muted: Dict[int, bool] = {}
        self._paused: Dict[int, bool] = {}
        self._loop: Dict[int, bool] = {}
        self._last_prefix: Optional[str] = None
        self._is_pytgcalls_client: bool = False
        self._tgcalls: Any = None
        self._active_tasks: List[asyncio.Task] = []
        self._expected_leave: set = set()
        self._reconnect_attempts: Dict[int, int] = {}
        self._track_start_time: Dict[int, float] = {}
        self._diag: Dict[str, Any] = {
            "init_error": None,
            "backend": "None",
        }

    async def client_ready(self, client=None, db=None):
        self._client = client or getattr(self, "_client", None) or getattr(self, "client", None)
        self._db = db or getattr(self, "_db", None) or getattr(self, "db", None)
        self._temp_dir = tempfile.mkdtemp(prefix="heroku_voicemod_")
        self._ensure_local_ffmpeg_path()
        self._last_prefix = self._prefix()

        _ensure_site_packages()
        _setup_telethon_alias()
        if self._client and hasattr(self._client, "_no_updates") is False:
            with contextlib.suppress(Exception):
                self._client._no_updates = False

        if self._client:
            success, err = _try_import_pytgcalls()
            if success and PyTgCallsClass is not None:
                try:
                    _patch_bridged_client()
                    _alias_pytgcalls_telethon_client()
                    self._tgcalls = PyTgCallsClass(self._client)
                    _patch_telethon_client()
                    try:
                        self._tgcalls.loop = asyncio.get_running_loop()
                    except Exception:
                        pass
                    start_res = self._tgcalls.start()
                    if inspect.isawaitable(start_res):
                        await start_res
                    self._is_pytgcalls_client = True
                    self._diag["backend"] = f"PyTgCalls (v{PYTGCALLS_VERSION})"
                    self._diag["init_error"] = None

                    for event_name in ("on_stream_end", "on_playout_ended"):
                        if hasattr(self._tgcalls, event_name):
                            try:
                                decorator = getattr(self._tgcalls, event_name)
                                @decorator()
                                async def _dyn_on_stream_end(app, update):
                                    chat_id = getattr(update, "chat_id", None) or getattr(update, "id", None)
                                    if chat_id:
                                        curr = self._current.get(chat_id)
                                        if curr:
                                            track_id = curr.get("track_id")
                                            task = asyncio.create_task(self._handle_track_end(chat_id, expected_track_id=track_id))
                                            self._active_tasks.append(task)
                            except Exception as e_stream_end:
                                logger.debug(f"[RemakeVoiceMod] Hook {event_name} failed: {e_stream_end}")
                                
                except Exception as e1:
                    logger.warning(f"[RemakeVoiceMod] Ошибка запуска PyTgCalls: {e1}")
                    tb1 = traceback.format_exc()
                    self._diag["init_error"] = f"PyTgCalls start error: {e1}\n{tb1[-300:]}".strip()
                    self._is_pytgcalls_client = False
            else:
                self._diag["init_error"] = err or "Библиотека py-tgcalls не установлена"

        if not self._is_pytgcalls_client and HAS_GROUP_CALL_FACTORY:
            self._diag["backend"] = "GroupCallFactory"

    async def _ensure_backend_ready(self) -> bool:
        if self._is_pytgcalls_client and self._tgcalls:
            return True

        client = getattr(self, "_client", None) or getattr(self, "client", None)
        if not client:
            self._diag["init_error"] = "Telegram клиент не готов (client_ready ещё не выполнен)"
            return False
        self._client = client

        success, err = _try_import_pytgcalls()
        if not success or PyTgCallsClass is None:
            self._diag["init_error"] = err or "Библиотека py-tgcalls не установлена"
            return False

        if hasattr(self._client, "_no_updates") is False:
            with contextlib.suppress(Exception):
                self._client._no_updates = False

        try:
            _patch_bridged_client()
            _alias_pytgcalls_telethon_client()
            self._tgcalls = PyTgCallsClass(self._client)
            _patch_telethon_client()
            try:
                self._tgcalls.loop = asyncio.get_running_loop()
            except Exception:
                pass
            start_res = self._tgcalls.start()
            if inspect.isawaitable(start_res):
                await start_res
            self._is_pytgcalls_client = True
            self._diag["backend"] = f"PyTgCalls (v{PYTGCALLS_VERSION})"
            self._diag["init_error"] = None

            for event_name in ("on_stream_end", "on_playout_ended"):
                if hasattr(self._tgcalls, event_name):
                    try:
                        decorator = getattr(self._tgcalls, event_name)
                        @decorator()
                        async def _dyn_on_stream_end(app, update):
                            chat_id = getattr(update, "chat_id", None) or getattr(update, "id", None)
                            if chat_id:
                                curr = self._current.get(chat_id)
                                if curr:
                                    track_id = curr.get("track_id")
                                    task = asyncio.create_task(self._handle_track_end(chat_id, expected_track_id=track_id))
                                    self._active_tasks.append(task)
                    except Exception as e_stream_end:
                        logger.debug(f"[RemakeVoiceMod] Hook {event_name} failed: {e_stream_end}")
            return True
        except Exception as e:
            logger.warning(f"[RemakeVoiceMod] _ensure_backend_ready error: {e}")
            tb2 = traceback.format_exc()
            self._diag["init_error"] = f"PyTgCalls start error: {e}\n{tb2[-300:]}".strip()
            return False

    async def on_unload(self):
        for task in self._active_tasks:
            if not task.done():
                task.cancel()

        for chat_id in list(self._calls.keys()):
            with contextlib.suppress(Exception):
                await self._leave_call(chat_id)

        if self._tgcalls and self._is_pytgcalls_client:
            with contextlib.suppress(Exception):
                if hasattr(self._tgcalls, "stop"):
                    res = self._tgcalls.stop()
                    if inspect.isawaitable(res):
                        await res

        if self._temp_dir and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _format_duration(self, seconds: Optional[int]) -> str:
        if not seconds or seconds <= 0:
            return "Стрим / Live"
        mins, secs = divmod(int(seconds), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _get_marked_chat_id(self, obj: Any) -> int:
        if obj is None:
            return 0
        try:
            import telethon.utils as tl_utils
            if hasattr(obj, "peer_id") and obj.peer_id is not None:
                return tl_utils.get_peer_id(obj.peer_id)
            if hasattr(obj, "id") and not isinstance(obj, int):
                return tl_utils.get_peer_id(obj)
            if hasattr(obj, "chat_id") and obj.chat_id is not None:
                return obj.chat_id
        except Exception:
            pass

        if isinstance(obj, int):
            if obj < 0:
                return obj
            if obj > 1000000000:
                return -1000000000000 - obj
            return -obj

        raw_id = utils.get_chat_id(obj)
        if raw_id > 0:
            if raw_id > 1000000000:
                return -1000000000000 - raw_id
            return -raw_id
        return raw_id

    async def _ensure_marked_chat_id(self, chat_id: int) -> int:
        if chat_id < 0:
            return chat_id
        try:
            entity = await self._client.get_entity(chat_id)
            import telethon.utils as tl_utils
            marked = tl_utils.get_peer_id(entity)
            if marked < 0:
                return marked
        except Exception:
            pass
        if chat_id > 1000000000:
            return -1000000000000 - chat_id
        return -chat_id

    async def _resolve_target(self, message: Message) -> Tuple[int, Any]:
        args = utils.get_args_raw(message)
        if args:
            parts = args.split(maxsplit=1)
            target = parts[0]
            if target.startswith("-100") or target.startswith("-") or target.isdigit() or target.startswith("@"):
                try:
                    target_val = int(target) if target.lstrip("-").isdigit() else target
                    entity = await self._client.get_entity(target_val)
                    chat_id = self._get_marked_chat_id(entity)
                    return chat_id, entity
                except Exception:
                    pass
        chat = await message.get_chat()
        chat_id = getattr(message, "chat_id", None)
        if chat_id is None and chat:
            chat_id = self._get_marked_chat_id(chat)
        if chat_id is None:
            chat_id = self._get_marked_chat_id(message)
        return chat_id, chat

    async def _get_active_call(self, chat_id: int) -> Optional[types.InputGroupCall]:
        chat_id = await self._ensure_marked_chat_id(chat_id)
        try:
            peer = await self._client.get_input_entity(chat_id)
            if isinstance(peer, types.InputPeerChannel):
                full = await self._client(functions.channels.GetFullChannelRequest(peer))
                return getattr(full.full_chat, "call", None)
            elif isinstance(peer, types.InputPeerChat):
                full = await self._client(functions.messages.GetFullChatRequest(peer.chat_id))
                return getattr(full.full_chat, "call", None)
        except Exception as e:
            logger.debug(f"[RemakeVoiceMod] Ошибка проверки group call: {e}")
        return None

    def _ensure_local_ffmpeg_path(self) -> None:
        candidate_dirs = [
            os.path.abspath("ffmpeg_bin"),
            os.path.expanduser("~/.local/bin"),
            os.path.join(tempfile.gettempdir(), "ffmpeg_bin"),
        ]
        path_env = os.environ.get("PATH", "")
        paths = path_env.split(os.pathsep)
        for c_dir in candidate_dirs:
            if os.path.isdir(c_dir):
                has_bin = any(
                    os.path.isfile(os.path.join(c_dir, name))
                    for name in ("ffmpeg", "ffmpeg.exe")
                )
                if has_bin and c_dir not in paths:
                    os.environ["PATH"] = c_dir + os.pathsep + os.environ.get("PATH", "")
                    paths.insert(0, c_dir)

    def _prefix(self, message_or_id: Optional[Any] = None) -> str:
        if message_or_id is not None:
            raw_text = (
                getattr(message_or_id, "raw_text", None)
                or getattr(message_or_id, "message", None)
                or getattr(message_or_id, "text", None)
            )
            if isinstance(raw_text, str) and raw_text:
                stripped = raw_text.strip()
                cmd_names = (
                    "vplay", "vvideo", "vjoin", "vleave", "vstop", "vpause",
                    "vresume", "vmute", "vunmute", "vskip", "vqueue", "vnow",
                    "vloop", "vplaylist"
                )
                pattern = r"^(.*?)(" + "|".join(cmd_names) + r")(?:\s|$)"
                m = re.match(pattern, stripped, flags=re.IGNORECASE)
                if m:
                    extracted = m.group(1).strip()
                    if extracted:
                        self._last_prefix = extracted
                        return extracted

                m2 = re.match(r"^(\S+?)[a-zA-Zа-яА-Я]", stripped)
                if m2:
                    extracted = m2.group(1).strip()
                    if extracted and len(extracted) <= 5:
                        self._last_prefix = extracted
                        return extracted

        ent_id = None
        if isinstance(message_or_id, int):
            ent_id = message_or_id
        elif message_or_id is not None:
            ent_id = getattr(message_or_id, "sender_id", None) or getattr(message_or_id, "from_id", None)

        if not ent_id:
            ent_id = getattr(self, "tg_id", None) or getattr(getattr(self, "_client", None), "tg_id", None)

        for fn in (
            getattr(self, "get_prefix", None),
            getattr(getattr(self, "allmodules", None), "get_prefix", None),
        ):
            if callable(fn):
                with contextlib.suppress(Exception):
                    if ent_id:
                        p = fn(ent_id)
                        if p and p != ".":
                            self._last_prefix = str(p)
                            return str(p)
                    p = fn()
                    if p and p != ".":
                        self._last_prefix = str(p)
                        return str(p)

        db = getattr(self, "_db", None) or getattr(self, "db", None)
        if db:
            for namespace in ("heroku.main", "__main__", "main"):
                with contextlib.suppress(Exception):
                    prefixes = db.get(namespace, "command_prefixes", {})
                    if prefixes and isinstance(prefixes, dict):
                        if ent_id and str(ent_id) in prefixes:
                            p = str(prefixes[str(ent_id)])
                            if p:
                                self._last_prefix = p
                                return p
                        for val in prefixes.values():
                            if val and val != ".":
                                self._last_prefix = str(val)
                                return str(val)

                    p = db.get(namespace, "command_prefix", None)
                    if p and p != ".":
                        self._last_prefix = str(p)
                        return str(p)

        for fn in (
            getattr(self, "get_prefixes", None),
            getattr(getattr(self, "allmodules", None), "get_prefixes", None),
        ):
            if callable(fn):
                with contextlib.suppress(Exception):
                    all_p = fn()
                    if all_p and isinstance(all_p, (set, list, tuple)):
                        for p in all_p:
                            if p and p != ".":
                                self._last_prefix = str(p)
                                return str(p)

        client_pref = getattr(getattr(self, "_client", None), "command_prefix", None)
        if client_pref and client_pref != ".":
            self._last_prefix = str(client_pref)
            return str(client_pref)

        if hasattr(self, "_last_prefix") and self._last_prefix:
            return self._last_prefix

        if db:
            with contextlib.suppress(Exception):
                p = db.get("heroku.main", "command_prefix", ".")
                if p:
                    return str(p)

        return "."

    def _str_no_pytgcalls(self, p: Optional[str] = None, err: Optional[str] = None) -> str:
        actual_p = p or self._prefix()
        actual_err = err or self._diag.get("init_error") or PYTGCALLS_IMPORT_ERROR or "Библиотека py-tgcalls не установлена"
        try:
            return self.strings("no_pytgcalls").format(p=actual_p, err=actual_err)
        except Exception:
            return (
                f"<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Библиотека py-tgcalls не установлена или не работает!</b>\n"
                f"<tg-emoji emoji-id=\"5409235172979672859\">⚠️</tg-emoji> <b>Ошибка:</b> <code>{actual_err}</code>\n\n"
                f"Установите её через терминал: <code>{actual_p}terminal pip install py-tgcalls yt-dlp</code>\n"
                f"После установки: <code>{actual_p}restart</code>"
            )

    def _is_ffmpeg_installed(self) -> Tuple[bool, Optional[str]]:
        self._ensure_local_ffmpeg_path()
        bin_path = shutil.which("ffmpeg")
        return (bool(bin_path), bin_path)

    async def _get_ffmpeg_version(self) -> str:
        has_ff, bin_path = self._is_ffmpeg_installed()
        if not has_ff:
            return "Не установлен"
        try:
            proc = await asyncio.create_subprocess_exec(
                bin_path,
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if stdout:
                lines = stdout.decode("utf-8", errors="ignore").splitlines()
                if lines:
                    return lines[0].strip()
        except Exception as e:
            logger.debug(f"[RemakeVoiceMod] Ошибка проверки версии ffmpeg: {e}")
        return "Установлен (версия неизвестна)"

    def _download_and_extract_static(self, url: str, is_zip: bool, dest_dir: str):
        os.makedirs(dest_dir, exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        tmp_archive = os.path.join(tempfile.gettempdir(), f"ffmpeg_dl_{uuid.uuid4().hex[:8]}")

        try:
            with urllib.request.urlopen(req, timeout=180) as resp, open(tmp_archive, "wb") as f_out:
                shutil.copyfileobj(resp, f_out)

            if is_zip:
                with zipfile.ZipFile(tmp_archive, "r") as z:
                    for member in z.namelist():
                        base = os.path.basename(member).lower()
                        if base in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
                            target_file = os.path.join(dest_dir, os.path.basename(member))
                            with z.open(member) as src, open(target_file, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            with contextlib.suppress(Exception):
                                os.chmod(target_file, 0o755)
            else:
                with tarfile.open(tmp_archive, "r:*") as tar:
                    for member in tar.getmembers():
                        base = os.path.basename(member.name).lower()
                        if base in ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"):
                            target_file = os.path.join(dest_dir, os.path.basename(member.name))
                            extracted_f = tar.extractfile(member)
                            if extracted_f:
                                with open(target_file, "wb") as dst:
                                    shutil.copyfileobj(extracted_f, dst)
                                with contextlib.suppress(Exception):
                                    os.chmod(target_file, 0o755)
        finally:
            if os.path.exists(tmp_archive):
                with contextlib.suppress(Exception):
                    os.remove(tmp_archive)

    async def _install_ffmpeg_routine(self, status_callback=None) -> Tuple[bool, str]:
        is_win = sys.platform.startswith("win")
        is_linux = sys.platform.startswith("linux")
        is_darwin = sys.platform.startswith("darwin")
        is_root = False
        if hasattr(os, "geteuid"):
            with contextlib.suppress(Exception):
                is_root = (os.geteuid() == 0)

        cmd = None
        if is_linux:
            if shutil.which("apt-get") or shutil.which("apt"):
                pm = shutil.which("apt-get") or shutil.which("apt")
                cmd = [pm, "install", "-y", "ffmpeg"]
            elif shutil.which("apk"):
                cmd = ["apk", "add", "--no-cache", "ffmpeg"]
            elif shutil.which("pacman"):
                cmd = ["pacman", "-Sy", "--noconfirm", "ffmpeg"]
            elif shutil.which("dnf"):
                cmd = ["dnf", "install", "-y", "ffmpeg"]
            elif shutil.which("pkg"):
                cmd = ["pkg", "install", "-y", "ffmpeg"]
            if cmd and not is_root and shutil.which("sudo"):
                cmd = ["sudo", *cmd]
        elif is_darwin:
            if shutil.which("brew"):
                cmd = ["brew", "install", "ffmpeg"]
        elif is_win:
            if shutil.which("winget"):
                cmd = ["winget", "install", "Gyan.FFmpeg", "--accept-package-agreements", "--accept-source-agreements"]
            elif shutil.which("choco"):
                cmd = ["choco", "install", "ffmpeg", "-y"]

        if cmd:
            if status_callback:
                await status_callback(f"Попытка установки через пакетный менеджер ({cmd[0]})...")
            try:
                utils.ensure_child_watcher()
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=300)
                if proc.returncode == 0:
                    self._ensure_local_ffmpeg_path()
                    has_ff, path = self._is_ffmpeg_installed()
                    if has_ff:
                        ver = await self._get_ffmpeg_version()
                        return True, f"Установлен через {cmd[0]}: {ver} ({path})"
            except Exception as e:
                logger.warning(f"[RemakeVoiceMod] Системный установщик не сработал: {e}")

        if status_callback:
            await status_callback("Скачивание портативного статического FFmpeg бинарника (~60-90 МБ)...")

        machine = platform.machine().lower()
        url = None
        is_zip = False

        if is_win:
            url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            is_zip = True
        elif is_darwin:
            url = "https://evermeet.cx/ffmpeg/getrelease/zip"
            is_zip = True
        elif is_linux:
            if "arm" in machine or "aarch64" in machine:
                url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
            else:
                url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
            is_zip = False

        if not url:
            return False, f"Не поддерживаемая ОС/архитектура для прямой загрузки: {sys.platform} ({machine})"

        dest_dir = os.path.abspath("ffmpeg_bin")
        try:
            os.makedirs(dest_dir, exist_ok=True)
            test_file = os.path.join(dest_dir, ".test_write")
            with open(test_file, "w") as f:
                f.write("1")
            os.remove(test_file)
        except Exception:
            dest_dir = os.path.join(tempfile.gettempdir(), "ffmpeg_bin")
            os.makedirs(dest_dir, exist_ok=True)

        try:
            await asyncio.to_thread(self._download_and_extract_static, url, is_zip, dest_dir)
        except Exception as dl_err:
            logger.error(f"[RemakeVoiceMod] Ошибка загрузки FFmpeg: {dl_err}", exc_info=True)
            return False, f"Ошибка загрузки бинарника: {dl_err}"

        self._ensure_local_ffmpeg_path()
        has_ff, path = self._is_ffmpeg_installed()
        if not has_ff:
            return False, f"Бинарник распакован в {dest_dir}, но не найден в PATH"

        ver = await self._get_ffmpeg_version()
        return True, f"{ver} ({path})"

    def _get_silence_file(self) -> str:
        silence_path = os.path.join(self._temp_dir, "silence.wav")
        if not os.path.exists(silence_path):
            try:
                import wave
                with wave.open(silence_path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(48000)
                    w.writeframes(b"\x00\x00" * 48000)
            except Exception:
                with open(silence_path, "wb") as f:
                    f.write(b"\x00" * 192000)
        return silence_path

    def _get_video_quality_params(self) -> Tuple[Any, int]:
        val = str(self.config.get("video_quality", "720p")).lower()
        mapping = {
            "360p": ("SD_360p", 360),
            "480p": ("SD_480p", 480),
            "720p": ("HD_720p", 720),
            "1080p": ("FHD_1080p", 1080),
        }
        attr, height = mapping.get(val, ("HD_720p", 720))
        param = getattr(VideoQualityClass, attr, None) if VideoQualityClass is not None else None
        return param, height

    def _get_cache_size(self) -> Tuple[int, int]:
        if not self._temp_dir or not os.path.exists(self._temp_dir):
            return 0, 0
        total_size = 0
        file_count = 0
        for entry in os.scandir(self._temp_dir):
            if entry.is_file():
                try:
                    total_size += entry.stat().st_size
                    file_count += 1
                except Exception:
                    pass
        return total_size, file_count

    def _enforce_cache_limit(self):
        if not self._temp_dir or not os.path.exists(self._temp_dir):
            return

        max_mb = self.config.get("max_cache_mb", 500)
        max_bytes = max_mb * 1024 * 1024

        total_size, _ = self._get_cache_size()
        if total_size <= max_bytes:
            return

        active_files = set()
        silence_file = os.path.join(self._temp_dir, "silence.raw")
        active_files.add(os.path.abspath(silence_file))

        for track in self._current.values():
            for k in ("file_path", "raw_path"):
                p = track.get(k)
                if p:
                    active_files.add(os.path.abspath(p))

        for q in self._queue.values():
            for track in q:
                for k in ("file_path", "raw_path"):
                    p = track.get(k)
                    if p:
                        active_files.add(os.path.abspath(p))

        candidates = []
        for entry in os.scandir(self._temp_dir):
            if entry.is_file():
                abs_p = os.path.abspath(entry.path)
                if abs_p not in active_files:
                    try:
                        st = entry.stat()
                        candidates.append((st.st_mtime, st.st_size, entry.path))
                    except Exception:
                        pass

        candidates.sort(key=lambda x: x[0])
        target_size = int(max_bytes * 0.75)

        for _, size, path in candidates:
            if total_size <= target_size:
                break
            with contextlib.suppress(Exception):
                os.remove(path)
                total_size -= size

    async def _extract_track_info(self, query: str, is_video: bool = False) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        _, max_height = self._get_video_quality_params()

        def _yt_extract():
            import yt_dlp
            fmt = f"best[height<={max_height}]/bestvideo[height<={max_height}]+bestaudio/best" if is_video else "bestaudio[ext=m4a]/bestaudio/best"
            ydl_opts = {
                "format": fmt,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "default_search": "ytsearch",
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                target = query if re.match(r"^https?://", query) else f"ytsearch1:{query}"
                info = ydl.extract_info(target, download=False)
                if "entries" in info and info["entries"]:
                    info = info["entries"][0]

                video_url = info.get("url")
                audio_url = None
                req_formats = info.get("requested_formats")
                if req_formats and len(req_formats) >= 2:
                    video_url = req_formats[0].get("url")
                    audio_url = req_formats[1].get("url")

                return {
                    "title": info.get("title", "Неизвестный трек"),
                    "duration": info.get("duration", 0),
                    "url": video_url,
                    "audio_url": audio_url,
                    "webpage_url": info.get("webpage_url", query),
                    "is_live": info.get("is_live", False),
                    "is_video": is_video,
                }

        return await loop.run_in_executor(None, _yt_extract)

    async def _convert_to_raw(self, source_path_or_url: str, output_path: str) -> bool:
        self._ensure_local_ffmpeg_path()
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", source_path_or_url,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", "2",
            "-ar", "48000",
            output_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            return proc.returncode == 0 and os.path.exists(output_path)
        except FileNotFoundError:
            logger.error("[RemakeVoiceMod] FFmpeg не найден в системе!")
            return False
        except Exception as e:
            logger.error(f"[RemakeVoiceMod] Ошибка конвертации FFmpeg: {e}")
            return False

    def _spawn_monitor(self, chat_id: int, track_id: str, duration: int):
        async def monitor():
            while True:
                await asyncio.sleep(1.5)
                curr = self._current.get(chat_id)
                if not curr or curr.get("track_id") != track_id:
                    break
                
                is_paused = self._paused.get(chat_id, False)
                start_t = self._track_start_time.get(chat_id, 0)
                
                if is_paused:
                    self._track_start_time[chat_id] = start_t + 1.5
                    continue
                    
                elapsed = time.time() - start_t
                
                if duration > 0 and elapsed >= duration + 3.0:
                    logger.info(f"[RemakeVoiceMod] Монитор зафиксировал окончание трека для {chat_id}.")
                    await self._handle_track_end(chat_id, expected_track_id=track_id)
                    break

        task = asyncio.create_task(monitor())
        self._active_tasks.append(task)

    async def _play_stream(self, chat_id: int, track: Dict[str, Any]):
        chat_id = await self._ensure_marked_chat_id(chat_id)
        
        track_id = uuid.uuid4().hex
        track["track_id"] = track_id
        
        self._current[chat_id] = track
        self._paused[chat_id] = False
        self._muted[chat_id] = False

        is_video = bool(track.get("is_video", False))

        if self._is_pytgcalls_client and self._tgcalls:
            stream_source = track.get("url") or track.get("file_path")
            audio_source = track.get("audio_url")
            stream = stream_source

            if is_video:
                video_param, _ = self._get_video_quality_params()
                if MediaStreamClass is not None:
                    try:
                        ms_kwargs = {}
                        if video_param is not None:
                            ms_kwargs["video_parameters"] = video_param
                        elif VideoQualityClass is not None and hasattr(VideoQualityClass, "HD_720p"):
                            ms_kwargs["video_parameters"] = getattr(VideoQualityClass, "HD_720p")
                        if AudioQualityClass is not None and hasattr(AudioQualityClass, "HIGH"):
                            ms_kwargs["audio_parameters"] = getattr(AudioQualityClass, "HIGH")
                        if audio_source:
                            ms_kwargs["audio_path"] = audio_source
                        stream = MediaStreamClass(stream_source, **ms_kwargs)
                    except Exception as e_ms:
                        logger.debug(f"[RemakeVoiceMod] MediaStream video wrap failed: {e_ms}")
                        stream = stream_source
                elif AudioVideoPipedClass is not None:
                    try:
                        piped_args = []
                        if HighQualityAudioClass is not None:
                            piped_args.append(HighQualityAudioClass())
                        if HighQualityVideoClass is not None:
                            piped_args.append(HighQualityVideoClass())
                        stream = AudioVideoPipedClass(stream_source, *piped_args)
                    except Exception as e_av:
                        logger.debug(f"[RemakeVoiceMod] AudioVideoPiped wrap failed: {e_av}")
                        stream = stream_source
                elif AudioPipedClass is not None:
                    stream = AudioPipedClass(stream_source)
            else:
                if MediaStreamClass is not None:
                    try:
                        ms_kwargs = {}
                        flags = getattr(MediaStreamClass, "Flags", None)
                        ignore_flag = getattr(flags, "IGNORE", None) if flags else None
                        if ignore_flag is not None:
                            ms_kwargs["video_flags"] = ignore_flag
                        if AudioQualityClass is not None and hasattr(AudioQualityClass, "HIGH"):
                            ms_kwargs["audio_parameters"] = getattr(AudioQualityClass, "HIGH")
                        stream = MediaStreamClass(stream_source, **ms_kwargs)
                    except Exception as e_ms:
                        logger.debug(f"[RemakeVoiceMod] MediaStream audio wrap failed: {e_ms}")
                        stream = stream_source
                elif AudioPipedClass is not None:
                    try:
                        if HighQualityAudioClass is not None:
                            stream = AudioPipedClass(stream_source, HighQualityAudioClass())
                        else:
                            stream = AudioPipedClass(stream_source)
                    except Exception as e_pipe:
                        logger.debug(f"[RemakeVoiceMod] AudioPiped wrap failed: {e_pipe}")
                        stream = stream_source

            if hasattr(self._tgcalls, "play"):
                try:
                    res = self._tgcalls.play(chat_id, stream)
                    if inspect.isawaitable(res):
                        await res
                    self._track_start_time[chat_id] = time.time()
                    self._expected_leave.discard(chat_id)
                    self._spawn_monitor(chat_id, track_id, track.get("duration", 0))
                    return
                except Exception as e_play:
                    logger.warning(f"[RemakeVoiceMod] self._tgcalls.play failed ({e_play})")
                    if not hasattr(self._tgcalls, "join_group_call"):
                        raise RuntimeError(f"PyTgCalls: {e_play}")

            if hasattr(self._tgcalls, "join_group_call"):
                try:
                    kwargs = {}
                    if StreamTypeClass is not None:
                        with contextlib.suppress(Exception):
                            kwargs["stream_type"] = StreamTypeClass().pulse_stream
                    res = self._tgcalls.join_group_call(chat_id, stream, **kwargs)
                    if inspect.isawaitable(res):
                        await res
                    self._track_start_time[chat_id] = time.time()
                    self._expected_leave.discard(chat_id)
                    self._spawn_monitor(chat_id, track_id, track.get("duration", 0))
                    return
                except Exception as e1:
                    if hasattr(self._tgcalls, "change_stream"):
                        try:
                            res = self._tgcalls.change_stream(chat_id, stream)
                            if inspect.isawaitable(res):
                                await res
                            self._track_start_time[chat_id] = time.time()
                            self._expected_leave.discard(chat_id)
                            self._spawn_monitor(chat_id, track_id, track.get("duration", 0))
                            return
                        except Exception as e2:
                            logger.error(f"[RemakeVoiceMod] Ошибка PyTgCalls join/change: {e1} | {e2}")
                            raise RuntimeError(f"PyTgCalls: {e1}")
                    raise RuntimeError(f"PyTgCalls: {e1}")

        if HAS_GROUP_CALL_FACTORY:
            raw_path = os.path.join(self._temp_dir, f"vc_{abs(chat_id)}_{uuid.uuid4().hex[:6]}.raw")
            source = track.get("url") or track.get("file_path")
            success = await self._convert_to_raw(source, raw_path)
            if not success:
                raise RuntimeError("Ошибка конвертации FFmpeg (проверьте наличие ffmpeg в системе)")

            track["raw_path"] = raw_path

            if chat_id not in self._calls:
                factory = GroupCallFactoryClass(
                    self._client,
                    GroupCallFactoryClass.MTPROTO_CLIENT_TYPE.TELETHON,
                )
                call = factory.get_file_group_call(raw_path)
                self._calls[chat_id] = call

                try:
                    await call.start(chat_id)
                except Exception:
                    entity = await self._client.get_entity(chat_id)
                    await call.start(getattr(entity, "id", chat_id))
            else:
                call = self._calls[chat_id]
                old_raw = track.get("raw_path")
                if old_raw and old_raw != raw_path and os.path.exists(old_raw):
                    with contextlib.suppress(Exception):
                        os.remove(old_raw)
                call.input_filename = raw_path
            
            self._track_start_time[chat_id] = time.time()
            self._expected_leave.discard(chat_id)
            self._spawn_monitor(chat_id, track_id, track.get("duration", 0))
            return

        raise RuntimeError(self._str_no_pytgcalls(self._prefix()))

    async def _pytgcalls_call(self, method_names: List[str], chat_id: int) -> bool:
        if not self._tgcalls:
            return False
        chat_id = await self._ensure_marked_chat_id(chat_id)
        for name in method_names:
            if hasattr(self._tgcalls, name):
                try:
                    func = getattr(self._tgcalls, name)
                    res = func(chat_id)
                    if inspect.isawaitable(res):
                        await res
                    return True
                except Exception as e:
                    logger.debug(f"[RemakeVoiceMod] Call {name} failed: {e}")
        return False

    async def _handle_track_end(self, chat_id: int, force_skip: bool = False, expected_track_id: str = None):
        if chat_id in self._expected_leave:
            return

        current = self._current.get(chat_id)
        if not current:
            return
            
        if expected_track_id and current.get("track_id") != expected_track_id:
            return

        if self.config["auto_reconnect"]:
            start_t = self._track_start_time.get(chat_id, 0)
            elapsed = time.time() - start_t
            duration = current.get("duration", 0)
            is_live = current.get("is_live", False)
            
            premature = is_live or (duration > 0 and elapsed < (duration - 8))
            if premature and not force_skip:
                attempts = self._reconnect_attempts.get(chat_id, 0)
                if attempts < 3:
                    vc_call = await self._get_active_call(chat_id)
                    if vc_call:
                        self._reconnect_attempts[chat_id] = attempts + 1
                        logger.info(f"[RemakeVoiceMod] Premature stream end in {chat_id}. Reconnecting ({attempts + 1}/3)...")
                        await asyncio.sleep(2)
                        
                        if current.get("webpage_url") and not current.get("file_path"):
                            try:
                                info = await self._extract_track_info(current["webpage_url"], is_video=current.get("is_video", False))
                                current["url"] = info["url"]
                                if "audio_url" in info:
                                    current["audio_url"] = info["audio_url"]
                            except Exception:
                                pass

                        try:
                            await self._play_stream(chat_id, current)
                            return
                        except Exception as e_rec:
                            logger.warning(f"[RemakeVoiceMod] Reconnect attempt {attempts + 1} failed: {e_rec}")

        self._reconnect_attempts.pop(chat_id, None)
        self._track_start_time.pop(chat_id, None)

        if self._loop.get(chat_id) and not force_skip:
            current_copy = current.copy()
            queue = self._queue.setdefault(chat_id, [])
            queue.insert(0, current_copy)

        current = self._current.pop(chat_id, None)

        if current:
            raw_path = current.get("raw_path")
            if raw_path and os.path.exists(raw_path):
                with contextlib.suppress(Exception):
                    os.remove(raw_path)
            
            file_path = current.get("file_path")
            if file_path and os.path.exists(file_path):
                in_use = any(t.get("file_path") == file_path for t in self._queue.get(chat_id, []))
                if not in_use:
                    with contextlib.suppress(Exception):
                        os.remove(file_path)

        queue = self._queue.get(chat_id, [])
        if queue:
            next_track = queue.pop(0)
            
            if next_track.get("webpage_url") and not next_track.get("file_path"):
                try:
                    info = await self._extract_track_info(next_track["webpage_url"], is_video=next_track.get("is_video", False))
                    next_track["url"] = info["url"]
                    if "audio_url" in info:
                        next_track["audio_url"] = info["audio_url"]
                except Exception as e:
                    logger.debug(f"[RemakeVoiceMod] Error updating url for queue/loop: {e}")

            try:
                await self._play_stream(chat_id, next_track)
                
                text = self._format_now_playing(chat_id)
                buttons = self._get_player_buttons(chat_id)
                try:
                    me_id = getattr(self._client, "tg_id", None)
                    if not me_id:
                        me = await self._client.get_me()
                        me_id = me.id
                        
                    form_msg = await self.inline.form(
                        text=text,
                        reply_markup=buttons,
                        message=me_id,
                    )
                    
                    if form_msg:
                        with contextlib.suppress(Exception):
                            await form_msg.delete()
                        
                except Exception as form_e:
                    logger.debug(f"[RemakeVoiceMod] Не удалось отправить пульт: {form_e}")
                    
            except Exception as e:
                logger.error(f"[RemakeVoiceMod] Next track play failed: {e}")
        else:
            if self.config["auto_leave"]:
                await self._leave_call(chat_id)

        self._enforce_cache_limit()

    async def _leave_call(self, chat_id: int):
        chat_id = await self._ensure_marked_chat_id(chat_id)
        self._expected_leave.add(chat_id)
        self._reconnect_attempts.pop(chat_id, None)
        self._track_start_time.pop(chat_id, None)

        if self._is_pytgcalls_client and self._tgcalls:
            with contextlib.suppress(Exception):
                await self._pytgcalls_call(["leave_group_call", "leave_call", "leave"], chat_id)

        if chat_id in self._calls:
            with contextlib.suppress(Exception):
                await self._calls[chat_id].stop()
            del self._calls[chat_id]

        queue = self._queue.pop(chat_id, [])
        for item in queue:
            for key in ("file_path", "raw_path"):
                path = item.get(key)
                if path and os.path.exists(path):
                    with contextlib.suppress(Exception):
                        os.remove(path)

        current = self._current.pop(chat_id, None)
        if current:
            for key in ("file_path", "raw_path"):
                path = current.get(key)
                if path and os.path.exists(path):
                    with contextlib.suppress(Exception):
                        os.remove(path)

        self._muted.pop(chat_id, None)
        self._paused.pop(chat_id, None)
        self._loop.pop(chat_id, None)

    def _get_player_buttons(self, chat_id: int) -> List[List[Dict[str, Any]]]:
        is_paused = self._paused.get(chat_id, False)
        is_muted = self._muted.get(chat_id, False)
        is_loop = self._loop.get(chat_id, False)

        btn_pp = {
            "text": "▶️ Играть" if is_paused else "⏸ Пауза",
            "callback": self._cb_toggle_play,
            "args": (chat_id,),
        }
        btn_mm = {
            "text": "🔈 Включить" if is_muted else "🔇 Заглушить",
            "callback": self._cb_toggle_mute,
            "args": (chat_id,),
        }
        btn_skip = {
            "text": "⏭ След.",
            "callback": self._cb_skip,
            "args": (chat_id,),
        }
        btn_stop = {
            "text": "⏹ Стоп",
            "callback": self._cb_stop,
            "args": (chat_id,),
        }
        btn_queue = {
            "text": "📋 Очередь",
            "callback": self._cb_show_queue,
            "args": (chat_id,),
        }
        btn_loop = {
            "text": "🔁 Выкл. повтор" if is_loop else "🔁 Вкл. повтор",
            "callback": self._cb_toggle_loop,
            "args": (chat_id,),
        }

        return [
            [btn_pp, btn_mm],
            [btn_loop, btn_skip],
            [btn_queue, btn_stop],
        ]

    async def _cb_toggle_play(self, call: InlineCall, chat_id: int):
        is_paused = self._paused.get(chat_id, False)
        try:
            if self._is_pytgcalls_client and self._tgcalls:
                methods = ["resume", "resume_stream"] if is_paused else ["pause", "pause_stream"]
                await self._pytgcalls_call(methods, chat_id)
            elif chat_id in self._calls:
                if is_paused:
                    self._calls[chat_id].resume_playout()
                else:
                    self._calls[chat_id].pause_playout()

            self._paused[chat_id] = not is_paused
            await call.edit(
                self._format_now_playing(chat_id),
                reply_markup=self._get_player_buttons(chat_id),
            )
            await call.answer("Воспроизведение возобновлено." if is_paused else "Воспроизведение приостановлено.")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)

    async def _cb_toggle_mute(self, call: InlineCall, chat_id: int):
        is_muted = self._muted.get(chat_id, False)
        try:
            if self._is_pytgcalls_client and self._tgcalls:
                methods = ["unmute", "unmute_stream"] if is_muted else ["mute", "mute_stream"]
                await self._pytgcalls_call(methods, chat_id)
            elif chat_id in self._calls:
                self._calls[chat_id].set_is_mute(not is_muted)

            self._muted[chat_id] = not is_muted
            await call.edit(
                self._format_now_playing(chat_id),
                reply_markup=self._get_player_buttons(chat_id),
            )
            await call.answer("Микрофон включен." if is_muted else "Микрофон заглушен.")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)

    async def _cb_toggle_loop(self, call: InlineCall, chat_id: int):
        is_loop = self._loop.get(chat_id, False)
        self._loop[chat_id] = not is_loop
        
        try:
            temp_msg = await self._client.send_message("me", f"/vloop {chat_id}")
            await temp_msg.delete()
        except Exception as e:
            logger.debug(f"[RemakeVoiceMod] Ошибка отправки vloop в избранное: {e}")

        await call.edit(
            self._format_now_playing(chat_id),
            reply_markup=self._get_player_buttons(chat_id),
        )
        await call.answer("Повтор включен" if not is_loop else "Повтор выключен")

    async def _cb_skip(self, call: InlineCall, chat_id: int):
        queue = self._queue.get(chat_id, [])
        if not queue and chat_id not in self._current:
            await call.answer("Очередь пуста!", show_alert=True)
            return

        await call.answer("⏭ Пропускаем трек...")
        curr = self._current.get(chat_id)
        if curr:
            await self._handle_track_end(chat_id, force_skip=True, expected_track_id=curr.get("track_id"))
        else:
            await self._handle_track_end(chat_id, force_skip=True)
            
        if chat_id not in self._current:
            await call.edit(self.strings("stopped"))

    async def _cb_stop(self, call: InlineCall, chat_id: int):
        await self._leave_call(chat_id)
        await call.answer("Воспроизведение остановлено.")
        await call.edit(self.strings("stopped"))

    async def _cb_show_queue(self, call: InlineCall, chat_id: int):
        queue = self._queue.get(chat_id, [])
        if not queue:
            await call.answer("Очередь пуста!", show_alert=True)
            return

        lines = []
        for i, item in enumerate(queue[:10], start=1):
            dur = self._format_duration(item.get("duration"))
            lines.append(f"<b>{i}.</b> <code>{item['title']}</code> (<tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> {dur})")

        text = self.strings("queue_title").format(
            count=len(queue),
            items="\n".join(lines),
        )
        markup = [
            [
                {
                    "text": "◀️ Назад к плееру",
                    "callback": self._cb_back_to_player,
                    "args": (chat_id,),
                }
            ]
        ]
        await call.edit(text, reply_markup=markup)

    async def _cb_back_to_player(self, call: InlineCall, chat_id: int):
        if chat_id not in self._current:
            await call.edit(self.strings("stopped"))
            return
        await call.edit(
            self._format_now_playing(chat_id),
            reply_markup=self._get_player_buttons(chat_id),
        )

    def _format_now_playing(self, chat_id: int) -> str:
        current = self._current.get(chat_id)
        if not current:
            return self.strings("empty_queue")

        queue_len = len(self._queue.get(chat_id, []))
        is_video = current.get("is_video", False)
        template_key = "playing_video" if is_video else "playing"
        return self.strings(template_key).format(
            title=current["title"],
            duration=self._format_duration(current.get("duration")),
            requester=current.get("requester", "Аноним"),
            queue_len=f"{queue_len} трек(ов)",
        )

    async def _play_common(self, message: Message, is_video: bool = False):
        p = self._prefix(message)
        ready = await self._ensure_backend_ready()
        if not ready and not HAS_GROUP_CALL_FACTORY:
            return await utils.answer(
                message,
                self._str_no_pytgcalls(p),
            )

        has_ffmpeg, _ = self._is_ffmpeg_installed()
        if not has_ffmpeg:
            return await utils.answer(message, self.strings("ffmpeg_missing").format(p=p))

        chat_id, _ = await self._resolve_target(message)
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()

        query = args.strip() if args else ""
        if query and (query.split()[0].startswith("-100") or query.split()[0].startswith("@")):
            parts = query.split(maxsplit=1)
            query = parts[1] if len(parts) > 1 else ""

        if not query and not (reply and reply.media):
            return await utils.answer(message, self.strings("no_args"))

        active_call = await self._get_active_call(chat_id)
        if not active_call:
            return await utils.answer(message, self.strings("no_active_vc"))

        msg = await utils.answer(message, self.strings("searching"))

        sender = await message.get_sender()
        requester = f"@{sender.username}" if sender and getattr(sender, "username", None) else (
            sender.first_name if sender else "Пользователь"
        )

        track: Optional[Dict[str, Any]] = None

        if reply and reply.media:
            msg = await utils.answer(msg, self.strings("downloading"))
            is_media_video = bool(getattr(reply, "video", False) or getattr(reply, "video_note", False))
            ext = ".mp4" if is_media_video else (".ogg" if getattr(reply, "voice", False) else ".mp3")

            temp_file = os.path.join(self._temp_dir, f"dl_{uuid.uuid4().hex[:8]}{ext}")
            await reply.download_media(file=temp_file)
            self._enforce_cache_limit()

            title = "Медиафайл"
            if reply.file and reply.file.name:
                title = reply.file.name
            elif getattr(reply, "voice", False):
                title = "Голосовое сообщение"
            elif getattr(reply, "video_note", False):
                title = "Видеосообщение"
            elif is_media_video:
                title = "Видео"
            elif getattr(reply, "audio", False):
                title = "Аудиозапись"

            duration = 0
            if reply.file and hasattr(reply.file, "duration"):
                duration = reply.file.duration or 0

            track = {
                "title": title,
                "duration": duration,
                "file_path": temp_file,
                "requester": requester,
                "is_video": is_video or is_media_video,
            }

        elif query:
            try:
                info = await self._extract_track_info(query, is_video=is_video)
                track = {
                    "title": info["title"],
                    "duration": info["duration"],
                    "url": info["url"],
                    "audio_url": info.get("audio_url"),
                    "webpage_url": info["webpage_url"],
                    "requester": requester,
                    "is_video": is_video,
                }
            except Exception as e:
                return await utils.answer(msg, self.strings("error").format(err=f"yt-dlp: {e}"))

        if not track:
            return await utils.answer(msg, self.strings("error").format(err="Не удалось извлечь медиа"))

        if chat_id in self._current:
            self._queue.setdefault(chat_id, []).append(track)
            pos = len(self._queue[chat_id])
            dur = self._format_duration(track.get("duration"))
            media_icon = "<tg-emoji emoji-id=\"5332480894764614680\">🖥</tg-emoji>" if track.get("is_video") else "<tg-emoji emoji-id=\"5408850846421124323\">🎵</tg-emoji>"
            return await utils.answer(
                msg,
                self.strings("queued").format(pos=pos, icon=media_icon, title=track["title"], duration=dur),
            )

        try:
            await self._play_stream(chat_id, track)
            text = self._format_now_playing(chat_id)
            buttons = self._get_player_buttons(chat_id)
            await self.inline.form(
                message=msg,
                text=text,
                reply_markup=buttons,
            )
        except Exception as e:
            logger.error(f"[RemakeVoiceMod] Ошибка запуска стрима: {e}", exc_info=True)
            await utils.answer(msg, self.strings("error").format(err=str(e)))

    @loader.command()
    async def vplay(self, message: Message):
        """[чат] <ссылка/поиск/реплай> - Включить или добавить трек в очередь голосового чата"""
        await self._play_common(message, is_video=False)

    @loader.command()
    async def vvideo(self, message: Message):
        """[чат] <ссылка/поиск/реплай> - Воспроизвести видео со звуком в голосовом чате"""
        await self._play_common(message, is_video=True)

    @loader.command()
    async def vnow(self, message: Message):
        """[чат] - Показать текущий трек и инлайн-пульт управления"""
        self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        if chat_id not in self._current:
            return await utils.answer(message, self.strings("empty_queue"))

        text = self._format_now_playing(chat_id)
        buttons = self._get_player_buttons(chat_id)
        await self.inline.form(
            message=message,
            text=text,
            reply_markup=buttons,
        )

    @loader.command()
    async def vqueue(self, message: Message):
        """[чат] - Показать очередь воспроизведения"""
        self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        queue = self._queue.get(chat_id, [])
        if not queue and chat_id not in self._current:
            return await utils.answer(message, self.strings("empty_queue"))

        lines = []
        if chat_id in self._current:
            curr = self._current[chat_id]
            lines.append(f"<tg-emoji emoji-id=\"5411341373402025345\">⏩</tg-emoji> <b>Сейчас:</b> <code>{curr['title']}</code> (<tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> {self._format_duration(curr.get('duration'))})")

        for i, item in enumerate(queue, start=1):
            dur = self._format_duration(item.get("duration"))
            lines.append(f"<b>{i}.</b> <code>{item['title']}</code> (<tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> {dur})")

        await utils.answer(
            message,
            self.strings("queue_title").format(
                count=len(queue) + (1 if chat_id in self._current else 0),
                items="\n".join(lines),
            ),
        )

    @loader.command()
    async def vloop(self, message: Message):
        """[чат] - Включить/выключить постоянный повтор текущего трека/видео"""
        chat_id, _ = await self._resolve_target(message)
        if chat_id not in self._current:
            return await utils.answer(message, "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Нет активного трека или видео для повтора.")
        
        current_loop = self._loop.get(chat_id, False)
        self._loop[chat_id] = not current_loop
        status = "включен" if not current_loop else "выключен"
        
        try:
            temp_msg = await self._client.send_message("me", f"/vloop {chat_id}")
            await temp_msg.delete()
        except Exception as e:
            logger.debug(f"[RemakeVoiceMod] Ошибка отправки vloop в избранное: {e}")
            
        await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5404857686477015710\">🔄</tg-emoji> Повтор текущего трека/видео <b>{status}</b>.")

    @loader.command()
    async def vplaylist(self, message: Message):
        """[save/load/list/del] [название] - Управление плейлистами"""
        p = self._prefix(message)
        args = utils.get_args_raw(message).strip().split(maxsplit=1)
        action = args[0].lower() if len(args) > 0 else "list"
        name = args[1] if len(args) > 1 else None

        db = getattr(self, "_db", getattr(self, "db", None))
        if not db:
            return await utils.answer(message, "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> База данных недоступна.")

        playlists = db.get("RemakeVoiceMod", "playlists", {})

        if action in ("list", "ls"):
            if not playlists:
                return await utils.answer(message, "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5409105409132757277\">🫗</tg-emoji> У вас нет сохраненных плейлистов.")
            
            text = "<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5332510792031959942\">📄</tg-emoji> Ваши плейлисты:</b>\n\n"
            for pl_name, tracks in playlists.items():
                text += f"▪️ <code>{pl_name}</code> — {len(tracks)} треков\n"
            text += f"\n<i>Загрузить:</i> <code>{p}vplaylist load название</code>"
            return await utils.answer(message, text)

        if action == "save":
            if not name:
                return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Укажите название плейлиста: <code>{p}vplaylist save MyMix</code>")
            
            chat_id, _ = await self._resolve_target(message)
            current = self._current.get(chat_id)
            queue = self._queue.get(chat_id, [])
            
            all_tracks = []
            if current:
                all_tracks.append(current)
            all_tracks.extend(queue)
            
            saved_tracks = []
            for t in all_tracks:
                if t.get("webpage_url"):
                    saved_tracks.append({
                        "title": t.get("title", "Unknown Track"),
                        "webpage_url": t["webpage_url"],
                        "duration": t.get("duration", 0),
                        "is_video": t.get("is_video", False)
                    })
            
            if not saved_tracks:
                return await utils.answer(message, "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Очередь пуста или треки не поддерживают сохранение (локальные файлы).")
            
            playlists[name] = saved_tracks
            db.set("RemakeVoiceMod", "playlists", playlists)
            return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5404754074685966817\">✅</tg-emoji> Плейлист <code>{name}</code> сохранен ({len(saved_tracks)} треков)!")

        if action == "load":
            if not name:
                return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Укажите название плейлиста: <code>{p}vplaylist load MyMix</code>")
            if name not in playlists:
                return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Плейлист <code>{name}</code> не найден.")
            
            ready = await self._ensure_backend_ready()
            if not ready and not HAS_GROUP_CALL_FACTORY:
                return await utils.answer(message, self._str_no_pytgcalls(p))
            
            chat_id, _ = await self._resolve_target(message)
            active_call = await self._get_active_call(chat_id)
            if not active_call:
                return await utils.answer(message, self.strings("no_active_vc"))

            sender = await message.get_sender()
            requester = f"@{sender.username}" if sender and getattr(sender, "username", None) else (
                sender.first_name if sender else "Пользователь"
            )

            tracks_to_load = playlists[name]
            msg = await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> Загрузка плейлиста <code>{name}</code>...")
            
            for st in tracks_to_load:
                self._queue.setdefault(chat_id, []).append({
                    "title": st["title"],
                    "webpage_url": st["webpage_url"],
                    "duration": st.get("duration", 0),
                    "is_video": st.get("is_video", False),
                    "requester": requester
                })
            
            if chat_id not in self._current and self._queue.get(chat_id):
                first_track = self._queue[chat_id].pop(0)
                await utils.answer(msg, "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408834714523959238\">👁</tg-emoji> Извлечение первого трека...")
                
                try:
                    info = await self._extract_track_info(first_track["webpage_url"], is_video=first_track.get("is_video", False))
                    first_track["url"] = info["url"]
                    if "audio_url" in info:
                        first_track["audio_url"] = info["audio_url"]
                except Exception as e:
                    return await utils.answer(msg, f"<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5409235172979672859\">⚠️</tg-emoji> Ошибка извлечения трека:</b> <code>{e}</code>")

                try:
                    await self._play_stream(chat_id, first_track)
                    text = self._format_now_playing(chat_id)
                    buttons = self._get_player_buttons(chat_id)
                    await self.inline.form(message=msg, text=text, reply_markup=buttons)
                except Exception as e:
                    await utils.answer(msg, f"<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5409235172979672859\">⚠️</tg-emoji> Ошибка воспроизведения:</b> <code>{e}</code>")
            else:
                await utils.answer(msg, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5404754074685966817\">✅</tg-emoji> Плейлист <code>{name}</code> ({len(tracks_to_load)} треков) добавлен в очередь!")
            return

        if action in ("delete", "del", "rm"):
            if not name:
                return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Укажите название плейлиста: <code>{p}vplaylist del MyMix</code>")
            if name not in playlists:
                return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Плейлист <code>{name}</code> не найден.")
            
            del playlists[name]
            db.set("RemakeVoiceMod", "playlists", playlists)
            return await utils.answer(message, f"<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5409328197676334300\">⏹</tg-emoji> Плейлист <code>{name}</code> удален.")
            
        await utils.answer(message, f"<b>[RemakeVoiceMod] <tg-emoji emoji-id=\"5408830797513784663\">🚫</tg-emoji> Неизвестное действие.</b>\n<i>Доступно: save, load, list, del</i>")

    @loader.command()
    async def vskip(self, message: Message):
        """[чат] - Пропустить текущий трек"""
        self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        if chat_id not in self._current:
            return await utils.answer(message, self.strings("empty_queue"))

        await utils.answer(message, self.strings("skipped"))
        curr = self._current.get(chat_id)
        if curr:
            await self._handle_track_end(chat_id, force_skip=True, expected_track_id=curr.get("track_id"))
        else:
            await self._handle_track_end(chat_id, force_skip=True)

    @loader.command()
    async def vpause(self, message: Message):
        """[чат] - Приостановить воспроизведение"""
        chat_id, _ = await self._resolve_target(message)
        p = self._prefix(message)
        if chat_id not in self._current and chat_id not in self._calls:
            return await utils.answer(message, self.strings("not_joined").format(p=p))

        if self._is_pytgcalls_client and self._tgcalls:
            await self._pytgcalls_call(["pause", "pause_stream"], chat_id)
        elif chat_id in self._calls:
            self._calls[chat_id].pause_playout()

        self._paused[chat_id] = True
        await utils.answer(message, self.strings("paused"))

    @loader.command()
    async def vresume(self, message: Message):
        """[чат] - Возобновить воспроизведение"""
        p = self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        if chat_id not in self._current and chat_id not in self._calls:
            return await utils.answer(message, self.strings("not_joined").format(p=p))

        if self._is_pytgcalls_client and self._tgcalls:
            await self._pytgcalls_call(["resume", "resume_stream"], chat_id)
        elif chat_id in self._calls:
            self._calls[chat_id].resume_playout()

        self._paused[chat_id] = False
        await utils.answer(message, self.strings("resumed"))

    @loader.command()
    async def vmute(self, message: Message):
        """[чат] - Заглушить бота в голосовом чате"""
        p = self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        if chat_id not in self._current and chat_id not in self._calls:
            return await utils.answer(message, self.strings("not_joined").format(p=p))

        if self._is_pytgcalls_client and self._tgcalls:
            await self._pytgcalls_call(["mute", "mute_stream"], chat_id)
        elif chat_id in self._calls:
            self._calls[chat_id].set_is_mute(True)

        self._muted[chat_id] = True
        await utils.answer(message, self.strings("muted"))

    @loader.command()
    async def vunmute(self, message: Message):
        """[чат] - Включить микрофон бота в голосовом чате"""
        p = self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        if chat_id not in self._current and chat_id not in self._calls:
            return await utils.answer(message, self.strings("not_joined").format(p=p))

        if self._is_pytgcalls_client and self._tgcalls:
            await self._pytgcalls_call(["unmute", "unmute_stream"], chat_id)
        elif chat_id in self._calls:
            self._calls[chat_id].set_is_mute(False)

        self._muted[chat_id] = False
        await utils.answer(message, self.strings("unmuted"))

    @loader.command()
    async def vstop(self, message: Message):
        """[чат] - Остановить воспроизведение и очистить очередь"""
        self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        await self._leave_call(chat_id)
        await utils.answer(message, self.strings("stopped"))

    @loader.command()
    async def vjoin(self, message: Message):
        """[чат] - Подключиться к голосовому чату без воспроизведения"""
        p = self._prefix(message)
        ready = await self._ensure_backend_ready()
        if not ready and not HAS_GROUP_CALL_FACTORY:
            return await utils.answer(message, self._str_no_pytgcalls(p))

        chat_id, _ = await self._resolve_target(message)
        chat_id = await self._ensure_marked_chat_id(chat_id)

        active_call = await self._get_active_call(chat_id)
        if not active_call:
            return await utils.answer(message, self.strings("no_active_vc"))

        msg = await utils.answer(message, "<b>[RemakeVoiceMod]</b> <tg-emoji emoji-id=\"5332688668102525212\">⌛</tg-emoji> Подключение...")

        if self._is_pytgcalls_client and self._tgcalls:
            silence_file = self._get_silence_file()
            stream = silence_file
            if MediaStreamClass is not None:
                try:
                    stream = MediaStreamClass(silence_file)
                except Exception:
                    stream = silence_file
            elif AudioPipedClass is not None:
                try:
                    if HighQualityAudioClass is not None:
                        stream = AudioPipedClass(silence_file, HighQualityAudioClass())
                    else:
                        stream = AudioPipedClass(silence_file)
                except Exception:
                    stream = silence_file

            if hasattr(self._tgcalls, "play"):
                try:
                    res = self._tgcalls.play(chat_id, stream)
                    if inspect.isawaitable(res):
                        await res
                    return await utils.answer(msg, self.strings("joined"))
                except Exception as e:
                    logger.warning(f"[RemakeVoiceMod] vjoin play failed: {e}")
                    if not hasattr(self._tgcalls, "join_group_call"):
                        return await utils.answer(msg, self.strings("error").format(err=f"PyTgCalls: {e}"))

            if hasattr(self._tgcalls, "join_group_call"):
                try:
                    kwargs = {}
                    if StreamTypeClass is not None:
                        with contextlib.suppress(Exception):
                            kwargs["stream_type"] = StreamTypeClass().pulse_stream
                    res = self._tgcalls.join_group_call(chat_id, stream, **kwargs)
                    if inspect.isawaitable(res):
                        await res
                    return await utils.answer(msg, self.strings("joined"))
                except Exception as e:
                    logger.error(f"[RemakeVoiceMod] Ошибка vjoin PyTgCalls: {e}")
                    return await utils.answer(msg, self.strings("error").format(err=f"PyTgCalls: {e}"))

        if HAS_GROUP_CALL_FACTORY:
            try:
                if chat_id not in self._calls:
                    silence_file = self._get_silence_file()
                    factory = GroupCallFactoryClass(
                        self._client,
                        GroupCallFactoryClass.MTPROTO_CLIENT_TYPE.TELETHON,
                    )
                    self._calls[chat_id] = factory.get_file_group_call(silence_file)
                    try:
                        await self._calls[chat_id].start(chat_id)
                    except Exception:
                        entity = await self._client.get_entity(chat_id)
                        await self._calls[chat_id].start(getattr(entity, "id", chat_id))

                return await utils.answer(msg, self.strings("joined"))
            except Exception as e:
                logger.error(f"[RemakeVoiceMod] Ошибка vjoin GroupCallFactory: {e}")
                return await utils.answer(msg, self.strings("error").format(err=f"GroupCall: {e}"))

        await utils.answer(msg, self._str_no_pytgcalls(p))

    @loader.command()
    async def vleave(self, message: Message):
        """[чат] - Покинуть голосовой чат"""
        self._prefix(message)
        chat_id, _ = await self._resolve_target(message)
        await self._leave_call(chat_id)
        await utils.answer(message, self.strings("left"))
```<FollowUp label="Нужна помощь с загрузкой этого кода на твой хостинг?" query="Как правильно залить или обновить этот модуль на сервере, где работает юзербот?"/>