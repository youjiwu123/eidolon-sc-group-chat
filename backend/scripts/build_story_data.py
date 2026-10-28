"""Build the story replay data (「剧情回放」): `characters/story/` from the offline outline export.

Reads, never writes, the exporter's output under `.scratch/outline/`:

- `index.jsonl` — one row per episode: its source (`browser` / `scsp`), `id`, `kind`, the `unit`
  it belongs to, that unit's `unit_label`, the chapter's Japanese title, the cast (character ids)
  and the script lines (not read here).
- `summaries.jsonl` — batches of `{id, t, s}`: the episode's one-line Chinese title and summary.
  An episode a later batch summarized again keeps that later text.
- `rollups.jsonl` — one rollup per unit: its `name`, `gist`, `themes`, `shape` and cast.
- `scsp_chapters.jsonl` — one rollup per SCSP chapter (`s10_01010000`): `name`, `gist`.

Writes:

- `characters/story/index.json` — every unit, with its episode count and where it sits in the
  page's groups, and no episode text (the detail files hold that, once each).
- `characters/story/<unit id>.json` — one unit: its rollup, its cast and its chapters. Browser
  units have one chapter per episode; SCSP units gather the two to four episodes of a chapter
  under the chapter's own rollup, as the outline does.

A unit is what the outline calls one: a route line for one idol (`route:W.I.N.G.編:mano`), an
event (`evt:4001001`), a special (`sp:Endless×Loop`), a card's story (`P卡剧情:…:mano`), a
homepage story (`mypage:mano`), or an SCSP story group (`s01`). Units are grouped for the page:
routes by route (`W.I.N.G.編`), cards by the character they belong to, the rest left flat.

Unit ids are URL- and file-name-safe and never change while the source's `unit` does not:
`route-wing-mano`, `event-4001001`, `mypage-mano`, `scsp-s01`, `bu-…`, `other-…`, and a short
digest of the source unit for specials and cards (`special-1a2b3c4d5e6f`,
`card-mano-1a2b3c4d5e6f`). The source `unit` itself is kept in both files.

Run it from anywhere, with the backend's virtual environment:

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\build_story_data.py
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUTLINE = REPO / ".scratch" / "outline"
DEFAULT_OUT = REPO / "characters" / "story"

INDEX_FILE = "index.json"

#: The page's sections, top to bottom; the outline's own order (route, event, special, card,
#: homepage, SCSP) and the two leftovers last.
SECTION_ORDER = ("route", "event", "special", "card", "mypage", "scsp", "bu", "other")

#: A route's name in a unit (`route:<name>:<idol>`) and in the page, in the outline's order and
#: spelled the outline's way (`大綱.md`「页游：培育路线」).
ROUTES = (
    ("W.I.N.G.編", "wing"),
    ("Landing Point編", "landing-point"),
    ("G.R.A.D.編", "grad"),
    ("S.T.E.P.編", "step"),
    ("ファン感謝祭編", "fan-thanks"),
    ("Morning", "morning"),
    ("约定", "promise"),
    ("共通", "common"),
    ("试镜", "audition"),
)
ROUTE_SLUGS = dict(ROUTES)
ROUTE_RANK = {name: rank for rank, (name, _) in enumerate(ROUTES)}

#: The longest text kept for a unit's gist or a chapter's summary, in characters; the source's
#: gists run to 538 and its summaries to 193, so nothing in hand is cut.
MAX_TEXT = 600

CARD_NAMES = ("P卡剧情", "S卡剧情")

_DIGEST = re.compile(r"[^0-9a-z]+")


def slug(text: str) -> str:
    """`text` as a URL- and file-name-safe id piece: lowercase ASCII letters and digits, one
    dash between runs."""
    return _DIGEST.sub("-", text.lower()).strip("-")


def digest(text: str) -> str:
    """A short stable id for a unit whose own name is not ASCII (special projects, card names)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def clipped(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT].rstrip() + "…"


def described(values: Iterable[str]) -> list[str]:
    """The strings in `values` that say something, each once, in order."""
    return [value for value in dict.fromkeys(str(v).strip() for v in values) if value]


def read_summaries(path: Path) -> dict[str, dict[str, Any]]:
    """The best summary of each episode by id: the outline summarized a few episodes more than
    once and the later batch's text is the one kept."""
    batches: dict[str, tuple[str, dict[str, Any]]] = {}
    for batch in rows(path):
        name = str(batch["batch"])
        for item in batch["items"]:
            episode = str(item["id"])
            kept = batches.get(episode)
            if kept is None or name > kept[0]:
                batches[episode] = (name, item)
    return {episode: item for episode, (_, item) in batches.items()}


def read_rollups(path: Path) -> dict[str, dict[str, Any]]:
    return {str(item["unit"]): item for item in rows(path)}


def read_scsp_chapters(path: Path) -> dict[str, dict[str, Any]]:
    return {str(item["chapter"]): item for item in rows(path)}


def rollup_scope(key: str) -> tuple[str, str, str] | None:
    """The rollup a unit's key may be spelled differently from: its source, its category and
    the character at its end (`browser`, `P卡剧情`, `meguru`). The outline's index and its
    rollups disagree on five card names (Japanese kanji against simplified Chinese), so those
    units are matched to the closest rollup of their scope."""
    src, _, rest = key.partition(":")
    parts = rest.split(":")
    if len(parts) < 2:
        return None
    return src, parts[0], parts[-1]


def rollup_for(
    unit: "Unit", rollups: dict[str, dict[str, Any]], scoped: dict[tuple[str, str, str], list[str]]
) -> tuple[dict[str, Any], str]:
    """The unit's rollup, by its key or, when the spelling differs, the closest one of its
    scope; raises when there is none close enough to trust."""
    rolled = rollups.get(unit.key)
    if rolled is not None:
        return rolled, unit.key
    scope = rollup_scope(unit.key)
    candidates = scoped.get(scope, []) if scope is not None else []
    scored = sorted(
        ((difflib.SequenceMatcher(None, unit.key, key).ratio(), key) for key in candidates),
        reverse=True,
    )
    if not scored or scored[0][0] < 0.85 or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.02):
        raise RuntimeError(f"单元 {unit.key} 在 rollups.jsonl 里找不到总述，也没有足够接近的一条")
    return rollups[scored[0][1]], scored[0][1]


class Unit:
    """One unit while it is put together: its source rows, in the order the outline lists them."""

    def __init__(self, key: str, source: dict[str, Any]) -> None:
        self.key = key
        self.src = str(source["src"])
        self.unit = str(source["unit"])
        self.kind = str(source["kind"])
        self.label = str(source["unit_label"])
        self.episodes: list[dict[str, Any]] = []
        self.seen = 0  # its first episode's position in the export; the caller sets it

    @property
    def rank(self) -> int:
        return self.seen

    def add(self, row: dict[str, Any]) -> None:
        self.episodes.append(row)


def group_of(unit: Unit) -> tuple[str | None, str | None]:
    """The page's group for `unit`: routes by route, cards by character, the rest flat. An
    unclassified card (`unit:…:?`) is its own group at the end, called 未分类."""
    if unit.kind == "route":
        route = unit.unit.split(":")[1]
        return f"route-{ROUTE_SLUGS.get(route, slug(route))}", route
    if unit.kind == "card":
        character = unit.unit.rsplit(":", 1)[-1]
        if character == "?" or not slug(character):
            return "char-unknown", "未分类"
        return f"char-{slug(character)}", card_character_name(unit.label, character)
    return None, None


def card_character_name(label: str, character: str) -> str:
    """「P卡剧情・樱木真乃（…）」 → 樱木真乃; the id when the label does not say."""
    _, _, rest = label.partition("・")
    name = rest.split("（", 1)[0].strip() if rest else ""
    return name or character


def route_name(unit: Unit) -> str:
    return unit.unit.split(":")[1]


def unit_id(unit: Unit) -> str:
    """The unit's stable id: readable where the source is ASCII, a digest where it is not."""
    kind, raw = unit.kind, unit.unit
    if kind == "route":
        _, route, character = raw.split(":")
        return f"route-{ROUTE_SLUGS.get(route, slug(route)) or digest(route)}-{slug(character) or digest(character)}"
    if kind == "event":
        return f"event-{slug(raw.split(':', 1)[-1])}"
    if kind == "mypage":
        return f"mypage-{slug(raw.split(':', 1)[-1])}"
    if kind == "scsp":
        return f"scsp-{slug(raw.split(':', 1)[-1]) or 'other'}"
    if kind == "bu":
        return f"bu-{slug(raw.split(':', 1)[-1])}"
    if kind == "other":
        return f"other-{slug(raw) or digest(raw)}"
    if kind == "special":
        return f"special-{digest(raw)}"
    if kind == "card":
        character = raw.rsplit(":", 1)[-1]
        return f"card-{slug(character) or 'unknown'}-{digest(raw)}"
    return f"unit-{digest(raw)}"


def ordered(units: Iterable[Unit]) -> list[Unit]:
    """The units of one section in the order the page lists them: routes by route and idol,
    cards by character (`卡面按角色`), specials by size (the outline lists them so), the rest as
    exported."""
    units = list(units)
    if not units:
        return units
    kind = units[0].kind
    if kind == "route":
        return sorted(units, key=lambda u: (ROUTE_RANK.get(route_name(u), len(ROUTES)), u.rank))
    if kind == "card":
        rank: dict[str | None, int] = {}
        for unit in units:  # units arrive in the exporter's order, which is the characters' order
            rank.setdefault(group_of(unit)[0], len(rank))
        return sorted(units, key=lambda u: (rank[group_of(u)[0]], u.rank))
    if kind == "special":
        return sorted(units, key=lambda u: (-len(u.episodes), u.rank))
    return units


def cast_of(episodes: Iterable[dict[str, Any]]) -> list[str]:
    return described(cid for episode in episodes for cid in episode["cast"])


def chapter_of(episode: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """One episode as the page's card: its Chinese title and summary, the source's Japanese
    chapter title (the 「出处」), and who speaks in it."""
    chapter: dict[str, Any] = {
        "id": str(episode["id"]),
        "title": clipped(str(summary.get("t", ""))),
        "ja": str(episode["chapter"] or episode["title_ja"]).strip(),
        "summary": clipped(str(summary.get("s", ""))),
        "cast": list(episode["cast"]),
    }
    if not chapter["ja"]:
        del chapter["ja"]
    return chapter


def scsp_chapters(
    unit: Unit, rollups: dict[str, dict[str, Any]], summaries: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """An SCSP story group's chapters: the episodes of one chapter under the chapter's rollup,
    a chapter the outline did not summarize as a card of its own."""
    by_chapter: dict[str, list[dict[str, Any]]] = {}
    for episode in unit.episodes:
        by_chapter.setdefault(str(episode["chapter"]), []).append(episode)
    chapters: list[dict[str, Any]] = []
    for chapter_id, episodes in by_chapter.items():
        key = f"{unit.unit}_{chapter_id}"
        rolled = rollups.get(key)
        if rolled is None:
            chapters.extend(
                {
                    "id": str(episode["id"]),
                    "title": clipped(str(summaries[str(episode["id"])].get("t", ""))),
                    "summary": clipped(str(summaries[str(episode["id"])].get("s", ""))),
                    "cast": list(episode["cast"]),
                }
                for episode in episodes
            )
            continue
        chapters.append(
            {
                "id": key,
                "title": clipped(str(rolled.get("name", "") or chapter_id)),
                "summary": clipped(str(rolled.get("gist", ""))),
                "cast": cast_of(episodes),
                "episodes": [
                    {
                        "id": str(episode["id"]),
                        "title": clipped(str(summaries[str(episode["id"])].get("t", ""))),
                        "cast": list(episode["cast"]),
                    }
                    for episode in episodes
                ],
            }
        )
    return chapters


def detail_of(unit: Unit, rolled: dict[str, Any], summaries: dict[str, dict[str, Any]],
              scsp_rollups: dict[str, dict[str, Any]], group: tuple[str | None, str | None]) -> dict[str, Any]:
    episodes = unit.episodes
    chapters = (
        scsp_chapters(unit, scsp_rollups, summaries)
        if unit.kind == "scsp"
        else [chapter_of(episode, summaries[str(episode["id"])]) for episode in episodes]
    )
    detail: dict[str, Any] = {
        "id": unit_id(unit),
        "kind": unit.kind,
        "label": unit.label,
        "name": clipped(str(rolled.get("name", ""))),
        "gist": clipped(str(rolled.get("gist", ""))),
        "shape": clipped(str(rolled.get("shape", ""))),
        "themes": described(rolled.get("themes", [])),
        "cast": cast_of(episodes),
        "src": unit.src,
        "unit": unit.unit,
        "group": group[0],
        "group_label": group[1],
        "episodes": len(episodes),
        "chapters": chapters,
    }
    return detail


def indexed(detail: dict[str, Any]) -> dict[str, Any]:
    """One unit as `index.json` keeps it: all of its rollup and who is in it, no chapters.
    The page's list is served from this, trimmed to what it shows (`StoryUnit.as_listed`)."""
    return {
        "id": detail["id"],
        "kind": detail["kind"],
        "label": detail["label"],
        "name": detail["name"],
        "gist": detail["gist"],
        "themes": detail["themes"],
        "shape": detail["shape"],
        "episodes": detail["episodes"],
        "src": detail["src"],
        "cast": detail["cast"],
        "unit": detail["unit"],
        "group": detail["group"],
        "group_label": detail["group_label"],
    }


def build(outline: Path, out: Path) -> tuple[list[dict[str, Any]], int]:
    """Write `out` and return the index entries and how many episodes they cover."""
    summaries = read_summaries(outline / "summaries.jsonl")
    rollups = read_rollups(outline / "rollups.jsonl")
    scsp_rollups = read_scsp_chapters(outline / "scsp_chapters.jsonl")

    units: dict[str, Unit] = {}
    position = 0
    for row in rows(outline / "index.jsonl"):
        key = f"{row['src']}:{row['unit']}"
        unit = units.get(key)
        if unit is None:
            unit = units[key] = Unit(key, row)
            unit.seen = position
        unit.add(
            {
                "id": str(row["id"]),
                "chapter": str(row["chapter"]),
                "title_ja": str(row["title_ja"]),
                "cast": described(row["cast"]),
            }
        )
        position += 1

    unknown = [episode["id"] for unit in units.values() for episode in unit.episodes
               if str(episode["id"]) not in summaries]
    if unknown:
        raise RuntimeError(
            f"以下话在 summaries.jsonl 里没有摘要（共 {len(unknown)} 条）：" + "、".join(unknown[:5])
        )

    scoped: dict[tuple[str, str, str], list[str]] = {}
    for key in rollups:
        scope = rollup_scope(key)
        if scope is not None:
            scoped.setdefault(scope, []).append(key)

    ordered_units: list[Unit] = []
    for kind in SECTION_ORDER:
        ordered_units.extend(ordered(unit for unit in units.values() if unit.kind == kind))
    # Anything the exporter grew that this script does not know about still gets a section.
    known = set(SECTION_ORDER)
    ordered_units.extend(unit for unit in units.values() if unit.kind not in known)

    out.mkdir(parents=True, exist_ok=True)
    seen_ids: dict[str, str] = {}
    listing: list[dict[str, Any]] = []
    respelled: list[tuple[str, str]] = []
    total = 0
    for unit in ordered_units:
        group = group_of(unit)
        rolled, matched = rollup_for(unit, rollups, scoped)
        if matched != unit.key:
            respelled.append((unit.key, matched))
        detail = detail_of(unit, rolled, summaries, scsp_rollups, group)
        if detail["id"] in seen_ids:
            raise RuntimeError(
                f"单元 id {detail['id']} 撞了：{seen_ids[detail['id']]} 和 {unit.key}"
            )
        seen_ids[detail["id"]] = unit.key
        payload = json.dumps(detail, ensure_ascii=False, separators=(",", ":")) + "\n"
        (out / f"{detail['id']}.json").write_text(payload, encoding="utf-8")
        listing.append(indexed(detail))
        total += detail["episodes"]

    index = json.dumps(listing, ensure_ascii=False, separators=(",", ":")) + "\n"
    (out / INDEX_FILE).write_text(index, encoding="utf-8")
    return listing, total, respelled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outline", type=Path, default=DEFAULT_OUTLINE, help="the exporter's directory")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where characters/story goes")
    args = parser.parse_args(argv)
    if not (args.outline / "index.jsonl").is_file():
        print(f"找不到 {args.outline / 'index.jsonl'}", file=sys.stderr)
        return 1
    listing, total, respelled = build(args.outline, args.out)
    index_size = (args.out / INDEX_FILE).stat().st_size
    unit_sizes = [path.stat().st_size for path in args.out.glob("*.json") if path.name != INDEX_FILE]
    by_kind: dict[str, int] = {}
    for entry in listing:
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
    print(f"{len(listing)} 个单元、{total} 话 → {args.out}")
    print("按类型：" + "、".join(f"{kind} {count}" for kind, count in by_kind.items()))
    print(
        f"{INDEX_FILE} {index_size / 1024:.0f} KB；{len(unit_sizes)} 个单元文件 "
        f"{sum(unit_sizes) / 1024 / 1024:.2f} MB（最大 {max(unit_sizes) / 1024:.0f} KB）；"
        f"共 {(index_size + sum(unit_sizes)) / 1024 / 1024:.2f} MB"
    )
    for unit, matched in respelled:
        print(f"总述按拼写最接近的对上：{unit} ← {matched}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
