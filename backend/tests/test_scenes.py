"""通话场景（`scenes.py`）：场景表读得对、判断模型挑的场景落在表里、冷启动按她的预设行为走。

判断模型是假的：`scenes.judge` 只拿它吐出来的那行 JSON，不碰网络。
"""

from pathlib import Path

import pytest

from eidolon.scenes import (
    Catalog,
    Picked,
    judge,
    load_scenes,
    parse,
    pick_by_behavior,
)

TOML = """
[[scenes]]
id = "lounge"
name = "事务所休息室"
hint = "沙发、茶水间"
image = "lounge.jpg"

[[scenes]]
id = "studio"
name = "练习室"
hint = "练舞、镜子"
image = "studio.jpg"

[[behaviors]]
character = "*"
scene = "lounge"
text = "在休息室等人"

[[behaviors]]
character = "mano"
scene = "studio"
text = "在练习室练舞"
"""


def written(tmp_path: Path, text: str = TOML) -> Path:
    path = tmp_path / "scenes.toml"
    path.write_text(text, encoding="utf-8")
    return path


def catalog(tmp_path: Path) -> Catalog:
    return load_scenes(written(tmp_path))


class Chat:
    """A chat service that answers with what it was given, in one chunk."""

    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def stream(self, messages, tools=(), *, forbid_calls=False):
        yield self.answer


def test_the_catalog_reads_its_scenes_and_behaviors(tmp_path: Path) -> None:
    scenes = catalog(tmp_path)

    assert [scene.name for scene in scenes.scenes] == ["事务所休息室", "练习室"]
    assert scenes.scene("studio").hint == "练舞、镜子"
    assert len(scenes.behaviors) == 2


def test_a_behavior_may_only_name_a_scene_in_the_table(tmp_path: Path) -> None:
    broken = TOML.replace('scene = "studio"\ntext = "在练习室练舞"', 'scene = "moon"\ntext = "在月球"')

    with pytest.raises(RuntimeError, match="moon"):
        load_scenes(written(tmp_path, broken))


def test_her_own_behavior_comes_before_the_shared_ones(tmp_path: Path) -> None:
    scenes = catalog(tmp_path)

    picked = pick_by_behavior(scenes, "mano")
    shared = pick_by_behavior(scenes, "kogane")

    assert picked is not None and picked.scene.id == "studio"
    assert picked.source == "behavior"
    assert shared is not None and shared.scene.id == "lounge"


def test_a_scene_is_matched_by_its_name_and_an_invented_one_is_refused(tmp_path: Path) -> None:
    scenes = catalog(tmp_path)

    # `parse` 现在给的是（场景, 理由, 开场白日语, 开场白字幕）：开场白写不出来时后两项是空的。
    assert parse('{"scene": "练习室", "why": "在练舞"}', scenes) == (
        scenes.scene("studio"),
        "在练舞",
        "",
        "",
    )
    assert parse(
        '{"scene": "练习室", "why": "在练舞", "opener_ja": "はい、もしもし", "opener_zh": "喂，是我"}',
        scenes,
    ) == (scenes.scene("studio"), "在练舞", "はい、もしもし", "喂，是我")
    assert parse("我觉得她在事务所", scenes) is None
    assert parse('{"scene": "月球"}', scenes) is None


async def test_the_judge_gives_back_the_scene_the_model_named(tmp_path: Path) -> None:
    scenes = catalog(tmp_path)

    picked = await judge(scenes, Chat('{"scene": "事务所休息室", "why": "沙发"}'), None, [("制作人", "在事务所吗？")])

    assert isinstance(picked, Picked)
    assert picked.scene.id == "lounge"
    assert picked.source == "chat"
    assert picked.why == "沙发"


async def test_the_judge_says_nothing_when_the_model_answers_nonsense(tmp_path: Path) -> None:
    scenes = catalog(tmp_path)

    assert await judge(scenes, Chat("我不知道"), None, [("制作人", "喂？")]) is None


def test_no_behavior_at_all_still_falls_back_to_a_scene(tmp_path: Path) -> None:
    scenes = load_scenes(written(tmp_path, TOML.split("[[behaviors]]")[0]))

    assert pick_by_behavior(scenes, "mano") is None
    assert scenes.fallback().id == "lounge"
