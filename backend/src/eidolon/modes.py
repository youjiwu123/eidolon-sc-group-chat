"""特殊档等模式：只在好感最高档（love）之上、用户选中时追加到提示词。

模式表在 `characters/modes.toml`（`load_modes`），和 `characters.toml` 同目录。表里每一条
是一个 `[[modes]]`：`id`、`name`、`description` 和 `prompt`；`prompt` 原样进入提示词，
以后加模式只改这个文件。

缺文件就是空表：这个功能不打开，其他照常。表存在但读不了、缺字段、id 重复时报 RuntimeError，
说清楚是哪个文件、哪一条。

红线：模式只写态度、说话方式和第四面墙，不写性描写或身体描写；这不是情色功能。
"""

import json
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MODES_FILE = "modes.toml"
"""The mode table's name, beside `characters.toml`."""


@dataclass(frozen=True)
class Mode:
    """A mode the producer may choose: its id, what it is called and described in settings,
    and what is appended to her prompt at love."""

    id: str
    name: str
    description: str
    prompt: str


def modes_path(characters_path: Path) -> Path:
    """Where the mode table is, beside the character configuration."""
    return characters_path.parent / MODES_FILE


def load_modes(path: Path) -> dict[str, Mode]:
    """Read the mode table at `path`, by id; an empty table if there is no file.

    Raises RuntimeError saying what is wrong with a file that is there but unreadable or
    incomplete. Prompt text is kept as written, but for the blank line around it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise RuntimeError(f"模式表 {path} 读不了：{e}") from e
    return parse_modes(text, path)


def parse_modes(text: str, path: Path) -> dict[str, Mode]:
    """The mode table in `text`, as `load_modes` reads it from `path`.

    The admin console checks what it is about to save with this before writing it, so a
    table that would not load is refused rather than left in place.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"模式表 {path} 读不了：{e}") from e

    items = data.get("modes", [])
    if not isinstance(items, list):
        raise RuntimeError(f"模式表 {path} 里的 modes 需要是一张表（[[modes]]）")
    modes: dict[str, Mode] = {}
    for number, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"模式表 {path} 第 {number} 条不是一张表（[[modes]]）")
        mode_id = _text(item, "id", path, number)
        if mode_id in modes:
            raise RuntimeError(f"模式表 {path}：模式 id「{mode_id}」重复了")
        modes[mode_id] = Mode(
            id=mode_id,
            name=_text(item, "name", path, number),
            description=str(item.get("description", "")).strip(),
            prompt=_text(item, "prompt", path, number),
        )
    return modes


def _text(item: dict, key: str, path: Path, number: int) -> str:
    """A required non-empty string from one mode table, or a clear error saying which."""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"模式表 {path} 第 {number} 条缺少 {key}（需要非空字符串）")
    return value.strip()


def render_mode(mode: Mode) -> str:
    """`mode` as one `[[modes]]` block, the way the table writes it: the admin console appends
    this when an admin makes one of their own."""
    return (
        "[[modes]]\n"
        f"id = {_line(mode.id)}\n"
        f"name = {_line(mode.name)}\n"
        f"description = {_line(mode.description)}\n"
        f"prompt = {_quoted(mode.prompt)}\n"
    )


def _line(text: str) -> str:
    """A short one-line value as a TOML string (JSON's escapes are TOML's too)."""
    return json.dumps(text, ensure_ascii=False)


def _quoted(text: str) -> str:
    """`text` as a TOML string: triple-quoted when that reads better and is safe, else escaped."""
    if '"""' not in text and "\\" not in text and not text.endswith('"'):
        return f'"""{text}"""'
    return json.dumps(text, ensure_ascii=False)


def render_mode_body(mode: Mode) -> str:
    """One mode as the admin console edits it: its name, description and prompt, without the
    id (which keys it) or the `[[modes]]` line."""
    return (
        f"name = {_line(mode.name)}\n"
        f"description = {_line(mode.description)}\n"
        f"prompt = {_quoted(mode.prompt)}\n"
    )


def parse_mode_body(text: str, path: Path) -> tuple[str, str, str]:
    """`render_mode_body`'s text back: the name, description and prompt it holds."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"模式表 {path} 读不了：{e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"模式表 {path} 需要是一张表")
    name, prompt = data.get("name"), data.get("prompt")
    description = data.get("description", "")
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(f"模式表 {path} 缺少 name（需要非空字符串）")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError(f"模式表 {path} 缺少 prompt（需要非空字符串）")
    if not isinstance(description, str):
        raise RuntimeError(f"模式表 {path} 的 description 需要是字符串")
    return name.strip(), description.strip(), prompt.strip()


def table_header(text: str) -> str:
    """The comments a mode table opens with, before its first `[[modes]]`; the admin console
    keeps them as they are when it rewrites a mode."""
    head = text.split("[[modes]]", 1)[0]
    return head.rstrip() + "\n\n" if head.strip() else ""


def render_table(header: str, modes: Iterable[Mode]) -> str:
    """The whole table: `header` (its comments) as it is, then each mode's block."""
    blocks = "\n".join(render_mode(mode) for mode in modes)
    head = header.rstrip()
    return f"{head}\n\n{blocks}" if head else blocks
