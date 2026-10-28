"""好感度各档的提示词（`affinity_prompts`）：没有文件时用内置的原文，文件里只写要改的那几条，
写坏了（坏 TOML、id 不认识、缺 prompt、shared 不是表）读的时候就报错、说清楚是哪个文件；
后台「提示词」页保存前也用同一套解析验一遍。"""

from pathlib import Path

import pytest

from eidolon.affinity_prompts import (
    AFFINITY_FILE,
    DEFAULT_PROMPTS,
    FONDNESS_TIERS,
    TIERS,
    load_affinity_prompts,
    parse_affinity_prompts,
    render_affinity_prompts,
)

REPO = Path(__file__).parents[2] / "characters" / AFFINITY_FILE


def test_without_a_file_the_built_in_words_are_used(tmp_path: Path):
    assert load_affinity_prompts(tmp_path / AFFINITY_FILE) == DEFAULT_PROMPTS


def test_the_repository_file_has_every_tier():
    """仓库里那份是部署一开始拿到的；它可以在后台改，所以只查结构：五档、三句甜度和三句共用都在，
    而且都不是空的。"""
    prompts = load_affinity_prompts(REPO)

    assert set(prompts.tiers) == set(TIERS)
    assert set(prompts.fondness) == set(FONDNESS_TIERS)
    assert all(text.strip() for text in (*prompts.tiers.values(), *prompts.fondness.values()))
    assert prompts.in_her_own_way.strip() and prompts.sweet_within_bounds.strip()
    assert prompts.whatever_the_tier.strip()


def test_the_rendered_file_reads_back_as_the_same_words(tmp_path: Path):
    path = tmp_path / AFFINITY_FILE
    path.write_text(render_affinity_prompts(), encoding="utf-8")

    assert load_affinity_prompts(path) == DEFAULT_PROMPTS


def test_a_file_may_change_only_the_tiers_it_names(tmp_path: Path):
    text = (
        '[[tiers]]\nid = "love"\nprompt = "改过的 love 档。"\n\n'
        '[[fondness]]\nid = "close"\nprompt = "改过的 close 甜度。"\n\n'
        '[shared]\nwhatever_the_tier = "改过的兜底。"\n'
    )

    prompts = parse_affinity_prompts(text, tmp_path / AFFINITY_FILE)

    assert prompts.tiers["love"] == "改过的 love 档。"
    assert prompts.fondness["close"] == "改过的 close 甜度。"
    assert prompts.whatever_the_tier == "改过的兜底。"
    # 没写的那几条照旧。
    assert prompts.tiers["cold"] == DEFAULT_PROMPTS.tiers["cold"]
    assert prompts.fondness["love"] == DEFAULT_PROMPTS.fondness["love"]
    assert prompts.in_her_own_way == DEFAULT_PROMPTS.in_her_own_way


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("[[tiers]\nid = \"love\"", "读不了"),
        ('[[tiers]]\nid = "trust"\nprompt = "x"\n', "id 只能是"),
        ('[[tiers]]\nid = "love"\nprompt = "x"\n[[tiers]]\nid = "love"\nprompt = "y"\n', "重复"),
        ('[[tiers]]\nid = "love"\n', "缺少 prompt"),
        ('[[tiers]]\nid = "love"\nprompt = "  "\n', "缺少 prompt"),
        ("[[fondness]]\nid = \"cold\"\nprompt = \"x\"\n", "id 只能是"),
        ("[shared]\nin_her_own_way = \"\"\n", "非空"),
        ("[shared]\nin_her_own_way = 3\n", "非空"),
    ],
)
def test_a_table_that_would_not_load_is_refused(tmp_path: Path, text: str, said: str):
    with pytest.raises(RuntimeError, match=said):
        parse_affinity_prompts(text, tmp_path / AFFINITY_FILE)


def test_every_tier_and_fondness_tier_is_written():
    assert set(DEFAULT_PROMPTS.tiers) == set(TIERS)
    assert set(DEFAULT_PROMPTS.fondness) == set(FONDNESS_TIERS)
    assert "trust" not in DEFAULT_PROMPTS.tiers  # 信任档没有自己的话
