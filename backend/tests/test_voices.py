"""她的原声（功能 1）：原声表怎么读、回复里怎么匹配、音频怎么送、消息里怎么挂。"""

import json
from pathlib import Path

import pytest

from eidolon.voices import (
    VoiceLibrary,
    audio_file,
    audio_url,
    load_voices,
)
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import FakeLLM
from tests.test_text_turn import send_turn, start_conversation

SCENES = """
[[scenes]]
id = "sky"
name = "天空"
hint = "外面"
image = "sky.jpg"
"""


@pytest.fixture(autouse=True)
def scenes(characters: CharacterConfig) -> None:
    """`create_app` 读场景表；这里只写一份最小的，和原声无关。"""
    characters.write("scenes.toml", SCENES)


def voice(**fields: object) -> dict:
    """一条原声，字段可以改；默认是真乃的一句名台词。"""
    line: dict = {
        "character": "mano",
        "story": "s01_01010000_00",
        "line": "0030",
        "text": "今日は集まってくれてありがとう、みんな",
        "subtitle": "谢谢你们今天聚在一起",
        "audio": "voices/mano/s01_01010000_00_0030.mp3",
        "seconds": 4.2,
        "kind": "quote",
    }
    line.update(fields)
    return line


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    return json.dumps(str(value), ensure_ascii=False)


def write_voices(directory: Path, lines: list[dict]) -> Path:
    """把几条原声写成 `voices.toml`，返回它的路径。"""
    directory.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(
        "[[line]]\n" + "\n".join(f"{key} = {_toml(value)}" for key, value in line.items())
        for line in lines
    )
    path = directory / "voices.toml"
    path.write_text(body + "\n", encoding="utf-8")
    return path


def write_audio(directory: Path, relative: str, data: bytes = b"ID3 fake mp3") -> Path:
    """在 `characters/` 下放一段音频（表里的 `audio` 那一段）。"""
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---- 读表 -------------------------------------------------------------------


def test_a_catalog_is_read_and_grouped_by_character(tmp_path: Path) -> None:
    path = write_voices(
        tmp_path,
        [
            voice(),
            voice(character="amana", line="0030", text="おはようございます、プロデューサーさん"),
            voice(kind="birthday", story="s20_11400100_01", line="0060"),
        ],
    )

    catalog = load_voices(path)

    assert [line.character for line in catalog.lines] == ["mano", "amana", "mano"]
    assert catalog.characters == ("mano", "amana")
    assert [line.line for line in catalog.of_character("mano")] == ["0030", "0060"]
    assert [line.line for line in catalog.of_character("mano", "birthday")] == ["0060"]
    assert catalog.of_character("kogane") == ()
    # 中文字幕可以没有；audio_url 按表里的相对路径拼出来。
    assert catalog.lines[0].subtitle == "谢谢你们今天聚在一起"
    assert audio_url(catalog.lines[0]) == "/api/voices/voices/mano/s01_01010000_00_0030.mp3"
    assert catalog.lines[0].seconds == 4.2


def test_subtitle_may_be_left_out(tmp_path: Path) -> None:
    line = voice()
    del line["subtitle"]
    catalog = load_voices(write_voices(tmp_path, [line]))

    assert catalog.lines[0].subtitle == ""


def test_a_missing_table_says_which_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="缺少原声表"):
        load_voices(tmp_path / "voices.toml")


@pytest.mark.parametrize(
    ("name", "body", "match"),
    [
        ("broken-toml", "[[line]\ncharacter = \"mano\"", "读不了"),
        ("no-character", '[[line]]\nstory = "s"\nline = "1"\ntext = "あ"\naudio = "voices/a.mp3"', "character"),
        ("no-text", '[[line]]\ncharacter = "mano"\nstory = "s"\nline = "1"\naudio = "voices/a.mp3"', "text"),
        (
            "unknown-kind",
            '[[line]]\ncharacter = "mano"\nstory = "s"\nline = "1"\ntext = "あいうえおか"\n'
            'audio = "voices/a.mp3"\nkind = "shout"',
            "kind",
        ),
        (
            "audio-elsewhere",
            '[[line]]\ncharacter = "mano"\nstory = "s"\nline = "1"\ntext = "あいうえおか"\n'
            'audio = "sheets/mano.md"',
            "voices/",
        ),
        (
            "audio-traversal",
            '[[line]]\ncharacter = "mano"\nstory = "s"\nline = "1"\ntext = "あいうえおか"\n'
            'audio = "voices/../characters.toml"',
            "上下级",
        ),
    ],
)
def test_a_broken_table_says_what_is_wrong(tmp_path: Path, name: str, body: str, match: str) -> None:
    path = tmp_path / "voices.toml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(RuntimeError, match=match):
        load_voices(path)


def test_a_broken_table_reads_as_empty_in_the_library(tmp_path: Path) -> None:
    path = tmp_path / "voices.toml"
    path.write_text("{not toml", encoding="utf-8")

    assert VoiceLibrary(path).catalog().lines == ()


def test_the_library_rereads_a_changed_table(tmp_path: Path) -> None:
    path = write_voices(tmp_path, [voice()])
    library = VoiceLibrary(path)
    assert len(library.catalog().lines) == 1

    write_voices(tmp_path, [voice(), voice(line="0040")])

    assert len(library.catalog().lines) == 2


def test_no_table_anywhere_is_empty(tmp_path: Path) -> None:
    assert VoiceLibrary(tmp_path / "voices.toml").catalog().lines == ()


# ---- 匹配 -------------------------------------------------------------------


def test_match_finds_the_longest_lines_the_reply_contains(tmp_path: Path) -> None:
    short = voice(text="ほわっ", line="0001")
    long = voice(text="今日は集まってくれてありがとう、みんな", line="0002")
    other = voice(text="実は、３人に大事な話があるんだ", line="0003")
    catalog = load_voices(write_voices(tmp_path, [short, long, other]))

    matched = catalog.match("そうだ、実は、３人に大事な話があるんだ。今日は集まってくれてありがとう、みんな。")

    # 长的那句在前。
    assert [line.line for line in matched] == ["0002", "0003"]
    # 太短的那句不参与。
    assert catalog.match("ほわっ") == ()


def test_match_ignores_newlines_on_both_sides(tmp_path: Path) -> None:
    line = voice(text="今日は集まってくれて\nありがとう、みんな")
    catalog = load_voices(write_voices(tmp_path, [line]))

    assert len(catalog.match("今日は集まってくれてありがとう、みんな！")) == 1
    assert len(catalog.match("今日は集まってくれて\nありがとう、みんな")) == 1


def test_match_takes_at_most_two_and_skips_duplicates(tmp_path: Path) -> None:
    first = voice(text="おはようございます、プロデューサーさん", line="0001")
    second = voice(text="今日もいい一日にしましょうね", line="0002")
    third = voice(text="またあとで会いましょう", line="0003")
    same = voice(text="おはようございます、プロデューサーさん", line="0004")
    catalog = load_voices(write_voices(tmp_path, [first, second, third, same]))

    matched = catalog.match(
        "おはようございます、プロデューサーさん。今日もいい一日にしましょうね。またあとで会いましょう。"
    )

    assert len(matched) == 2
    assert [line.line for line in matched] == ["0001", "0002"]


def test_match_without_a_reply_is_empty(tmp_path: Path) -> None:
    catalog = load_voices(write_voices(tmp_path, [voice()]))

    assert catalog.match(None) == ()
    assert catalog.match("") == ()


# ---- 音频文件 ----------------------------------------------------------------


def test_the_audio_file_stays_under_the_characters_directory(tmp_path: Path) -> None:
    characters = tmp_path / "characters"
    audio = write_audio(characters, "voices/mano/a.mp3")
    (characters / "characters.toml").write_text("", encoding="utf-8")

    assert audio_file(characters, "voices/mano/a.mp3") == audio
    for unsafe in (
        "../characters.toml",
        "voices/../characters.toml",
        "voices/mano/../../characters.toml",
        "sheets/mano.md",
        "voices/mano/nope.mp3",
        "voices\\mano\\a.mp3",
        "/etc/passwd",
        "C:/Windows/win.ini",
    ):
        assert audio_file(characters, unsafe) is None, unsafe


def test_audio_url_keeps_slashes_and_escapes_the_rest(tmp_path: Path) -> None:
    line = voice(audio="voices/mano/第 1 話.mp3")
    catalog = load_voices(write_voices(tmp_path, [line]))

    assert audio_url(catalog.lines[0]) == "/api/voices/voices/mano/%E7%AC%AC%201%20%E8%A9%B1.mp3"


# ---- 接口 -------------------------------------------------------------------


async def test_the_api_lists_her_voices_and_their_audio_url(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(
        characters.directory,
        [voice(), voice(character="amana", text="おはようございます、プロデューサーさん")],
    )
    client = make_client(FakeLLM())

    res = await client.get("/api/characters/mano/voices")

    assert res.status_code == 200
    [listed] = res.json()["voices"]
    assert listed == {
        "story": "s01_01010000_00",
        "line": "0030",
        "text": "今日は集まってくれてありがとう、みんな",
        "subtitle": "谢谢你们今天聚在一起",
        "audio_url": "/api/voices/voices/mano/s01_01010000_00_0030.mp3",
        "seconds": 4.2,
        "kind": "quote",
    }


async def test_the_api_filters_by_kind(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(
        characters.directory,
        [voice(), voice(kind="birthday", story="s20_11400100_01", line="0060")],
    )
    client = make_client(FakeLLM())

    birthdays = await client.get("/api/characters/mano/voices?kind=birthday")
    quotes = await client.get("/api/characters/mano/voices?kind=quote")

    assert [line["kind"] for line in birthdays.json()["voices"]] == ["birthday"]
    assert [line["kind"] for line in quotes.json()["voices"]] == ["quote"]
    refused = await client.get("/api/characters/mano/voices?kind=shout")
    assert refused.status_code == 422


async def test_all_voices_group_by_character(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(
        characters.directory,
        [voice(), voice(character="amana", text="おはようございます、プロデューサーさん")],
    )
    client = make_client(FakeLLM())

    res = await client.get("/api/voices?kind=quote")

    assert [line["character"] for line in res.json()["voices"]] == ["mano", "amana"]
    assert res.json()["voices"][0]["audio_url"].startswith("/api/voices/voices/mano/")


async def test_an_unknown_character_has_no_voices_route(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [voice()])
    client = make_client(FakeLLM())

    assert (await client.get("/api/characters/ghost/voices")).status_code == 404


async def test_without_a_voice_table_she_has_none(make_client: ClientFactory) -> None:
    client = make_client(FakeLLM())

    res = await client.get("/api/characters/mano/voices")

    assert res.status_code == 200
    assert res.json() == {"voices": []}
    assert (await client.get("/api/voices")).json() == {"voices": []}


async def test_the_api_serves_the_audio(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_audio(characters.directory, "voices/mano/a.mp3", b"ID3 real enough")
    write_voices(characters.directory, [voice(audio="voices/mano/a.mp3")])
    client = make_client(FakeLLM())

    res = await client.get("/api/voices/voices/mano/a.mp3")

    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert "max-age" in res.headers["cache-control"]
    assert res.content == b"ID3 real enough"


@pytest.mark.parametrize(
    "path",
    [
        "/api/voices/characters.toml",
        "/api/voices/voices/%2E%2E/characters.toml",
        "/api/voices/voices/mano/%2E%2E/%2E%2E/characters.toml",
        "/api/voices/voices/mano/nope.mp3",
        "/api/voices/../characters.toml",
    ],
)
async def test_the_api_will_not_serve_anything_but_her_voice_files(
    make_client: ClientFactory, characters: CharacterConfig, path: str
) -> None:
    write_audio(characters.directory, "voices/mano/a.mp3")
    write_voices(characters.directory, [voice(audio="voices/mano/a.mp3")])
    client = make_client(FakeLLM())

    res = await client.get(path)

    assert res.status_code == 404, path


async def test_a_reply_carries_the_original_take_it_says_and_history_has_it_too(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_audio(characters.directory, "voices/mano/a.mp3")
    write_voices(characters.directory, [voice(audio="voices/mano/a.mp3")])
    reply = "<ja>今日は集まってくれてありがとう、みんな。それじゃあ始めようか</ja><zh>谢谢你们聚在一起。那我们就开始吧</zh>"
    client = make_client(FakeLLM(reply))
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "在吗")
    done = next(event for event in events if event["type"] == "done")

    assert done["message"]["voice"] == {
        "audio_url": "/api/voices/voices/mano/a.mp3",
        "text": "今日は集まってくれてありがとう、みんな",
        "subtitle": "谢谢你们今天聚在一起",
        "seconds": 4.2,
    }
    history = (await client.get(f"/api/conversations/{conversation}/messages")).json()
    assert [entry["voice"] for entry in history] == [None, done["message"]["voice"]]


async def test_a_reply_that_says_none_of_them_has_no_take(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [voice()])
    client = make_client(FakeLLM("<ja>こんにちは</ja><zh>你好</zh>"))
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "在吗")

    done = next(event for event in events if event["type"] == "done")
    assert done["message"]["voice"] is None


async def test_without_a_voice_table_a_reply_carries_no_take(
    make_client: ClientFactory,
) -> None:
    client = make_client(FakeLLM("<ja>今日は集まってくれてありがとう、みんな</ja><zh>谢谢你们</zh>"))
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "在吗")

    done = next(event for event in events if event["type"] == "done")
    assert done["message"]["voice"] is None
    history = (await client.get(f"/api/conversations/{conversation}/messages")).json()
    assert [entry["voice"] for entry in history] == [None, None]
