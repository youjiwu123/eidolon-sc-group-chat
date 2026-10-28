"""剧情回放（功能 4）：`characters/story/` 的读取和 `/api/story` 的两个只读接口。

目录、单元文件和坏文件都是临时写的（`backend/scripts/build_story_data.py` 构建出来的那批数据在
`characters/story/`，测试不读它，免得数据一改测试就跟着动）。接口这半边照旧走整个后端：
`make_client` 建一个签好到的用户。场景表也在这里写一份最小的，`create_app` 读得到它。
"""

import json
from pathlib import Path

import pytest

from eidolon.story import empty_catalog, load_story_catalog
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import FakeLLM

SCENES = """
[[scenes]]
id = "lounge"
name = "事务所休息室"
hint = "沙发、茶水间"
image = "lounge.jpg"

[[behaviors]]
character = "*"
scene = "lounge"
text = "在休息室等人"
"""

HEADER = {
    "label": "W.I.N.G.編（樱木真乃）",
    "gist": "制作人在公园听见樱木真乃唱歌，劝她当偶像。",
    "shape": "2话路线短篇合集",
    "themes": ["成长", "自信"],
    "cast": ["mano"],
    "src": "browser",
    "unit": "route:W.I.N.G.編:mano",
    "group": "route-wing",
    "group_label": "W.I.N.G.編",
}

UNITS = [
    {
        "id": "route-wing-mano",
        "kind": "route",
        "name": "W.I.N.G.篇（樱木真乃）",
        "episodes": 2,
        **HEADER,
    },
    {
        "id": "scsp-s01",
        "kind": "scsp",
        "label": "闪耀色彩主线第一季",
        "name": "主线第一季",
        "gist": "三人结成。",
        "shape": "2话主线剧情",
        "themes": ["结成"],
        "cast": ["mano", "hiori"],
        "src": "scsp",
        "unit": "s01",
        "group": None,
        "group_label": None,
        "episodes": 2,
    },
    {
        "id": "card-mano-0a1b2c3d4e5f",
        "kind": "card",
        "label": "P卡剧情・樱木真乃（【ナチュラルモード】櫻木真乃）",
        "name": "自然模式 樱木真乃",
        "gist": "真乃和制作人下班后逛街。",
        "shape": "1话P卡剧情",
        "themes": ["日常"],
        "cast": ["mano"],
        "src": "browser",
        "unit": "P卡剧情:【ナチュラルモード】櫻木真乃:mano",
        "group": "char-mano",
        "group_label": "樱木真乃",
        "episodes": 1,
    },
]

CHAPTERS = {
    "route-wing-mano": [
        {
            "id": "produce_communication_auditions/500100100011",
            "title": "试镜合格实感",
            "ja": "オーディション後 勝利①",
            "summary": "试镜合格后，制作人向她道喜。",
            "cast": ["mano"],
        },
        {
            "id": "produce_communication_auditions/500100100021",
            "title": "第一次的舞台",
            "ja": "オーディション後 勝利②",
            "summary": "她在舞台上第一次唱自己的歌。",
            "cast": ["mano"],
        },
    ],
    "scsp-s01": [
        {
            "id": "s01_01010000",
            "title": "三人的相遇",
            "summary": "三个女孩在事务所第一次碰面。",
            "cast": ["mano", "hiori"],
            "episodes": [
                {"id": "s01_01010000_00", "title": "被看见的歌声", "cast": ["mano"]},
                {"id": "s01_01010000_01", "title": "窗边的邀请", "cast": ["mano", "hiori"]},
            ],
        }
    ],
    "card-mano-0a1b2c3d4e5f": [
        {
            "id": "produce_events/200100301",
            "title": "背包店的选择",
            "ja": "ショッピング日和",
            "summary": "真乃在包店看中一只棕色背包。",
            "cast": ["mano"],
        }
    ],
}


def story_files(path: Path, units: list[dict] | None = None) -> Path:
    """写出一个能读的剧情目录：索引加每个单元自己的文件。"""
    path.mkdir(parents=True, exist_ok=True)
    units = UNITS if units is None else units
    (path / "index.json").write_text(json.dumps(units, ensure_ascii=False), encoding="utf-8")
    for unit in units:
        chapters = CHAPTERS.get(unit["id"], [])
        detail = {**unit, "chapters": chapters}
        (path / f'{unit["id"]}.json').write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def scenes(characters: CharacterConfig) -> None:
    """`create_app` 读场景表；这里只写一份最小的，和剧情无关。"""
    characters.write("scenes.toml", SCENES)


@pytest.fixture
def story_dir(characters: CharacterConfig) -> Path:
    return story_files(characters.directory / "story")


def test_the_catalog_reads_its_units_in_order(story_dir: Path) -> None:
    catalog = load_story_catalog(story_dir)

    assert [unit.id for unit in catalog.units] == ["route-wing-mano", "scsp-s01", "card-mano-0a1b2c3d4e5f"]
    assert catalog.total_episodes == 5
    assert catalog.unit("card-mano-0a1b2c3d4e5f").group_label == "樱木真乃"
    assert catalog.unit("route-wing-mano").label == "W.I.N.G.編（樱木真乃）"
    assert catalog.unit("nope") is None


def test_the_listing_gives_every_unit_and_its_episode_count(story_dir: Path) -> None:
    listing = load_story_catalog(story_dir).listing()

    assert listing["total_episodes"] == 5
    assert listing["units"][0] == {
        "id": "route-wing-mano",
        "kind": "route",
        "name": "W.I.N.G.篇（樱木真乃）",
        "episodes": 2,
        "group": "route-wing",
        "group_label": "W.I.N.G.編",
    }
    # 列表里不带总述和每一话：那是单元自己的文件里的事。
    assert set(listing["units"][0]) == {"id", "kind", "name", "episodes", "group", "group_label"}


def test_a_unit_reads_its_chapters(story_dir: Path) -> None:
    detail = load_story_catalog(story_dir).detail("route-wing-mano")

    assert detail is not None
    assert [chapter.title for chapter in detail.chapters] == ["试镜合格实感", "第一次的舞台"]
    assert detail.chapters[0].ja == "オーディション後 勝利①"
    assert detail.chapters[0].cast == ("mano",)
    shown = detail.as_json()
    assert shown["id"] == "route-wing-mano"
    assert shown["episodes"] == 2
    assert shown["chapters"][0] == {
        "id": "produce_communication_auditions/500100100011",
        "title": "试镜合格实感",
        "summary": "试镜合格后，制作人向她道喜。",
        "cast": ["mano"],
        "ja": "オーディション後 勝利①",
    }


def test_an_scsp_chapter_gathers_its_episodes(story_dir: Path) -> None:
    detail = load_story_catalog(story_dir).detail("scsp-s01")

    assert detail is not None
    [chapter] = detail.chapters
    assert chapter.id == "s01_01010000"
    assert chapter.ja == ""
    assert [episode.title for episode in chapter.episodes] == ["被看见的歌声", "窗边的邀请"]
    shown = detail.as_json()["chapters"][0]
    assert "ja" not in shown
    assert shown["episodes"][1] == {"id": "s01_01010000_01", "title": "窗边的邀请", "cast": ["mano", "hiori"]}


def test_an_unknown_unit_reads_as_none(story_dir: Path) -> None:
    assert load_story_catalog(story_dir).detail("nope") is None


def test_a_missing_index_says_which_file_to_build(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="缺少剧情索引") as raised:
        load_story_catalog(tmp_path / "story")
    assert "build_story_data.py" in str(raised.value)


def test_a_broken_index_says_which_file(tmp_path: Path) -> None:
    story_files(tmp_path)
    (tmp_path / "index.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="读不了"):
        load_story_catalog(tmp_path)


def test_an_index_that_is_not_a_list_is_refused(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text('{"units": []}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="单元列表"):
        load_story_catalog(tmp_path)


def test_an_entry_that_says_nothing_about_its_id_is_refused(tmp_path: Path) -> None:
    story_files(tmp_path)
    (tmp_path / "index.json").write_text(json.dumps([{"kind": "route"}]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="缺少 id"):
        load_story_catalog(tmp_path)


def test_a_unit_without_its_file_is_refused_when_loading(tmp_path: Path) -> None:
    story_files(tmp_path)
    (tmp_path / "card-mano-0a1b2c3d4e5f.json").unlink()

    with pytest.raises(RuntimeError, match="没有文件"):
        load_story_catalog(tmp_path)


def test_a_broken_unit_file_says_which_file(tmp_path: Path) -> None:
    story_files(tmp_path)
    (tmp_path / "route-wing-mano.json").write_text("{not json", encoding="utf-8")
    catalog = load_story_catalog(tmp_path)

    with pytest.raises(RuntimeError, match="剧情单元"):
        catalog.detail("route-wing-mano")


def test_a_unit_file_that_is_not_the_unit_is_refused(tmp_path: Path) -> None:
    story_files(tmp_path)
    detail = {**UNITS[0], "id": "someone-else", "chapters": []}
    (tmp_path / "route-wing-mano.json").write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    catalog = load_story_catalog(tmp_path)

    with pytest.raises(RuntimeError, match="对不上"):
        catalog.detail("route-wing-mano")


def test_an_empty_catalog_has_nothing_and_no_episodes(tmp_path: Path) -> None:
    catalog = empty_catalog(tmp_path)

    assert catalog.units == ()
    assert catalog.total_episodes == 0
    assert catalog.detail("route-wing-mano") is None


async def test_the_api_lists_every_unit(make_client: ClientFactory, story_dir: Path) -> None:
    client = make_client(FakeLLM())

    res = await client.get("/api/story")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total_episodes"] == 5
    assert [unit["id"] for unit in body["units"]] == [
        "route-wing-mano",
        "scsp-s01",
        "card-mano-0a1b2c3d4e5f",
    ]
    assert body["units"][1]["kind"] == "scsp"
    assert body["units"][1]["group"] is None


async def test_the_api_serves_one_unit(make_client: ClientFactory, story_dir: Path) -> None:
    client = make_client(FakeLLM())

    res = await client.get("/api/story/scsp-s01")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["label"] == "闪耀色彩主线第一季"
    assert body["themes"] == ["结成"]
    assert body["cast"] == ["mano", "hiori"]
    assert body["chapters"][0]["episodes"][0]["title"] == "被看见的歌声"


async def test_the_api_answers_404_for_an_unknown_unit(make_client: ClientFactory, story_dir: Path) -> None:
    client = make_client(FakeLLM())

    res = await client.get("/api/story/nope")

    assert res.status_code == 404, res.text


async def test_the_api_needs_a_signed_in_user(make_client: ClientFactory, story_dir: Path) -> None:
    client = make_client(FakeLLM(), user=None)

    assert (await client.get("/api/story")).status_code == 401
    assert (await client.get("/api/story/route-wing-mano")).status_code == 401


async def test_a_deployment_without_story_data_lists_nothing(make_client: ClientFactory) -> None:
    # 不请求 story_dir：这个部署还没有构建剧情数据，接口空着，但后端照常起来。
    client = make_client(FakeLLM())

    res = await client.get("/api/story")

    assert res.status_code == 200, res.text
    assert res.json() == {"total_episodes": 0, "units": []}
