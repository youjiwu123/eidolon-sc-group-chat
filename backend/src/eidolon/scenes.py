"""通话场景（DESIGN.md「通话场景」）：接通电话时她身后那张背景，怎么挑。

场景表在 `characters/scenes.toml`（`load_scenes`），图在 `characters/scenes/`，由
`/api/scenes/<id>` 送出。

接通时先看这通电话有没有「已经在聊」的东西：

- 有（最近至少有几句来回）：把最近二十句交给判断模型，只让它从场景表里挑一个；挑不出来、
  或者是「说不准」以外胡编的，就回落。
- 没有（新对话，或者一句话都没有）：随机挑一条她的预设行为（`[behaviors]`），按行为的场景
  接通——「在练习室练舞」就是练习室，不必再问模型。

有排期表的角色（29 位里 28 位，`characters/schedules.<id>.week*.toml` 或
`characters/schedules/<id>.week*.toml`）不走上面第二条：单聊接通和页首用同一格
（`app.current_scene`，按节日 / 事件 / 星期几 + 时段 / 随机池挑，种子按角色、日期、时段
固定），开场白按那一格的活动写；群通话的冷启动仍由 `schedules.py` 现挑。
`[[behaviors]]` 是她没有排期表、或者排期表挑不出来时的兜底。

判断模型只出场景 id 和一句理由，不碰别的；它拿到的提示词里，场景是有名字和辨识依据的清单。
"""

from __future__ import annotations

import json
import logging
import random
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eidolon.characters import Character
from eidolon.llm import ChatMessage

log = logging.getLogger(__name__)

FALLBACK = "sky"
"""什么都没有时用的场景（外景天空）：说不准的时候看着也不怪。"""


@dataclass(frozen=True)
class Scene:
    id: str
    name: str
    hint: str
    image: str


@dataclass(frozen=True)
class Behavior:
    """她现在在做什么：冷启动时随机挑一条，按它的场景接通。"""

    character: str
    """哪位角色的；`*` 是所有人共用的。"""
    scene: str
    text: str


@dataclass(frozen=True)
class Catalog:
    scenes: tuple[Scene, ...]
    behaviors: tuple[Behavior, ...]

    def scene(self, scene_id: str) -> Scene | None:
        for scene in self.scenes:
            if scene.id == scene_id:
                return scene
        return None

    def fallback(self) -> Scene:
        return self.scene(FALLBACK) or self.scenes[0]

    def behavior(self, character_id: str, rng: random.Random | None = None) -> Behavior | None:
        """她的一条预设行为：自己的优先，没有就用所有人共用的。"""
        mine = [b for b in self.behaviors if b.character == character_id]
        shared = [b for b in self.behaviors if b.character == "*"]
        candidates = mine or shared
        if not candidates:
            return None
        return (rng or random).choice(candidates)


def load_scenes(path: Path) -> Catalog:
    """Read the scene table at `path`, raising RuntimeError saying what is wrong with it."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RuntimeError(f"缺少场景表 {path}") from e
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise RuntimeError(f"场景表 {path} 读不了：{e}") from e
    scenes = tuple(
        Scene(str(item["id"]), str(item["name"]), str(item.get("hint", "")), str(item["image"]))
        for item in data.get("scenes", [])
    )
    if not scenes:
        raise RuntimeError(f"场景表 {path} 里没有 [[scenes]]")
    ids = {scene.id for scene in scenes}
    behaviors = []
    for item in data.get("behaviors", []):
        scene = str(item["scene"])
        if scene not in ids:
            raise RuntimeError(f"场景表 {path}：行为用到了不存在的场景 {scene}")
        behaviors.append(Behavior(str(item.get("character", "*")), scene, str(item["text"])))
    return Catalog(scenes, tuple(behaviors))


@dataclass(frozen=True)
class Picked:
    """接通时的场景、为什么是它，和她接通时说的第一句（开场白，跟着场景走）。"""

    scene: Scene
    why: str
    source: str
    """`chat`：按最近的对话判的；`behavior`：按预设行为挑的；`schedule`：按排期表挑的；
    `slot`/`pool`/`holiday`/`event`：排期表那一格具体是哪一步挑中的（单聊接通，和页首
    同一格）；`fallback`：兜底那张。"""
    opener_ja: str = ""
    """开场白的日语原文，可以带语气提示（`[softly]`）；写不出来就是空的。"""
    opener_zh: str = ""
    """开场白的中文字幕。"""
    activity: str = ""
    """排期表挑中的那一格她在做什么；开场白按它写，也是开场白缓存的键之一。"""


def prompt(catalog: Catalog, character: Character | None, said: Sequence[tuple[str, str]], title: str | None) -> list[ChatMessage]:
    """给判断模型的问题：她是谁、最近的对话、只能从里面挑的场景表，和开场白。"""
    who = f"这位是{character.name_zh or character.name}。" if character else "这是一通群聊电话。"
    listed = "\n".join(f"- {scene.name}（{scene.hint}）" for scene in catalog.scenes)
    transcript = "\n".join(f"{speaker}：{text}" for speaker, text in said if text.strip())
    system = (
        "你是「シャニマス」的制作人助手。制作人刚给下面这位偶像打了电话。\n"
        "根据最近这段对话，判断电话接通的那一刻，她最可能在什么地方。\n\n"
        f"只能从这些场景里选一个，不要发明新的：\n{listed}\n\n"
        "对话里没有任何地点线索时，选「说不准」。\n\n"
        "还要写她接通电话时说的第一句（开场白）：就在这个场景里、接着这段对话，用她的口吻写一句"
        "日语（可以带 [softly] 这类语气提示），配一句中文字幕；不超过两句，不要提「场景」这个词。\n"
        "只输出一行 JSON，不要解释："
        '{"scene": "场景名", "why": "不超过 20 字", "opener_ja": "日语", "opener_zh": "中文"}'
    )
    title_line = f"（对话标题：{title}）\n" if title else ""
    user = f"{who}{title_line}最近的对话：\n{transcript}\n\n按上面的要求给 JSON。"
    return [ChatMessage("system", system), ChatMessage("user", user)]


def parse(answer: str, catalog: Catalog) -> tuple[Scene, str, str, str] | None:
    """The scene the judge picked, its one-line reason, and her opener (Japanese, subtitle):
    the scene's name, matched against the catalog; None if it invented one or answered
    nothing usable."""
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    chosen = data.get("scene")
    if not isinstance(chosen, str):
        return None
    why = data.get("why")
    ja = data.get("opener_ja")
    zh = data.get("opener_zh")
    for scene in catalog.scenes:
        if chosen.strip() == scene.name or chosen.strip() == scene.id:
            return (
                scene,
                why.strip() if isinstance(why, str) else "",
                ja.strip() if isinstance(ja, str) else "",
                zh.strip() if isinstance(zh, str) else "",
            )
    return None


async def judge(
    catalog: Catalog,
    chat: object,
    character: Character | None,
    said: Sequence[tuple[str, str]],
    title: str | None = None,
) -> Picked | None:
    """Ask the judge where she is and what she says first; None if it could not be asked."""
    chunks: list[str] = []
    stream = chat.stream(prompt(catalog, character, said, title), (), forbid_calls=True)  # type: ignore[attr-defined]
    try:
        async for item in stream:
            if isinstance(item, str):
                chunks.append(item)
    except Exception:
        log.exception("scene: could not ask where she is")
        return None
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
    judged = parse("".join(chunks), catalog)
    if judged is None:
        return None
    scene, why, ja, zh = judged
    return Picked(scene, why, "chat", ja, zh)


def opener_prompt(catalog: Catalog, character: Character | None, behavior: Behavior) -> list[ChatMessage]:
    """冷启动时只写开场白：她这会儿在做什么（预设行为），按它写第一句。"""
    return opener_prompt_for(character, behavior.text)


def opener_prompt_for(character: Character | None, activity: str) -> list[ChatMessage]:
    """按「她这会儿在做什么」写开场白：预设行为是一条，排期表挑中的一格也是一条。"""
    who = character.name_zh or character.name if character else "她"
    system = (
        "你是「シャニマス」的制作人助手。制作人刚给下面这位偶像打了电话，她接起来。\n"
        f"她这会儿在：{activity}\n\n"
        "用她的口吻写她接通电话时说的第一句：一句日语（可以带 [softly] 这类语气提示）"
        "和一句中文字幕；不超过两句，不要提「场景」这个词。\n"
        "只输出一行 JSON，不要解释："
        '{"opener_ja": "日语", "opener_zh": "中文"}'
    )
    return [ChatMessage("system", system), ChatMessage("user", f"这位是{who}。给 JSON。")]


async def opener_for(chat: object, catalog: Catalog, character: Character | None, behavior: Behavior) -> tuple[str, str]:
    """The opener written for a preset behavior: (Japanese, subtitle); empty when it could
    not be written."""
    return await opener_for_activity(chat, character, behavior.text)


async def opener_for_activity(
    chat: object, character: Character | None, activity: str
) -> tuple[str, str]:
    """按排期表挑中的那一格写开场白：和预设行为走同一套写法，只是把「在做什么」换成一格的活动。

    (日语, 字幕)；写不出来就是空的。"""
    chunks: list[str] = []
    stream = chat.stream(opener_prompt_for(character, activity), (), forbid_calls=True)  # type: ignore[attr-defined]
    try:
        async for item in stream:
            if isinstance(item, str):
                chunks.append(item)
    except Exception:
        log.exception("scene: could not write the opener")
        return "", ""
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
    return _opener_from("".join(chunks))


def _opener_from(answer: str) -> tuple[str, str]:
    """从那行 JSON 里取（日语, 字幕）；没有 JSON 或者字段不对就是空的。"""
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        return "", ""
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return "", ""
    ja = data.get("opener_ja") if isinstance(data, dict) else None
    zh = data.get("opener_zh") if isinstance(data, dict) else None
    return (ja.strip() if isinstance(ja, str) else "", zh.strip() if isinstance(zh, str) else "")


def pick_by_behavior(catalog: Catalog, character_id: str) -> Picked | None:
    """冷启动：随机一条预设行为，按行为的场景接通（开场白另外让模型写）。"""
    behavior = catalog.behavior(character_id)
    if behavior is None:
        return None
    scene = catalog.scene(behavior.scene)
    if scene is None:
        return None
    return Picked(scene, behavior.text, "behavior")


def behavior_of(catalog: Catalog, character_id: str) -> Behavior | None:
    """The preset behavior a cold call picked, for writing its opener."""
    return catalog.behavior(character_id)


def move_prompt(
    catalog: Catalog,
    character: Character | None,
    current: Scene | None,
    said: Sequence[tuple[str, str]],
) -> list[ChatMessage]:
    """问判断模型：这一来一回里，他们是不是说定了换到别的地方，换了是哪里。

    只认「说定了」的：提一句、开玩笑、还没答应都不算。场景只能从表里挑。"""
    who = f"这位是{character.name_zh or character.name}。" if character else "这是一通群聊电话。"
    listed = "\n".join(f"- {scene.name}（{scene.hint}）" for scene in catalog.scenes)
    now = f"她现在在：{current.name}（{current.hint}）。\n" if current else ""
    transcript = "\n".join(f"{speaker}：{text}" for speaker, text in said if text.strip())
    system = (
        "你是「シャニマス」的制作人助手。下面是制作人和这位偶像最近的几句话。\n"
        f"{now}"
        "看这几句里，他们有没有**说定**换到别的地方去：有人提议（例如「去咖啡厅吧」「要不要去公园」），"
        "另一个人答应了，或者说「那我们走吧」。只是提一句、开玩笑、还没答应，都算没换。\n\n"
        f"说定了就只能从这些场景里挑一个，不要发明新的：\n{listed}\n\n"
        "只输出一行 JSON，不要解释："
        '{"moved": true, "scene": "场景名"} 或 {"moved": false}'
    )
    user = f"{who}最近的对话：\n{transcript}\n\n按上面的要求给 JSON。"
    return [ChatMessage("system", system), ChatMessage("user", user)]


def parse_move(answer: str, catalog: Catalog) -> Scene | None:
    """Judged answer → the scene they moved to; None if they did not move, it answered no, it
    invented a scene, or it said 说不准."""
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("moved") is not True:
        return None
    chosen = data.get("scene")
    if not isinstance(chosen, str):
        return None
    for scene in catalog.scenes:
        if chosen.strip() in (scene.name, scene.id):
            return None if scene.id == FALLBACK else scene
    return None


async def judge_move(
    catalog: Catalog,
    chat: object,
    character: Character | None,
    current: Scene | None,
    said: Sequence[tuple[str, str]],
) -> Scene | None:
    """Ask the judge whether they said out loud they are going somewhere else; None if it
    could not be asked, or they are not."""
    chunks: list[str] = []
    stream = chat.stream(move_prompt(catalog, character, current, said), (), forbid_calls=True)  # type: ignore[attr-defined]
    try:
        async for item in stream:
            if isinstance(item, str):
                chunks.append(item)
    except Exception:
        log.exception("scene: could not ask whether they moved")
        return None
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
    return parse_move("".join(chunks), catalog)
