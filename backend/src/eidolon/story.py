"""剧情回放（GLOSSARY.md「剧情」「剧情目录」）：把整理好的全作品剧情摘要做成一个能一页页翻的目录。

数据由 `backend/scripts/build_story_data.py` 从 `.scratch/outline/` 的导出构建，放在
`characters/story/`：`index.json` 是全部单元，`<单元 id>.json` 是每个单元自己的话。单元就是导出里
的那个：一位偶像的一条培育路线、一期活动、一个特别企划、一张卡的剧情、一段主页剧情，或一个 SCSP
剧本组；页面上按路线、活动、特别企划、卡面（按角色）、主页营业、SCSP 分区列出。

这里只管读：`load_story_catalog` 读索引（同时确认每个单元的文件都在），`StoryCatalog.detail` 读一个
单元的话。文件缺了或读不了都抛 RuntimeError，说清楚是哪个文件、少的是什么，和 `scenes.py` 一样。

剧情是作品的东西，不是任何用户的：目录对每个登录的用户都一样，接口只读。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

INDEX_FILE = "index.json"
"""The list of every unit, and the story directory's entry point."""

UNIT_FILE_SUFFIX = ".json"


@dataclass(frozen=True)
class StoryEpisode:
    """One 话 of a chapter that gathers several (SCSP's chapters hold two to four)."""

    id: str
    title: str
    cast: tuple[str, ...] = ()

    def as_json(self) -> dict:
        return {"id": self.id, "title": self.title, "cast": list(self.cast)}


@dataclass(frozen=True)
class StoryChapter:
    """One card of the page: a whole episode, or a chapter of several with a summary of its own."""

    id: str
    title: str
    summary: str
    cast: tuple[str, ...]
    ja: str = ""
    """The chapter's title in the original Japanese, the 「出处」 shown under the Chinese one."""
    episodes: tuple[StoryEpisode, ...] = ()
    """For a chapter that gathers several episodes, those episodes; empty for one episode a card."""

    def as_json(self) -> dict:
        shown: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "cast": list(self.cast),
        }
        if self.ja:
            shown["ja"] = self.ja
        if self.episodes:
            shown["episodes"] = [episode.as_json() for episode in self.episodes]
        return shown


@dataclass(frozen=True)
class StoryUnit:
    """One unit of the story catalog, as the page's list and its detail's header show it."""

    id: str
    kind: str
    """`route`, `event`, `special`, `card`, `mypage`, `scsp`, or the outline's leftovers `bu` and
    `other`."""
    label: str
    """The unit's name as the source spells it, its character or card included (「出处」)."""
    name: str
    """Its short name, from the outline's rollup."""
    gist: str
    shape: str
    themes: tuple[str, ...]
    cast: tuple[str, ...]
    src: str
    """`browser` (the page game) or `scsp`."""
    unit: str
    """The source's own unit key (`route:W.I.N.G.編:mano`), kept for checking the build."""
    group: str | None
    """The group the page lists the unit under (a route, a character); None when it stands alone."""
    group_label: str | None
    episodes: int
    """How many episodes the unit has, the number of its cards when it has no chapters of several."""

    def as_listed(self) -> dict:
        """What the page's list needs: no rollup text and no episodes."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "episodes": self.episodes,
            "group": self.group,
            "group_label": self.group_label,
        }


@dataclass(frozen=True)
class StoryUnitDetail:
    """One unit read from its own file: the rollup and its chapters."""

    unit: StoryUnit
    chapters: tuple[StoryChapter, ...]

    def as_json(self) -> dict:
        return {
            "id": self.unit.id,
            "kind": self.unit.kind,
            "label": self.unit.label,
            "name": self.unit.name,
            "gist": self.unit.gist,
            "shape": self.unit.shape,
            "themes": list(self.unit.themes),
            "cast": list(self.unit.cast),
            "src": self.unit.src,
            "unit": self.unit.unit,
            "group": self.unit.group,
            "group_label": self.unit.group_label,
            "episodes": self.unit.episodes,
            "chapters": [chapter.as_json() for chapter in self.chapters],
        }


@dataclass(frozen=True)
class StoryCatalog:
    """The story units there are, and where their files are."""

    path: Path
    units: tuple[StoryUnit, ...]

    @property
    def total_episodes(self) -> int:
        return sum(unit.episodes for unit in self.units)

    def unit(self, unit_id: str) -> StoryUnit | None:
        for unit in self.units:
            if unit.id == unit_id:
                return unit
        return None

    def detail(self, unit_id: str) -> StoryUnitDetail | None:
        """The unit's chapters, read from `<path>/<unit_id>.json`; None for no such unit."""
        unit = self.unit(unit_id)
        if unit is None:
            return None
        return _read_detail(self.path / f"{unit_id}{UNIT_FILE_SUFFIX}", unit)

    def listing(self) -> dict:
        """The page's list: every unit, and how many episodes there are all told."""
        return {
            "total_episodes": self.total_episodes,
            "units": [unit.as_listed() for unit in self.units],
        }


def empty_catalog(path: Path) -> StoryCatalog:
    """没有剧情数据时用的空目录（数据还没构建的部署里，剧情页先空着，别的照常）。"""
    return StoryCatalog(path=path, units=())


def load_story_catalog(path: Path) -> StoryCatalog:
    """Read the story catalog at `path`, raising RuntimeError saying what is wrong with it."""
    index_path = path / INDEX_FILE
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RuntimeError(
            f"缺少剧情索引 {index_path}（先在仓库根跑 backend/scripts/build_story_data.py）"
        ) from e
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"剧情索引 {index_path} 读不了：{e}") from e
    if not isinstance(data, list):
        raise RuntimeError(f"剧情索引 {index_path} 应该是一个单元列表，而不是 {type(data).__name__}")
    units = tuple(_read_unit(item, index_path, position) for position, item in enumerate(data))
    seen: set[str] = set()
    for unit in units:
        if unit.id in seen:
            raise RuntimeError(f"剧情索引 {index_path} 里单元 id {unit.id} 重复了")
        seen.add(unit.id)
    missing = [unit.id for unit in units if not (path / f"{unit.id}{UNIT_FILE_SUFFIX}").is_file()]
    if missing:
        raise RuntimeError(
            f"剧情索引 {index_path} 提到的单元没有文件（共 {len(missing)} 个）："
            + "、".join(missing[:3])
        )
    return StoryCatalog(path=path, units=units)


def _read_unit(item: Any, index_path: Path, position: int) -> StoryUnit:
    """One entry of the index, checked; its number in the file tells where a bad one is."""
    where = f"剧情索引 {index_path} 第 {position + 1} 条"
    if not isinstance(item, dict):
        raise RuntimeError(f"{where}不是一个对象")
    for field in ("id", "kind", "name", "episodes"):
        if field not in item:
            raise RuntimeError(f"{where}缺少 {field}")
    unit_id = item["id"]
    if not isinstance(unit_id, str) or not unit_id or "/" in unit_id or "\\" in unit_id:
        raise RuntimeError(f"{where}的单元 id 不是能当文件名的字符串：{unit_id!r}")
    episodes = item["episodes"]
    if not isinstance(episodes, int) or isinstance(episodes, bool) or episodes < 0:
        raise RuntimeError(f"{where}的 episodes 不是非负整数：{episodes!r}")
    return StoryUnit(
        id=unit_id,
        kind=str(item["kind"]),
        label=str(item.get("label", "")),
        name=str(item.get("name", "")),
        gist=str(item.get("gist", "")),
        shape=str(item.get("shape", "")),
        themes=_strings(item.get("themes")),
        cast=_strings(item.get("cast")),
        src=str(item.get("src", "")),
        unit=str(item.get("unit", "")),
        group=_optional_string(item.get("group")),
        group_label=_optional_string(item.get("group_label")),
        episodes=episodes,
    )


def _read_detail(path: Path, unit: StoryUnit) -> StoryUnitDetail:
    """One unit's file, checked; the index's entry is the authority on what it should say."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RuntimeError(f"缺少剧情单元 {path}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"剧情单元 {path} 读不了：{e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"剧情单元 {path} 不是一个对象")
    if data.get("id") != unit.id:
        raise RuntimeError(f"剧情单元 {path} 的 id 和索引里的 {unit.id} 对不上：{data.get('id')!r}")
    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        raise RuntimeError(f"剧情单元 {path} 缺少 chapters 列表")
    return StoryUnitDetail(
        unit=unit,
        chapters=tuple(_read_chapter(item, path, position) for position, item in enumerate(chapters)),
    )


def _read_chapter(item: Any, path: Path, position: int) -> StoryChapter:
    where = f"剧情单元 {path} 第 {position + 1} 章"
    if not isinstance(item, dict):
        raise RuntimeError(f"{where}不是一个对象")
    for field in ("id", "title"):
        if field not in item:
            raise RuntimeError(f"{where}缺少 {field}")
    episodes = item.get("episodes", [])
    if not isinstance(episodes, list):
        raise RuntimeError(f"{where}的 episodes 不是列表")
    return StoryChapter(
        id=str(item["id"]),
        title=str(item["title"]),
        summary=str(item.get("summary", "")),
        cast=_strings(item.get("cast")),
        ja=str(item.get("ja", "")),
        episodes=tuple(_read_episode(episode, where, index) for index, episode in enumerate(episodes)),
    )


def _read_episode(item: Any, where: str, position: int) -> StoryEpisode:
    if not isinstance(item, dict) or "id" not in item or "title" not in item:
        raise RuntimeError(f"{where}的第 {position + 1} 话缺 id 或 title")
    return StoryEpisode(id=str(item["id"]), title=str(item["title"]), cast=_strings(item.get("cast")))


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, (str, int)) and str(item).strip())


def _optional_string(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None
