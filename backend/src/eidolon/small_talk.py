"""她的小台词（DESIGN.md「对话页的立绘小人」）：点她一下时随机说的一句。

素材由 `scripts/import-sc-time-small-talk.py` 从 SC-Time 整理到 `corpus/small-talk/<角色标识>/`：每句一句
日语原文、一句中文字幕、一条她自己的语音，以及这句的心情和适合的时段。语料和立绘一样不进仓库。
没有整理过这一位、或者语料读不了时不说话，前端退回只做一个表情。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

# 时段：一句台词要么什么时候都能说（`all`），要么只在某一段说。
PERIODS = ("morning", "afternoon", "night")

# 她这会儿的心情，和前端 `lib/standAnimations.ts` 的七种一致；语料里写了别的就按平静。
MOODS = ("calm", "happy", "shy", "surprised", "sad", "angry", "thinking")


@dataclass(frozen=True)
class Line:
    """她的一句小台词。"""

    id: str
    """这句在语料里的编号，也用来找它的语音。"""
    ja: str
    zh: str
    voice: str
    """语音文件的名字，在她那一份语料的 `voice/` 下。"""
    mood: str
    """这句的心情：平静、开心、害羞、惊讶、难过、生气、思考之一。"""
    period: str = "all"
    body: str = ""
    """原作里这句配的身体动作（衣装上没有的话，前端按心情挑一个）。"""
    face: str = ""
    """原作里这句配的表情；`blank` 是把脸交回身体动作。"""


def load(root: Path, character_id: str) -> list[Line]:
    """这位角色的小台词；没整理过、或者文件坏了时为空。"""
    try:
        data = json.loads((root / character_id / "lines.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lines: list[Line] = []
    for entry in data.get("lines") or []:
        if not isinstance(entry, dict):
            continue
        ja, voice = entry.get("ja"), entry.get("voice")
        if not isinstance(ja, str) or not ja.strip() or not isinstance(voice, str) or not voice:
            continue
        mood = str(entry.get("mood") or "calm")
        period = str(entry.get("period") or "all")
        lines.append(
            Line(
                id=str(entry.get("id") or voice),
                ja=ja,
                zh=str(entry.get("zh") or ""),
                voice=voice,
                mood=mood if mood in MOODS else "calm",
                period=period if period in PERIODS else "all",
                body=str(entry.get("body") or ""),
                face=str(entry.get("face") or ""),
            )
        )
    return lines


def voice_path(root: Path, character_id: str, voice: str) -> Path | None:
    """这一句的语音文件；没有时为 None。`voice` 只认文件名，不认路径。"""
    if not voice or "/" in voice or "\\" in voice or voice.startswith("."):
        return None
    path = root / character_id / "voice" / voice
    return path if path.is_file() else None


def period_of(hour: int | None) -> str | None:
    """这个钟点适合的时段（本地时间）；不知道钟点时为 None，只从什么时候都能说的里挑。"""
    if hour is None or not 0 <= hour <= 23:
        return None
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    return "night"


def pick(lines: list[Line], hour: int | None = None, rng: random.Random | None = None) -> Line | None:
    """随机挑一句：这个时段能说的，加上什么时候都能说的。"""
    period = period_of(hour)
    candidates = [line for line in lines if line.period == "all" or line.period == period]
    if not candidates:
        return None
    return (rng or random).choice(candidates)
