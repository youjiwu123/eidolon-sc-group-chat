"""她的原声（名台词和生日祝福）：从原作里截下来的那几句，连同音频一起用。

原声表在 `characters/voices.toml`（`load_voices`），音频在 `characters/` 下、按 `audio`
写的相对路径放（`audio_file`），由 `/api/voices/<path>` 原样送出。每条是一句她说过的话：

- `kind = "quote"` 是名台词，对话页气泡旁那个「原声」键和 `/voices` 页用它；
- `kind = "birthday"` 是生日祝福，制作人生日那天由 `/api/birthday` 拿出来。

回复里原样包含某一句（换行不算）时，回复就带上那一句的原声（`VoicesCatalog.match`）：逐字
包含、至少 `MIN_MATCH_LENGTH` 个字、最长的那两句里挑。太短的「ほわっ」不参与，免得每个气泡
都挂一个。

原声表由维护者生成后放进仓库；`VoiceLibrary` 按文件的修改时刻缓存，文件一改下一次请求就读
新的，不必重启（文件没有时当作一句都没有，接口照常返回空列表）。
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

VOICES_DIR = "voices"
"""音频在她原声表旁边的这个目录下：`audio` 一律写成 `voices/<角色>/<故事>_<行>.mp3`。"""

SOURCE_FILE = "voices.toml"
"""原声表本身（`characters/voices.toml`，由 `characters/voices/` 脚本生成）。"""

AUDIO_PREFIX = "/api/voices/"
"""音频的网址前缀，后面接表里 `audio` 那一段（`audio_url`）。"""

AUDIO_CACHE = "public, max-age=86400"
"""一句原声在它的地址上不会变（换一句就是另一条），浏览器留一天，和头像一样。"""

KINDS = ("quote", "birthday")
"""`quote` 是名台词，`birthday` 是生日祝福。"""

MIN_MATCH_LENGTH = 6
"""太短的一句（「ほわっ」）不参与匹配：几乎每条回复都“包含”它，挂上去只是噪音。"""

MAX_MATCHES = 2
"""一条回复最多挂两句原声。"""


@dataclass(frozen=True)
class VoiceLine:
    """她说过的一句原声。"""

    character: str
    """哪位角色的。"""
    story: str
    """这句话出自哪一段剧情（剧情库里的单元或话的编号）。"""
    line: str
    """在这段剧情里的第几句，四位编号，按它排序。"""
    text: str
    """日语原文，可以带换行（原样显示，匹配时把换行去掉）。"""
    subtitle: str
    """官方中译；没有时是空字符串。"""
    audio: str
    """音频相对 `characters/` 的路径，如 `voices/mano/s01_01010000_00_0030.mp3`。"""
    seconds: float
    """这段音频大约多长（秒），给进度用；表里没写就是 0。"""
    kind: str
    """`quote` 或 `birthday`。"""

    @property
    def spoken(self) -> str:
        """这句话去掉了换行的样子：匹配回复时两边都这样比。"""
        return _one_line(self.text)


def _one_line(text: str) -> str:
    """去掉换行，其余原样。"""
    return text.replace("\r", "").replace("\n", "")


def audio_url(line: VoiceLine) -> str:
    """这一句的音频网址：`/api/voices/` 加上表里 `audio` 那一段（路径分隔符不转义）。"""
    return AUDIO_PREFIX + quote(line.audio, safe="/")


@dataclass(frozen=True)
class VoicesCatalog:
    """整份原声表，按表里的顺序。"""

    lines: tuple[VoiceLine, ...] = ()

    @property
    def characters(self) -> tuple[str, ...]:
        """表里出现过的角色，按第一次出现的顺序。"""
        return tuple(dict.fromkeys(line.character for line in self.lines))

    def of_character(self, character_id: str, kind: str | None = None) -> tuple[VoiceLine, ...]:
        """她的原声，可以只看某一种（`kind`）；表里没有她时是空的。"""
        return tuple(
            line
            for line in self.lines
            if line.character == character_id and (kind is None or line.kind == kind)
        )

    def of_kind(self, kind: str) -> tuple[VoiceLine, ...]:
        """某一种的全部原声，按表里的顺序。"""
        return tuple(line for line in self.lines if line.kind == kind)

    def match(self, said: str | None) -> tuple[VoiceLine, ...]:
        """她说的一段回复里逐字包含的原声：换行不算，至少 `MIN_MATCH_LENGTH` 个字，
        按长度从长到短，最多 `MAX_MATCHES` 句。同样文字的两条只留先出现的那条。"""
        if not said:
            return ()
        heard = _one_line(said)
        hits: list[VoiceLine] = []
        seen: set[str] = set()
        for line in self.lines:
            spoken = line.spoken
            if len(spoken) < MIN_MATCH_LENGTH or spoken in seen or spoken not in heard:
                continue
            seen.add(spoken)
            hits.append(line)
        hits.sort(key=lambda line: len(line.spoken), reverse=True)
        return tuple(hits[:MAX_MATCHES])


def load_voices(path: Path) -> VoicesCatalog:
    """读 `path` 的原声表，读不了时抛 RuntimeError 说清楚哪里不对；表里一条都没有就是空的。"""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RuntimeError(f"缺少原声表 {path}") from e
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise RuntimeError(f"原声表 {path} 读不了：{e}") from e
    lines: list[VoiceLine] = []
    entries = data.get("line", [])
    if not isinstance(entries, list):
        raise RuntimeError(f"原声表 {path} 的 [[line]] 应为列表")
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise RuntimeError(f"原声表 {path} 第 {index} 条 [[line]] 应为一张表")
        label = f"原声表 {path} 第 {index} 条 [[line]]"
        character = _text(entry, "character", label)
        story = _text(entry, "story", label)
        number = _text(entry, "line", label)
        text = _text(entry, "text", label)
        audio = _text(entry, "audio", label)
        if not audio.startswith(f"{VOICES_DIR}/"):
            raise RuntimeError(f"{label} 的 audio 应写成 {VOICES_DIR}/<角色>/<文件>.mp3，现在是 {audio!r}")
        if "\\" in audio or "\x00" in audio or ".." in Path(audio).parts:
            raise RuntimeError(f"{label} 的 audio 不能带上下级目录，现在是 {audio!r}")
        kind = entry.get("kind", "quote")
        if kind not in KINDS:
            raise RuntimeError(f"{label} 的 kind 只能是 {' / '.join(KINDS)}，现在是 {kind!r}")
        seconds = entry.get("seconds", 0)
        if type(seconds) not in (int, float) or seconds < 0:
            raise RuntimeError(f"{label} 的 seconds 应为不小于 0 的秒数，现在是 {seconds!r}")
        subtitle = entry.get("subtitle", "")
        if not isinstance(subtitle, str):
            raise RuntimeError(f"{label} 的 subtitle 应为字符串，现在是 {subtitle!r}")
        lines.append(
            VoiceLine(
                character=character,
                story=story,
                line=number,
                text=text,
                subtitle=subtitle.strip(),
                audio=audio,
                seconds=float(seconds),
                kind=kind,
            )
        )
    return VoicesCatalog(tuple(lines))


def _text(entry: dict, field: str, label: str) -> str:
    """表里一个必填的字符串字段，去掉首尾空白后不空。"""
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} 缺少 {field}（不空的字符串）")
    return value.strip()


def audio_file(characters: Path, relative: str) -> Path | None:
    """`relative`（表里的 `audio`）在 `characters/` 下指的文件；不是 `voices/` 下的普通文件、
    或者想跑出这个目录时是 None（防目录穿越）。"""
    if not relative.startswith(f"{VOICES_DIR}/") or "\\" in relative or "\x00" in relative:
        return None
    parts = Path(relative).parts
    if any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        return None
    root = characters.resolve()
    path = (root / Path(*parts)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


class VoiceLibrary:
    """原声表（`characters/voices.toml`），按文件的修改时刻缓存：文件没动就不读盘，改了下一次
    请求就读新的（热加载）。

    没有表、或者表读不了时就是一句都没有，不报错：名台词页空着，回复也不挂原声。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._read: tuple[int, int] | None = None
        self._catalog = VoicesCatalog()
        self._warned = False

    def catalog(self) -> VoicesCatalog:
        path = self._path
        if not path.is_file():
            if not self._warned:
                log.warning("voices: 没有原声表（%s），名台词和生日彩蛋先空着", path)
                self._warned = True
            self._read, self._catalog = None, VoicesCatalog()
            return self._catalog
        try:
            stat = path.stat()
        except OSError:
            return VoicesCatalog()
        read = (stat.st_mtime_ns, stat.st_size)
        if read != self._read:
            try:
                self._catalog = load_voices(path)
            except RuntimeError:
                log.exception(
                    "voices: 原声表 %s 读不了，先当作没有（改好文件后下一次请求会重读）", path
                )
                self._catalog = VoicesCatalog()
            self._read = read
            self._warned = False
        return self._catalog
