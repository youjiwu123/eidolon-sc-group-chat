"""The admin console's prompt editor, under `/api/admin/prompts`, for admins only.

What may be edited is a whitelist, never a path the browser names: the character sheets the
character configuration refers to (`characters/sheets/<id>.md`), each mode of the mode table
(`characters/modes.toml`, one `modes/<id>` entry each) and the affinity tiers' prompts
(`characters/affinity.toml`). A sheet is the whole file; a mode is its own name, description and
prompt; the affinity tiers are the whole file, with `modes.parse_mode_body` and
`affinity_prompts.parse_affinity_prompts` checking that what is about to be saved still loads
before anything is written. Anything else, absolute paths and `..` included, is 404. This is the
character prompts, not the adult-content gate or any character's age.

Saving backs the old content up under `characters/backups/prompts/<key>.<timestamp>.bak`, writes
a temporary file beside the target and replaces the target with it. Then it reloads the
characters, the modes and the affinity prompts into the running backend, in place: the API's
`characters` mapping and the engine's are the same dict, so the next turn already uses the new
sheet, and `ConversationEngine.reload_modes` / `reload_affinity_prompts` swap the rest for the
next turn and call. A mode is saved in its place in the table, the other modes and the table's own
comments kept.
"""

import logging
import os
import tempfile
import threading
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from eidolon.accounts import is_admin
from eidolon.affinity_prompts import (
    AFFINITY_FILE,
    load_affinity_prompts,
    parse_affinity_prompts,
    render_affinity_prompts,
)
from eidolon.assembly import Backend
from eidolon.characters import load_characters
from eidolon.modes import (
    Mode,
    load_modes,
    parse_mode_body,
    parse_modes,
    render_mode_body,
    render_table,
    table_header,
)
from eidolon.sessions import session_user
from eidolon.store import User

log = logging.getLogger(__name__)

MAX_PROMPT_BYTES = 200 * 1024
"""The most a prompt may be, in UTF-8 bytes."""

MODES_KEY = "modes.toml"

MODES_DIR = "modes"
"""Each mode's own entry is `modes/<id>`: the table is edited one mode at a time."""

_WRITE_LOCK = threading.Lock()
"""Saving reloads the whole character configuration; one save at a time keeps the mapping
from being swapped while another save is half way through."""


@dataclass(frozen=True)
class PromptEntry:
    """One editable prompt: the key the API names it by, what it is, and where it is."""

    key: str
    kind: str
    """`sheet` for a character sheet, `mode` for one mode of the table, `modes` for the whole
    table (only when it cannot be read), `affinity` for the affinity tiers' prompts."""
    label: str
    path: Path


class PromptInput(BaseModel):
    """What to save: the whole text (`content`), or, for one mode, its three fields. A mode
    is normally edited as fields (名字、说明、提示词), so no TOML quoting has to be typed by
    hand; `content` is still taken for the mode table as a whole."""

    content: str | None = None
    name: str | None = None
    description: str | None = None
    prompt: str | None = None


class NewMode(BaseModel):
    """A special mode an admin makes of their own: what it is called, what settings says
    about it, and what is appended to her prompt at the top tier."""

    name: str
    description: str = ""
    prompt: str


MAX_MODE_NAME = 40
"""The most a mode's name may be, in characters."""

MAX_MODE_DESCRIPTION = 200
"""The most its description may be, in characters."""

MAX_MODE_PROMPT_BYTES = 20 * 1024
"""The most its prompt may be, in UTF-8 bytes."""

MODES_HEADER = """# 特殊档等「模式」：只在好感最高档（love）之上、用户选中时追加到提示词。
# 红线：这里只写态度、说话方式和第四面墙；不要加性描写或身体描写，这不是情色功能。
# 加模式只改这个文件，不改代码；prompt 原样进入提示词。
"""
"""What a mode table the admin console makes from nothing starts with."""


def prompt_admin_user(request: Request) -> User:
    """The admin who may edit prompts; 403 for anyone else."""
    backend: Backend = request.app.state.backend
    user = session_user(request)
    if (
        user is None
        or user.consented_at is None
        or user.banned_at is not None
        or not backend.settings.admins
        or not is_admin(backend.store, backend.settings, user.id)
    ):
        raise HTTPException(403, "需要管理员权限")
    return user


PromptAdmin = Annotated[User, Depends(prompt_admin_user)]


def prompt_entries(characters_path: Path) -> dict[str, PromptEntry]:
    """The prompts that may be edited: every sheet the character configuration names, then
    the mode table. A sheet whose path is not a plain `sheets/<name>.md` under the
    characters directory, or that would lead out of it, is left out."""
    root = characters_path.resolve().parent
    try:
        config = tomllib.loads(characters_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise RuntimeError(f"读不了角色配置 {characters_path}：{e}") from e

    entries: dict[str, PromptEntry] = {}
    for character in config.get("characters", []):
        if not isinstance(character, dict) or not isinstance(character.get("sheet"), str):
            continue
        key = _safe_sheet_key(root, character["sheet"])
        if key is None or key in entries:
            continue
        name_zh = character.get("name_zh")
        name = character.get("name")
        label = name_zh if isinstance(name_zh, str) and name_zh.strip() else name
        if not isinstance(label, str) or not label.strip():
            label = str(character.get("id") or key)
        entries[key] = PromptEntry(
            key=key,
            kind="sheet",
            label=label,
            path=(root / PurePosixPath(key)).resolve(),
        )

    modes_path = root / MODES_KEY
    if modes_path.exists() and not modes_path.is_file():
        log.warning("prompt: %s is not a file; leaving it out of the editor", modes_path)
    elif modes_path.exists() and modes_path.resolve().parent != root:
        log.warning("prompt: %s points outside the characters directory; leaving it out", modes_path)
    else:
        # 每个模式单独一格（`modes/<id>`），列表里按表里的顺序排；表读不了时退回整份一格，
        # 好让管理员还能把它改回来。
        try:
            modes = load_modes(modes_path)
        except RuntimeError:
            log.exception("prompt: the mode table is broken; offering it whole")
            modes = None
        if modes is None:
            entries[MODES_KEY] = PromptEntry(
                key=MODES_KEY,
                kind="modes",
                label="模式表（读不了，整份改）",
                path=modes_path.resolve(),
            )
        else:
            for mode in modes.values():
                entries[f"{MODES_DIR}/{mode.id}"] = PromptEntry(
                    key=f"{MODES_DIR}/{mode.id}",
                    kind="mode",
                    label=mode.name,
                    path=modes_path.resolve(),
                )

    # 好感度各档的那几段：文件还没建也算一条，编辑器里先给默认的那份，保存就建出来。
    entries[AFFINITY_FILE] = PromptEntry(
        key=AFFINITY_FILE,
        kind="affinity",
        label="好感度提示词",
        path=(root / AFFINITY_FILE).resolve(),
    )
    return entries


def _safe_sheet_key(root: Path, sheet: str) -> str | None:
    """The canonical key of a sheet path, if it is a plain Markdown file in `sheets/` that
    resolves inside that directory; None for anything else."""
    if "\\" in sheet or "\x00" in sheet:
        return None
    path = PurePosixPath(sheet)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "sheets":
        return None
    if path.suffix != ".md" or ".." in path.parts or "." in path.parts:
        return None
    target = (root / path).resolve()
    try:
        target.relative_to((root / "sheets").resolve())
    except ValueError:
        return None
    return path.as_posix() if target.is_file() else None


def _entry_or_404(characters_path: Path, key: str) -> PromptEntry:
    """The entry `key` names; 404 for anything outside the whitelist, however it was written
    (`..`, an absolute path, a Windows path)."""
    entries = prompt_entries(characters_path)
    entry = entries.get(key)
    if entry is None:
        raise HTTPException(404, "没有这条提示词")
    if entry.kind == "sheet":
        # Recheck after reading the whitelist: a sheet may have been replaced by a symlink.
        target = entry.path.resolve()
        try:
            target.relative_to((characters_path.resolve().parent / "sheets").resolve())
        except ValueError:
            raise HTTPException(404, "没有这条提示词") from None
        if not target.is_file():
            raise HTTPException(404, "没有这条提示词")
    elif entry.kind in ("modes", "mode", "affinity") and entry.path.exists() and (
        not entry.path.is_file() or entry.path.resolve().parent != characters_path.resolve().parent
    ):
        raise HTTPException(404, "没有这条提示词")
    return entry


def _describe(entry: PromptEntry) -> dict:
    """An entry as the list gives it, without its content."""
    exists = entry.path.is_file()
    if entry.kind == "mode":
        mode = _mode_of(entry)
        body = render_mode_body(mode) if mode is not None else ""
        return {
            "key": entry.key,
            "kind": entry.kind,
            "label": mode.name if mode is not None else entry.label,
            "bytes": len(body.encode("utf-8")),
            "updated_at": _mtime(entry.path) if exists else None,
        }
    return {
        "key": entry.key,
        "kind": entry.kind,
        "label": entry.label,
        "bytes": entry.path.stat().st_size if exists else 0,
        "updated_at": _mtime(entry.path) if exists else None,
    }


def _detail(entry: PromptEntry) -> dict:
    """An entry as the editor reads it: its whole text, exactly as saved; for one mode, its
    three fields too, so the editor can show them as a form."""
    if entry.kind == "mode":
        mode = _mode_of(entry)
        if mode is None:
            raise HTTPException(404, "没有这条提示词")
        return {
            **_describe(entry),
            "content": render_mode_body(mode),
            "fields": {
                "name": mode.name,
                "description": mode.description,
                "prompt": mode.prompt,
            },
        }
    if entry.path.is_file():
        content = _read_exact(entry.path)
    elif entry.kind == "affinity":
        # 文件还没建：给默认的那份，管理员看得见现在的字，保存就落成文件。
        content = render_affinity_prompts()
    else:
        content = ""
    return {
        **_describe(entry),
        "content": content,
    }


def _detail_after_save(
    characters_path: Path, key: str, entry: PromptEntry, data: bytes
) -> dict:
    """The saved prompt as the editor reads it back. A whole mode table that a save fixed is
    no longer an entry of its own (it is one per mode now), so it is described as written."""
    try:
        return _detail(_entry_or_404(characters_path, key))
    except HTTPException:
        return {
            "key": key,
            "kind": entry.kind,
            "label": entry.label,
            "bytes": len(data),
            "updated_at": _mtime(entry.path),
            "content": data.decode("utf-8"),
        }


def _mode_of(entry: PromptEntry) -> Mode | None:
    """The mode a `modes/<id>` entry names, as the table has it now."""
    mode_id = entry.key.split("/", 1)[1]
    try:
        return load_modes(entry.path).get(mode_id)
    except RuntimeError:
        log.exception("prompt: could not read %s", entry.path)
        return None


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _read_exact(path: Path) -> str:
    """The file as text with its newlines exactly as on disk, unlike `Path.read_text`, which
    would turn CRLF into LF and make an unchanged save look changed."""
    with path.open("r", encoding="utf-8", newline="") as file:
        return file.read()


def _validated(content: str, entry: PromptEntry) -> bytes:
    """The bytes to write, after checking that the prompt is non-empty UTF-8 within the size
    limit and that, whole or one mode of it, the table still loads."""
    if not content.strip():
        raise HTTPException(422, "提示词不能为空")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(422, "提示词不是合法的 UTF-8 文本") from None
    if len(data) > MAX_PROMPT_BYTES:
        raise HTTPException(422, f"提示词太长了：最多 {MAX_PROMPT_BYTES // 1024} KB")
    if entry.kind == "modes":
        try:
            parse_modes(content, Path(MODES_KEY))
        except RuntimeError as e:
            raise HTTPException(422, f"{e}（没有保存）") from None
    elif entry.kind == "mode":
        try:
            parse_mode_body(content, Path(MODES_KEY))
        except RuntimeError as e:
            raise HTTPException(422, f"{e}（没有保存）") from None
    elif entry.kind == "affinity":
        try:
            parse_affinity_prompts(content, Path(AFFINITY_FILE))
        except RuntimeError as e:
            raise HTTPException(422, f"{e}（没有保存）") from None
    return data


def _backup_path(entry: PromptEntry) -> Path:
    """Where the previous content of `entry` goes, under the characters directory so a
    deployment's read-write bind mount keeps it: `backups/prompts/<key>.<timestamp>.bak`."""
    root = entry.path.parent if entry.kind in ("modes", "mode") else entry.path.parent.parent
    key = PurePosixPath(entry.key)
    target = root / "backups" / "prompts" / Path(*key.parts)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    candidate = target.with_name(f"{target.name}.{stamp}.bak")
    number = 0
    while candidate.exists():
        number += 1
        candidate = target.with_name(f"{target.name}.{stamp}-{number}.bak")
    return candidate


def _atomic_write(path: Path, data: bytes) -> None:
    """Write `path` with a temporary file and `os.replace`, so a reader sees the old content
    or the new one, never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if path.exists():
            # Keep the permissions the deployment gave the file, where the filesystem has them.
            try:
                os.chmod(temp_path, path.stat().st_mode)
            except OSError:
                pass
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _reload(backend: Backend) -> None:
    """Reload the characters, the modes and the affinity prompts from disk into the running
    backend, in place.

    `Backend.characters` is the dict the API handlers, the engine, memories and reach-outs
    hold, so clearing and filling it changes what the next turn sees. Modes are passed to the
    engine explicitly, as a missing modes file makes it hold a dict of its own; the affinity
    prompts likewise, as a missing file makes it hold the built-in ones.
    """
    characters = load_characters(backend.settings.characters_path)
    modes = load_modes(backend.settings.modes_path)
    affinity_prompts = load_affinity_prompts(backend.settings.affinity_prompts_path)
    backend.characters.clear()
    backend.characters.update(characters)
    backend.modes.clear()
    backend.modes.update(modes)
    backend.engine.reload_modes(backend.modes)
    backend.engine.reload_affinity_prompts(affinity_prompts)
    log.info(
        "prompt: reloaded %d characters, %d modes and the affinity prompts into the running"
        " backend",
        len(characters),
        len(modes),
    )


def _back_up(entry: PromptEntry, previous: bytes) -> Path:
    path = _backup_path(entry)
    _atomic_write(path, previous)
    return path


def _checked_mode(name: str, description: str, prompt: str) -> tuple[str, str, str]:
    """A mode's three fields, checked; 422 saying which is wrong."""
    name = name.strip()
    description = description.strip()
    prompt = prompt.strip()
    if not name:
        raise HTTPException(422, "名字不能为空")
    if len(name) > MAX_MODE_NAME:
        raise HTTPException(422, f"名字太长了：最多 {MAX_MODE_NAME} 个字")
    if len(description) > MAX_MODE_DESCRIPTION:
        raise HTTPException(422, f"说明太长了：最多 {MAX_MODE_DESCRIPTION} 个字")
    if not prompt:
        raise HTTPException(422, "提示词不能为空")
    if len(prompt.encode("utf-8")) > MAX_MODE_PROMPT_BYTES:
        raise HTTPException(422, f"提示词太长了：最多 {MAX_MODE_PROMPT_BYTES // 1024} KB")
    return name, description, prompt


def _pasted_mode(text: str) -> tuple[str, str, str] | None:
    """The mode a whole `[[modes]]` block (or one mode's body) pasted into the prompt field
    holds: its name, description and prompt; None when it is just a prompt."""
    if "[[modes]]" in text:
        try:
            found = parse_modes(text, Path(MODES_KEY))
        except RuntimeError:
            return None
        if len(found) != 1:
            return None
        mode = next(iter(found.values()))
        return mode.name, mode.description, mode.prompt
    try:
        return parse_mode_body(text, Path(MODES_KEY))
    except RuntimeError:
        return None


def _new_mode(body: NewMode, existing: Mapping[str, Mode]) -> Mode:
    """The mode `body` describes, checked, with an id nothing else has yet.

    A prompt field holding a whole `[[modes]]` block or a mode body is taken apart: its
    name, description and prompt are used, and what the form's own fields say wins where they
    are filled in. That is how the old editor's copy-paste habit still works."""
    name, description, prompt = body.name.strip(), body.description.strip(), body.prompt.strip()
    pasted = _pasted_mode(prompt)
    if pasted is not None:
        pasted_name, pasted_description, pasted_prompt = pasted
        name = name or pasted_name
        description = description or pasted_description
        prompt = pasted_prompt
    name, description, prompt = _checked_mode(name, description, prompt)
    if any(mode.name == name for mode in existing.values()):
        raise HTTPException(422, f"已经有一个叫「{name}」的特殊档了")
    number = 1
    while f"custom-{number}" in existing:
        number += 1
    return Mode(id=f"custom-{number}", name=name, description=description, prompt=prompt)


def _with_mode(previous: bytes | None, mode: Mode, modes: Mapping[str, Mode]) -> str:
    """The mode table as `previous` has it (its own comments kept), with `mode` at the end."""
    text = previous.decode("utf-8") if previous is not None else MODES_HEADER
    return render_table(table_header(text), [*modes.values(), mode])


def _mode_content(entry: PromptEntry, body: PromptInput) -> str:
    """One mode's body to save: its three fields when the editor sends them (名字、说明、
    提示词，不用手写 TOML), else the text as it came."""
    mode_id = entry.key.split("/", 1)[1]
    if body.name is None and body.description is None and body.prompt is None:
        if body.content is None:
            raise HTTPException(422, "缺少要保存的内容")
        return body.content
    current = load_modes(entry.path).get(mode_id)
    return render_mode_body(
        Mode(
            id=mode_id,
            name=current.name if body.name is None and current else (body.name or ""),
            description=current.description
            if body.description is None and current
            else (body.description or ""),
            prompt=current.prompt if body.prompt is None and current else (body.prompt or ""),
        )
    )


def _save_mode(entry: PromptEntry, content: str, backend: Backend) -> dict:
    """Rewrite one mode in its place: its name, description and prompt, the other modes and
    the table's own comments kept; then reload. Called with `_WRITE_LOCK` held."""
    modes = load_modes(entry.path)
    mode_id = entry.key.split("/", 1)[1]
    current = modes.get(mode_id)
    if current is None:
        raise HTTPException(404, "没有这条提示词")
    name, description, prompt = _checked_mode(*parse_mode_body(content, entry.path))
    modes[mode_id] = replace(current, name=name, description=description, prompt=prompt)
    previous = entry.path.read_bytes()
    data = render_table(table_header(previous.decode("utf-8")), modes.values()).encode("utf-8")
    parse_modes(data.decode("utf-8"), entry.path)  # 写之前先确认它还能读
    _back_up(entry, previous)
    _atomic_write(entry.path, data)
    try:
        _reload(backend)
    except Exception as e:
        log.exception("prompt: mode %s saved but reloading failed; putting it back", entry.key)
        _restore_after_failure(entry, previous, backend)
        raise HTTPException(500, f"特殊档没有保存：重新加载失败（{e}）") from None
    return _detail(entry)


def _delete_mode(entry: PromptEntry, backend: Backend) -> dict:
    """Take one mode out of the table in its place: the other modes and the table's own
    comments kept, the switches that had it on turned off with it; then reload. Called with
    `_WRITE_LOCK` held."""
    modes = load_modes(entry.path)
    mode_id = entry.key.split("/", 1)[1]
    if mode_id not in modes:
        raise HTTPException(404, "没有这条提示词")
    previous = entry.path.read_bytes()
    rest = [mode for key, mode in modes.items() if key != mode_id]
    data = render_table(table_header(previous.decode("utf-8")), rest).encode("utf-8")
    parse_modes(data.decode("utf-8"), entry.path)  # 写之前先确认它还能读
    _back_up(entry, previous)
    _atomic_write(entry.path, data)
    try:
        _reload(backend)
    except Exception as e:
        log.exception("prompt: mode %s deleted but reloading failed; putting it back", entry.key)
        _restore_after_failure(entry, previous, backend)
        raise HTTPException(500, f"特殊档没有删除：重新加载失败（{e}）") from None
    backend.character_modes.forget(mode_id)
    return {"key": entry.key, "deleted": True}


def _restore_after_failure(entry: PromptEntry, previous: bytes | None, backend: Backend) -> None:
    """Put the previous file back after a failed reload, and try to reload that."""
    try:
        if previous is None:
            entry.path.unlink(missing_ok=True)
        else:
            _atomic_write(entry.path, previous)
        _reload(backend)
    except Exception:
        log.exception("prompt: could not put %s back after a failed reload", entry.key)


def add_prompt_admin_routes(app: FastAPI, backend: Backend) -> None:
    characters_path = backend.settings.characters_path
    modes_path = backend.settings.modes_path

    @app.get("/api/admin/prompts")
    def list_prompts(_: PromptAdmin) -> list[dict]:
        """The editable prompts: the configured character sheets, the mode table and the
        affinity prompts, with their sizes and when they were last changed."""
        return [
            _describe(entry)
            for entry in prompt_entries(characters_path).values()
        ]

    @app.post("/api/admin/modes", status_code=201)
    def create_mode(body: NewMode, _: PromptAdmin) -> dict:
        """Make a new special mode of the admin's own: its name, description and prompt, put
        into the mode table (backed up, written atomically), then reloaded, so that the
        chat's affinity popover offers it as one more switch from now on. It takes effect at
        the top tier only, as every mode does.

        The id is made here (`custom-<n>`): the browser causes no paths. 422 for a blank or
        too long name, description or prompt, or a name another mode already has."""
        with _WRITE_LOCK:
            entry = PromptEntry(
                key=MODES_KEY, kind="modes", label="模式提示词", path=modes_path.resolve()
            )
            existing = load_modes(modes_path)
            mode = _new_mode(body, existing)
            previous = modes_path.read_bytes() if modes_path.is_file() else None
            text = _with_mode(previous, mode, existing)
            parse_modes(text, modes_path)  # 写之前先确认它还能读
            if previous is not None:
                _back_up(entry, previous)
            _atomic_write(modes_path, text.encode("utf-8"))
            try:
                _reload(backend)
            except Exception as e:
                log.exception("prompt: mode %s saved but reloading failed; putting it back", mode.id)
                _restore_after_failure(entry, previous, backend)
                raise HTTPException(500, f"特殊档没有保存：重新加载失败（{e}）") from None
            log.info("prompt: made the mode %s (%s)", mode.id, mode.name)
            return {"id": mode.id, "name": mode.name}

    @app.get("/api/admin/prompts/{key:path}")
    def get_prompt(key: str, _: PromptAdmin) -> dict:
        """One prompt's whole text; 404 for anything outside the whitelist."""
        return _detail(_entry_or_404(characters_path, key))

    @app.delete("/api/admin/prompts/{key:path}")
    def delete_prompt(key: str, _: PromptAdmin) -> dict:
        """Delete one special mode of the table by name, backed up and written atomically, and
        reloaded; the per-character switches that had it on go with it. 422 for anything but
        one mode: the mode table as a whole, sheets and the affinity prompts are not deleted
        here, only edited."""
        with _WRITE_LOCK:
            entry = _entry_or_404(characters_path, key)
            if entry.kind != "mode":
                raise HTTPException(422, "只有特殊档能单独删除")
            return _delete_mode(entry, backend)

    @app.put("/api/admin/prompts/{key:path}")
    def save_prompt(key: str, _: PromptAdmin, body: PromptInput = Body()) -> dict:
        """Check the text, back the old one up, replace it atomically, and reload the
        characters and modes so the next turn uses it; 422 if it would not load."""
        with _WRITE_LOCK:
            entry = _entry_or_404(characters_path, key)
            if entry.kind == "mode":
                content = _mode_content(entry, body)
                _validated(content, entry)  # 422 说清楚哪里不对
                saved = _save_mode(entry, content, backend)
                return {**saved, "reload_required": False}
            if body.content is None:
                raise HTTPException(422, "缺少要保存的正文")
            data = _validated(body.content, entry)
            previous = entry.path.read_bytes() if entry.path.is_file() else None
            if previous is not None:
                _back_up(entry, previous)
            _atomic_write(entry.path, data)
            try:
                _reload(backend)
            except Exception as e:
                log.exception("prompt: %s saved but reloading failed; putting it back", key)
                _restore_after_failure(entry, previous, backend)
                raise HTTPException(500, f"提示词没有保存：重新加载失败（{e}）") from None
            saved = _detail_after_save(characters_path, key, entry, data)
            return {**saved, "reload_required": False}
