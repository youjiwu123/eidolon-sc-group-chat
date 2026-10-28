"""她的小台词（DESIGN.md「对话页的立绘小人」）：`scripts/import-sc-time-small-talk.py` 整理出来的
那份语料，读得出来、按时段挑、找得到每句的录音。"""

import json
from pathlib import Path

from eidolon import small_talk


def corpus(root: Path, character: str, lines: list[dict], voices: list[str]) -> Path:
    directory = root / character
    (directory / "voice").mkdir(parents=True)
    for voice in voices:
        (directory / "voice" / voice).write_bytes(b"RIFF")
    (directory / "lines.json").write_text(
        json.dumps({"lines": lines}, ensure_ascii=False), encoding="utf-8"
    )
    return root


def line(id: str, period: str = "all", voice: str | None = None, mood: str = "happy") -> dict:
    return {"id": id, "ja": f"せりふ {id}", "zh": f"台词 {id}", "voice": voice or f"{id}.m4a", "mood": mood, "period": period}


def test_her_lines_are_read_with_their_voice_and_mood(tmp_path: Path) -> None:
    root = corpus(tmp_path, "mano", [line("1"), line("2", mood="shy")], ["1.m4a", "2.m4a"])
    lines = small_talk.load(root, "mano")
    assert [said.id for said in lines] == ["1", "2"]
    assert lines[1].zh == "台词 2"
    assert lines[1].mood == "shy"
    assert small_talk.voice_path(root, "mano", "2.m4a") == root / "mano" / "voice" / "2.m4a"


def test_a_character_without_lines_or_with_a_broken_file_says_nothing(tmp_path: Path) -> None:
    assert small_talk.load(tmp_path, "mano") == []
    (tmp_path / "mano").mkdir()
    (tmp_path / "mano" / "lines.json").write_text("{oops", encoding="utf-8")
    assert small_talk.load(tmp_path, "mano") == []
    assert small_talk.voice_path(tmp_path, "mano", "../etc/passwd") is None


def test_a_line_at_this_hour_is_picked_before_one_for_another_time(tmp_path: Path) -> None:
    root = corpus(
        tmp_path,
        "mano",
        [line("all"), line("morning", "morning"), line("night", "night")],
        ["all.m4a", "morning.m4a", "night.m4a"],
    )
    lines = small_talk.load(root, "mano")
    morning = [small_talk.pick(lines, 8).id for _ in range(40)]
    assert set(morning) <= {"all", "morning"} and "morning" in morning
    evening = [small_talk.pick(lines, 22).id for _ in range(40)]
    assert set(evening) <= {"all", "night"} and "night" in evening
    # 不知道钟点时就只从什么时候都能说的里挑
    assert {small_talk.pick(lines, None).id for _ in range(40)} == {"all"}


def test_nothing_to_pick_is_none(tmp_path: Path) -> None:
    assert small_talk.pick([], 9) is None
