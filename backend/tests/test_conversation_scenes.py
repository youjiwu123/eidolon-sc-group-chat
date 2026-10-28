"""页首手动选地点（DESIGN.md「通话场景」）：选一个场景只作用在这段对话上，`source` 是
`manual`；取消就回到排期表算的地方。下拉栏的清单来自场景表（`GET /api/scenes`）。"""

from pathlib import Path

from eidolon.conversation_scenes import ConversationScenes
from eidolon.store import Store
from tests.conftest import SCENE_IDS, ClientFactory
from tests.fakes import FakeLLM
from tests.test_text_turn import start_conversation


async def test_a_place_picked_by_hand_is_manual_and_clearing_it_goes_back(
    make_client: ClientFactory,
) -> None:
    client = make_client(FakeLLM())
    conversation = await start_conversation(client)
    before = (await client.get(f"/api/conversations/{conversation}/now")).json()

    picked = await client.put(
        f"/api/conversations/{conversation}/place", json={"scene_id": "lounge"}
    )

    assert picked.status_code == 200
    assert picked.json()["scene"]["id"] == "lounge"
    assert picked.json()["scene"]["name"] == "事务所休息室"
    assert picked.json()["source"] == "manual"
    # 返回的和 `/now` 是同一张。
    shown = (await client.get(f"/api/conversations/{conversation}/now")).json()
    assert shown == picked.json()

    cleared = await client.put(
        f"/api/conversations/{conversation}/place", json={"scene_id": None}
    )

    assert cleared.status_code == 200
    now = (await client.get(f"/api/conversations/{conversation}/now")).json()
    assert now == cleared.json()
    assert now["source"] != "manual"
    # 回到按排期表算的地方（这里没有排期表，落到她的预设行为）：不是刚才手动选的那里。
    assert now["scene"]["id"] == before["scene"]["id"]
    assert before["source"] != "manual"


async def test_a_scene_not_in_the_table_is_not_found(make_client: ClientFactory) -> None:
    client = make_client(FakeLLM())
    conversation = await start_conversation(client)

    res = await client.put(
        f"/api/conversations/{conversation}/place", json={"scene_id": "moon"}
    )

    assert res.status_code == 404
    now = (await client.get(f"/api/conversations/{conversation}/now")).json()
    assert now["source"] != "manual"


async def test_a_place_for_a_conversation_that_is_not_there_is_not_found(
    make_client: ClientFactory,
) -> None:
    client = make_client(FakeLLM())

    res = await client.put(
        "/api/conversations/no-such-conversation/place", json={"scene_id": "lounge"}
    )

    assert res.status_code == 404


async def test_the_scene_table_is_listed_for_choosing(make_client: ClientFactory) -> None:
    client = make_client(FakeLLM())

    res = await client.get("/api/scenes")

    assert res.status_code == 200
    scenes = res.json()
    assert {"id": "home", "name": "她的家", "hint": "粉色房间"} in scenes
    assert {scene["id"] for scene in scenes} == set(SCENE_IDS)
    assert all(set(scene) == {"id", "name", "hint"} for scene in scenes)


def test_picked_keeps_the_source_and_forget_drops_it(tmp_path: Path) -> None:
    database = tmp_path / "eidolon.db"
    store = Store(database)
    scenes = ConversationScenes(database)
    try:
        user = store.create_user("producer")
        conversation = store.create_conversation(user.id, "mano")

        assert scenes.picked(conversation.id) is None
        scenes.keep(
            conversation.id, "lounge", "2026-10-26T12:00:00+00:00", source="manual"
        )
        assert scenes.picked(conversation.id) == ("lounge", "manual")
        assert scenes.of(conversation.id) == "lounge"

        scenes.forget(conversation.id)

        assert scenes.picked(conversation.id) is None
        assert scenes.of(conversation.id) is None
    finally:
        scenes.close()
        store.close()
