"""生日原声彩蛋（功能 2）：今天是不是制作人的生日，是的话给谁听、一天只给一次。"""

from datetime import UTC, datetime, timedelta

import pytest

from eidolon.birthday import BirthdayTriggers, by_source, is_producer_birthday, pick_birthday
from eidolon.characters import Character
from eidolon.producer import Birthday, ProducerProfile
from eidolon.voices import VoicesCatalog, VoiceLine
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import FakeClock, FakeLLM
from tests.test_voices import SCENES, write_audio, write_voices

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # 上海 9 月 25 日 20:00


@pytest.fixture(autouse=True)
def scenes(characters: CharacterConfig) -> None:
    """`create_app` 读场景表；这里只写一份最小的，和生日无关。"""
    characters.write("scenes.toml", SCENES)


def birthday_line(character: str = "mano", story: str = "s20_11400100_01", line: str = "0030", text: str = "誕生日おめでとう。素敵な一年になりますように") -> dict:
    return {
        "character": character,
        "story": story,
        "line": line,
        "text": text,
        "subtitle": "生日快乐。愿你拥有美好的一年。",
        "audio": f"voices/{character}/{story}_{line}.mp3",
        "seconds": 3.8,
        "kind": "birthday",
    }


def quote(character: str = "mano") -> dict:
    return {
        "character": character,
        "story": "s01_01010000_00",
        "line": "0030",
        "text": "今日は集まってくれてありがとう、みんな",
        "subtitle": "谢谢你们今天聚在一起",
        "audio": f"voices/{character}/s01_01010000_00_0030.mp3",
        "seconds": 4.2,
        "kind": "quote",
    }


async def set_birthday(
    client, month: int, day: int, timezone: str | None = None
) -> None:
    res = await client.put(
        "/api/profile",
        json={
            "form_of_address": None,
            "gender": None,
            "timezone": timezone,
            "birthday": {"month": month, "day": day},
        },
    )
    assert res.status_code == 200, res.text


# ---- 判断 -------------------------------------------------------------------


def test_the_birthday_is_counted_where_the_producer_is() -> None:
    profile = ProducerProfile(birthday=Birthday(9, 25))

    assert is_producer_birthday(profile, NOW)
    assert not is_producer_birthday(profile, NOW + timedelta(days=1))
    assert not is_producer_birthday(ProducerProfile(), NOW)


def test_february_29_falls_on_february_28_in_common_years() -> None:
    profile = ProducerProfile(birthday=Birthday(2, 29))

    assert is_producer_birthday(profile, datetime(2028, 2, 29, 12, tzinfo=UTC))
    assert is_producer_birthday(profile, datetime(2027, 2, 28, 12, tzinfo=UTC))
    assert not is_producer_birthday(profile, datetime(2027, 3, 1, 12, tzinfo=UTC))


def test_each_user_is_claimed_once_a_day() -> None:
    triggers = BirthdayTriggers()

    assert triggers.claim("someone", NOW.date()) is True
    assert triggers.claim("someone", NOW.date()) is False
    assert triggers.claim("someone", NOW.date() + timedelta(days=1)) is True
    assert triggers.claim("other", NOW.date()) is True


def line(character: str, text: str, line: str = "0030", story: str = "s20_11400100_01") -> VoiceLine:
    return VoiceLine(
        character=character,
        story=story,
        line=line,
        text=text,
        subtitle="",
        audio=f"voices/{character}/{story}_{line}.mp3",
        seconds=1.0,
        kind="birthday",
    )


def test_the_character_with_the_most_characters_is_chosen_and_her_lines_sorted() -> None:
    catalog = VoicesCatalog(
        (
            line("mano", "ありがとう", line="0060"),
            line("amana", "お誕生日、おめでとうございます。素敵な一年になりますように", line="0030"),
            line("mano", "誕生日おめでとう", line="0030"),
            line("amana", "今日は特別な日ですね", line="0060"),
        )
    )
    characters = {
        "mano": _character("mano"),
        "amana": _character("amana"),
    }

    picked = pick_birthday(catalog, characters)

    assert picked is not None
    assert picked.character.id == "amana"
    assert [voice_line.line for voice_line in picked.lines] == ["0030", "0060"]


def test_no_birthday_lines_is_nobody() -> None:
    assert pick_birthday(VoicesCatalog(), {"mano": _character("mano")}) is None


def test_her_lines_are_ordered_by_story_and_their_number() -> None:
    catalog = VoicesCatalog(
        (
            line("mano", "三", line="0100", story="s20_11400100_01"),
            line("mano", "二", line="0090", story="s20_11400100_01"),
            line("mano", "一", line="0030", story="s19_11400100_01"),
        )
    )

    picked = pick_birthday(catalog, {"mano": _character("mano")})

    assert picked is not None
    assert [one.line for one in picked.lines] == ["0030", "0090", "0100"]
    assert [one.line for one in sorted(picked.lines, key=by_source)] == ["0030", "0090", "0100"]


def _character(character_id: str) -> Character:
    return Character(
        id=character_id,
        name=character_id,
        intro="",
        voice_id="voice",
        sheet="",
        avatar=None,
        color="#ffbad6",
        name_zh=character_id,
    )


# ---- 接口 -------------------------------------------------------------------


async def test_not_the_birthday_without_a_profile(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [birthday_line()])
    client = make_client(FakeLLM(), clock=FakeClock(NOW))

    assert (await client.get("/api/birthday")).json() == {"active": False}


async def test_a_profile_without_a_birthday_gets_nothing(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [birthday_line()])
    client = make_client(FakeLLM(), clock=FakeClock(NOW))
    await client.put(
        "/api/profile",
        json={"form_of_address": None, "gender": None, "timezone": None, "birthday": None},
    )

    assert (await client.get("/api/birthday")).json() == {"active": False}


async def test_another_day_gets_nothing(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [birthday_line()])
    client = make_client(FakeLLM(), clock=FakeClock(NOW))
    await set_birthday(client, 9, 26)

    assert (await client.get("/api/birthday")).json() == {"active": False}


async def test_on_the_birthday_she_gives_her_lines_sorted(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_audio(characters.directory, "voices/mano/s20_11400100_01_0060.mp3")
    write_audio(characters.directory, "voices/mano/s20_11400100_01_0030.mp3")
    write_voices(
        characters.directory,
        [
            quote(),
            birthday_line(story="s20_11400100_01", line="0060", text="これからも、ずっと一緒にいようね"),
            birthday_line(story="s20_11400100_01", line="0030"),
        ],
    )
    client = make_client(FakeLLM(), clock=FakeClock(NOW))
    await set_birthday(client, 9, 25)

    res = await client.get("/api/birthday")

    assert res.status_code == 200
    body = res.json()
    assert body["active"] is True
    assert body["character"] == {
        "id": "mano",
        "name": "櫻木真乃",
        "name_zh": None,
        "color": "#ffbad6",
        "avatar_url": "/api/characters/mano/avatar",
    }
    assert [one["text"] for one in body["lines"]] == [
        "誕生日おめでとう。素敵な一年になりますように",
        "これからも、ずっと一緒にいようね",
    ]
    assert (
        body["lines"][0]["audio_url"]
        == "/api/voices/voices/mano/s20_11400100_01_0030.mp3"
    )
    assert body["lines"][0]["subtitle"] == "生日快乐。愿你拥有美好的一年。"
    # 名台词不混进生日祝福。
    assert all("audio_url" in one for one in body["lines"])


async def test_the_character_with_the_most_characters_is_the_one_celebrating(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(
        characters.directory,
        [
            birthday_line(character="mano", text="ありがとう"),
            birthday_line(
                character="kogane", text="お誕生日、おめでとうございます。素敵な一年になりますように"
            ),
        ],
    )
    client = make_client(FakeLLM(), clock=FakeClock(NOW))
    await set_birthday(client, 9, 25)

    body = (await client.get("/api/birthday")).json()

    assert body["active"] is True
    assert body["character"]["id"] == "kogane"


async def test_without_birthday_lines_there_is_no_egg(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [quote()])
    client = make_client(FakeLLM(), clock=FakeClock(NOW))
    await set_birthday(client, 9, 25)

    assert (await client.get("/api/birthday")).json() == {"active": False}


async def test_a_birthday_line_of_a_character_no_longer_configured_is_passed_over(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [birthday_line(character="ghost")])
    client = make_client(FakeLLM(), clock=FakeClock(NOW))
    await set_birthday(client, 9, 25)

    assert (await client.get("/api/birthday")).json() == {"active": False}


async def test_the_egg_is_given_once_a_day(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    write_voices(characters.directory, [birthday_line()])
    clock = FakeClock(NOW)
    client = make_client(FakeLLM(), clock=clock)
    await set_birthday(client, 9, 25)

    assert (await client.get("/api/birthday")).json()["active"] is True
    assert (await client.get("/api/birthday")).json() == {"active": False}

    clock.advance(days=1)  # 第二天，还是他的生日
    await set_birthday(client, 9, 26)
    assert (await client.get("/api/birthday")).json()["active"] is True


async def test_the_day_is_counted_in_the_producers_time_zone(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    # UTC 还是 25 日，上海已经是 26 日凌晨：生日按上海算。
    late = datetime(2026, 9, 25, 16, 30, tzinfo=UTC)
    write_voices(characters.directory, [birthday_line()])
    client = make_client(FakeLLM(), clock=FakeClock(late))
    await set_birthday(client, 9, 26)

    assert (await client.get("/api/birthday")).json()["active"] is True

    other = make_client(FakeLLM(), "other", clock=FakeClock(late))
    await set_birthday(other, 9, 25)
    assert (await other.get("/api/birthday")).json() == {"active": False}


async def test_a_timezone_in_the_profile_wins_over_the_device(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    # UTC 还是 25 日晚上，纽约也是 25 日晚上：按纽约算生日是 25 日。
    late = datetime(2026, 9, 25, 23, 30, tzinfo=UTC)
    write_voices(characters.directory, [birthday_line()])
    client = make_client(FakeLLM(), clock=FakeClock(late))
    await set_birthday(client, 9, 25, timezone="America/New_York")

    res = await client.get("/api/birthday", headers={"X-Timezone": "Asia/Tokyo"})

    assert res.json()["active"] is True


async def test_the_devices_timezone_counts_without_one_in_the_profile(
    make_client: ClientFactory, characters: CharacterConfig
) -> None:
    # UTC 15:30 是上海 23:30（还是 25 日）、东京 26 日 00:30。
    evening = datetime(2026, 9, 25, 15, 30, tzinfo=UTC)
    write_voices(characters.directory, [birthday_line()])

    tokyo = make_client(FakeLLM(), clock=FakeClock(evening))
    await set_birthday(tokyo, 9, 26)
    assert (await tokyo.get("/api/birthday", headers={"X-Timezone": "Asia/Tokyo"})).json()[
        "active"
    ] is True

    shanghai = make_client(FakeLLM(), clock=FakeClock(evening))
    await set_birthday(shanghai, 9, 26)
    assert (await shanghai.get("/api/birthday")).json() == {"active": False}
