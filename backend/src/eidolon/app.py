"""The backend's HTTP API."""

import asyncio
from datetime import UTC, date, datetime, timedelta
import hashlib
import base64
import binascii
import json
import logging
import math
import random
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.types import Receive, Scope, Send
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eidolon.admission import CoolingDown
from eidolon.assembly import Backend
from eidolon.call import (
    CallFailed,
    CallNotFound,
    CallOptions,
    IceCandidate,
    Quality,
    SessionDescription,
)
from eidolon.characters import Character, ScriptedLine, in_idol_order
from eidolon.bailian import transcribe
from eidolon.birthday import BirthdayTriggers, day_of, is_producer_birthday, pick_birthday
from eidolon.emotion import SaidSegment, SegmentToJudge
from eidolon.engine import ENDED, TurnDone, TurnJudged, shown
from eidolon.llm import ChatLLM, ChatMessage
from eidolon.greetings import (
    LANDING_MEMORY_STILL_PATH,
    call_opener_path,
    call_poster_path,
    greeting_path,
    voice_line,
    voxels_path,
)
from eidolon.delivery_cues import spoken_by, voiced, without_cues
from eidolon.reply_format import SegmentComplete, SegmentDelta, SpeechDelta
from eidolon.scenes import (
    Behavior,
    Picked,
    Scene,
    behavior_of,
    judge as judge_scene,
    judge_move,
    load_scenes,
    opener_for,
    opener_for_activity,
)
from eidolon.story import (
    INDEX_FILE as STORY_INDEX_FILE,
    StoryCatalog,
    empty_catalog,
    load_story_catalog,
)
from eidolon.schedules import (
    ScheduleCatalog,
    load_schedules,
    pick as pick_scheduled,
    span_at,
    stable_pick,
    stable_seed,
)
from eidolon.own_keys import BroughtKeys, CallsUnavailable, UnknownService, named_services
from eidolon.throttle import Throttled
from eidolon.producer import (
    MAX_FORM_OF_ADDRESS_LENGTH,
    Birthday,
    Gender,
    Place,
    ProducerProfile,
    effective_timezone,
    is_day_of_the_year,
    is_timezone,
)
from eidolon.account_api import OwnKeysInput, add_account_routes
from eidolon.admin_api import add_admin_routes
from eidolon.admin_backup_api import add_admin_backup_routes
from eidolon.dashboard import add_dashboard_routes
from eidolon.data_package_api import add_data_package_routes
from eidolon.admin_users_api import add_admin_user_routes
from eidolon.admin_config_api import add_admin_config_routes
from eidolon.admin_prices_api import add_admin_price_routes
from eidolon.prompt_admin import add_prompt_admin_routes
from eidolon.announcements_api import add_announcement_routes
from eidolon import group_chat
from eidolon import small_talk
from eidolon.gifts_api import add_gift_routes
from eidolon.photos_api import add_photo_routes
from eidolon.sessions import UserId, session_middleware
from eidolon.sponsor_api import add_sponsor_routes
from eidolon.stats import add_stats_routes
from eidolon.service_status import add_service_status_routes
from eidolon.stand_outfits import list_path, outfit_path
from eidolon.store import Conversation, ConversationEvent, IsCurrent, Message, ReachOut, Recorded
from eidolon.turn_outcome import TurnOutcome
from eidolon.usage import OverLimit
from eidolon.voices import (
    AUDIO_CACHE as VOICE_CACHE,
    KINDS as VOICE_KINDS,
    SOURCE_FILE as VOICES_SOURCE_FILE,
    VoiceLibrary,
    VoiceLine,
    audio_file,
    audio_url,
)
from eidolon.world import World

log = logging.getLogger(__name__)

_PICTURE_CACHE = {"Cache-Control": "public, max-age=86400"}
"""Avatars and call backgrounds change only with a deploy (ADR-0003): browsers keep them a
day, then revalidate by ETag, so lists showing every avatar don't download them each visit."""

NO_CHAT_MODEL = (
    "还没有配置对话模型：在服务器的 .env 里填 CHAT_LLM_BASE_URL、CHAT_LLM_API_KEY、"
    "CHAT_LLM_MODEL（或在后台配置页里填），重启后端后就能对话"
)
"""What a turn answers while `EIDOLON_CHAT_LLM_OPTIONAL=1` and no model is filled in yet."""

MAX_TURN_IMAGE_BYTES = 8 * 1024 * 1024
"""The largest picture a turn may bring, in bytes: a bigger one is refused, not shrunk."""

MAX_VOICE_BYTES = 8 * 1024 * 1024
"""The largest voice message, in bytes: 16 kHz 16-bit mono, about four minutes."""

PICTURE_QUESTION = (
    "先客观描述这张图片，一两句中文，只写看得见的东西（颜色、物体、场景），不要发挥。\n"
    "然后另起一行，只回答图里的人物是谁，三选一：\n"
    "- 就是「{name}」（{name_zh}）本人：回答「本人」；\n"
    "- 是下面名单里的另一位，只写她的名字（必须名字和她的外表特征都对得上，拿不准就回答「不确定」，不要猜）；\n"
    "- 都不是，或者看不出来：回答「不确定」。\n"
    "名单：{roster}\n"
    "「{name}」的外表特征：{appearance}"
)
"""What the model is asked about a picture the user sent, apart from her character prompt: a
long role-play prompt drowns the picture out on smaller models, so what it shows is worked
out first and then told to her in words — whether it is her, and which of the others it is,
an anime character being hard to place from a picture alone."""


async def _describe_picture(
    llm: "ChatLLM",
    picture: tuple[bytes, str],
    character: Character | None = None,
    roster: str = "",
) -> tuple[str, bool | None, str | None]:
    """What the picture shows, in a sentence; whether it is her (None when it cannot be
    told); and, when it is another of the characters, which one."""
    appearance = (character.photo_appearance if character else None) or "（没有记录）"
    question = PICTURE_QUESTION.format(
        name=character.name if character else "这位角色",
        name_zh=character.name_zh if character else "",
        appearance=appearance,
        roster=roster or "（没有名单）",
    )
    said = ""
    async for item in llm.stream([ChatMessage("user", question, image=picture)]):
        if isinstance(item, str):
            said += item
    lines = [line.strip() for line in said.strip().splitlines() if line.strip()]
    if not lines:
        return "", None, None
    verdict = lines[-1]
    description = " ".join(lines[:-1]).strip()[:500] or verdict
    if "本人" in verdict:
        return description, True, None
    if "不确定" in verdict or "不是" in verdict:
        return description, None, None
    return description, False, verdict[:40]  # one of the others, as she is named


def _decode_turn_image(data_url: str | None) -> tuple[bytes, str] | None:
    """The picture a turn brought, and its media type, out of its data URL; None if it
    brought none. What is not one is refused, saying what it should look like."""
    if not data_url:
        return None
    head, _, payload = data_url.partition(",")
    if not head.startswith("data:image/") or not head.endswith(";base64"):
        raise HTTPException(422, "图片要写成 data:image/<类型>;base64,<数据>")
    mime = head[len("data:"):-len(";base64")]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "图片的 base64 数据不合法") from None
    if len(raw) > MAX_TURN_IMAGE_BYTES:
        raise HTTPException(413, "图片太大了，最大 8 MB")
    return raw, mime


def _picture(path: Path, request: Request) -> Response:
    """An avatar or call background, or a 304 when the browser's copy is still current;
    FileResponse sets the ETag but, unlike StaticFiles, never answers 304 itself."""
    response = FileResponse(path, headers=_PICTURE_CACHE, stat_result=path.stat())
    etag = response.headers["etag"]
    cached_etags = request.headers.get("if-none-match", "")
    if etag in (tag.strip() for tag in cached_etags.split(",")):
        return Response(status_code=304, headers={"ETag": etag, **_PICTURE_CACHE})
    return response


class NewConversation(BaseModel):
    character_id: str


class TurnInput(BaseModel):
    text: str
    image: str | None = None
    """The user's picture for this turn, as a data URL (`data:image/png;base64,…`): sent to
    a model that can see it, and kept on the turn's message for the record to show."""
    own_keys: OwnKeysInput | None = None
    """The user's own keys, which their browser keeps, for the turn to run on; the shape
    calls bring too. A turn uses only the LLMs and image generation, voice keys brought
    along go unused."""
    own_llm: object = None
    """Where pages from before brought their own LLM. Transitional, to be deleted once no
    such page is left open: a turn bringing it is refused, asking for a refresh, rather
    than quietly run on the deployer's key and counted."""


class CallRequest(BaseModel):
    """一通电话带上来的：单聊的对话（群通话不带，群在路径里），以及静音、音质、自带 key。"""

    conversation_id: str | None = None
    muted: bool = False
    quality: Quality = "standard"
    own_keys: OwnKeysInput | None = None
    """The user's own keys, which their browser keeps, for the call to run on."""


class BirthdayInput(BaseModel):
    month: int
    day: int

    @model_validator(mode="after")
    def _day_of_the_year(self) -> "BirthdayInput":
        if not is_day_of_the_year(self.month, self.day):
            raise ValueError(f"没有 {self.month} 月 {self.day} 日这一天")
        return self


class ProfileInput(BaseModel):
    """The whole producer profile; a field left out or empty returns to its default,
    but `special_mode` left out keeps the mode already chosen."""

    form_of_address: str | None = None
    gender: Gender | None = None
    timezone: str | None = None
    birthday: BirthdayInput | None = None
    special_mode: str | None = None
    """The chosen mode's id (`modes.load_modes`), or '' for none; null or absent keeps it."""

    @field_validator("form_of_address")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if len(value) > MAX_FORM_OF_ADDRESS_LENGTH:
            raise ValueError(f"称呼最多 {MAX_FORM_OF_ADDRESS_LENGTH} 个字")
        return value or None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if value and not is_timezone(value):
            raise ValueError(f"不认识的时区 {value}")
        return value or None

    @field_validator("special_mode")
    @classmethod
    def _special_mode(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ModesInput(BaseModel):
    """The special modes a user turns on for one character (特殊档等), by id; empty for none."""

    enabled: list[str]


class PlaceInput(BaseModel):
    """A place the user picks by hand for one conversation (or a group), by scene id; None
    goes back to what her schedule says."""

    scene_id: str | None = None


class Offer(BaseModel):
    """A WebRTC offer as the Pipecat client sends it; `requestData` carries our CallRequest."""

    model_config = ConfigDict(populate_by_name=True)

    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    call: CallRequest | None = Field(None, alias="requestData")


class IceCandidateInput(BaseModel):
    candidate: str
    sdp_mid: str
    sdp_mline_index: int


class IceCandidates(BaseModel):
    """ICE candidates the browser trickles in for one of its calls."""

    pc_id: str
    candidates: list[IceCandidateInput]


DeviceTimezone = Annotated[str | None, Header(alias="X-Timezone")]
"""The time zone the browser detected; the producer profile's own time zone overrides it."""


def _stand(character: Character, assets_url: str | None) -> dict | None:
    """Her stand on the call screen: where her default outfit's files are, and her outfit
    list (`stand_outfits`). None, and her call background alone, unless her idol, her
    default outfit and the stand assets are all configured."""
    if character.idol_id is None or character.default_outfit is None or assets_url is None:
        return None
    outfit = character.default_outfit
    return {
        "default_outfit": {"id": outfit, "url": f"{assets_url}/{outfit_path(outfit)}"},
        "outfits_url": f"{assets_url}/{list_path(character.idol_id)}",
    }


def _greeting(character: Character, assets_url: str | None) -> dict | None:
    """Her greeting on the landing page: what she says as people see it, its subtitle, and
    where `eidolon greeting upload` puts its audio (`greeting_path`), without asking the
    bucket whether it is there; no audio unless the stand assets and her voice are
    configured. None without a greeting."""
    return _scripted(character.greeting, greeting_path(character), assets_url)


def _call_opener(character: Character, assets_url: str | None) -> dict | None:
    """Her call opener on the landing page, as her greeting is (`call_opener_path`); None
    without one."""
    return _scripted(character.call_opener, call_opener_path(character), assets_url)


def _call_poster(character: Character, assets_url: str | None) -> str | None:
    """Her card on the landing page's incoming call (ADR-0003, 2026-10-12), at
    `call_poster_path`, listed without asking the bucket whether it is there (the page shows
    her colour instead when it is not). None unless the stand assets are served."""
    return f"{assets_url}/{call_poster_path(character)}" if assets_url else None


def _voxels(character: Character, assets_url: str | None) -> str | None:
    """Her voxel figure in the landing page's act about memory (ADR-0003, 2026-10-16), at
    `voxels_path`, listed as her call poster is."""
    return f"{assets_url}/{voxels_path(character)}" if assets_url else None


def _scripted(line: ScriptedLine | None, path: str | None, assets_url: str | None) -> dict | None:
    if line is None:
        return None
    return {
        "ja": line.ja,
        "subtitle": line.subtitle,
        "audio_url": f"{assets_url}/{path}" if assets_url and path else None,
    }


def _unit(character: Character, world: World | None) -> dict:
    """Her unit, its reading in hiragana, and where it is in the units' official order
    (`World.unit_of`); all None without the world setting, or if its sources could not
    agree on her unit."""
    unit, order = (world.unit_of(character.name) if world else None) or (None, None)
    reading = world.units[order].reading if world and order is not None else None
    return {"unit": unit, "unit_reading": reading, "unit_order": order}


def _activity_key(activity: str) -> str:
    """这一格活动的指纹：开场白按（角色、场景、活动）缓存，语音地址也带上它——
    同一个场景里的不同活动各有各的一句，不能混着用。"""
    return hashlib.sha1(activity.encode("utf-8")).hexdigest()[:12] if activity.strip() else ""


def _story_catalog(backend: Backend) -> StoryCatalog:
    """The story replay data (`characters/story/`, built by `backend/scripts/build_story_data.py`).

    A deployment that has not built it yet (or an old checkout) still runs: the story page is
    empty, and nothing else changes. Present but broken data raises, saying which file is wrong,
    as the scene table does."""
    directory = backend.settings.characters_path.parent / "story"
    if not (directory / STORY_INDEX_FILE).is_file():
        log.warning(
            "story: 没有剧情数据 %s，剧情页先空着（先跑 backend/scripts/build_story_data.py）", directory
        )
        return empty_catalog(directory)
    return load_story_catalog(directory)


def _voice_library(backend: Backend) -> VoiceLibrary:
    """她的原声表（`characters/voices.toml`）：名台词和生日祝福都在里面。

    表没有、或者读不了时一句都没有，接口照常返回空列表；`VoiceLibrary` 按修改时刻重读，
    重新生成原声库以后不必重启后端。"""
    directory = backend.settings.characters_path.parent
    return VoiceLibrary(directory / VOICES_SOURCE_FILE)


def create_app(backend: Backend) -> FastAPI:
    """The API over `backend`, which the app closes when it shuts down."""
    store, characters, engine = backend.store, backend.characters, backend.engine
    memory, calls, admissions = backend.memories, backend.calls, backend.admissions
    gift_catalog, titles = backend.gift_catalog, backend.titles
    scene_catalog = load_scenes(backend.settings.characters_path.parent / "scenes.toml")
    story_catalog = _story_catalog(backend)
    voice_library = _voice_library(backend)
    # 每个用户一天只给一次生日彩蛋：进程里记着，不建表（重启会重放，前端也记着当天看过）。
    birthday_triggers = BirthdayTriggers()
    openers: dict[tuple[str, str, str], tuple[str, str]] = {}
    # （角色, 场景, 这一格的活动指纹）→ 开场白，进程里记着，语音合成也跟着省一次
    schedules: dict[str, ScheduleCatalog | None] = {}
    # 角色 → 她的排期表（characters/schedules.<id>.week*.toml）；None 是查过了没有、或者读坏了
    now_scenes: dict[tuple[str, date, str], dict] = {}
    # （角色, 日期, 时段）→ 她现在在哪；同一格反复打开页面结果一样，也省得每次重算
    group_chat.ensure_schema(store._db)  # 群聊的表，和单聊分开

    def schedule_of(character_id: str) -> ScheduleCatalog | None:
        """她的排期表：`characters/schedules.<id>.week*.toml` 或 `characters/schedules/<id>.week*.toml`。

        没有这个文件、或者读坏了就是 None，走预设行为。`week.toml` 比 `week.draft.toml` 先看，
        平铺的比 `schedules/` 目录里的先看（真乃那份是平铺的）。"""
        if character_id not in schedules:
            directory = backend.settings.characters_path.parent
            loaded: ScheduleCatalog | None = None
            for name in (
                f"schedules.{character_id}.week.toml",
                f"schedules/{character_id}.week.toml",
                f"schedules.{character_id}.week.draft.toml",
                f"schedules/{character_id}.week.draft.toml",
            ):
                path = directory / name
                if not path.is_file():
                    continue
                try:
                    loaded = load_schedules(path, catalog=scene_catalog)
                except RuntimeError:
                    log.exception("scene: 排期表读不了，改用预设行为（%s）", path)
                break
            schedules[character_id] = loaded
        return schedules[character_id]

    async def scene_from_chat(
        character: Character | None, said: list[tuple[str, str]], title: str | None
    ) -> Picked | None:
        """把最近的对话交给判断模型挑场景；判不出来、或者部署没有对话模型时返回 None。

        模型走的是**线上配置**（后台改过的才算数），不是 `.env` 里那一份：管理员可能只填在
        后台配置页里。"""
        try:
            lease = backend.config.lease()
        except Exception:
            return None
        try:
            return await judge_scene(scene_catalog, lease.keys.chat_llm, character, said, title)
        finally:
            lease.release()

    async def cold_scene(character: Character) -> tuple[Picked, Behavior | None]:
        """冷启动：有排期表的按排期接（节日 > 事件 > 槽位 > 池子），没有的随机一条预设行为。

        排期表挑不出来（或者这个钟点不在它的五段里）也回落到预设行为。写开场白要用的东西
        一起交回去：排期表那一格的活动放在 `Picked.activity` 里，预设行为另外交回一条
        `Behavior`。"""
        scheduled = schedule_of(character.id)
        if scheduled is not None:
            choice = pick_scheduled(
                scheduled, character.id, datetime.now(ZoneInfo("Asia/Tokyo"))
            )
            scene = scene_catalog.scene(choice.scene_id) if choice is not None else None
            if choice is not None and scene is not None:
                log.info("scene: %s 按排期接通 %s（%s）", character.id, scene.id, choice.source)
                # 随机池里的地点没有写活动，就用场景本身当「她这会儿在」，开场白照它写
                activity = choice.activity_text.strip() or f"{scene.name}（{scene.hint}）"
                return Picked(scene, choice.why, "schedule", activity=activity), None
        behavior = behavior_of(scene_catalog, character.id)
        if behavior is None:
            return Picked(scene_catalog.fallback(), "", "fallback"), None
        scene = scene_catalog.scene(behavior.scene)
        if scene is None:
            return Picked(scene_catalog.fallback(), "", "fallback"), None
        # 预设行为的活动也进缓存键：同一个场景里的不同行为不能共用一句开场白。
        return Picked(scene, behavior.text, "behavior", activity=behavior.text), behavior

    async def scene_move(
        conversation: Conversation,
        character: Character,
        said: str,
        recorded: Message,
        chat: "ChatLLM",
    ) -> Scene | None:
        """这一回合里，他们有没有说定换到别的地方；换了就是新场景。

        回复已经记下以后再问（和语气一样，不拖慢回复）：问陪她说话的那个模型，答案是一行
        JSON。判不出来、答得不像 JSON、挑了个不存在的场景，都算没换。"""
        current_id = backend.conversation_scenes.of(conversation.id)
        current = scene_catalog.scene(current_id) if current_id else None
        exchange = [
            ("制作人", said),
            (character.name_zh or character.name, recorded.ja or recorded.zh or ""),
        ]
        return await judge_move(scene_catalog, chat, character, current, exchange)

    def current_scene(character: Character, conversation_id: str | None = None) -> dict:
        """她这会儿在哪，不打电话也看得到（页面页首的「现在：…」）。

        这段对话里要是搬过地方（`conversation_scenes`），就是那个场景：页首、通话背景、
        回合的「此刻」都是它；`source` 是 `chat`（对话里说定的）或 `manual`（用户在页首
        的下拉栏里自己选的），两种都只作用在这段对话上。没搬过才按排期表算——
        选法和通话的冷启动一样（节日 > 事件 > 槽位 > 池子），种子按（角色、日期、时段）
        固定：同一格反复问都是同一张，不会刷新一次换一个地方。没有排期表、或者这个钟点
        不在五段里（2:00-6:00），回落到她的 `[[behaviors]]`，同样按格固定。
        结果按同一组键记在进程里，页面反复刷新不必重算。"""
        answer = scheduled_scene(character)
        moved = (
            backend.conversation_scenes.picked(conversation_id) if conversation_id else None
        )
        scene = scene_catalog.scene(moved[0]) if moved else None
        if scene is None:
            return answer
        return {
            **answer,
            "scene": {
                "id": scene.id,
                "name": scene.name,
                "image_url": f"/api/scenes/{scene.id}",
            },
            "activity": f"{scene.name}（{scene.hint}）",
            "source": moved[1] if moved else "chat",
        }

    def scheduled_scene(character: Character) -> dict:
        """按排期表算出来的那一格；`current_scene` 在没有搬过地方时用它。"""
        at = datetime.now(ZoneInfo("Asia/Tokyo"))
        span = span_at(at, "Asia/Tokyo")
        slot = span.slot or "gap"
        key = (character.id, span.day, slot)
        cached = now_scenes.get(key)
        if cached is not None:
            return cached
        scheduled = schedule_of(character.id)
        choice = stable_pick(scheduled, character.id, at) if scheduled is not None else None
        scene = scene_catalog.scene(choice.scene_id) if choice is not None else None
        if choice is not None and scene is not None:
            # 和接通时一样：随机池里的地点没写活动，就用场景本身当「她这会儿在」
            activity = choice.activity_text.strip() or f"{scene.name}（{scene.hint}）"
            source = choice.source
        else:
            behavior = scene_catalog.behavior(
                character.id, random.Random(stable_seed(character.id, span.day, slot))
            )
            scene = scene_catalog.scene(behavior.scene) if behavior is not None else None
            if behavior is not None and scene is not None:
                activity = behavior.text
                source = "behavior"
            else:
                scene = scene_catalog.fallback()
                activity = ""
                source = "fallback"
        answer = {
            "scene": {
                "id": scene.id,
                "name": scene.name,
                "image_url": f"/api/scenes/{scene.id}",
            },
            "activity": activity,
            "source": source,
            "until": span.until.isoformat(timespec="seconds"),
        }
        now_scenes[key] = answer
        return answer

    def current_place(character: Character, conversation_id: str | None = None) -> Place | None:
        """她此刻在哪儿，页首的「现在：…」那一张，给回合的「此刻」用。

        这段对话里说定搬过地方（咖啡厅、公园…）就告诉她，哪怕她没有排期表；没搬过时，
        没有排期表就不告诉她：页首那张是从预设行为里挑的，不能当成她的安排。"""
        moved = backend.conversation_scenes.of(conversation_id) if conversation_id else None
        if not moved and schedule_of(character.id) is None:
            return None
        answer = current_scene(character, conversation_id)
        scene = answer.get("scene") or {}
        name = str(scene.get("name") or "").strip()
        if not name:
            return None
        return Place(name, str(answer.get("activity") or ""))

    def current_picked(character: Character) -> tuple[Picked, dict]:
        """页首那一格（`current_scene`）做成接通用的 `Picked`：场景、活动、来源都取同一份。

        有排期表的角色，通话背景和开场白都从这里出，和页首、提示词的「此刻」是同一张；
        这一格到几点结束（`until`）也一起交回，通话只在下一通按它换。"""
        answer = current_scene(character)
        scene = scene_catalog.scene(str((answer.get("scene") or {}).get("id") or ""))
        picked = Picked(
            scene or scene_catalog.fallback(),
            "",
            str(answer.get("source") or "fallback"),
            activity=str(answer.get("activity") or ""),
        )
        return picked, answer

    def opener_key(picked: Picked) -> str:
        """开场白缓存和语音地址用的键：这一格的活动；判断模型写的那句没有活动，
        就用它自己的话——同一个场景里不同活动、不同对话各有各的一句，不能混着用。"""
        return _activity_key(picked.activity) or _activity_key(picked.opener_ja)

    async def with_opener(
        picked: Picked, character: Character, behavior: Behavior | None
    ) -> Picked:
        """给她这一通的开场白：判场景时写过的就用那条；冷启动的现写一次，按（角色、场景、
        这一格的活动）记住——同一个场景里的不同活动各有一句，语音也不用再合成。"""
        key = (character.id, picked.scene.id, opener_key(picked))
        if picked.opener_ja:
            # 判断模型写的那句也记下来：语音地址只带场景和这个键，不记就会合成她固定的那句，
            # 和显示出来的开场白对不上。
            openers[key] = (picked.opener_ja, picked.opener_zh)
            return picked
        ja, zh = openers.get(key, ("", ""))
        if not ja and (picked.activity or behavior is not None):
            try:
                lease = backend.config.lease()
            except Exception:
                return picked
            try:
                if picked.activity:
                    ja, zh = await opener_for_activity(
                        lease.keys.chat_llm, character, picked.activity
                    )
                elif behavior is not None:
                    ja, zh = await opener_for(
                        lease.keys.chat_llm, scene_catalog, character, behavior
                    )
            finally:
                lease.release()
            if ja:
                openers[key] = (ja, zh)
        return replace(picked, opener_ja=ja, opener_zh=zh) if ja else picked

    def scene_json(picked: Picked | None, character_id: str | None = None) -> dict:
        """接通时的场景：判出来的、冷启动挑的，或者兜底的那一张；还有她的开场白。"""
        chosen = picked or Picked(scene_catalog.fallback(), "", "fallback")
        activity = opener_key(chosen)
        return {
            "scene": {
                "id": chosen.scene.id,
                "name": chosen.scene.name,
                "hint": chosen.scene.hint,
                "image_url": f"/api/scenes/{chosen.scene.id}",
                "why": chosen.why,
                "source": chosen.source,
                "opener": (
                    {
                        # 给人看的台词去掉语气提示（和她的固定开场白一样）；语音仍按原文合成。
                        "ja": without_cues(chosen.opener_ja),
                        "zh": without_cues(chosen.opener_zh),
                        "speech_url": (
                            f"/api/characters/{character_id}/call-opener/speech"
                            f"?scene={chosen.scene.id}"
                            + (f"&activity={activity}" if activity else "")
                        ),
                    }
                    if chosen.opener_ja
                    else None
                ),
            }
        }

    def gift_of(event: ConversationEvent) -> dict:
        """For a gift record, which gift and its name, to show it by."""
        if event.gift_id is None:
            return {}
        return {"gift_id": event.gift_id, "gift_name": gift_catalog[event.gift_id].name}

    def sound(line: VoiceLine) -> dict:
        """一句原声给前端的样子：去哪儿听、日语原文、中文字幕。"""
        return {
            "audio_url": audio_url(line),
            "text": line.text,
            "subtitle": line.subtitle,
            "seconds": line.seconds,
        }

    def voice_of(message: Message) -> dict | None:
        """这条回复里她说的原声（`voices.py` 里的名台词）：回复逐字包含它时才有，取最长的那句；
        没有就是 None。历史消息也算得出来，不另存一份。"""
        said = message.without_cues()  # 语气提示不参与比较（回复是怎么写的不影响她说的字）
        if said.role != "character" or not said.ja:
            return None
        matched = voice_library.catalog().match(said.ja)
        return sound(matched[0]) if matched else None

    def listed_voice(line: VoiceLine) -> dict:
        """一句原声在列表里（`/api/voices`、`/api/characters/<id>/voices`）的样子。"""
        return {
            "story": line.story,
            "line": line.line,
            "text": line.text,
            "subtitle": line.subtitle,
            "audio_url": audio_url(line),
            "seconds": line.seconds,
            "kind": line.kind,
        }

    def checked_kind(kind: str | None) -> str | None:
        """`kind` 过滤参数：不认识的报 422，比默默返回空列表好查。"""
        if kind is not None and kind not in VOICE_KINDS:
            raise HTTPException(422, f"没有这种原声：{kind}（只有 {'、'.join(VOICE_KINDS)}）")
        return kind or None

    def last_shown(last: Recorded | None) -> dict | None:
        """The last thing in a conversation as a list shows it: a message without its
        delivery cues, marked `photo` if it is her reply with a photo she sent (not one being
        generated or not sent after all), or a conversation event, or her reach-out, shown as
        her message is, marked `reach_out`; None while it has none."""
        if last is None:
            return None
        if isinstance(last, ConversationEvent):
            return {"type": "event", "kind": last.kind, "created_at": last.created_at} | gift_of(
                last
            )
        if isinstance(last, ReachOut):
            said = last.without_cues()
            return {
                "role": "character",
                "text": None,
                "ja": said.ja,
                "zh": said.zh,
                "created_at": said.created_at,
                "reach_out": True,
            }
        shown = last.without_cues()
        return {
            "role": shown.role,
            "text": shown.text,
            "ja": shown.ja,
            "zh": shown.zh,
            "created_at": shown.created_at,
        } | ({"photo": True} if shown.photo_sent else {})

    def recorded(entry: Recorded) -> dict:
        """A message, conversation event or reach-out as the browser reads it; a reply also
        carries the original take (`voice_of`) it says, null when it says none."""
        if isinstance(entry, ConversationEvent):
            return entry.shown() | gift_of(entry)
        if isinstance(entry, Message):
            return entry.shown() | {"voice": voice_of(entry)}
        return entry.shown()

    async def auto_chat_loop() -> None:
        """每 20 秒看一眼：哪些群开着自动聊天，就让她们聊一轮。"""
        while True:
            try:
                await asyncio.sleep(20)
                now = datetime.now(UTC).isoformat()
                group_chat.stop_expired_auto_chat(store, now)
                for group in group_chat.auto_chat_groups(store, now):
                    members = [characters[c] for c in group.participants if c in characters]
                    if len(members) < 2:
                        continue
                    recent = group_chat.messages_of(store, group.id, limit=1)
                    if recent:
                        last = datetime.fromisoformat(recent[-1].created_at)
                        if (datetime.now(UTC) - last).total_seconds() < 30:
                            continue  # 刚有人说过话，这一轮跳过
                    admission = admissions.turn(group.user_id, members[0].id, BroughtKeys())
                    async for _ in group_chat.run_chatter(
                        store, group, characters, admission.llms.chat, admission.llms.background,
                        modes=group_modes(group.user_id, list(group.participants)),
                        place=group_place(group),
                    ):
                        pass
            except Exception:
                log.exception("auto chat loop")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await backend.start()
        # 自动聊天由页面自己驱动（关掉网页就停），服务器这边不主动开口：
        # 后台循环留着没启用，免得它替不在此处的用户说话。
        try:
            yield
        finally:
            pass
        await backend.aclose()

    app = FastAPI(title="Eidolon-SC", lifespan=lifespan)
    app.state.backend = backend
    app.middleware("http")(session_middleware(backend.settings))

    @app.exception_handler(OverLimit)
    async def over_limit(_: Request, e: OverLimit) -> JSONResponse:
        """Refused for now, with when the user can go on (also as `Retry-After`); or, set
        to their own keys only, with no time to wait for."""
        if e.retry_at is None:
            return JSONResponse({"detail": str(e), "retry_at": None}, status_code=429)
        wait = max(1, math.ceil((e.retry_at - e.now).total_seconds()))
        return JSONResponse(
            {"detail": str(e), "retry_at": e.retry_at.isoformat()},
            status_code=429,
            headers={"Retry-After": str(wait)},
        )

    @app.exception_handler(CoolingDown)
    async def cooling_down(_: Request, e: CoolingDown) -> JSONResponse:
        """Refused while she is in a cooldown, with when it ends; told apart from the limit's
        429."""
        return JSONResponse(
            {"detail": str(e), "cooldown_until": e.cooldown_until.isoformat()}, status_code=409
        )

    @app.exception_handler(CallsUnavailable)
    async def calls_unavailable(_: Request, e: CallsUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=503)

    @app.exception_handler(Throttled)
    async def throttled(_: Request, e: Throttled) -> JSONResponse:
        """Asked services on the internet too often: when to ask again, in words too."""
        wait = e.retry_after
        later = f"{wait} 秒" if wait < 120 else f"{math.ceil(wait / 60)} 分钟"
        return JSONResponse(
            {"detail": f"{e}，请 {later}后再试"}, status_code=429,
            headers={"Retry-After": str(wait)},
        )

    @app.exception_handler(UnknownService)
    async def unknown_service(_: Request, e: UnknownService) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=422)

    @app.exception_handler(CallNotFound)
    async def call_not_found(_: Request, e: CallNotFound) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(CallFailed)
    async def call_failed(_: Request, e: CallFailed) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=500)

    def conversation_or_404(conversation_id: str, user_id: str) -> Conversation:
        conversation = store.get_conversation(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise HTTPException(404, "对话不存在")
        if conversation.character_id not in characters:  # removed from the configuration
            raise HTTPException(404, "角色不存在")
        return conversation

    def refuse_if_ended(conversation: Conversation) -> None:
        """A call into a conversation she has ended (GLOSSARY.md「已结束的对话」) is refused,
        before anything is asked or spent; told apart from the limit's 429."""
        if store.ended(conversation.id) is not None:
            raise HTTPException(409, ENDED)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    add_account_routes(app, backend)
    add_admin_routes(app, backend)
    add_dashboard_routes(app, backend)
    add_admin_backup_routes(app, backend)
    add_admin_user_routes(app, backend)
    add_admin_config_routes(app, backend)
    add_admin_price_routes(app, backend)
    add_prompt_admin_routes(app, backend)
    add_announcement_routes(app, backend)
    add_gift_routes(app, backend)
    add_photo_routes(app, backend)
    add_sponsor_routes(app, backend)
    add_data_package_routes(app, backend)
    add_stats_routes(app, backend)
    add_service_status_routes(app, backend.service_status)

    @app.get("/api/ice-servers")
    def ice_servers(user_id: UserId, own: str = "", conversation: str | None = None) -> dict:
        """What the browser needs before calling, if the call is to bring the user's own
        keys for the services `own` names (as `llm,tts,stt`), but none of the keys; also
        tells it when calls are unavailable, or, for a call into `conversation`, when she
        is in a cooldown or has ended it."""
        character_id = None
        if conversation:
            into = conversation_or_404(conversation, user_id)
            refuse_if_ended(into)
            character_id = into.character_id
        return calls.ice_servers(user_id, named_services(own), character_id)

    @app.post("/api/offer")
    async def offer(
        body: Offer, user_id: UserId, device_timezone: DeviceTimezone = None
    ) -> dict:
        """WebRTC signalling: a new call into one of the user's conversations, on the user's
        own keys it brings, or a renegotiation, which brings none."""
        description = SessionDescription(body.sdp, body.type)
        if body.pc_id is not None:  # renegotiating, possibly on a fresh peer connection
            return await calls.renegotiate(
                user_id, body.pc_id, description, bool(body.restart_pc)
            )
        call = body.call
        # 打给哪个对话一定要说清（群通话走各自的路由）；没说清的是请求本身不对，不是找不到。
        if call is None or call.conversation_id is None:
            raise HTTPException(422, "缺少要通话的对话")
        conversation = conversation_or_404(call.conversation_id, user_id)
        refuse_if_ended(conversation)
        character = characters[conversation.character_id]
        return await calls.start(
            user_id,
            conversation,
            character,
            CallOptions(call.muted, call.quality, device_timezone),
            description,
            call.own_keys.brought() if call.own_keys else BroughtKeys(),
            place=current_place(character, conversation.id),
        )

    @app.patch("/api/offer")
    async def ice_candidates(body: IceCandidates, user_id: UserId) -> dict:
        candidates = [
            IceCandidate(c.candidate, c.sdp_mid, c.sdp_mline_index) for c in body.candidates
        ]
        await calls.add_candidates(user_id, body.pc_id, candidates)
        return {"ok": True}

    @app.get("/api/modes")
    def list_modes() -> list[dict]:
        """The modes the profile may choose (特殊档等), as settings lists them; what is
        appended to her prompt at love is not sent."""
        return [
            {"id": mode.id, "name": mode.name, "description": mode.description}
            for mode in backend.modes.values()
        ]

    @app.get("/api/profile")
    def get_profile(user_id: UserId) -> dict:
        return asdict(store.get_profile(user_id))

    @app.put("/api/profile")
    def update_profile(body: ProfileInput, user_id: UserId) -> dict:
        birthday = body.birthday and Birthday(body.birthday.month, body.birthday.day)
        # 别的字段照旧整份覆盖；special_mode 不传时保留已经选的模式。只带 special_mode 的
        # 请求（设置里换模式）也只改它：档案还没保存的其他草稿不会被顺手存下去或清掉。
        current = store.get_profile(user_id)
        if body.model_fields_set == {"special_mode"} and body.special_mode is not None:
            profile = replace(current, special_mode=body.special_mode)
        else:
            profile = ProducerProfile(
                body.form_of_address,
                body.gender,
                body.timezone,
                birthday,
                current.special_mode if body.special_mode is None else body.special_mode,
            )
        store.save_profile(user_id, profile)
        return asdict(profile)

    @app.get("/api/characters")
    def list_characters() -> list[dict]:
        """Who there is to talk to; shown before signing in too, and on the landing page.
        In the order of their idol numbers, those without one after them as configured."""
        listed = in_idol_order(characters.values())
        return [
            {
                "id": c.id,
                "name": c.name,
                "intro": c.intro,
                "avatar_url": f"/api/characters/{c.id}/avatar" if c.avatar else None,
                "scsp_avatar_url": f"/api/characters/{c.id}/scsp-avatar" if c.scsp_avatar else None,
                "color": c.color,
                "background_url": f"/api/characters/{c.id}/background" if c.background else None,
                "stand": _stand(c, backend.settings.stand_assets_url),
                "idol_id": c.idol_id,
                "name_zh": c.name_zh,
                "name_kana": c.name_kana,
                "name_romaji": c.name_romaji,
                **_unit(c, backend.world),
                "greeting": _greeting(c, backend.settings.stand_assets_url),
                "call_opener": _call_opener(c, backend.settings.stand_assets_url),
                "call_poster_url": _call_poster(c, backend.settings.stand_assets_url),
                "voxels_url": _voxels(c, backend.settings.stand_assets_url),
            }
            for c in listed
        ]

    @app.get("/api/landing")
    def landing() -> dict:
        """What the landing page shows that belongs to no one character: its act about memory
        as one picture, for visitors who see no animation (ADR-0003, 2026-10-16). Listed as a
        call poster is, without asking the bucket whether it is there (the page shows only the
        words instead); None unless the stand assets are served."""
        assets_url = backend.settings.stand_assets_url
        return {"memory_still_url": f"{assets_url}/{LANDING_MEMORY_STILL_PATH}" if assets_url else None}

    @app.get("/api/characters/{character_id}/avatar")
    def character_avatar(character_id: str, request: Request) -> Response:
        character = characters.get(character_id)
        if character is None or character.avatar is None:
            raise HTTPException(404, "没有这位角色的头像")
        return _picture(character.avatar, request)

    @app.get("/api/characters/{character_id}/scsp-avatar")
    def character_scsp_avatar(character_id: str, request: Request) -> Response:
        """Her avatar in SCSP's set, for users who switched to it in settings."""
        character = characters.get(character_id)
        if character is None or character.scsp_avatar is None:
            raise HTTPException(404, "没有这位角色的 SCSP 头像")
        return _picture(character.scsp_avatar, request)

    @app.get("/api/characters/{character_id}/background")
    def character_background(character_id: str, request: Request) -> Response:
        """The picture behind her call screen, served like her avatar."""
        character = characters.get(character_id)
        if character is None or character.background is None:
            raise HTTPException(404, "没有这位角色的通话背景图")
        return _picture(character.background, request)

    @app.get("/api/voices")
    def all_voices(_: UserId, kind: str | None = None) -> dict:
        """所有角色的原声（名台词和生日祝福），按原声表的顺序；`kind` 可以只看一种。

        前端按角色分组（`/voices` 页只用 `kind=quote`）。原声表还没有、或者读坏了时是空列表。"""
        chosen = checked_kind(kind)
        return {
            "voices": [
                {"character": line.character} | listed_voice(line)
                for line in voice_library.catalog().lines
                if chosen is None or line.kind == chosen
            ]
        }

    @app.get("/api/characters/{character_id}/voices")
    def character_voices(character_id: str, _: UserId, kind: str | None = None) -> dict:
        """她的原声，按原声表的顺序；`kind` 可以只看一种（`quote` 名台词、`birthday` 生日祝福）。
        她没有原声、或者原声表还没有时是空列表，不是 404。"""
        if character_id not in characters:
            raise HTTPException(404, "角色不存在")
        chosen = checked_kind(kind)
        return {
            "voices": [
                listed_voice(line)
                for line in voice_library.catalog().of_character(character_id, chosen)
            ]
        }

    @app.get("/api/voices/{path:path}")
    def voice_audio(path: str) -> Response:
        """一句原声的音频：`characters/` 下的 `path`（表里 `audio` 那一段，形如
        `voices/mano/s01_01010000_00_0030.mp3`），原样送出，带一天的缓存。

        只送 `characters/voices/` 下的普通文件：绝对路径、`..`、指向别处的都不送（404）。"""
        found = audio_file(backend.settings.characters_path.parent, path)
        if found is None:
            raise HTTPException(404, "没有这段原声")
        return FileResponse(
            found, media_type="audio/mpeg", headers={"Cache-Control": VOICE_CACHE}
        )

    @app.get("/api/birthday")
    def birthday_egg(user_id: UserId, device_timezone: DeviceTimezone = None) -> dict:
        """今天的生日原声彩蛋（GLOSSARY.md「生日」）。

        今天是制作人的生日（按他档案里的时区算）时，挑原声表里 `kind = "birthday"` 条目字数
        最多的那位角色，把她的几段按 `story`、行号的数值排好一起给出来（同一位角色的几条是
        一段连续的祝贺）；不是生日、没填生日、或者
        原声表里还没有生日祝福时是 `{"active": false}`。每个用户一天只给一次（进程里记着，
        重启会重放；前端在这台设备上也记着当天看过）。"""
        profile = store.get_profile(user_id)
        now = backend.clock()
        if not is_producer_birthday(profile, now, device_timezone):
            return {"active": False}
        greeting = pick_birthday(voice_library.catalog(), characters)
        if greeting is None:
            return {"active": False}
        if not birthday_triggers.claim(user_id, day_of(profile, now, device_timezone)):
            return {"active": False}
        character = greeting.character
        return {
            "active": True,
            "character": {
                "id": character.id,
                "name": character.name,
                "name_zh": character.name_zh,
                "color": character.color,
                "avatar_url": f"/api/characters/{character.id}/avatar"
                if character.avatar is not None
                else None,
            },
            "lines": [sound(line) for line in greeting.lines],
        }

    @app.get("/api/characters/{character_id}/affinity")
    def affinity(character_id: str, user_id: UserId) -> dict | None:
        """Her affinity with the user now, by tier only, and when the cooldown ends if she
        is in one; null while affinity is off."""
        if character_id not in characters:
            raise HTTPException(404, "角色不存在")
        status = backend.affinities.status(user_id, character_id)
        return status and status.shown()

    @app.get("/api/characters/{character_id}/modes")
    def character_modes_of(character_id: str, user_id: UserId) -> dict:
        """The special modes the user turned on for her (特殊档等), by id; hers alone."""
        if character_id not in characters:
            raise HTTPException(404, "角色不存在")
        return {"enabled": list(backend.character_modes.of(user_id, character_id))}

    @app.put("/api/characters/{character_id}/modes")
    def set_character_modes(character_id: str, body: ModesInput, user_id: UserId) -> dict:
        """Turn exactly these modes on for her, every other off; 404 for no such character,
        422 for a mode the deployment's table does not have."""
        if character_id not in characters:
            raise HTTPException(404, "角色不存在")
        unknown = [mode_id for mode_id in body.enabled if mode_id not in backend.modes]
        if unknown:
            raise HTTPException(422, f"没有这些模式：{'、'.join(unknown)}")
        turned_on = backend.character_modes.set(user_id, character_id, body.enabled)
        return {"enabled": list(turned_on)}

    @app.get("/api/memories")
    async def list_memories(user_id: UserId) -> list[dict]:
        """Newest first, each with the name of the character it was told to and whether
        it has been superseded (ADR-0014)."""
        return [
            {
                "id": m.id,
                "text": m.text,
                "source_character_id": m.source_character_id,
                "source_character_name": m.source_character_name,
                "created_at": m.created_at,
                "superseded": m.superseded_by is not None,
            }
            for m in await memory.entries(user_id)
        ]

    @app.delete("/api/memories/{memory_id}", status_code=204)
    async def delete_memory(memory_id: int, user_id: UserId) -> None:
        if not await memory.delete(user_id, memory_id):
            raise HTTPException(404, "记忆不存在")

    @app.delete("/api/memories", status_code=204)
    async def clear_memories(user_id: UserId) -> None:
        await memory.clear(user_id)

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: NewConversation, user_id: UserId) -> dict:
        if body.character_id not in characters:
            raise HTTPException(404, "角色不存在")
        return asdict(store.create_conversation(user_id, body.character_id))

    @app.get("/api/conversations")
    async def list_conversations(character_id: str, user_id: UserId) -> list[dict]:
        """Her conversations with the user, newest first, the first her current one; each
        with its title, null if it has none, the last thing in it, as the conversation list
        shows it, and whether she has ended it. Those being named are waited for a while."""
        await titles.settle(user_id)
        listed = await asyncio.to_thread(store.list_conversations, user_id, character_id)
        return [
            asdict(c) | {"last_message": last_shown(last), "ended": ended}
            for c, last, ended in listed
        ]

    @app.get("/api/conversations/latest")
    def latest_conversations(user_id: UserId) -> list[dict]:
        """For the conversation list: each character's newest conversation with the user, the
        last thing in it, a message, a conversation event or a reach-out (null while it has
        none), and whether it has a reach-out the user has not seen, in one request."""
        return [
            {
                "character_id": c.character_id,
                "conversation_id": c.id,
                "created_at": c.created_at,
                "last_message": last_shown(last),
                "unseen_reach_out": unseen,
            }
            for c, last, unseen in store.latest_conversations(user_id)
        ]

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str, user_id: UserId) -> None:
        """Delete a past conversation (GLOSSARY.md「历史对话」), for good; her current one is
        not deleted (409)."""
        try:
            store.delete_conversation(conversation_or_404(conversation_id, user_id))
        except IsCurrent:
            raise HTTPException(409, "当前对话不能删除") from None

    @app.get("/api/conversations/{conversation_id}/messages")
    def list_messages(conversation_id: str, user_id: UserId) -> list[dict]:
        """The conversation's record: its messages, conversation events and reach-outs, in
        order. The user reads it: its reach-outs are seen from now on."""
        conversation = conversation_or_404(conversation_id, user_id)
        entries = [recorded(entry) for entry in store.read_by_user(conversation.id)]
        with_images = store.user_image_message_ids(conversation.id)
        for entry in entries:  # a message the user sent a picture with says so, for the page
            if entry.get("id") in with_images:
                entry["image"] = True
        return entries

    @app.get("/api/messages/{message_id}/image")
    def message_image(message_id: int, user_id: UserId) -> Response:
        """The picture the user sent with that message; 404 for anyone else's."""
        found = store.user_image(message_id, user_id)
        if found is None:
            raise HTTPException(404, "没有这张图片")
        data, mime = found
        return Response(
            data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000"}
        )

    # How she said each reply, judged on demand for the pet while one is read aloud: her replies
    # do not change, so each is judged at most once.
    judged_moods: dict[str, tuple[str, str | None, float]] = {}

    @app.get("/api/messages/{message_id}/emotion")
    async def message_emotion(message_id: int, user_id: UserId) -> dict:
        """How she said this reply (DESIGN.md「对话页的立绘小人」): judged the first time it is
        asked for, for the pet to take up while the reply is read aloud."""
        speaking = store.message_to_speak(message_id, user_id)
        if speaking is None:
            raise HTTPException(404, "没有这条消息")
        character_id, _, conversation_id = speaking
        character = characters.get(character_id)
        if character is None:
            raise HTTPException(404, "角色不存在")
        judged = judged_moods.get(f"m:{message_id}")
        if judged is None:
            record = store.record(conversation_id)
            said = SaidSegment(ja="", zh="")
            heard = ""
            for entry in record:
                if isinstance(entry, Message) and entry.id == message_id and entry.role == "character":
                    said = SaidSegment(ja=entry.ja or "", zh=entry.zh or "")
                    break
                if isinstance(entry, Message) and entry.role == "user":
                    heard = entry.text or ""
            lease = backend.config.lease()
            try:
                emotions = lease.keys.emotions
                if emotions is None:
                    raise HTTPException(503, "还没有配置判断模型")
                answer = await emotions.answer(SegmentToJudge(character, heard, (), said), 0.3)
            finally:
                lease.release()
            if answer is None:
                raise HTTPException(503, "这次没能判断出来")
            judged = judged_moods[f"m:{message_id}"] = answer
        emotion, nod, strength = judged
        return {"emotion": emotion, "nod": nod, "strength": round(strength, 2)}

    @app.get("/api/messages/{message_id}/speech")
    async def message_speech(message_id: int, user_id: UserId) -> Response:
        """Her reply said aloud: voiced the first time the user asks for it, on the
        deployer's voice, and kept with the message so asking again voices nothing; 404 for
        anyone else's."""
        speaking = store.message_to_speak(message_id, user_id)
        if speaking is None:
            raise HTTPException(404, "没有这条消息")
        kept = store.message_speech(message_id)
        if kept is not None:
            data, mime = kept
            return Response(
                data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000"}
            )
        voice = backend.config.voice
        if voice is None:
            raise HTTPException(503, "还没有配置语音合成")
        character_id, ja, conversation_id = speaking
        character = characters.get(character_id)
        voice_id = (character.voice_id if character else "").strip()
        if not voice_id:
            raise HTTPException(503, "她还没有声音")
        said = spoken_by(voiced(ja), voice.model)
        if not said.strip():
            raise HTTPException(503, "这条回复没有可以念出来的文字")
        try:
            data = await voice_line(voice, said, voice_id)
        except Exception as e:  # voiced or not, the reply itself stays
            raise HTTPException(502, f"语音合成失败了：{e}") from e
        store.keep_message_speech(message_id, conversation_id, "audio/mpeg", data)
        return Response(
            data, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=31536000"}
        )

    @app.get("/api/characters/{character_id}/call-opener/emotion")
    async def call_opener_emotion(character_id: str, user_id: UserId) -> dict:
        """她开场白是什么语气（DESIGN.md「开场白」）：判一次、按角色记住，通话接通放开场白时
        立绘照它摆，和回完一条回复时一样。"""
        character = characters.get(character_id)
        if character is None or character.call_opener is None:
            raise HTTPException(404, "她没有开场白")
        key = f"opener:{character_id}"
        judged = judged_moods.get(key)
        if judged is None:
            line = character.call_opener
            lease = backend.config.lease()
            try:
                emotions = lease.keys.emotions
                if emotions is None:
                    raise HTTPException(503, "还没有配置判断模型")
                answer = await emotions.answer(
                    SegmentToJudge(
                        character=character,
                        user_said="",
                        before=(),
                        segment=SaidSegment(ja=line.ja, zh=line.subtitle),
                    ),
                    0.3,
                )
            finally:
                lease.release()
            if answer is None:
                raise HTTPException(503, "这次没能判断出来")
            judged = judged_moods[key] = answer
        emotion, nod, strength = judged
        return {"emotion": emotion, "nod": nod, "strength": round(strength, 2)}

    @app.get("/api/characters/{character_id}/call-opener/speech")
    async def call_opener_speech(
        character_id: str, scene: str | None = None, activity: str | None = None
    ) -> Response:
        """Her call opener said aloud, so that answering a call she speaks first.

        With `scene`, the opener written for that scene at connect (`openers`), if there is
        one; with `activity` too, the one written for that activity in it (a schedule's slot
        has its own line, the same scene may have several). Otherwise the one line she has
        always had. Voiced the first time it is asked for and kept on disk by its text, so
        a scene's opener is only synthesized once."""
        character = characters.get(character_id)
        if character is None:
            raise HTTPException(404, "她没有开场白")
        written = openers.get((character_id, scene, activity or "")) if scene else None
        if written is None and character.call_opener is None:
            raise HTTPException(404, "她没有开场白")
        voice = backend.config.voice
        if voice is None:
            raise HTTPException(503, "还没有配置语音合成")
        voice_id = (character.voice_id or "").strip()
        if not voice_id:
            raise HTTPException(503, "她还没有声音")
        ja = written[0] if written else (getattr(character.call_opener, "ja", "") or "")
        said = spoken_by(voiced(ja), voice.model)
        if not said.strip():
            raise HTTPException(503, "开场白没有可以念出来的文字")
        digest = hashlib.sha1(f"{voice.model}:{voice_id}:{said}".encode()).hexdigest()[:16]
        kept = Path("/data/speech") / f"opener-{character_id}-{digest}.mp3"
        if not kept.exists():
            try:
                data = await voice_line(voice, said, voice_id)
            except Exception as e:
                raise HTTPException(502, f"语音合成失败了：{e}") from e
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes(data)
        return Response(
            kept.read_bytes(),
            media_type="audio/mpeg",
            headers={"Cache-Control": "private, max-age=31536000"},
        )

    @app.get("/api/characters/{character_id}/small-talk")
    def small_talk_line(character_id: str, user_id: UserId, hour: int | None = None) -> dict:
        """点她一下时她说的一句（DESIGN.md「对话页的立绘小人」）：从整理好的语料里随机挑一句，
        这个钟点适合说的优先，带上这一句的语音地址。没有整理过这一位时 404，前端退回只做一个表情。"""
        if character_id not in characters:
            raise HTTPException(404, "角色不存在")
        root = backend.settings.small_talk_path
        line = small_talk.pick(small_talk.load(root, character_id), hour)
        if line is None:
            raise HTTPException(404, "她还没有可以说的台词")
        return {
            "line": {
                "id": line.id,
                "ja": line.ja,
                "zh": line.zh,
                "mood": line.mood,
                "body": line.body,
                "face": line.face,
                "voice": f"/api/characters/{character_id}/small-talk/{line.id}/voice",
            }
        }

    @app.get("/api/characters/{character_id}/small-talk/{line_id}/voice")
    def small_talk_voice(character_id: str, line_id: str, user_id: UserId) -> Response:
        """这一句的录音：她自己说的那一句，原样取自她的那份语料（不是合成的）。"""
        if character_id not in characters:
            raise HTTPException(404, "角色不存在")
        root = backend.settings.small_talk_path
        for line in small_talk.load(root, character_id):
            if line.id != line_id:
                continue
            path = small_talk.voice_path(root, character_id, line.voice)
            if path is None:
                raise HTTPException(404, "这一句没有录音")
            return Response(
                path.read_bytes(),
                media_type="audio/mp4",
                headers={"Cache-Control": "private, max-age=31536000"},
            )
        raise HTTPException(404, "没有这一句")

    @app.post("/api/voice")
    async def hear_voice(request: Request, user_id: UserId) -> dict[str, str]:
        """What a voice message says, so the composer can send it as text: 16 kHz 16-bit mono
        PCM in the body, transcribed on the deployer's speech recognition."""
        pcm = await request.body()
        if not pcm:
            raise HTTPException(422, "没有收到声音")
        if len(pcm) > MAX_VOICE_BYTES:
            raise HTTPException(413, "语音太长了，最多 8 MB")
        hearing = backend.config.hearing
        if hearing is None or hearing.provider != "bailian":
            raise HTTPException(503, "还没有配置语音识别")
        try:
            heard = await transcribe(
                api_key=hearing.api_key,
                model=backend.settings.bailian_stt_model,
                region=hearing.region,
                pcm=pcm,
            )
        except Exception as e:  # nothing was sent, so nothing is lost
            raise HTTPException(502, f"没能听清这段语音：{e}") from e
        if not heard.strip():
            raise HTTPException(422, "没有听清，再说一次？")
        return {"text": heard}

    class GroupInput(BaseModel):
        character_ids: list[str]
        title: str | None = None

    class GroupTurnInput(BaseModel):
        text: str
        target_id: str | None = None

    def group_or_404(group_id: str, user_id: str) -> group_chat.Group:
        group = group_chat.get_group(store, group_id)
        if group is None or group.user_id != user_id:
            raise HTTPException(404, "没有这个群")
        return group

    def group_json(group: group_chat.Group, last: group_chat.GroupMessage | None) -> dict:
        return {
            "id": group.id,
            "title": group.title,
            "participants": list(group.participants),
            "created_at": group.created_at,
            "auto_chat": group.auto_chat,
            "last_message": message_json(last) if last else None,
        }

    def message_json(message: group_chat.GroupMessage | None) -> dict | None:
        if message is None:
            return None
        return {
            "id": message.id,
            "role": message.role,
            "speaker_id": message.speaker_id,
            "segments": [{"ja": s.ja, "zh": s.zh} for s in message.segments],
            "created_at": message.created_at,
        }

    def group_tiers(user_id: str, ids: list[str]) -> dict[str, str]:
        """群里每个人现在的好感档位：只读，用来让她们说话有分寸，不改分数。"""
        tiers: dict[str, str] = {}
        for cid in ids:
            status = backend.affinities.status(user_id, cid)
            if status is not None:
                tiers[cid] = status.tier
        return tiers

    def group_modes(user_id: str, ids: list[str]) -> dict[str, str]:
        """群里每个人身上开着的特殊档正文（`character_modes` + `modes.load_modes`）：
        只轮到她时进提示词，别人的不进来；好感各档都算。"""
        return {
            cid: "\n\n".join(
                mode.prompt
                for mode in backend.modes.values()
                if mode.id in set(backend.character_modes.of(user_id, cid))
            )
            for cid in ids
            if backend.character_modes.of(user_id, cid)
        }

    @app.post("/api/groups")
    def make_group(body: GroupInput, user_id: UserId) -> dict:
        """建一个群，拉 2–4 个人。"""
        wanted = list(dict.fromkeys(body.character_ids))
        unknown = [c for c in wanted if c not in characters]
        if unknown:
            raise HTTPException(422, f"没有这些角色：{', '.join(unknown)}")
        if not group_chat.MIN_PARTICIPANTS <= len(wanted) <= group_chat.MAX_PARTICIPANTS:
            raise HTTPException(
                422,
                f"群聊要 {group_chat.MIN_PARTICIPANTS}–{group_chat.MAX_PARTICIPANTS} 个人",
            )
        group = group_chat.create_group(store, user_id, wanted, body.title)
        return group_json(group, None)

    @app.get("/api/groups")
    def my_groups(user_id: UserId) -> dict:
        return {
            "groups": [
                group_json(group, last) for group, last in group_chat.list_groups(store, user_id)
            ]
        }

    @app.get("/api/scenes/{scene_id}")
    def scene_image(scene_id: str, request: Request) -> Response:
        """接通电话时她身后的场景图（DESIGN.md「通话场景」）。"""
        scene = scene_catalog.scene(scene_id)
        if scene is None:
            raise HTTPException(404, "没有这个场景")
        path = backend.settings.characters_path.parent / "scenes" / scene.image
        if not path.is_file():
            raise HTTPException(404, "场景图不在了")
        return _picture(path, request)

    @app.get("/api/story")
    def story_index(_: UserId) -> dict:
        """剧情回放的全部分区单元和话数：`{total_episodes, units}`，单元按导出里的顺序
        （路线、活动、特别企划、卡面按角色、主页营业、SCSP、其他），前端按 kind 分区。"""
        return story_catalog.listing()

    @app.get("/api/story/{unit_id}")
    def story_unit(unit_id: str, _: UserId) -> dict:
        """一个剧情单元：总述、主题、出场角色，和它的每一话（SCSP 一章里含几话）。"""
        detail = story_catalog.detail(unit_id)
        if detail is None:
            raise HTTPException(404, "没有这个剧情单元")
        return detail.as_json()

    @app.get("/api/conversations/{conversation_id}/scene")
    async def conversation_scene(conversation_id: str, user_id: UserId) -> dict:
        """接通前问一次：这通电话她身后该是什么场景，她第一句说什么。

        有排期表的角色取页首那一格（`current_scene`）：同一格里页首、背景、开场白和提示词的
        「此刻」是同一张，不会每通电话重掷。没有排期表的角色照旧：最近的对话够多就交给判断
        模型；不够（或者判不出来）就随机一条她的预设行为。"""
        conversation = conversation_or_404(conversation_id, user_id)
        character = characters[conversation.character_id]
        # 这段对话里说定搬过地方：背景就画那儿，开场白按那儿现写，不管她有没有排期表。
        moved = scene_catalog.scene(backend.conversation_scenes.of(conversation.id) or "")
        if moved is not None:
            picked = Picked(moved, "", "chat", activity=f"{moved.name}（{moved.hint}）")
            picked = await with_opener(picked, character, None)
            answer = scene_json(picked, character.id)
            answer["activity"] = picked.activity
            answer["source"] = "chat"
            if schedule_of(character.id) is not None:
                answer["until"] = current_picked(character)[1]["until"]
            return answer
        if schedule_of(character.id) is not None:
            picked, current = current_picked(character)
            picked = await with_opener(picked, character, None)
            answer = scene_json(picked, character.id)
            answer["activity"] = current["activity"]
            answer["source"] = current["source"]
            answer["until"] = current["until"]
            return answer
        said: list[tuple[str, str]] = []
        for entry in store.record(conversation.id)[-20:]:
            if not isinstance(entry, Message):
                continue
            if entry.role == "user":
                said.append(("制作人", entry.text or ""))
            else:
                said.append((character.name_zh or character.name, entry.ja or entry.zh or ""))
        picked = await scene_from_chat(character, said, conversation.title) if len(said) >= 2 else None
        behavior = None
        if picked is None:
            picked, behavior = await cold_scene(character)
        picked = await with_opener(picked, character, behavior)
        return scene_json(picked, character.id)

    @app.get("/api/conversations/{conversation_id}/now")
    def conversation_now(conversation_id: str, user_id: UserId) -> dict:
        """她现在在哪（不打电话也看得到）：这段对话里搬过地方就是那儿（说定的或用户选的），
        否则按排期表算的当前场景，同一格不变。

        和 `/scene` 分开：这个给页面页首的「现在：…」；`/scene` 接通前问一次，有排期表的
        角色取的是同一格（`current_scene`），没有排期表的才另挑。"""
        conversation = conversation_or_404(conversation_id, user_id)
        return current_scene(characters[conversation.character_id], conversation.id)

    @app.put("/api/conversations/{conversation_id}/place")
    def set_place(conversation_id: str, body: PlaceInput, user_id: UserId) -> dict:
        """页首的下拉栏里自己挑一个地方：只作用在这段对话上，换一段就回到排期表；
        `scene_id` 为 null 时取消，回到按排期表算的地方。"""
        conversation = conversation_or_404(conversation_id, user_id)
        if body.scene_id is None:
            backend.conversation_scenes.forget(conversation.id)
        else:
            if scene_catalog.scene(body.scene_id) is None:
                raise HTTPException(404, "没有这个场景")
            backend.conversation_scenes.keep(
                conversation.id, body.scene_id, backend.clock().isoformat(), source="manual"
            )
        return current_scene(characters[conversation.character_id], conversation.id)

    @app.get("/api/scenes")
    def scenes(_: UserId) -> list[dict]:
        """场景表里能挑的地方：页首的下拉栏用。"""
        return [
            {"id": scene.id, "name": scene.name, "hint": scene.hint}
            for scene in scene_catalog.scenes
        ]

    def group_place(group: group_chat.Group) -> str | None:
        """群里现在的地点，给提示词的一句现成的话；没选就是 None。"""
        scene = scene_catalog.scene(group_chat.place_of(store, group.id) or "")
        if scene is None:
            return None
        return f"你们现在在「{scene.name}」（{scene.hint}）。"

    @app.get("/api/groups/{group_id}/place")
    def group_place_of(group_id: str, user_id: UserId) -> dict:
        """群聊现在的地点：没选就是 null。"""
        group = group_or_404(group_id, user_id)
        scene = scene_catalog.scene(group_chat.place_of(store, group.id) or "")
        return {
            "scene": (
                None
                if scene is None
                else {"id": scene.id, "name": scene.name, "image_url": f"/api/scenes/{scene.id}"}
            )
        }

    @app.put("/api/groups/{group_id}/place")
    def set_group_place(group_id: str, body: PlaceInput, user_id: UserId) -> dict:
        """在群聊页首挑一个地方（null 取消）：下一句起她们就知道自己在哪儿。"""
        group = group_or_404(group_id, user_id)
        if body.scene_id is not None and scene_catalog.scene(body.scene_id) is None:
            raise HTTPException(404, "没有这个场景")
        group_chat.set_place(store, group.id, body.scene_id)
        return group_place_of(group_id, user_id)

    @app.get("/api/groups/{group_id}/scene")
    async def group_scene(group_id: str, user_id: UserId) -> dict:
        """群通话接通前的场景：按群里最近的话判；冷启动就随机一位的预设行为。"""
        group = group_or_404(group_id, user_id)
        members = [characters[cid] for cid in group.participants if cid in characters]
        if not members:
            raise HTTPException(422, "群里没有人")
        said: list[tuple[str, str]] = []
        for message in group_chat.messages_of(store, group.id, limit=20):
            text = "".join(segment.ja or segment.zh for segment in message.segments)
            if not text.strip():
                continue
            if message.role == "user":
                said.append(("制作人", text))
                continue
            speaker = characters.get(message.speaker_id or "")
            said.append((speaker.name_zh or speaker.name if speaker else "她", text))
        picked = await scene_from_chat(None, said, None) if len(said) >= 2 else None
        if picked is None:
            picked, _ = await cold_scene(random.choice(members))
        return scene_json(picked)

    @app.get("/api/groups/{group_id}/messages")
    def group_messages(group_id: str, user_id: UserId) -> dict:
        group = group_or_404(group_id, user_id)
        return {
            "group": group_json(group, None),
            "messages": [message_json(m) for m in group_chat.messages_of(store, group.id)],
        }

    @app.get("/api/groups/{group_id}/messages/{message_id}/emotion")
    async def group_message_emotion(group_id: str, message_id: int, user_id: UserId) -> dict:
        """她这一句是什么语气（DESIGN.md「对话页的立绘小人」的群聊版）：群消息不在单聊的表里，
        单独判一次、按（群，消息）记住，群里的几个小人各自照它摆。"""
        group = group_or_404(group_id, user_id)
        message = group_chat.message_by_id(store, group.id, message_id)
        if message is None or message.role != "character" or not message.speaker_id:
            raise HTTPException(404, "没有这条消息")
        character = characters.get(message.speaker_id)
        if character is None:
            raise HTTPException(404, "角色不存在")
        key = f"g:{group.id}:{message_id}"
        judged = judged_moods.get(key)
        if judged is None:
            heard = ""
            for entry in group_chat.messages_of(store, group.id):
                if entry.id == message_id:
                    break
                if entry.role == "user" and entry.segments:
                    heard = entry.segments[0].zh
            said = SaidSegment(
                ja="\n".join(segment.ja for segment in message.segments),
                zh="".join(segment.zh for segment in message.segments),
            )
            lease = backend.config.lease()
            try:
                emotions = lease.keys.emotions
                if emotions is None:
                    raise HTTPException(503, "还没有配置判断模型")
                answer = await emotions.answer(SegmentToJudge(character, heard, (), said), 0.3)
            finally:
                lease.release()
            if answer is None:
                raise HTTPException(503, "这次没能判断出来")
            judged = judged_moods[key] = answer
        emotion, nod, strength = judged
        return {"emotion": emotion, "nod": nod, "strength": round(strength, 2)}

    @app.get("/api/groups/{group_id}/ice-servers")
    def group_ice_servers(group_id: str, user_id: UserId) -> dict:
        """群通话前浏览器要的：ICE 服务器、这通电话能打多久。群里第一位成员的冷却也算上，
        和通话准入用的是同一位。"""
        group = group_or_404(group_id, user_id)
        members = [characters[cid] for cid in group.participants if cid in characters]
        return calls.ice_servers(user_id, frozenset(), members[0].id if members else None)

    @app.patch("/api/groups/{group_id}/call")
    async def group_ice_candidates(group_id: str, body: IceCandidates, user_id: UserId) -> dict:
        """群通话的 ICE candidate：和单聊一样，补到那条 peer connection 上。"""
        group_or_404(group_id, user_id)
        candidates = [
            IceCandidate(c.candidate, c.sdp_mid, c.sdp_mline_index) for c in body.candidates
        ]
        await calls.add_candidates(user_id, body.pc_id, candidates)
        return {"ok": True}

    @app.post("/api/groups/{group_id}/call")
    async def group_call(
        group_id: str, body: Offer, user_id: UserId, device_timezone: DeviceTimezone = None
    ) -> dict:
        """群通话（DESIGN.md「群聊语音房」）：一通电话里几个人轮流说，各自用自己的音色。

        和单聊的通话同一个信令（`/api/offer` 的 body）：带 `pc_id` 是重新协商。"""
        group = group_or_404(group_id, user_id)
        members = [characters[cid] for cid in group.participants if cid in characters]
        if not members:
            raise HTTPException(422, "群里没有人")
        description = SessionDescription(body.sdp, body.type)
        if body.pc_id is not None:
            return await calls.renegotiate(
                user_id, body.pc_id, description, bool(body.restart_pc)
            )
        quality = body.call.quality if body.call else "standard"
        return await calls.start_group(
            user_id, group, characters, CallOptions(False, quality, device_timezone), description
        )

    @app.patch("/api/groups/{group_id}")
    def rename_group(group_id: str, body: dict, user_id: UserId) -> dict:
        """给群改个名字；传空名字就回到「成员名」。"""
        group = group_or_404(group_id, user_id)
        title = (body.get("title") or "").strip() or None
        if title is not None and len(title) > 40:
            raise HTTPException(422, "名字太长了，40 个字以内")
        group_chat.rename_group(store, group.id, title)
        return group_json(group_chat.get_group(store, group.id) or group, None)

    @app.get("/api/groups/{group_id}/messages/{message_id}/speech")
    async def group_message_speech(group_id: str, message_id: int, user_id: UserId) -> Response:
        """群里她这句话念出来：第一次合成后缓存，之后直接给。"""
        group = group_or_404(group_id, user_id)
        message = group_chat.message_by_id(store, group.id, message_id)
        if message is None or message.role != "character" or not message.speaker_id:
            raise HTTPException(404, "没有这条消息")
        kept = group_chat.speech_of(store, message_id)
        if kept is not None:
            data, mime = kept
            return Response(
                data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000"}
            )
        voice = backend.config.voice
        if voice is None:
            raise HTTPException(503, "还没有配置语音合成")
        character = characters.get(message.speaker_id)
        voice_id = (character.voice_id if character else "").strip()
        if not voice_id:
            raise HTTPException(503, "她还没有声音")
        ja = " ".join(s.ja for s in message.segments if s.ja).strip()
        said = spoken_by(voiced(ja), voice.model)
        if not said.strip():
            raise HTTPException(503, "这句话没有可以念出来的文字")
        try:
            data = await voice_line(voice, said, voice_id)
        except Exception as e:
            raise HTTPException(502, f"语音合成失败了：{e}") from e
        group_chat.keep_speech(store, message_id, "audio/mpeg", data)
        return Response(
            data, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=31536000"}
        )

    @app.post("/api/groups/{group_id}/auto")
    def set_auto_chat(group_id: str, body: dict, user_id: UserId) -> dict:
        """开/关「让她们自己聊」。开关存在服务器上：关掉网页、锁屏，她们照样继续，
        到点（默认 20 分钟）自己停。"""
        group = group_or_404(group_id, user_id)
        enabled = bool(body.get("enabled"))
        if not enabled:
            group_chat.set_auto_chat(store, group.id, None)
            return {"auto_chat": False, "until": None}
        minutes = int(body.get("minutes") or 20)
        minutes = max(1, min(minutes, 120))
        until = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
        group_chat.set_auto_chat(store, group.id, until)
        return {"auto_chat": True, "until": until}

    @app.post("/api/groups/{group_id}/chatter")
    async def group_chatter(group_id: str, user_id: UserId) -> StreamingResponse:
        """没人说话时，让她们自己聊两三句。"""
        group = group_or_404(group_id, user_id)
        members = [characters[c] for c in group.participants if c in characters]
        if len(members) < 2:
            raise HTTPException(422, "群里至少要两个人")
        admission = admissions.turn(user_id, members[0].id, BroughtKeys())

        async def events() -> AsyncIterator[str]:
            def send(payload: dict) -> str:
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            async for kind, speaker_id, message in group_chat.run_chatter(
                store, group, characters, admission.llms.chat, admission.llms.background,
                tiers=group_tiers(user_id, list(group.participants)),
                modes=group_modes(user_id, list(group.participants)),
                place=group_place(group),
            ):
                if kind == "thinking":
                    yield send({"type": "thinking", "speaker_id": speaker_id})
                elif message is not None:
                    yield send({"type": "message", "message": message_json(message)})
            yield send({"type": "done"})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/groups/{group_id}/members")
    def invite_member(group_id: str, body: dict, user_id: UserId) -> dict:
        """把一个人拉进群。"""
        group = group_or_404(group_id, user_id)
        character_id = (body.get("character_id") or "").strip()
        if character_id not in characters:
            raise HTTPException(422, "没有这个角色")
        if character_id in group.participants:
            raise HTTPException(422, "她已经在这个群里了")
        if len(group.participants) >= group_chat.MAX_PARTICIPANTS:
            raise HTTPException(422, f"一个群最多 {group_chat.MAX_PARTICIPANTS} 个人")
        updated = group_chat.add_member(store, group.id, character_id)
        notice = group_chat.join_notice(store, group.id, characters[character_id])
        return {**group_json(updated, None), "notice": message_json(notice)}

    @app.post("/api/groups/{group_id}/welcome")
    async def group_welcome(group_id: str, body: dict, user_id: UserId) -> StreamingResponse:
        """刚进群的人打个招呼，另一个人接一句。"""
        group = group_or_404(group_id, user_id)
        character_id = (body.get("character_id") or "").strip()
        if character_id not in characters or character_id not in group.participants:
            raise HTTPException(422, "她不在这个群里")
        members = [characters[c] for c in group.participants if c in characters]
        admission = admissions.turn(user_id, members[0].id, BroughtKeys())

        async def events() -> AsyncIterator[str]:
            def send(payload: dict) -> str:
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            async for kind, speaker_id, message in group_chat.run_welcome(
                store, group, characters, characters[character_id],
                admission.llms.chat, admission.llms.background,
                tiers=group_tiers(user_id, list(group.participants)),
                modes=group_modes(user_id, list(group.participants)),
                place=group_place(group),
            ):
                if kind == "thinking":
                    yield send({"type": "thinking", "speaker_id": speaker_id})
                elif message is not None:
                    yield send({"type": "message", "message": message_json(message)})
            yield send({"type": "done"})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.delete("/api/groups/{group_id}")
    def drop_group(group_id: str, user_id: UserId) -> dict:
        group = group_or_404(group_id, user_id)
        group_chat.delete_group(store, group.id)
        return {"deleted": group.id}

    @app.post("/api/groups/{group_id}/turns")
    async def group_turn(group_id: str, body: GroupTurnInput, user_id: UserId) -> StreamingResponse:
        """我发一句话，她们一条接一条地说。一条一条推给页面，别一起冒出来。

        事件：`{"type":"thinking","speaker_id":...}`（她想说话）、
        `{"type":"message","message":{...}}`（她说完了）、`{"type":"done"}`。"""
        group = group_or_404(group_id, user_id)
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "说点什么吧")
        members = [characters[c] for c in group.participants if c in characters]
        if not members:
            raise HTTPException(422, "群里没有人")
        brought = BroughtKeys()
        if not backend.config.chat_model.text.configured and brought.llm is None:
            raise HTTPException(503, NO_CHAT_MODEL)
        admission = admissions.turn(user_id, members[0].id, brought)

        async def events() -> AsyncIterator[str]:
            def send(payload: dict) -> str:
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # 这一轮之前群里说过什么：记忆要用它当上下文（群消息不是单聊的历史）。
            before = [
                (
                    "制作人"
                    if entry.role == "user"
                    else (
                        characters[entry.speaker_id].name_zh
                        or characters[entry.speaker_id].name
                        if entry.speaker_id in characters
                        else entry.speaker_id or "？"
                    ),
                    " ".join(segment.zh or segment.ja for segment in entry.segments),
                )
                for entry in group_chat.messages_of(store, group.id)
            ]
            spoke: str | None = None
            yield send({"type": "user", "segments": [{"ja": "", "zh": text}]})
            async for kind, speaker_id, message in group_chat.run_turn(
                store,
                group,
                characters,
                text,
                admission.llms.chat,
                admission.llms.background,
                forced=(body.target_id,) if body.target_id else (),
                tiers=group_tiers(user_id, list(group.participants)),
                modes=group_modes(user_id, list(group.participants)),
                place=group_place(group),
            ):
                if kind == "thinking":
                    yield send({"type": "thinking", "speaker_id": speaker_id})
                elif message is not None:
                    spoke = spoke or speaker_id
                    yield send({"type": "message", "message": message_json(message)})
            # 群里说的也记下来：关于制作人的那些，记在第一个接话的人名下（群消息没有
            # 自己的 conversation 行，`Memories.write_group` 会存成没有出处的记忆）。
            speaker = characters.get(spoke) if spoke else (members[0] if members else None)
            if speaker is not None:
                profile = store.get_profile(user_id)
                memory.write_group(
                    user_id,
                    speaker,
                    effective_timezone(profile, None),
                    before,
                    text,
                    admission.llms.background,
                )
            yield send({"type": "done"})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/conversations/{conversation_id}/turns")
    def text_turn(
        conversation_id: str,
        body: TurnInput,
        user_id: UserId,
        device_timezone: DeviceTimezone = None,
    ) -> StreamingResponse:
        conversation = conversation_or_404(conversation_id, user_id)
        if body.own_llm is not None:  # transitional: see `TurnInput.own_llm`
            raise HTTPException(422, "页面已经更新，请刷新后再发")
        brought = body.own_keys.brought() if body.own_keys else BroughtKeys()
        if not backend.config.chat_model.text.configured and brought.llm is None:
            # A deployment still being set up (EIDOLON_CHAT_LLM_OPTIONAL=1) has no model of
            # its own: only a turn bringing its own LLM can run, and the rest are told why.
            raise HTTPException(503, NO_CHAT_MODEL)
        admission = admissions.turn(user_id, conversation.character_id, brought)
        outcome = TurnOutcome(admission.recording, admission.settle)
        picture = _decode_turn_image(body.image)
        place = current_place(characters[conversation.character_id], conversation.id)

        async def events() -> AsyncIterator[str]:
            # Closed as the response is, so that the turn is no longer under way once the user
            # has gone (`Store.taking_turn`).
            with outcome.running():
                note = None
                is_her: bool | None = None
                other: str | None = None
                recorded: Message | None = None
                if picture is not None:  # what it shows, worked out before her prompt is built
                    # A background model of its own was chosen, so let it read the picture: a
                    # cheap or better-seeing one, leaving the model that plays her to talk.
                    reader = (
                        admission.llms.background
                        if backend.settings.background_llm_explicit
                        else admission.llms.chat
                    )
                    try:
                        note, is_her, other = await _describe_picture(
                            reader,
                            picture,
                            characters.get(conversation.character_id),
                            roster="；".join(
                                f"{c.name}（{c.photo_appearance}）" if c.photo_appearance else c.name
                                for c in characters.values()
                            ),
                        )
                        note = note or None
                    except Exception:  # her turn still runs, just without the picture told
                        log.exception("could not describe the picture in conversation %s", conversation.id)
                async with aclosing(engine.turn(
                    conversation, body.text, admission.llms, device_timezone,
                    own_image=brought.image, image=picture, picture_note=note,
                    picture_is_her=is_her, picture_other=other, place=place,
                )) as turn:
                    async for event in turn:
                        outcome.see(event)
                        if isinstance(event, SegmentDelta):
                            outcome.began_speaking()  # the reply's first words have appeared
                        if isinstance(event, TurnDone):
                            recorded = event.message
                        if isinstance(event, SegmentComplete | SpeechDelta | TurnJudged):
                            continue
                        payload = shown(event)
                        if isinstance(event, TurnDone):
                            # 这条回复里她说到的原声，和历史消息一样现算（`voice_of`）。
                            payload["message"] = payload["message"] | {
                                "voice": voice_of(event.message)
                            }
                        yield _sse(payload)
            if picture is not None:  # kept once the turn is on the record, to show it again
                store.keep_user_image(conversation.id, body.text, picture[1], picture[0])
            # 这一回合里，他们有没有说定换到别的地方（DESIGN.md「通话场景」）：回复记下以后
            # 再问，和语气一样不拖慢回复；说定了就记下来，并告诉页面把「现在」和背景换过去。
            if backend.settings.scene_moves and recorded is not None:
                moved = await scene_move(
                    conversation,
                    characters[conversation.character_id],
                    body.text,
                    recorded,
                    admission.llms.chat,
                )
                if moved is not None:
                    backend.conversation_scenes.keep(
                        conversation.id, moved.id, backend.clock().isoformat()
                    )
                    yield _sse(
                        {
                            "type": "scene",
                            "scene": {
                                "id": moved.id,
                                "name": moved.name,
                                "image_url": f"/api/scenes/{moved.id}",
                            },
                        }
                    )
            # How she said it (DESIGN.md「对话页的立绘小人」): asked once the reply is recorded,
            # after `done`, so that the judge never holds the reply up. Nothing if it cannot be
            # judged, or if the turn runs on the user's own LLM, whose keys hold no judge.
            emotions = admission.keys.emotions
            if recorded is not None and emotions is not None:
                judged = await emotions.answer(
                    SegmentToJudge(
                        character=characters[conversation.character_id],
                        user_said=body.text,
                        before=(),
                        segment=SaidSegment(
                            ja="\n".join(segment.ja for segment in recorded.segments),
                            zh="".join(segment.zh for segment in recorded.segments),
                        ),
                    ),
                    # 宠物这一边宁可要一个鲜明的表情，也不要一句「平静」：门槛比通话里低。
                    0.3,
                )
                if judged is not None:
                    mood, nod, strength = judged
                    # 记下来：复读这条回复的语音时用同一个答案，两处摆出来的动作一样。
                    judged_moods[f"m:{recorded.id}"] = judged
                    yield _sse(
                        {"type": "emotion", "emotion": mood, "nod": nod, "strength": round(strength, 2)}
                    )

        return _TurnResponse(events(), lambda: outcome.over(cut_short_by_failure=False))

    return app


class _TurnResponse(StreamingResponse):
    """A text turn's events, `end` called once they are sent or the page is gone, even
    gone before they began, when the stream of them never runs."""

    def __init__(self, events: AsyncIterator[str], end: Callable[[], None]) -> None:
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self._end = end

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._end()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
