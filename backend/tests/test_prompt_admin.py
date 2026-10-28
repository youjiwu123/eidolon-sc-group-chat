"""The admin console's prompt editor: only the configured character sheets and the mode table
can be read or written, saves are backed up before they are replaced, the running characters are
reloaded at once, and malformed mode tables or oversized prompts are refused before they can
break the deployment."""

from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.affinity_prompts import render_affinity_prompts
from eidolon.config import Settings
from eidolon.modes import load_modes
from eidolon.prompt_admin import (
    MAX_MODE_DESCRIPTION,
    MAX_MODE_NAME,
    MAX_PROMPT_BYTES,
    MODES_HEADER,
    prompt_entries,
)
from tests.conftest import (
    CharacterConfig,
    ClientFactory,
    agree_to_terms,
    github_identity,
    sign_in_with,
)
from tests.fakes import FakeIdentityProvider, FakeLLM
from tests.test_admin_users import admin_client
from tests.test_delete_account import user_id

ADMIN = ("github", "9001")

MODE_TABLE = """\
# 测试用的模式表：这两行注释在改模式时要原样留着。
[[modes]]
id = "special"
name = "特殊档"
description = "特殊档的说明"
prompt = "你现在处在和制作人的「特殊档」：提示词后台测试用。"
"""


@pytest.fixture
def settings(settings: Settings, characters: CharacterConfig) -> Settings:
    """With an admin, and the mode table the app loads and the editor offers."""
    characters.write("modes.toml", MODE_TABLE)
    return replace(settings, admins=frozenset({ADMIN}))


def backups_of(characters: CharacterConfig, key: str) -> list[Path]:
    path = characters.directory / "backups" / "prompts" / key
    return sorted(path.parent.glob(f"{path.name}.*.bak"))


async def test_the_list_is_only_the_configured_sheets_the_modes_and_the_affinity_prompts(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    # A sheet nobody configured, even in `sheets/`, is not editable.
    characters.write("sheets/example.md", "# 示例\n")
    characters.write("sheets/mano.supplements.draft.md", "# 草稿\n")
    admin = await admin_client(make_client, github)

    res = await admin.get("/api/admin/prompts")

    assert res.status_code == 200, res.text
    listed = res.json()
    # 每个模式单独一格：列表里按模式表里的顺序排。
    assert [item["key"] for item in listed] == [
        "sheets/mano.md",
        "sheets/kogane.md",
        "modes/special",
        "affinity.toml",
    ]
    assert [item["kind"] for item in listed] == ["sheet", "sheet", "mode", "affinity"]
    assert [item["label"] for item in listed] == [
        "櫻木真乃",
        "月岡恋鐘",
        "特殊档",
        "好感度提示词",
    ]
    assert listed[0]["bytes"] == (characters.directory / "sheets" / "mano.md").stat().st_size
    assert listed[0]["updated_at"] is not None
    assert listed[2]["bytes"] > 0 and listed[2]["updated_at"] is not None
    # 好感度那份还没有文件：也算一条，还没保存过。
    assert listed[3]["bytes"] == 0 and listed[3]["updated_at"] is None


def test_the_repository_has_29_character_sheets_the_modes_and_the_affinity_prompts():
    entries = prompt_entries(Path(__file__).parents[2] / "characters" / "characters.toml")
    table = load_modes(Path(__file__).parents[2] / "characters" / "modes.toml")

    assert sum(entry.kind == "sheet" for entry in entries.values()) == 29
    # 模式表是部署者自己会加的：几条就几格，别把数字写死。
    assert sum(entry.kind == "mode" for entry in entries.values()) == len(table)
    assert {"modes/special", "modes/succubus"} <= set(entries)
    assert entries["affinity.toml"].kind == "affinity"
    assert len(entries) == 29 + len(table) + 1


async def test_a_sheet_reads_back_exactly_and_a_save_backs_it_up_and_reloads(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    before = (await admin.get("/api/admin/prompts/sheets/mano.md")).json()
    changed = "# 人设\n你是櫻木真乃。这是后台提示词测试插入的一句。\n"
    assert changed != before["content"]

    res = await admin.put(
        "/api/admin/prompts/sheets/mano.md",
        json={"content": changed},
    )

    assert res.status_code == 200, res.text
    saved = res.json()
    assert saved["key"] == "sheets/mano.md"
    assert saved["content"] == changed
    assert saved["bytes"] == len(changed.encode("utf-8"))
    assert saved["reload_required"] is False
    assert (characters.directory / "sheets" / "mano.md").read_text(encoding="utf-8") == changed

    [backup] = backups_of(characters, "sheets/mano.md")
    assert backup.read_bytes() == before["content"].encode("utf-8")

    # The engine and the API work from the same character mapping, which now has the new sheet.
    backend = admin._transport.app.state.backend
    assert backend.characters["mano"].sheet == changed.strip()
    assert backend.engine._characters["mano"].sheet == changed.strip()
    assert (await admin.get("/api/admin/prompts/sheets/mano.md")).json()["content"] == changed


async def test_a_mode_is_edited_in_its_own_cell_and_reloaded(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    """每个模式单独一格：改的是这一条的名字、说明和提示词，表里别的东西和注释都不动。"""
    admin = await admin_client(make_client, github)
    before = (await admin.get("/api/admin/prompts/modes/special")).json()
    assert before["kind"] == "mode" and before["label"] == "特殊档"
    assert "prompt = " in before["content"] and "[[modes]]" not in before["content"]
    changed = before["content"].replace("提示词后台测试用", "提示词后台测试用（已改）")

    res = await admin.put("/api/admin/prompts/modes/special", json={"content": changed})

    assert res.status_code == 200, res.text
    assert res.json()["reload_required"] is False
    written = (characters.directory / "modes.toml").read_text(encoding="utf-8")
    assert "（已改）" in written
    assert written.startswith("# 测试用的模式表")  # 文件自己的注释留着
    assert 'id = "special"' in written
    backend = admin._transport.app.state.backend
    assert "（已改）" in backend.modes["special"].prompt
    assert "（已改）" in backend.engine._modes["special"].prompt
    [backup] = backups_of(characters, "modes/special")
    assert backup.read_text(encoding="utf-8") == MODE_TABLE


async def test_a_mode_renamed_in_its_cell_is_listed_under_the_new_name(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    before = (await admin.get("/api/admin/prompts/modes/special")).json()
    renamed = before["content"].replace('name = "特殊档"', 'name = "特殊档（改）"')

    res = await admin.put("/api/admin/prompts/modes/special", json={"content": renamed})

    assert res.status_code == 200, res.text
    assert res.json()["label"] == "特殊档（改）"
    listed = (await admin.get("/api/admin/prompts")).json()
    assert [item["label"] for item in listed if item["kind"] == "mode"] == ["特殊档（改）"]


async def test_a_mode_table_that_is_broken_is_offered_whole(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    """表读不了的时候退回整份一格，管理员还能把它改回来。"""
    admin = await admin_client(make_client, github)
    characters.write("modes.toml", "[[modes]\nid = \"broken\"\n")

    listed = (await admin.get("/api/admin/prompts")).json()

    [broken] = [item for item in listed if item["kind"] == "modes"]
    assert broken["key"] == "modes.toml"
    res = await admin.put("/api/admin/prompts/modes.toml", json={"content": MODE_TABLE})
    assert res.status_code == 200, res.text
    assert (characters.directory / "modes.toml").read_text(encoding="utf-8") == MODE_TABLE


async def test_the_affinity_prompts_show_the_built_in_words_until_they_are_saved(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    before = await admin.get("/api/admin/prompts/affinity.toml")

    assert before.status_code == 200, before.text
    assert before.json()["kind"] == "affinity"
    # 文件还没建：编辑器里给的就是内置的那份，一个字不差。
    assert before.json()["content"] == render_affinity_prompts()
    changed = before.json()["content"].replace("露骨的情话不必说", "露骨的情话不必说（后台测试）")
    assert changed != before.json()["content"]

    res = await admin.put("/api/admin/prompts/affinity.toml", json={"content": changed})

    assert res.status_code == 200, res.text
    assert res.json()["reload_required"] is False
    assert (characters.directory / "affinity.toml").read_text(encoding="utf-8") == changed
    assert backups_of(characters, "affinity.toml") == []  # 之前没有文件，没什么可备份
    backend = admin._transport.app.state.backend
    assert "（后台测试）" in backend.engine._affinity_prompts.fondness["love"]


async def test_an_invalid_affinity_table_is_refused_and_nothing_is_written(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    original = (await admin.get("/api/admin/prompts/affinity.toml")).json()["content"]

    res = await admin.put(
        "/api/admin/prompts/affinity.toml",
        json={"content": '[[tiers]]\nid = "trust"\nprompt = "信任档没有自己的话"\n'},
    )

    assert res.status_code == 422, res.text
    assert not (characters.directory / "affinity.toml").exists()
    assert (await admin.get("/api/admin/prompts/affinity.toml")).json()["content"] == original


async def test_a_new_mode_is_appended_backed_up_and_reloaded(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    original = (characters.directory / "modes.toml").read_bytes()

    res = await admin.post(
        "/api/admin/modes",
        json={
            "name": "深夜值班",
            "description": "只在夜里出现的那一面。",
            "prompt": "你现在以「深夜值班」的样子出现：声音低、慢。",
        },
    )

    assert res.status_code == 201, res.text
    assert res.json() == {"id": "custom-1", "name": "深夜值班"}
    backend = admin._transport.app.state.backend
    assert backend.modes["custom-1"].prompt == "你现在以「深夜值班」的样子出现：声音低、慢。"
    assert backend.engine._modes["custom-1"].name == "深夜值班"
    written = (characters.directory / "modes.toml").read_text(encoding="utf-8")
    # 新的一条排在最后，原来的那条和文件自己的注释都还在。
    assert written.startswith("# 测试用的模式表")
    assert written.index('id = "special"') < written.index('id = "custom-1"')
    assert "深夜值班" in written
    [backup] = backups_of(characters, "modes.toml")
    assert backup.read_bytes() == original
    # 列表里就多了它这一格，排在模式表的后面。
    listed = (await admin.get("/api/admin/prompts")).json()
    assert [item["key"] for item in listed if item["kind"] == "mode"] == [
        "modes/special",
        "modes/custom-1",
    ]
    # 聊天界面的好感度弹层就是照这张表列开关的。
    modes = (await admin.get("/api/modes")).json()
    assert "深夜值班" in [mode["name"] for mode in modes]


async def test_a_new_mode_makes_the_mode_table_when_there_is_none(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    (characters.directory / "modes.toml").unlink()
    admin = await admin_client(make_client, github)

    res = await admin.post("/api/admin/modes", json={"name": "只看夜色", "prompt": "你现在只说夜里的 "})

    assert res.status_code == 201, res.text
    written = (characters.directory / "modes.toml").read_text(encoding="utf-8")
    assert written.startswith(MODES_HEADER)
    backend = admin._transport.app.state.backend
    assert backend.engine._modes["custom-1"].name == "只看夜色"


@pytest.mark.parametrize(
    "mode",
    [
        {"name": "", "prompt": "x"},
        {"name": "  ", "prompt": "x"},
        {"name": "x" * (MAX_MODE_NAME + 1), "prompt": "x"},
        {"name": "没有提示词", "prompt": " "},
        {"name": "特殊档", "prompt": "x"},  # 和已有的重名
        {"name": "x" * MAX_MODE_NAME, "description": "x" * (MAX_MODE_DESCRIPTION + 1), "prompt": "x"},
    ],
)
async def test_a_mode_that_does_not_make_sense_is_refused(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
    mode: dict,
):
    admin = await admin_client(make_client, github)
    original = (characters.directory / "modes.toml").read_bytes()

    res = await admin.post("/api/admin/modes", json=mode)

    assert res.status_code == 422, res.text
    assert (characters.directory / "modes.toml").read_bytes() == original
    assert backups_of(characters, "modes.toml") == []


@pytest.mark.parametrize(
    "content",
    [
        'name = "特殊档"\n',  # 没有 prompt
        'prompt = "只有提示词"\n',  # 没有 name
        'name = "特殊档"\ndescription = 3\nprompt = "x"\n',
        "不是 TOML",
    ],
)
async def test_a_mode_cell_that_would_not_load_is_refused(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
    content: str,
):
    admin = await admin_client(make_client, github)
    original = (characters.directory / "modes.toml").read_bytes()

    res = await admin.put("/api/admin/prompts/modes/special", json={"content": content})

    assert res.status_code == 422, res.text
    assert (characters.directory / "modes.toml").read_bytes() == original
    assert backups_of(characters, "modes/special") == []


async def test_a_non_admin_cannot_make_a_mode(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    await admin_client(make_client, github)
    producer = make_client(FakeLLM(), user=None)
    await sign_in_with(producer, github, github_identity("1001", name="producer"))
    await agree_to_terms(producer)

    res = await producer.post("/api/admin/modes", json={"name": "偷来的", "prompt": "x"})

    assert res.status_code == 403, res.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/prompts/..%2Fcharacters.toml",
        "/api/admin/prompts/%2E%2E%2Fcharacters.toml",
        "/api/admin/prompts/sheets%2F..%2F..%2Fcharacters.toml",
        "/api/admin/prompts/%2Fetc%2Fpasswd",
        "/api/admin/prompts/C%3A%5CWindows%5Cwin.ini",
    ],
)
async def test_paths_outside_the_whitelist_are_refused(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    path: str,
):
    admin = await admin_client(make_client, github)

    res = await admin.get(path)
    put = await admin.put(path, json={"content": "x"})

    assert res.status_code in (400, 404), res.text
    assert put.status_code in (400, 404), put.text


async def test_a_non_admin_is_refused(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
):
    await admin_client(make_client, github)
    producer = make_client(FakeLLM(), user=None)
    await sign_in_with(producer, github, github_identity("1001", name="producer"))
    await agree_to_terms(producer)

    res = await producer.get("/api/admin/prompts")

    assert res.status_code == 403, res.text


async def test_an_invalid_mode_table_is_refused_and_the_file_is_untouched(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    characters.write("modes.toml", "[[modes]\nid = \"broken\"\n")
    original = (characters.directory / "modes.toml").read_bytes()

    res = await admin.put(
        "/api/admin/prompts/modes.toml",
        json={"content": '[[modes]]\nid = "broken"\nname = "没有 prompt"\n'},
    )

    assert res.status_code == 422, res.text
    assert (characters.directory / "modes.toml").read_bytes() == original
    assert backups_of(characters, "modes.toml") == []


async def test_too_long_and_empty_prompts_are_refused(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    original = (characters.directory / "sheets" / "mano.md").read_bytes()

    too_long = await admin.put(
        "/api/admin/prompts/sheets/mano.md",
        json={"content": "x" * (MAX_PROMPT_BYTES + 1)},
    )
    empty = await admin.put(
        "/api/admin/prompts/sheets/mano.md",
        json={"content": "  \n"},
    )

    assert too_long.status_code == 422, too_long.text
    assert empty.status_code == 422, empty.text
    assert (characters.directory / "sheets" / "mano.md").read_bytes() == original
    assert backups_of(characters, "sheets/mano.md") == []


async def test_an_unlisted_sheet_is_not_there(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    characters.write("sheets/example.md", "# 示例\n")
    admin = await admin_client(make_client, github)

    assert (await admin.get("/api/admin/prompts/sheets/example.md")).status_code == 404
    assert (
        await admin.put("/api/admin/prompts/sheets/example.md", json={"content": "x"})
    ).status_code == 404


async def test_anonymous_visitors_are_refused(make_client: ClientFactory):
    visitor = make_client(FakeLLM(), user=None)

    res = await visitor.get("/api/admin/prompts")

    assert res.status_code == 403, res.text


async def test_a_prompt_that_cannot_be_reloaded_is_put_back(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    """The sheet itself is free text, but if the reload fails (here the character loader
    raises), the old content is put back and the save is refused rather than leaving the
    running API and the file disagreeing."""
    admin = await admin_client(make_client, github)
    original = (characters.directory / "sheets" / "mano.md").read_bytes()
    monkeypatch.setattr(
        "eidolon.prompt_admin.load_characters",
        lambda _: (_ for _ in ()).throw(RuntimeError("reload failed")),
    )

    res = await admin.put("/api/admin/prompts/sheets/mano.md", json={"content": "changed"})

    assert res.status_code == 500, res.text
    assert (characters.directory / "sheets" / "mano.md").read_bytes() == original


TWO_MODES = MODE_TABLE + """
[[modes]]
id = "night"
name = "夜里那一档"
description = "只在夜里。"
prompt = "你现在只说夜里的话。"
"""


async def test_a_mode_is_deleted_and_the_rest_of_the_table_stays(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
    settings: Settings,
):
    characters.write("modes.toml", TWO_MODES)
    admin = await admin_client(make_client, github)
    producer = make_client(FakeLLM())
    uid = user_id(settings.database_path, "producer")
    turned_on = await producer.put("/api/characters/mano/modes", json={"enabled": ["night"]})
    assert turned_on.status_code == 200, turned_on.text
    original = (characters.directory / "modes.toml").read_bytes()

    res = await admin.delete("/api/admin/prompts/modes/night")

    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is True
    written = (characters.directory / "modes.toml").read_text(encoding="utf-8")
    assert 'id = "night"' not in written
    assert 'id = "special"' in written and written.startswith("# 测试用的模式表")
    [backup] = backups_of(characters, "modes/night")
    assert backup.read_bytes() == original
    backend = admin._transport.app.state.backend
    assert "night" not in backend.modes and "night" not in backend.engine._modes
    # 她身上开着的那个开关跟着一起没了。
    assert backend.character_modes.of(uid, "mano") == ()
    assert [item["key"] for item in (await admin.get("/api/admin/prompts")).json()
            if item["kind"] == "mode"] == ["modes/special"]


async def test_only_a_mode_can_be_deleted(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    original = (characters.directory / "modes.toml").read_bytes()

    for key in ("sheets/mano.md", "affinity.toml"):
        res = await admin.delete(f"/api/admin/prompts/{key}")
        assert res.status_code == 422, res.text
    # 已经不在表里的那一格：404。
    assert (await admin.delete("/api/admin/prompts/modes/night")).status_code == 404
    assert (characters.directory / "modes.toml").read_bytes() == original


async def test_a_pasted_mode_block_is_taken_apart(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    """整段 [[modes]] 粘进「提示词」栏：名字、说明、正文拆出来存，不把 TOML 源码当正文。"""
    admin = await admin_client(make_client, github)
    pasted = """[[modes]]
id = "pasted"
name = "人偶"
description = "陪护型玩偶。"
prompt = """ + '"""' + """你现在是陪护型玩偶，住在主人家里。""" + '"""'

    res = await admin.post(
        "/api/admin/modes",
        json={"name": "人偶", "description": "", "prompt": pasted},
    )

    assert res.status_code == 201, res.text
    made = res.json()
    backend = admin._transport.app.state.backend
    assert backend.modes[made["id"]].prompt == "你现在是陪护型玩偶，住在主人家里。"
    assert backend.modes[made["id"]].description == "陪护型玩偶。"
    assert "[[modes]]" not in backend.modes[made["id"]].prompt


async def test_a_mode_is_saved_from_its_three_fields(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    """编辑器按三栏存特殊档：名字、说明、提示词，不用手写 TOML 引号。"""
    admin = await admin_client(make_client, github)

    res = await admin.put(
        "/api/admin/prompts/modes/special",
        json={"name": "特殊档（改）", "description": "说明也改了", "prompt": "你现在很严厉。"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["fields"] == {
        "name": "特殊档（改）", "description": "说明也改了", "prompt": "你现在很严厉。"
    }
    written = (characters.directory / "modes.toml").read_text(encoding="utf-8")
    assert 'name = "特殊档（改）"' in written and "你现在很严厉。" in written
    assert written.startswith("# 测试用的模式表")
    backend = admin._transport.app.state.backend
    assert backend.modes["special"].name == "特殊档（改）"
    assert backend.engine._modes["special"].prompt == "你现在很严厉。"
    listed = (await admin.get("/api/admin/prompts")).json()
    assert [item["label"] for item in listed if item["kind"] == "mode"] == ["特殊档（改）"]


async def test_a_mode_field_save_without_a_prompt_is_refused(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    characters: CharacterConfig,
):
    admin = await admin_client(make_client, github)
    original = (characters.directory / "modes.toml").read_bytes()

    res = await admin.put(
        "/api/admin/prompts/modes/special",
        json={"name": "特殊档", "description": "", "prompt": "  "},
    )

    assert res.status_code == 422, res.text
    assert (characters.directory / "modes.toml").read_bytes() == original
