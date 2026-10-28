"""SCSP 剧情原声切片的可复现流水线：`characters/voices.toml` + `characters/voices/`。

这份脚本是 `.scratch/voices/` 里一次性探索的收敛版：把「选行 → 找 ACB → 按 stream name
切 → 转 mp3 → 写表」固定成五段可单独运行、可续跑的命令，并把三个反直觉的坑写进代码。

    targets   把 `characters/voices.toml` 读回来，逐条到本地资源库里确认 cue 名
    fetch     用三级兜底解析 ACB 并下载（本地资源库 API，不碰游戏客户端）
    decode    vgmstream 按 **stream name** 定位并导出 wav（绝不用 `cue_index`）
    encode    ffmpeg 转单声道 mp3：96 kbps，超过 200 KB 再降到 48 kbps
    emit      按现有音频重新写 `characters/voices.toml`
    check     只读校验：392 条的文件、时长、cue 名、角色码；（--deep）再核 stream
    build     targets → fetch → 逐 story decode+encode → emit 的全量重建

为什么目标集合从 `voices.toml` 反推、而不是从 persona 重新生成？
探索阶段的目标集合依赖 `.scratch/outline/persona/`、`.scratch/outline/index.jsonl`、
`.scratch/corpus/scsp_raw/` 和 `.scratch/corpus/scsp_storylogs/` 这几份导出；它们不在
`characters/` 里，重跑会重新得到 184 条 `no_corpus_match` 的模糊结果。已生成的 392 条
是人工确认过的目标，所以这里把它当作唯一事实来源：新增一条台词 = 先在表里加一行
（story / line / character / text / kind），再跑本脚本补音频。探索期的匹配过程与失败
分类仍留在 `.scratch/voices/REPORT.md`，供需要重新选行时参考。

三个必须知道的坑（详细说明见 `docs/voices.md`）：

1. **`cue_index` 不是 subsong 序号。** 资源库的 `cue_index` 只是它自己索引里的序号；
   180 个用到的包里 26 个不能靠它定位（18 个真的错位，8 个单 subsong 包连
   `stream index` 都不打印）。唯一可靠的键是 vgmstream `-m` 打印的 `stream name`：
   它等于完整 cue 名。例：`s01_02010000_05` 的 `..._0180_05mamimi` 在库里
   `cue_index=9`，在 ACB 里是第 7 条 stream；用 `cue_index+1` 会切到
   `..._0130_06sakuya`（别人的台词）。
2. **ACB 命名不统一。** `s01_01010000_00` 是 `root/raw/s01_01010000_00.acb`，而
   `s61_10101001_00` 的实际文件是 `root/raw/s61_10101001.acb`（少了 `_00`）。
   `Library.resolve_bank()` 依次试「原 id / 去 `_00` / `/api/resources` 搜索」。
3. **124 个 story 的剧本 JSON 在资源库里不存在。** 探索期用
   `.scratch/corpus/scsp_storylogs/<story>_storylog.bytes` 补文本（cue 名自带行号），
   否则这些 story 的台词会漏掉。本脚本的 check 不再依赖这些本地导出；只有需要重新
   选行时才用得到，见 REPORT。

依赖（Windows 本机路径都可覆盖）：

    python backend/scripts/build_voices.py check --deep
    python backend/scripts/build_voices.py targets --work .scratch/voices-build
    ...

- 本地资源库：`http://127.0.0.1:8891`（SCSPDownloader 的资源服务；起不来会明确报错）
- vgmstream：`D:\\SCSPDownloader\\SCSPDownloader\\tools\\vgmstream\\r2117\\vgmstream-cli.exe`
- ffmpeg / ffprobe：`D:\\MOZA Pit House\\bin\\`（PATH 上没有；可用 `--ffmpeg` 覆盖）
- 只写 `--work` 指定的临时目录；`emit` 才会写 `characters/voices.toml`，
  `encode` 默认写 `characters/voices/`。`check` 不写任何东西（只读缓存）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]
CHARACTERS_DIR = REPO / "characters"
CHARACTERS_TOML = CHARACTERS_DIR / "characters.toml"
DEFAULT_SOURCE = CHARACTERS_DIR / "voices.toml"
DEFAULT_VOICES_DIR = CHARACTERS_DIR / "voices"
DEFAULT_WORK = REPO / ".scratch" / "voices-build"

#: 探索阶段的工作目录。只读复用它的 `bank_ids.json` / `banks/` / `acb/`，避免重复下载。
LEGACY_WORK = REPO / ".scratch" / "voices"

DEFAULT_API = os.environ.get("EIDOLON_SCSP_API", "http://127.0.0.1:8891")
DEFAULT_VGMSTREAM = Path(
    r"D:\SCSPDownloader\SCSPDownloader\tools\vgmstream\r2117\vgmstream-cli.exe"
)
DEFAULT_FFMPEG = Path(r"D:\MOZA Pit House\bin\ffmpeg.exe")
DEFAULT_FFPROBE = Path(r"D:\MOZA Pit House\bin\ffprobe.exe")

FIELDS = ("character", "story", "line", "text", "subtitle", "audio", "seconds", "kind")
KINDS = ("quote", "birthday")

#: 角色码与 characters.toml 的 `idol_id` 的唯一例外。はづき 的 SCSP cue 名固定用 90，
#: 而 characters.toml 的 idol_id 是 ShinyColorDB 的 91。角色归属以 cue 名尾部的罗马字
#: 为准（`..._90hazuki`），所以这里把 90 记为已知例外，任何其他不一致都算错误。
CUE_CODE_EXCEPTIONS = {
    "hazuki": ("90", "characters.toml 的 idol_id=91，SCSP cue 名用 90；以 cue 名的 hazuki 为准"),
}

MP3_BITRATE = "96k"
MP3_FALLBACK_BITRATE = "48k"
MAX_MP3_BYTES = 200 * 1024

STREAM_INDEX_NAME = re.compile(r"stream index:\s*(\d+)\s*\n\s*stream name:\s*(\S+)")
STREAM_NAME = re.compile(r"^stream name:\s*(\S+)\s*$", re.M)
STREAM_COUNT = re.compile(r"stream count:\s*(\d+)")
PLAY_DURATION = re.compile(r"play duration:\s*\d+ samples \(([\d:.]+) seconds\)")


class BuildError(RuntimeError):
    """Pipeline error with a message meant for the person running the script."""


# --------------------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------------------


def utf8_stdout() -> None:
    """Windows 控制台默认可能是 GBK；不这样改，打印日文/中文会 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 老终端不支持 reconfigure 时保持原样
            pass


def run(cmd: Iterable[Any], timeout: int = 300) -> tuple[int, str, str]:
    """Run a command without a shell and decode its output as UTF-8 (with replacement)."""
    argv = [str(part) for part in cmd]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise BuildError("找不到可执行文件：" + argv[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError("命令超时（%d 秒）：%s" % (timeout, " ".join(argv))) from exc
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def repo_rel(path: Path) -> str:
    """A path relative to the repo when possible, so generated JSON stays deterministic."""
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path)


def work_rel(path: Path, work: Path) -> str:
    """A wav path relative to `--work` when possible; absolute when it is on another drive."""
    try:
        return os.path.relpath(path.resolve(), work.resolve())
    except ValueError:
        return str(path.resolve())


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, value: Any) -> None:
    """Atomic-ish JSON write: a failed run must not leave half a state file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def cue_parts(name: str) -> tuple[str, str, str, str] | None:
    """Split a full cue name.

    `s01_02010000_05_0180_05mamimi` -> (`s01_02010000_05`, `0180`, `05`, `mamimi`).

    资源库的 cue 名和 ACB 的 stream name 用的是同一个格式，所以 cue 名本身就是
    「story + 剧本行号 + 角色码 + 角色罗马字」的三重校验，不需要也不应该看 `cue_index`。
    """
    parts = name.rsplit("_", 2)
    if len(parts) != 3:
        return None
    story, line4, tail = parts
    if len(line4) != 4 or not line4.isdigit():
        return None
    code, romaji = tail[:2], tail[2:]
    if not code.isdigit() or not romaji.isalpha():
        return None
    return story, line4, code, romaji


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Read `characters/voices.toml` (or a `--source` copy) into the 8-field row dicts."""
    if not path.is_file():
        raise BuildError("找不到台词表：%s" % path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise BuildError("TOML 解析失败：%s（%s）" % (path, exc)) from exc
    rows = data.get("line")
    if not isinstance(rows, list):
        raise BuildError("%s 里没有 [[line]] 表" % path)
    return [dict(row) for row in rows]


def load_characters() -> dict[str, dict[str, Any]]:
    if not CHARACTERS_TOML.is_file():
        raise BuildError("找不到角色表：%s" % CHARACTERS_TOML)
    with CHARACTERS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return {str(ch["id"]): ch for ch in data.get("characters") or []}


def entry_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return str(entry.get("character")), str(entry.get("story")), str(entry.get("line"))


def entry_path(entry: dict[str, Any], voices_dir: Path) -> Path:
    """The canonical audio path for a row: `voices/<character>/<story>_<line>.mp3`."""
    return voices_dir / str(entry["character"]) / ("%s_%s.mp3" % (entry["story"], entry["line"]))


def canonical_audio(entry: dict[str, Any]) -> str:
    return "voices/%s/%s_%s.mp3" % (entry["character"], entry["story"], entry["line"])


def selected_stories(args: argparse.Namespace) -> set[str] | None:
    stories = getattr(args, "story", None) or []
    return set(stories) if stories else None


# --------------------------------------------------------------------------------------
# 工具发现
# --------------------------------------------------------------------------------------


def _tool(
    label: str,
    explicit: Path | None,
    env_name: str,
    default: Path,
    which_name: str,
) -> Path:
    if explicit is not None:
        if Path(explicit).is_file():
            return Path(explicit)
        raise BuildError("%s 指定为 %s，但文件不存在" % (label, explicit))
    env = os.environ.get(env_name)
    if env:
        if Path(env).is_file():
            return Path(env)
        raise BuildError("%s 由环境变量 %s 指定为 %s，但文件不存在" % (label, env_name, env))
    if default.is_file():
        return default
    found = shutil.which(which_name)
    if found:
        return Path(found)
    raise BuildError(
        "找不到 %s。本机默认路径是 %s；请用 --%s 或环境变量 %s 指定"
        % (label, default, label.replace(" ", ""), env_name)
    )


def resolve_vgmstream(args: argparse.Namespace) -> Path:
    return _tool("vgmstream", args.vgmstream, "EIDOLON_VGMSTREAM", DEFAULT_VGMSTREAM,
                 "vgmstream-cli")


def resolve_ffmpeg(args: argparse.Namespace) -> Path:
    return _tool("ffmpeg", args.ffmpeg, "EIDOLON_FFMPEG", DEFAULT_FFMPEG, "ffmpeg")


def resolve_ffprobe(args: argparse.Namespace) -> Path:
    explicit = args.ffprobe
    if explicit is not None:
        if Path(explicit).is_file():
            return Path(explicit)
        raise BuildError("ffprobe 指定为 %s，但文件不存在" % explicit)
    env = os.environ.get("EIDOLON_FFPROBE")
    if env:
        if Path(env).is_file():
            return Path(env)
        raise BuildError("ffprobe 由环境变量 EIDOLON_FFPROBE 指定为 %s，但文件不存在" % env)
    # 优先跟着 --ffmpeg 走：两个可执行文件通常在同一目录。
    if args.ffmpeg is not None and Path(args.ffmpeg).is_file():
        sibling = Path(args.ffmpeg).with_name("ffprobe.exe")
        if sibling.is_file():
            return sibling
    if DEFAULT_FFPROBE.is_file():
        return DEFAULT_FFPROBE
    found = shutil.which("ffprobe")
    if found:
        return Path(found)
    raise BuildError(
        "找不到 ffprobe（默认 %s）。请用 --ffprobe 指定，或用 --fast 跳过时长校验"
        % DEFAULT_FFPROBE
    )


def ffprobe_seconds(path: Path, ffprobe: Path) -> float:
    rc, out, err = run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        timeout=120,
    )
    if rc != 0:
        raise BuildError("ffprobe 读不出时长：%s（%s）" % (path, (err or out).strip()[:200]))
    try:
        seconds = float(out.strip())
    except ValueError as exc:
        raise BuildError("ffprobe 返回的不是秒数：%s（%r）" % (path, out.strip())) from exc
    if seconds <= 0:
        raise BuildError("音频时长为 0：%s" % path)
    return seconds


# --------------------------------------------------------------------------------------
# 本地资源库
# --------------------------------------------------------------------------------------


class Library:
    """The read-only local resource library at `http://127.0.0.1:8891`.

    它同时是一个缓存层：先看 `--work`（本工具的目录），再看探索期的 `.scratch/voices`。
    `write_cache=False`（check 用）时绝不写盘。
    """

    def __init__(
        self,
        base: str,
        work: Path,
        *,
        read_dirs: Iterable[Path] = (),
        write_cache: bool = True,
    ) -> None:
        self.base = base.rstrip("/")
        self.work = work
        self.read_dirs = [work, *[d for d in read_dirs if d != work]]
        self.write_cache = write_cache
        self.bank_ids: dict[str, Any] = {}
        self._cues: dict[str, list[dict[str, Any]]] = {}
        for directory in self.read_dirs:
            path = directory / "bank_ids.json"
            if path.is_file():
                try:
                    loaded = read_json(path)
                except (OSError, ValueError):
                    continue
                if isinstance(loaded, dict):
                    self.bank_ids = loaded
                    break

    # -- HTTP ----------------------------------------------------------------

    def api(self, path: str, body: Any = None, timeout: int = 60) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method="POST" if body is not None else "GET",
        )
        request.add_header("Content-Type", "application/json")
        request.add_header("X-SCSP-Client", "1")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            # 4xx/5xx 是调用方要判断的正常分支（例如 /api/plan 对不存在的 id 报 400），
            # 不要把它说成「连不上」。
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise BuildError(
                "本地资源库 %s 连不上（%s）。先启动 SCSPDownloader 的资源服务，"
                "确认端口后再重试；也可以用 --api 指定地址。" % (self.base, exc)
            ) from exc

    def require_up(self) -> None:
        """Fail early with one clear sentence instead of 180 identical connection errors."""
        try:
            self.api("/api/meta", timeout=10)
        except BuildError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BuildError("本地资源库 %s 不可用：%s" % (self.base, exc)) from exc

    # -- bank resolution -----------------------------------------------------

    def resolve_bank(self, story: str) -> dict[str, Any]:
        """Find the real library id for a story's ACB.

        命名不统一，三级兜底（顺序固定，保证确定性）：
          1. `root/raw/<story>.acb`；
          2. `root/raw/<story 去掉末尾 _00>.acb`（例：s61_10101001_00 → s61_10101001.acb）；
          3. `GET /api/resources?q=<去掉 _00>&category=audio_story` 搜索（兜住其他命名）。

        例：`s01_01010000_00` 走第 1 级；`s61_10101001_00` 走第 2 级。
        """
        cached = self.bank_ids.get(story)
        if isinstance(cached, dict) and cached.get("bank_id"):
            return cached

        candidates = ["root/raw/%s.acb" % story]
        if story.endswith("_00"):
            candidates.append("root/raw/%s.acb" % story[:-3])
        candidates.append("root/raw/%s" % story)
        for candidate in candidates:
            try:
                plan = self.api(
                    "/api/plan",
                    {"ids": [candidate], "allow_unresolved": True},
                    timeout=60,
                )
            except urllib.error.HTTPError:
                continue
            items = plan.get("items") or []
            if items and items[0].get("size"):
                found = {
                    "bank_id": candidate,
                    "name": items[0].get("name") or candidate.rsplit("/", 1)[-1],
                    "size": items[0].get("size"),
                }
                self.bank_ids[story] = found
                return found

        # 第 3 级：搜索。查询词必须去掉末尾 `_00`，否则 `s61_10101001_00` 搜不到
        # `s61_10101001.acb`（服务端的名字匹配是前缀式的）。
        query = story[:-3] if story.endswith("_00") else story
        try:
            result = self.api(
                "/api/resources?q=%s&category=audio_story&page=1"
                % urllib.parse.quote(query),
                timeout=60,
            )
        except urllib.error.HTTPError:
            result = {}
        items = [
            item
            for item in (result.get("items") or [])
            if str(item.get("name") or "").endswith(".acb")
            and str(item.get("name") or "").startswith(query)
        ]
        preferred = [story + ".acb", query + ".acb"]
        items.sort(key=lambda item: (
            preferred.index(item.get("name")) if item.get("name") in preferred else len(preferred),
            str(item.get("name")),
        ))
        if items:
            item = items[0]
            found = {
                "bank_id": item.get("id"),
                "name": item.get("name"),
                "size": item.get("size"),
            }
            self.bank_ids[story] = found
            return found

        self.bank_ids[story] = None
        raise BuildError(
            "资源库里找不到 %s 的 ACB（试过 %s、去 _00、以及搜索 %s）"
            % (story, candidates[0], query)
        )

    def cues(self, story: str) -> list[dict[str, Any]]:
        """The library's cue rows for one story: `[{cue_index, cue_name, characters}]`."""
        if story in self._cues:
            return self._cues[story]
        for directory in self.read_dirs:
            cache = directory / "banks" / (story + ".json")
            if cache.is_file():
                try:
                    data = read_json(cache)
                except (OSError, ValueError):
                    continue
                rows = data.get("cues") or []
                self._cues[story] = rows
                return rows
        bank = self.resolve_bank(story)
        try:
            data = self.api(
                "/api/audio-index/bank?id=" + urllib.parse.quote(bank["bank_id"]),
                timeout=60,
            )
        except urllib.error.HTTPError as exc:
            raise BuildError(
                "资源库读取 %s 的 cue 列表失败（HTTP %s）：%s"
                % (story, exc.code, exc.reason)
            ) from exc
        rows = data.get("cues") or []
        if self.write_cache:
            write_json(self.work / "banks" / (story + ".json"), data)
        self._cues[story] = rows
        return rows

    def save(self) -> None:
        if self.write_cache and self.bank_ids:
            write_json(self.work / "bank_ids.json", self.bank_ids)


# --------------------------------------------------------------------------------------
# 目标集合
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    character: str
    story: str
    line: str
    text: str
    subtitle: str
    kind: str
    cue_name: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.character, self.story, self.line

    def as_json(self) -> dict[str, str]:
        return {
            "character": self.character,
            "story": self.story,
            "line": self.line,
            "text": self.text,
            "subtitle": self.subtitle,
            "kind": self.kind,
            "cue_name": self.cue_name,
        }


def resolve_targets(
    entries: list[dict[str, Any]], library: Library
) -> tuple[list[Target], list[tuple[tuple[str, str, str], str]]]:
    """Map every manifest row to the library cue that has the same story/line/character.

    这一层不下载、不解码，只回答一个问题：这一行的 `(story, line, 角色罗马字)` 在库里的
    某个 cue 名里是否同时成立？这也是「剧本行号 ↔ cue 名」唯一的连接方式。
    """
    targets: list[Target] = []
    problems: list[tuple[tuple[str, str, str], str]] = []
    by_story: dict[str, list[dict[str, Any]]] = {}
    rows_by_story: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        rows_by_story.setdefault(str(entry["story"]), []).append(entry)

    for story, rows in rows_by_story.items():
        try:
            by_story[story] = library.cues(story)
        except BuildError as exc:
            for entry in rows:
                problems.append((entry_key(entry), str(exc)))
    for entry in entries:
        story = str(entry["story"])
        if story not in by_story:
            continue
        matches: list[tuple[str, str, str, str]] = []
        same_line: list[str] = []
        for cue in by_story[story]:
            parts = cue_parts(str(cue.get("cue_name") or ""))
            if parts is None or parts[0] != story or parts[1] != str(entry["line"]):
                continue
            same_line.append(str(cue.get("cue_name")))
            if parts[3] == str(entry["character"]):
                matches.append(parts)
        if len(matches) == 1:
            targets.append(
                Target(
                    character=str(entry["character"]),
                    story=story,
                    line=str(entry["line"]),
                    text=str(entry.get("text") or ""),
                    subtitle=str(entry.get("subtitle") or ""),
                    kind=str(entry.get("kind") or ""),
                    cue_name=str(
                        next(
                            cue["cue_name"]
                            for cue in by_story[story]
                            if cue_parts(str(cue.get("cue_name") or ""))
                            == matches[0]
                        )
                    ),
                )
            )
        elif not matches:
            detail = ("；这一行的其他 cue：" + "、".join(same_line[:3])) if same_line else ""
            problems.append(
                (
                    entry_key(entry),
                    "库里的 cue 名对不上 (story=%s, line=%s, character=%s)%s"
                    % (story, entry["line"], entry["character"], detail),
                )
            )
        else:
            problems.append(
                (
                    entry_key(entry),
                    "库里有 %d 个同名/同行的候选 cue，无法唯一确定：%s"
                    % (len(matches), "、".join(name for _, _, _, name in matches)),
                )
            )
    return targets, problems


def read_targets(work: Path) -> list[Target]:
    path = work / "targets.json"
    if not path.is_file():
        raise BuildError("找不到 %s；先跑 `build_voices.py targets`" % path)
    payload = read_json(path)
    rows = payload.get("targets") or []
    targets: list[Target] = []
    for row in rows:
        missing = [field for field in ("character", "story", "line", "text", "subtitle",
                                       "kind", "cue_name") if field not in row]
        if missing:
            raise BuildError("%s 里的目标缺少字段：%s" % (path, "、".join(missing)))
        targets.append(
            Target(
                character=str(row["character"]),
                story=str(row["story"]),
                line=str(row["line"]),
                text=str(row["text"]),
                subtitle=str(row["subtitle"]),
                kind=str(row["kind"]),
                cue_name=str(row["cue_name"]),
            )
        )
    return targets


def filtered_targets(targets: list[Target], stories: set[str] | None) -> list[Target]:
    if not stories:
        return targets
    return [target for target in targets if target.story in stories]


# --------------------------------------------------------------------------------------
# fetch：三级兜底解析 + 下载
# --------------------------------------------------------------------------------------


def wait_for_job(library: Library, job_id: str, timeout: int = 1800) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        try:
            jobs = library.api("/api/jobs", timeout=60)
        except (BuildError, urllib.error.HTTPError):
            time.sleep(3)
            continue
        job = next((item for item in jobs if item.get("id") == job_id), None)
        if job is None:
            time.sleep(2)
            continue
        status = job.get("status")
        if status != last_status:
            print("    任务 %s：%s" % (job_id, status))
            last_status = status
        if status == "completed":
            return job
        if status in ("failed", "canceled"):
            raise BuildError("下载任务 %s 失败：%s" % (job_id, job.get("error") or status))
        time.sleep(2)
    raise BuildError("下载任务 %s 超过 %d 秒仍未完成" % (job_id, timeout))


def do_fetch(args: argparse.Namespace, targets: list[Target], library: Library) -> int:
    """Download missing ACBs into `--acb-dir`; existing non-empty files are skipped."""
    stories = sorted({target.story for target in targets})
    acb_dir = Path(args.acb_dir) if getattr(args, "acb_dir", None) else args.work / "acb"
    missing: list[tuple[str, str, str]] = []
    unresolved: list[str] = []
    for story in stories:
        path = acb_dir / (story + ".acb")
        if path.is_file() and path.stat().st_size > 0:
            continue
        try:
            bank = library.resolve_bank(story)
        except BuildError as exc:
            unresolved.append("%s：%s" % (story, exc))
            continue
        missing.append((story, str(bank["bank_id"]), str(bank.get("name") or "")))

    print("ACB：%d 个 story，已有 %d 个，待下载 %d 个"
          % (len(stories), len(stories) - len(missing) - len(unresolved), len(missing)))
    if unresolved:
        for line in unresolved[:10]:
            print("  解析失败：" + line, file=sys.stderr)
    if not missing:
        library.save()
        return 1 if unresolved else 0
    if args.dry_run:
        for story, bank_id, _name in missing:
            print("  会下载 %-20s <- %s" % (story, bank_id))
        library.save()
        return 1 if unresolved else 0

    acb_dir.mkdir(parents=True, exist_ok=True)
    library.require_up()
    failed: list[str] = []
    batch_size = 8
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        print("  下载 %d–%d / %d" % (start + 1, start + len(batch), len(missing)))
        try:
            job = library.api(
                "/api/download",
                {
                    "ids": [bank_id for _, bank_id, _ in batch],
                    "allow_unresolved": True,
                    "max_total_mb": 400,
                },
                timeout=180,
            )
            job_id = str(job["id"])
            finished = wait_for_job(library, job_id)
            source_dir = Path(finished.get("output_path") or "") / "raw" / "root" / "raw"
        except (BuildError, KeyError, urllib.error.HTTPError) as exc:
            print("  本批失败：%s" % exc, file=sys.stderr)
            failed.extend(story for story, _, _ in batch)
            continue
        for story, bank_id, _name in batch:
            source = source_dir / Path(bank_id).name
            target = acb_dir / (story + ".acb")
            if not source.is_file() or source.stat().st_size == 0:
                print("  下载结果里没有 %s（%s）" % (source.name, story), file=sys.stderr)
                failed.append(story)
                continue
            shutil.copy2(source, target)
            print("    %-22s %8d bytes" % (story, target.stat().st_size))
    library.save()
    print("下载完成：成功 %d / %d，失败 %d；目录 %s"
          % (len(missing) - len(failed), len(missing), len(failed), acb_dir))
    return 1 if failed or unresolved else 0


# --------------------------------------------------------------------------------------
# vgmstream：按 stream name 切
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stream:
    index: int
    name: str
    seconds: float


def parse_vgm_time(text: str) -> float:
    """`0:05.147` / `1:02:03.5` -> seconds."""
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return total


def vgm_streams(acb: Path, vgmstream: Path) -> list[Stream]:
    """List one bank's subsongs: `stream index`, `stream name`, `play duration`.

    **这里是本流水线最重要的反直觉点：不要拿资源库的 `cue_index` 当 subsong 序号。**
    180 个用到的包里 26 个不能这样定位：18 个真的把 cue 按另一个顺序排（例：
    `s01_02010000_05` 的 `..._0180_05mamimi` 在库里 cue_index=9，在 ACB 里是第 7 条
    stream；第 10 条是 `..._0130_06sakuya`），另有 8 个单 subsong 包根本不打印
    `stream index`。vgmstream `-m` 打印的 `stream name` 就是完整 cue 名，所以只按名字
    匹配；`-o ?s.wav` 的 `?s` 从 1 开始，数值上等于 `stream index`。
    """
    rc, out, err = run([vgmstream, "-m", "-s", "0", "-S", "0", acb], timeout=120)
    text = (out + err).replace("\r\n", "\n").replace("\r", "\n")
    if rc != 0:
        raise BuildError("vgmstream 读取失败（rc=%d）：%s（%s）"
                         % (rc, acb, (err or out).strip()[:300]))
    blocks = text.split("metadata for ")[1:]
    streams: list[Stream] = []
    for position, block in enumerate(blocks, 1):
        name_match = STREAM_NAME.search(block)
        if not name_match:
            continue
        index_match = re.search(r"^stream index:\s*(\d+)\s*$", block, re.M)
        duration_match = PLAY_DURATION.search(block)
        seconds = parse_vgm_time(duration_match.group(1)) if duration_match else 0.0
        streams.append(
            Stream(
                index=int(index_match.group(1)) if index_match else position,
                name=name_match.group(1),
                seconds=seconds,
            )
        )
    if not streams:
        # Some builds print the names without the `metadata for` frames; don't guess indices
        # from cue_index — just use the printed order.
        names = STREAM_NAME.findall(text)
        streams = [Stream(index=index, name=name, seconds=0.0)
                   for index, name in enumerate(names, 1)]
    if not streams:
        raise BuildError("vgmstream 没有打印任何 stream name：%s" % acb)
    streams.sort(key=lambda item: item.index)
    indices = [item.index for item in streams]
    if indices != list(range(1, len(streams) + 1)):
        raise BuildError("vgmstream 的 stream index 不是 1..N（%s）：%s"
                         % (acb, indices[:10]))
    announced = STREAM_COUNT.search(text)
    if announced and int(announced.group(1)) != len(streams):
        raise BuildError("vgmstream 声明 %s 条 stream，实际解析出 %d 条：%s"
                         % (announced.group(1), len(streams), acb))
    return streams


def export_wavs(
    acb: Path, outdir: Path, vgmstream: Path, force: bool, streams: list[Stream]
) -> dict[int, Path]:
    """Export every subsong to `<outdir>/<n>.wav` with `?s` (1-based stream index)."""
    expected_names = {stream.index for stream in streams}
    existing = {
        int(match.group(1)): path
        for path in outdir.glob("*.wav")
        if (match := re.fullmatch(r"(\d+)\.wav", path.name))
    } if outdir.is_dir() else {}
    reusable = expected_names and expected_names <= set(existing) and all(
        existing[index].stat().st_size > 0 for index in expected_names
    )
    if not reusable or force:
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        rc, out, err = run(
            [vgmstream, "-o", str(outdir / "?s.wav"), "-s", "0", "-S", "0", acb],
            timeout=600,
        )
        if rc != 0:
            raise BuildError("vgmstream 导出失败（rc=%d）：%s（%s）"
                             % (rc, acb, (err or out).strip()[:300]))
        existing = {
            int(match.group(1)): path
            for path in outdir.glob("*.wav")
            if (match := re.fullmatch(r"(\d+)\.wav", path.name))
        }
    missing = sorted(index for index in expected_names if index not in existing)
    if missing:
        raise BuildError("vgmstream 少导出了 stream %s：%s" % (missing[:10], acb))
    bad = [index for index in expected_names if existing[index].stat().st_size == 0]
    if bad:
        raise BuildError("vgmstream 导出的 wav 是空文件 stream %s：%s" % (bad[:10], acb))
    return existing


def decode_story(
    story: str,
    targets: list[Target],
    args: argparse.Namespace,
    vgmstream: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    acb = Path(args.acb_dir) / (story + ".acb")
    if not acb.is_file() or acb.stat().st_size == 0:
        return None, ["找不到 %s；先跑 fetch（或把 --acb-dir 指到已有缓存）" % acb]
    streams = vgm_streams(acb, vgmstream)
    by_name: dict[str, list[Stream]] = {}
    for stream in streams:
        by_name.setdefault(stream.name, []).append(stream)

    problems: list[str] = []
    results: dict[str, Any] = {}
    for target in targets:
        hits = by_name.get(target.cue_name, [])
        if len(hits) != 1:
            problems.append(
                "%s %s/%s：ACB 里 cue 名 %s 命中 %d 条 stream%s"
                % (story, target.character, target.line, target.cue_name, len(hits),
                   "（多为多人齐声 cue 的重复 stream，不能按名字唯一定位）" if hits else "")
            )
            continue
        stream = hits[0]
        results["%s|%s|%s" % target.key] = {
            "cue_name": target.cue_name,
            "stream_index": stream.index,
            "stream_seconds": round(stream.seconds, 3),
        }

    if problems:
        return None, problems
    if args.dry_run:
        return {"story": story, "streams": len(streams), "results": results}, []

    wav_dir = Path(args.wav_dir) / story
    try:
        wavs = export_wavs(acb, wav_dir, vgmstream, force=bool(args.force), streams=streams)
    except BuildError as exc:
        return None, [str(exc)]
    for key, row in results.items():
        path = wavs.get(int(row["stream_index"]))
        if path is None:
            problems.append("%s：没有导出的 %s.wav" % (key, row["stream_index"]))
            continue
        row["wav"] = work_rel(path, Path(args.work))
    if problems:
        return None, problems

    clip = {
        "schema": 1,
        "story": story,
        "streams": len(streams),
        "mapping": "stream_name",
        "results": results,
    }
    write_json(Path(args.work) / "clips" / (story + ".json"), clip)
    return clip, []


# --------------------------------------------------------------------------------------
# ffmpeg 编码
# --------------------------------------------------------------------------------------


def encode_mp3(source: Path, destination: Path, ffmpeg: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp.mp3")
    if temporary.exists():
        temporary.unlink()
    rc, out, err = run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", source,
         "-ac", "1", "-b:a", MP3_BITRATE, temporary],
        timeout=180,
    )
    if rc != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
        if temporary.exists():
            temporary.unlink()
        raise BuildError("ffmpeg 编码失败：%s（%s）" % (source, (err or out).strip()[:300]))
    if temporary.stat().st_size > MAX_MP3_BYTES:
        rc, out, err = run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", source,
             "-ac", "1", "-b:a", MP3_FALLBACK_BITRATE, temporary],
            timeout=180,
        )
        if rc != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            if temporary.exists():
                temporary.unlink()
            raise BuildError("ffmpeg 降码率失败：%s（%s）"
                             % (source, (err or out).strip()[:300]))
    temporary.replace(destination)


# --------------------------------------------------------------------------------------
# 命令：targets / fetch / decode / encode / emit
# --------------------------------------------------------------------------------------


def cmd_targets(args: argparse.Namespace) -> int:
    entries = load_manifest(Path(args.source))
    stories = selected_stories(args)
    if stories:
        entries = [entry for entry in entries if str(entry["story"]) in stories]
    if not entries:
        raise BuildError("没有选中任何行（检查 --story）")
    library = Library(
        args.api,
        Path(args.work),
        read_dirs=[LEGACY_WORK],
        write_cache=not args.dry_run,
    )
    library.require_up()
    targets, problems = resolve_targets(entries, library)
    if problems:
        for key, message in problems[:20]:
            print("  ✗ %s / %s / %s：%s" % (*key, message), file=sys.stderr)
        raise BuildError("%d 条目标无法在库内定位（共 %d 条）" % (len(problems), len(entries)))
    library.save()
    characters = load_characters()
    order = {cid: index for index, cid in enumerate(characters)}
    targets.sort(key=lambda target: (
        order.get(target.character, len(order)),
        target.kind != "quote",
        target.story,
        target.line,
    ))
    payload = {
        "schema": 1,
        "source": repo_rel(Path(args.source)),
        "characters": list(dict.fromkeys(target.character for target in targets)),
        "stories": sorted({target.story for target in targets}),
        "targets": [target.as_json() for target in targets],
    }
    if args.dry_run:
        print("targets（dry-run）：%d 条 / %d 个 story / %d 位角色"
              % (len(targets), len(payload["stories"]), len(payload["characters"])))
        return 0
    write_json(Path(args.work) / "targets.json", payload)
    print("targets：%d 条 / %d 个 story / %d 位角色 → %s"
          % (len(targets), len(payload["stories"]), len(payload["characters"]),
             Path(args.work) / "targets.json"))
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    targets = filtered_targets(read_targets(Path(args.work)), selected_stories(args))
    if not targets:
        raise BuildError("没有选中的目标；检查 --story 或先跑 targets")
    library = Library(args.api, Path(args.work), read_dirs=[LEGACY_WORK],
                      write_cache=not args.dry_run)
    library.require_up()
    return do_fetch(args, targets, library)


def cmd_decode(args: argparse.Namespace) -> int:
    targets = filtered_targets(read_targets(Path(args.work)), selected_stories(args))
    if not targets:
        raise BuildError("没有选中的目标；检查 --story 或先跑 targets")
    vgmstream = resolve_vgmstream(args)
    by_story: dict[str, list[Target]] = {}
    for target in targets:
        by_story.setdefault(target.story, []).append(target)
    failed = 0
    for story in sorted(by_story):
        rows = by_story[story]
        clip, problems = decode_story(story, rows, args, vgmstream)
        if clip is None:
            failed += 1
            for problem in problems:
                print("  ✗ " + problem, file=sys.stderr)
            continue
        results = clip["results"]
        detail = "、".join(
            "%s/%s→%d" % (key.split("|")[0], key.split("|")[2],
                           results[key]["stream_index"])
            for key in sorted(results)
        )
        if len(detail) > 120:
            detail = detail[:117] + "…"
        print("  %-22s %3d streams  %2d 条  %s" % (story, clip["streams"], len(results), detail))
    print("解码：%d 个 story / %d 条目标；失败 %d；wav 在 %s"
          % (len(by_story), len(targets), failed, Path(args.wav_dir)))
    return 1 if failed else 0


def cmd_encode(args: argparse.Namespace) -> int:
    targets = filtered_targets(read_targets(Path(args.work)), selected_stories(args))
    if not targets:
        raise BuildError("没有选中的目标；检查 --story 或先跑 targets")
    ffmpeg = resolve_ffmpeg(args)
    ffprobe = resolve_ffprobe(args)
    voices_dir = Path(args.voices_dir)
    by_story: dict[str, list[Target]] = {}
    for target in targets:
        by_story.setdefault(target.story, []).append(target)
    encoded = reused = failed = 0
    for story in sorted(by_story):
        clip_path = Path(args.work) / "clips" / (story + ".json")
        if not clip_path.is_file():
            raise BuildError("找不到 %s；先跑 decode（--story %s）" % (clip_path, story))
        clip = read_json(clip_path)
        results = clip.get("results") or {}
        ok = True
        for target in by_story[story]:
            key = "%s|%s|%s" % target.key
            row = results.get(key)
            if not isinstance(row, dict):
                print("  ✗ %s：clips 里没有这条（重新 decode）" % key, file=sys.stderr)
                failed += 1
                ok = False
                continue
            destination = entry_path(target.__dict__, voices_dir)
            try:
                if (destination.is_file() and destination.stat().st_size > 0
                        and not args.force):
                    seconds = ffprobe_seconds(destination, ffprobe)
                    reused += 1
                else:
                    if args.dry_run:
                        print("  会编码 %s" % destination)
                        continue
                    source = Path(row["wav"])
                    if not source.is_absolute():
                        source = Path(args.work) / source
                    if not source.is_file():
                        raise BuildError("找不到 wav %s（重新 decode）" % source)
                    encode_mp3(source, destination, ffmpeg)
                    seconds = ffprobe_seconds(destination, ffprobe)
                    encoded += 1
                row.update(
                    {
                        "audio": canonical_audio(target.__dict__),
                        "seconds": round(seconds, 2),
                        "bytes": destination.stat().st_size,
                        "encoded": True,
                    }
                )
            except BuildError as exc:
                print("  ✗ %s：%s" % (key, exc), file=sys.stderr)
                failed += 1
                ok = False
        if not args.dry_run:
            write_json(clip_path, clip)
        if ok and args.clean_wav and not args.dry_run:
            wav_dir = Path(args.wav_dir) / story
            if wav_dir.is_dir():
                shutil.rmtree(wav_dir)
        print("  %-22s 新编码/复用 %d" % (story, len(by_story[story])))
    print("编码：%d 个 story / %d 条目标；新编码 %d，复用 %d，失败 %d；mp3 在 %s"
          % (len(by_story), len(targets), encoded, reused, failed, voices_dir))
    return 1 if failed else 0


def toml_string(value: str) -> str:
    """A TOML basic string. JSON's escaping is a subset of TOML's for these strings."""
    return json.dumps(value, ensure_ascii=False)


def render_toml(rows: list[dict[str, Any]], total_bytes: int) -> str:
    quotes = sum(1 for row in rows if row["kind"] == "quote")
    lines = [
        "# 剧情原声台词库：characters/voices.toml",
        "#",
        "# 每条 [[line]] 是一条从 SCSP 剧情语音包里切出来的角色台词。",
        "#   character  本仓库的角色标识（characters.toml 的 id）",
        "#   story      SCSP 剧本包 id，对应 root/raw/<story>.acb",
        "#   line       剧本行号（4 位，来自剧本 JSON 的 key 后缀，与 cue 名的 4 位数字一致）",
        "#   text       日文剧本原文（换行写成字面 \\n）",
        "#   subtitle   中文字幕（民间汉化，不是官方中译）；没有时为空串",
        "#   audio      相对 characters/ 的音频路径（mp3, 单声道）",
        "#   seconds    音频时长（秒，ffprobe 量出来的）",
        "#   kind       quote = 口癖/名台词；birthday = 制作人生日祝贺",
        "#",
        "# 由 backend/scripts/build_voices.py 生成；%d 条（quote %d / birthday %d），"
        "共 %.1f MB" % (len(rows), quotes, len(rows) - quotes, total_bytes / 1e6),
        "",
    ]
    for row in rows:
        lines.append("[[line]]")
        for field in FIELDS:
            if field == "seconds":
                lines.append("seconds = %.2f" % float(row["seconds"]))
            else:
                lines.append("%s = %s" % (field, toml_string(str(row[field]))))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def clips_by_key(work: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    directory = work / "clips"
    if not directory.is_dir():
        return results
    for path in sorted(directory.glob("*.json")):
        try:
            clip = read_json(path)
        except (OSError, ValueError):
            continue
        for key, row in (clip.get("results") or {}).items():
            if isinstance(row, dict) and row.get("seconds"):
                results[str(key)] = row
    return results


def cmd_emit(args: argparse.Namespace) -> int:
    entries = load_manifest(Path(args.source))
    characters = load_characters()
    order = {cid: index for index, cid in enumerate(characters)}
    voices_dir = Path(args.voices_dir)
    clips = clips_by_key(Path(args.work))
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    ffprobe: Path | None = None
    for entry in entries:
        path = entry_path(entry, voices_dir)
        seconds = None
        clip = clips.get("%s|%s|%s" % entry_key(entry))
        if clip:
            seconds = float(clip["seconds"])
        if not path.is_file() or path.stat().st_size == 0:
            problems.append("音频不存在或为空：%s" % path)
            continue
        if seconds is None:
            if ffprobe is None:
                ffprobe = resolve_ffprobe(args)
            try:
                seconds = ffprobe_seconds(path, ffprobe)
            except BuildError as exc:
                problems.append(str(exc))
                continue
        rows.append(
            {
                "character": str(entry["character"]),
                "story": str(entry["story"]),
                "line": str(entry["line"]),
                "text": str(entry.get("text") or ""),
                "subtitle": str(entry.get("subtitle") or ""),
                "audio": canonical_audio(entry),
                "seconds": round(float(seconds), 2),
                "kind": str(entry["kind"]),
            }
        )
    if problems:
        for problem in problems[:20]:
            print("  ✗ " + problem, file=sys.stderr)
        raise BuildError("%d 条音频缺失/读不出时长，拒绝写表" % len(problems))
    rows.sort(key=lambda row: (
        order.get(row["character"], len(order)),
        row["kind"] != "quote",
        row["story"],
        row["line"],
    ))
    total_bytes = sum((voices_dir / row["audio"][len("voices/"):]).stat().st_size
                      for row in rows)
    text = render_toml(rows, total_bytes)
    output = Path(args.out) if args.out else Path(args.source)
    if args.dry_run:
        print("emit（dry-run）：%d 条（quote %d / birthday %d），%.1f MB → %s"
              % (len(rows), sum(1 for row in rows if row["kind"] == "quote"),
                 sum(1 for row in rows if row["kind"] != "quote"),
                 total_bytes / 1e6, output))
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    temporary.replace(output)
    print("emit：%d 条（quote %d / birthday %d），%.1f MB → %s"
          % (len(rows), sum(1 for row in rows if row["kind"] == "quote"),
             sum(1 for row in rows if row["kind"] != "quote"),
             total_bytes / 1e6, output))
    return 0


# --------------------------------------------------------------------------------------
# check：只读校验
# --------------------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    source = Path(args.source)
    entries = load_manifest(source)
    stories_filter = selected_stories(args)
    if stories_filter:
        entries = [entry for entry in entries if str(entry["story"]) in stories_filter]
    total = len(entries)
    chapters = Counter(str(entry.get("kind")) for entry in entries)
    characters = load_characters()
    problems: list[str] = []
    bad: dict[str, set[tuple[str, str, str]]] = {
        "basic": set(), "file": set(), "duration": set(), "cue": set(),
        "code": set(), "dup": set(), "deep": set(),
    }

    def fail(category: str, key: tuple[str, str, str], message: str) -> None:
        bad[category].add(key)
        problems.append("✗ %s / %s / %s：%s" % (*key, message))

    # 1) schema / required fields / canonical path
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = entry_key(entry)
        missing = [field for field in FIELDS if field not in entry]
        if missing:
            fail("basic", key, "缺少字段 %s" % "、".join(missing))
            continue
        if set(entry) != set(FIELDS):
            fail("basic", key, "字段集合不对：%s" % "、".join(sorted(set(entry) - set(FIELDS))))
        if str(entry["character"]) not in characters:
            fail("basic", key, "character %r 不在 characters.toml 里" % entry["character"])
        if not re.fullmatch(r"\d{4}", str(entry["line"])):
            fail("basic", key, "line 不是 4 位数字：%r" % entry["line"])
        if not re.fullmatch(r"s\d{2}_\d{8}_\d{2}", str(entry["story"])):
            fail("basic", key, "story 不像剧本包 id：%r" % entry["story"])
        if str(entry["kind"]) not in KINDS:
            fail("basic", key, "kind 只能是 quote/birthday：%r" % entry["kind"])
        if not str(entry.get("text") or "").strip():
            fail("basic", key, "text 为空")
        if not isinstance(entry.get("subtitle"), str):
            fail("basic", key, "subtitle 不是字符串")
        try:
            if float(entry.get("seconds") or 0) <= 0:
                fail("basic", key, "seconds 不是正数：%r" % entry.get("seconds"))
        except (TypeError, ValueError):
            fail("basic", key, "seconds 不是数字：%r" % entry.get("seconds"))
        expected_audio = canonical_audio(entry)
        if str(entry.get("audio")) != expected_audio:
            fail("basic", key, "audio 应为 %s，实际 %r"
                 % (expected_audio, entry.get("audio")))
        if key in seen:
            fail("dup", key, "同一 (story, line) 出现两次")
            fail("dup", entry_key(seen[key]), "同一 (story, line) 出现两次")
        seen[key] = entry

    # 2) file presence / bytes
    ffprobe: Path | None = None
    if not args.fast:
        ffprobe = resolve_ffprobe(args)
    for entry in entries:
        if any(field not in entry for field in FIELDS):
            continue
        key = entry_key(entry)
        path = entry_path(entry, DEFAULT_VOICES_DIR)
        if not path.is_file():
            fail("file", key, "音频文件不存在：%s" % path)
            continue
        if path.stat().st_size == 0:
            fail("file", key, "音频文件是 0 字节：%s" % path)
            continue
        if ffprobe is None:
            continue
        try:
            actual = ffprobe_seconds(path, ffprobe)
            expected = float(entry.get("seconds") or 0)
        except BuildError as exc:
            fail("duration", key, str(exc))
            continue
        except (TypeError, ValueError):
            fail("duration", key, "seconds 不是数字：%r" % entry.get("seconds"))
            continue
        if abs(actual - expected) > 0.011:
            fail("duration", key, "seconds=%.2f，ffprobe=%.2f" % (expected, actual))

    # 3) cue names (library) + 4) character codes
    library = Library(args.api, Path(args.work), read_dirs=[LEGACY_WORK],
                      write_cache=False)
    library.require_up()
    complete = [entry for entry in entries if all(field in entry for field in FIELDS)]
    targets, cue_problems = resolve_targets(complete, library)
    for key, message in cue_problems:
        fail("cue", key, message)
    code_matches = 0
    known_exception = 0
    for target in targets:
        key = target.key
        parts = cue_parts(target.cue_name)
        if parts is None:
            fail("cue", key, "cue 名格式无法解析：%s" % target.cue_name)
            continue
        expected_story, expected_line, code, romaji = parts
        if expected_story != target.story or expected_line != target.line:
            fail("cue", key, "cue 名与 story/line 不一致：%s" % target.cue_name)
        if romaji != target.character:
            fail("cue", key, "cue 名尾部的角色 %r != %r" % (romaji, target.character))
        idol_id = characters.get(target.character, {}).get("idol_id")
        if idol_id is None:
            continue
        if int(code) == int(idol_id):
            code_matches += 1
        elif target.character in CUE_CODE_EXCEPTIONS:
            expected_code, _why = CUE_CODE_EXCEPTIONS[target.character]
            if code == expected_code:
                known_exception += 1
            else:
                fail("code", key, "cue 角色码 %s 既不是 idol_id=%s，也不是已知例外 %s"
                     % (code, idol_id, expected_code))
        else:
            fail("code", key, "cue 角色码 %s != characters.toml idol_id=%s" % (code, idol_id))

    # 5) --deep: vgmstream stream names
    deep_stats = {"banks": 0, "coverage": 0, "unique": 0, "duration": 0,
                  "missing": 0, "max_diff": 0.0}
    if args.deep:
        vgmstream = resolve_vgmstream(args)
        acb_dir = Path(args.acb_dir) if args.acb_dir else None
        if acb_dir is None:
            for candidate in (Path(args.work) / "acb", LEGACY_WORK / "acb"):
                if candidate.is_dir():
                    acb_dir = candidate
                    break
        if acb_dir is None:
            print("  深度校验跳过：找不到 ACB 目录（--acb-dir）", file=sys.stderr)
        else:
            target_by_story: dict[str, list[Target]] = {}
            for target in targets:
                target_by_story.setdefault(target.story, []).append(target)
            for story in sorted(target_by_story):
                acb = acb_dir / (story + ".acb")
                if not acb.is_file():
                    deep_stats["missing"] += 1
                    continue
                try:
                    streams = vgm_streams(acb, vgmstream)
                    cues = library.cues(story)
                except BuildError as exc:
                    fail("deep", (target_by_story[story][0].character, story,
                                  target_by_story[story][0].line), str(exc))
                    continue
                deep_stats["banks"] += 1
                by_name: dict[str, list[Stream]] = {}
                for stream in streams:
                    by_name.setdefault(stream.name, []).append(stream)
                if all(str(cue.get("cue_name")) in by_name for cue in cues):
                    deep_stats["coverage"] += 1
                else:
                    missing = [str(cue.get("cue_name")) for cue in cues
                               if str(cue.get("cue_name")) not in by_name]
                    fail("deep", (target_by_story[story][0].character, story,
                                  target_by_story[story][0].line),
                         "库里的 %d 个 cue 名在 ACB 里找不到：%s"
                         % (len(missing), "、".join(missing[:3])))
                for target in target_by_story[story]:
                    hits = by_name.get(target.cue_name, [])
                    if len(hits) != 1:
                        fail("deep", target.key, "stream name %s 命中 %d 条"
                             % (target.cue_name, len(hits)))
                        continue
                    deep_stats["unique"] += 1
                    diff = abs(hits[0].seconds - float(seen[target.key].get("seconds") or 0))
                    deep_stats["max_diff"] = max(deep_stats["max_diff"], diff)
                    if diff > 0.12:
                        fail("deep", target.key,
                             "stream 时长 %.2fs 与 mp3 %.2fs 相差 %.2fs"
                             % (hits[0].seconds, float(seen[target.key]["seconds"]), diff))
                    else:
                        deep_stats["duration"] += 1

    # ---- report ----
    filtered_note = "（--story 过滤）" if stories_filter else ""
    print("读取 %s%s：%d 条（quote %d / birthday %d），%d 位角色，%d 个 story"
          % (repo_rel(source), filtered_note, total, chapters["quote"], chapters["birthday"],
             len({entry["character"] for entry in entries}),
             len({entry["story"] for entry in entries})))
    print()
    print("[1/5] 字段/路径        %d/%d" % (total - len(bad["basic"]), total))
    print("[2/5] 音频文件         %d/%d" % (total - len(bad["file"]), total))
    if args.fast:
        print("[3/5] 时长            跳过（--fast）")
    else:
        print("[3/5] 时长/seconds    %d/%d" % (total - len(bad["duration"]), total))
    print("[4/5] cue 名映射       %d/%d" % (total - len(bad["cue"]), total))
    print("[5/5] 重复 (story,line) %d 条" % len(bad["dup"]))
    code_total = code_matches + known_exception + len(bad["code"])
    detail = ""
    if known_exception:
        detail = "；%d 条已知例外：hazuki cue=90 / idol_id=91" % known_exception
    print("      角色码            %d/%d 已核对（%d 与 idol_id 一致%s）"
          % (code_total, total, code_matches, detail))
    if args.deep:
        print()
        print("深度校验（--deep，按 vgmstream stream name）")
        print("  ACB 可读             %d 个（缺 %d 个）"
              % (deep_stats["banks"], deep_stats["missing"]))
        print("  库内 cue 全覆盖      %d/%d 个 ACB"
              % (deep_stats["coverage"], deep_stats["banks"]))
        print("  目标 cue 唯一命中    %d/%d" % (deep_stats["unique"], len(targets)))
        print("  stream 时长 ≈ mp3    %d/%d（最大差 %.3fs）"
              % (deep_stats["duration"], len(targets), deep_stats["max_diff"]))
    if problems:
        print()
        print("问题（最多列 30 条，共 %d 条）：" % len(problems))
        for problem in problems[:30]:
            print("  " + problem)
        if len(problems) > 30:
            print("  …")
    passed = total - len(set().union(*bad.values()))
    print()
    print("%d/%d 条通过" % (passed, total))
    return 0 if not problems else 1


# --------------------------------------------------------------------------------------
# build：全量重建
# --------------------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    entries = load_manifest(Path(args.source))
    library = Library(args.api, Path(args.work), read_dirs=[LEGACY_WORK],
                      write_cache=not args.dry_run)
    library.require_up()
    targets, problems = resolve_targets(entries, library)
    library.save()
    if problems:
        for key, message in problems[:20]:
            print("  ✗ %s / %s / %s：%s" % (*key, message), file=sys.stderr)
        raise BuildError("%d 条目标无法在库内定位" % len(problems))
    print("阶段 1/5：targets")
    if args.dry_run:
        print("  dry-run：会解析 %d 条 / %d 个 story，不写盘" % (len(targets),
              len({target.story for target in targets})))
        print("  dry-run：后续 fetch/decode/encode/emit 均不执行")
        return 0
    payload = {
        "schema": 1,
        "source": repo_rel(Path(args.source)),
        "characters": list(dict.fromkeys(target.character for target in targets)),
        "stories": sorted({target.story for target in targets}),
        "targets": [target.as_json() for target in targets],
    }
    write_json(Path(args.work) / "targets.json", payload)

    print("阶段 2/5：fetch")
    library = Library(args.api, Path(args.work), read_dirs=[LEGACY_WORK])
    library.require_up()
    if do_fetch(args, targets, library) != 0:
        raise BuildError("ACB 没有全部就绪，停止")

    print("阶段 3–4/5：逐个 story decode + encode")
    vgmstream = resolve_vgmstream(args)
    ffmpeg = resolve_ffmpeg(args)
    ffprobe = resolve_ffprobe(args)
    original_clean = getattr(args, "clean_wav", False)
    args.clean_wav = True
    by_story: dict[str, list[Target]] = {}
    for target in targets:
        by_story.setdefault(target.story, []).append(target)
    try:
        for story in sorted(by_story):
            clip, story_problems = decode_story(story, by_story[story], args, vgmstream)
            if clip is None:
                raise BuildError("%s：%s" % (story, "；".join(story_problems)))
            # 直接调用单 story 的编码逻辑：把 targets 临时收窄，避免重复读全表
            sub = argparse.Namespace(**vars(args))
            sub.story = [story]
            sub.voices_dir = args.voices_dir
            if cmd_encode_for_story(sub, by_story[story], ffmpeg, ffprobe) != 0:
                raise BuildError("%s 编码失败" % story)
    finally:
        args.clean_wav = original_clean

    print("阶段 5/5：emit")
    return cmd_emit(args)


def cmd_encode_for_story(
    args: argparse.Namespace,
    targets: list[Target],
    ffmpeg: Path,
    ffprobe: Path,
) -> int:
    """Encode one story's already-decoded wavs. Kept separate from cmd_encode's CLI parsing."""
    story = targets[0].story
    clip_path = Path(args.work) / "clips" / (story + ".json")
    if not clip_path.is_file():
        raise BuildError("找不到 %s" % clip_path)
    clip = read_json(clip_path)
    results = clip.get("results") or {}
    voices_dir = Path(args.voices_dir)
    failed = 0
    for target in targets:
        key = "%s|%s|%s" % target.key
        row = results.get(key)
        if not isinstance(row, dict):
            print("  ✗ %s：clips 里没有这条" % key, file=sys.stderr)
            failed += 1
            continue
        destination = entry_path(target.__dict__, voices_dir)
        try:
            if destination.is_file() and destination.stat().st_size > 0 and not args.force:
                seconds = ffprobe_seconds(destination, ffprobe)
            else:
                source = Path(row["wav"])
                if not source.is_absolute():
                    source = Path(args.work) / source
                if not source.is_file():
                    raise BuildError("找不到 wav %s" % source)
                encode_mp3(source, destination, ffmpeg)
                seconds = ffprobe_seconds(destination, ffprobe)
            row.update({
                "audio": canonical_audio(target.__dict__),
                "seconds": round(seconds, 2),
                "bytes": destination.stat().st_size,
                "encoded": True,
            })
        except BuildError as exc:
            print("  ✗ %s：%s" % (key, exc), file=sys.stderr)
            failed += 1
    write_json(clip_path, clip)
    if not failed and args.clean_wav:
        wav_dir = Path(args.wav_dir) / story
        if wav_dir.is_dir():
            shutil.rmtree(wav_dir)
    print("  %-22s %d 条" % (story, len(targets)))
    return 1 if failed else 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK,
                        help="临时状态目录（targets.json / clips / acb / wav），默认 %(default)s")
    parser.add_argument("--api", default=DEFAULT_API,
                        help="本地资源库地址，默认 %(default)s")
    parser.add_argument("--vgmstream", type=Path, default=None, help="vgmstream-cli.exe")
    parser.add_argument("--ffmpeg", type=Path, default=None, help="ffmpeg.exe")
    parser.add_argument("--ffprobe", type=Path, default=None, help="ffprobe.exe")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    add_paths(common)

    targets = subparsers.add_parser("targets", parents=[common],
                                    help="从 voices.toml 反推目标并校验 cue 名")
    targets.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    targets.add_argument("--story", action="append", default=[], metavar="STORY")
    targets.add_argument("--dry-run", action="store_true")
    targets.set_defaults(func=cmd_targets)

    fetch = subparsers.add_parser("fetch", parents=[common],
                                  help="下载缺失的 ACB（三级兜底解析命名）")
    fetch.add_argument("--acb-dir", type=Path, default=None)
    fetch.add_argument("--story", action="append", default=[], metavar="STORY")
    fetch.add_argument("--dry-run", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    decode = subparsers.add_parser("decode", parents=[common],
                                   help="按 stream name 切 wav（不使用 cue_index）")
    decode.add_argument("--acb-dir", type=Path, default=None)
    decode.add_argument("--wav-dir", type=Path, default=None)
    decode.add_argument("--story", action="append", default=[], metavar="STORY")
    decode.add_argument("--dry-run", action="store_true")
    decode.add_argument("--force", action="store_true", help="重新导出已有 wav")
    decode.set_defaults(func=cmd_decode)

    encode = subparsers.add_parser("encode", parents=[common],
                                   help="ffmpeg 转单声道 mp3（96k，>200KB 降 48k）")
    encode.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES_DIR)
    encode.add_argument("--wav-dir", type=Path, default=None)
    encode.add_argument("--story", action="append", default=[], metavar="STORY")
    encode.add_argument("--dry-run", action="store_true")
    encode.add_argument("--force", action="store_true", help="重新编码已有 mp3")
    encode.add_argument("--clean-wav", action="store_true", help="编码成功后删掉该 story 的 wav")
    encode.set_defaults(func=cmd_encode)

    emit = subparsers.add_parser("emit", parents=[common],
                                 help="根据现有音频重写 characters/voices.toml")
    emit.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    emit.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES_DIR)
    emit.add_argument("--out", type=Path, default=None,
                      help="输出文件，默认与 --source 相同")
    emit.add_argument("--dry-run", action="store_true")
    emit.set_defaults(func=cmd_emit)

    check = subparsers.add_parser("check", parents=[common],
                                  help="只读校验现有 392 条；--deep 再核 stream name")
    check.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    check.add_argument("--acb-dir", type=Path, default=None)
    check.add_argument("--story", action="append", default=[], metavar="STORY")
    check.add_argument("--deep", action="store_true",
                       help="用 vgmstream -m 核对每个 ACB 的 stream name")
    check.add_argument("--fast", action="store_true", help="跳过 ffprobe 时长实测")
    check.set_defaults(func=cmd_check)

    build = subparsers.add_parser("build", parents=[common],
                                  help="全量重建：targets → fetch → decode+encode → emit")
    build.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    build.add_argument("--acb-dir", type=Path, default=None)
    build.add_argument("--wav-dir", type=Path, default=None)
    build.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES_DIR)
    build.add_argument("--out", type=Path, default=None,
                       help="输出文件，默认与 --source 相同")
    build.add_argument("--force", action="store_true")
    build.add_argument("--clean-wav", action="store_true", default=True)
    build.add_argument("--dry-run", action="store_true")
    build.set_defaults(func=cmd_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    arguments = list(sys.argv[1:] if argv is None else argv)
    # 让 `python backend/scripts/build_voices.py --check` 也能用（题面要求的写法）。
    if arguments and arguments[0] == "--check":
        arguments[0] = "check"
    parser = build_parser()
    args = parser.parse_args(arguments)
    # 未显式给的路径按 work 目录推导，方便把一次运行的全部中间产物放进同一个临时目录。
    # check 例外：它的 --acb-dir 留空表示「自动找 <work>/acb 或探索期缓存」。
    if args.command in ("fetch", "decode", "build") and args.acb_dir is None:
        args.acb_dir = Path(args.work) / "acb"
    if args.command in ("decode", "encode", "build") and args.wav_dir is None:
        args.wav_dir = Path(args.work) / "wav"
    try:
        return int(args.func(args))
    except BuildError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
