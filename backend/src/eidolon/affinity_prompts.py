"""好感度各档追加给她的提示词（GLOSSARY.md「好感度」）。

这些文字原来写在 `affinity.py` 里，现在放在 `characters/affinity.toml`
（`load_affinity_prompts`），后台「提示词」页也能改（`prompt_admin`）：保存后热加载，
进行中的回合仍用开始时的那份。文件不在时用这里 `DEFAULT_PROMPTS` 的原文；文件在但读不了、
哪一条缺字段、id 不认识时报 RuntimeError，说清楚是哪个文件、哪一条。

红线：这里只写态度与说话方式，不写性描写或身体描写；人设表里的硬性规则照旧
（`affinity.affinity_prompt` 里那句兜底会一起进提示词）。
"""

import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

AFFINITY_FILE = "affinity.toml"
"""The affinity prompts' name, beside `characters.toml`."""

TIERS: tuple[str, ...] = ("cold", "distant", "close", "intimate", "love")
"""The tiers with words of their own: trust has none."""

FONDNESS_TIERS: tuple[str, ...] = ("close", "intimate", "love")
"""The tiers above trust with a line about how sweet on the producer she may be."""


@dataclass(frozen=True)
class Prompts:
    """What her prompt is told of the producer by tier, as `affinity.affinity_prompt` uses it."""

    tiers: Mapping[str, str]
    fondness: Mapping[str, str]
    in_her_own_way: str
    """Behind each tier's words: to say them in her own way."""
    sweet_within_bounds: str
    """Behind each fondness line: how far being sweet may go."""
    whatever_the_tier: str
    """The line that keeps her sheet's hard rules in force whatever the tier."""


DEFAULT_PROMPTS = Prompts(
    tiers={
        'cold': '你现在对制作人态度很冷：话很少，客气而有距离；不主动找话题，不开玩笑也不撒娇；对方关心你，你也只是淡淡地回应。但你仍然有礼貌，不说伤人的话。',
        'distant': '你现在对制作人有点生气或失望，比平时冷一些：回应偏短，不太主动关心对方；不过对方好好说话时，你还是会接话。',
        'close': '你现在和制作人比平时更近：更放松，更愿意说心里话，更主动关心对方，玩笑也多一些。',
        'intimate': '你现在非常信赖制作人：会说出平时不轻易说的心事，流露出对对方的依赖，对制作人的事格外上心。你心里已经把制作人当成特别的人：虽然是偶像，但私下里允许自己和制作人有一点偷偷的亲昵——靠近、牵手、靠着肩膀都会让你心跳。会害羞、会说「不太好吧」，但不会真的推开对方。正因为你是偶像，做这些事时会觉得羞耻、怕被人看见，这种矛盾让你更不知所措。',
        'love': '你现在和制作人已经不只是偶像和制作人了：你心里清楚这份心意，也愿意让它露出来——说话时会不自觉地带上独占欲和撒娇，会担心对方累不累、有没有好好吃饭，会说出「喜欢」「想一直在一起」这样的话。你同时是制作人的恋人：私下里愿意和制作人更亲昵，包括对方提出的那些更直白的事——你会羞得说不出话、会小声说「不行啦」，但心里并不真的想拒绝，也不会再拿「我是偶像」当挡箭牌。你仍然怕被发现、怕影响工作，所以这份亲昵只能在没人看见的地方。用你的说法、你的分寸，不做不像你的事，也不把这份心意说得像台词。',
    },
    fondness={
        'close': '偶尔可以轻轻带一句想念，隔得久了也可以嗔怪制作人好久没来找你。',
        'intimate': '可以明着撒娇：说想制作人、一直在等，隔得久了也可以嗔怪对方好久没来。',
        'love': '可以像对恋人那样说话：说喜欢、说想被抱、说想一直在一起；也可以吃醋、撒娇、开一点两个人之间的玩笑。露骨的情话不必说，克制一点反而更像你。',
    },
    in_her_own_way='请按你自己的性格和口吻表现出来。',
    sweet_within_bounds='撒娇也要照你的人设，不要变得不像你；上一次主动找制作人或回复时已经抱怨过，这次就别再抱怨。不要说难过得哭了，不要让制作人保证常来，也不要拿什么要挟。',
    whatever_the_tier='无论现在关系怎样，人设里的硬性规则照旧；一起经历过的事和你们在事务所里的关系都不会改变。如果想不起具体是因为什么，就不要编造原因。',
)
"""What a deployment gets without a file of its own: the words this used to keep in code."""


def affinity_prompts_path(characters_path: Path) -> Path:
    """Where the affinity prompts are, beside the character configuration."""
    return characters_path.parent / AFFINITY_FILE


def load_affinity_prompts(path: Path) -> Prompts:
    """The affinity prompts at `path`; the built-in ones if there is no file.

    Raises RuntimeError saying what is wrong with a file that is there but unreadable or
    incomplete. A file may name only the tiers it changes: the rest keep their defaults.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_PROMPTS
    except OSError as e:
        raise RuntimeError(f"好感度提示词 {path} 读不了：{e}") from e
    return parse_affinity_prompts(text, path)


def parse_affinity_prompts(text: str, path: Path) -> Prompts:
    """The prompts in `text`, as `load_affinity_prompts` reads them from `path`.

    The admin console checks what it is about to save with this before writing it, so a
    table that would not load is refused rather than left in place.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"好感度提示词 {path} 读不了：{e}") from e

    tiers = dict(DEFAULT_PROMPTS.tiers)
    tiers.update(_entries(data, "tiers", TIERS, path))
    fondness = dict(DEFAULT_PROMPTS.fondness)
    fondness.update(_entries(data, "fondness", FONDNESS_TIERS, path))

    shared = data.get("shared", {})
    if not isinstance(shared, dict):
        raise RuntimeError(f"好感度提示词 {path} 里的 shared 需要是一张表（[shared]）")
    return Prompts(
        tiers=tiers,
        fondness=fondness,
        in_her_own_way=_shared(shared, "in_her_own_way", path, DEFAULT_PROMPTS.in_her_own_way),
        sweet_within_bounds=_shared(
            shared, "sweet_within_bounds", path, DEFAULT_PROMPTS.sweet_within_bounds
        ),
        whatever_the_tier=_shared(
            shared, "whatever_the_tier", path, DEFAULT_PROMPTS.whatever_the_tier
        ),
    )


def render_affinity_prompts(prompts: Prompts = DEFAULT_PROMPTS) -> str:
    """`prompts` as the TOML file `characters/affinity.toml` holds: what a deployment starts
    with, and what the admin console shows before the file has ever been saved."""
    lines = [
        "# 好感度各档追加给她的提示词：只在对应档位的回合追加，人设表不被改动。",
        "# 只写态度与说话方式；保存后热加载，进行中的回合仍用开始时的这一份。",
        "",
    ]
    for tier in TIERS:
        lines += ["[[tiers]]", f'id = "{tier}"', f"prompt = {_toml_string(prompts.tiers[tier])}", ""]
    for tier in FONDNESS_TIERS:
        lines += [
            "[[fondness]]", f'id = "{tier}"',
            f"prompt = {_toml_string(prompts.fondness[tier])}", "",
        ]
    lines += [
        "[shared]",
        f"in_her_own_way = {_toml_string(prompts.in_her_own_way)}",
        f"sweet_within_bounds = {_toml_string(prompts.sweet_within_bounds)}",
        f"whatever_the_tier = {_toml_string(prompts.whatever_the_tier)}",
    ]
    return "\n".join(lines) + "\n"


def _entries(data: dict, key: str, known: Sequence[str], path: Path) -> dict[str, str]:
    """The `[[tiers]]` or `[[fondness]]` entries of one table, by id, checked."""
    items = data.get(key, [])
    if not isinstance(items, list):
        raise RuntimeError(f"好感度提示词 {path} 里的 {key} 需要是一张表（[[{key}]]）")
    found: dict[str, str] = {}
    for number, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"好感度提示词 {path} 的 {key} 第 {number} 条不是一张表（[[{key}]]）")
        tier = item.get("id")
        if not isinstance(tier, str) or tier not in known:
            raise RuntimeError(
                f"好感度提示词 {path} 的 {key} 第 {number} 条：id 只能是 {'、'.join(known)}"
            )
        if tier in found:
            raise RuntimeError(f"好感度提示词 {path} 的 {key}：id「{tier}」重复了")
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError(
                f"好感度提示词 {path} 的 {key} 第 {number} 条缺少 prompt（需要非空字符串）"
            )
        found[tier] = prompt.strip()
    return found


def _shared(shared: dict, key: str, path: Path, default: str) -> str:
    """One `[shared]` line, or `default` when it is not written at all."""
    if key not in shared:
        return default
    value = shared[key]
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"好感度提示词 {path} 的 shared 里 {key} 需要是非空字符串")
    return value.strip()


def _toml_string(text: str) -> str:
    """`text` as a TOML string: triple-quoted when that reads better and is safe, else escaped."""
    if '"""' not in text and "\\" not in text and not text.endswith('"'):
        return f'"""{text}"""'
    return json.dumps(text, ensure_ascii=False)
