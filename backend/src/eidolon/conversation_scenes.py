"""She and the producer may move somewhere else as they talk（DESIGN.md「通话场景」）。

这里只记一段对话现在在哪儿，按场景表的 id（`characters/scenes.toml`）：页首的「现在」、
通话的背景、回合提示词里的「此刻」都先看它，再退回排期表。所以「去咖啡厅吧」说定了以后，
下一回合她就在咖啡厅，页首和通话背景也跟着换。

`source` 说明这一行是怎么来的：`chat` 是对话里说定的（`scenes.judge_move`），`manual` 是
用户在页首的下拉栏里自己选的——两种都只作用在这段对话上，换一段对话仍然按排期表算。

删这段对话时一起删（`database.CONVERSATION_DATA`），删用户时也一起删（`database.USER_DATA`）。
"""

import threading
from pathlib import Path

from eidolon.database import connect

_SCHEMA = """
-- 一段对话一行：它现在在哪儿，最后一次说定是什么时候，怎么来的。没搬过就没有这一行。
CREATE TABLE IF NOT EXISTS conversation_scenes (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
    scene_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'chat'
);
"""


class ConversationScenes:
    """每段对话现在在哪儿，按场景 id，以及是对话里说定的还是手动选的。"""

    def __init__(self, database_path: Path) -> None:
        self._db = connect(database_path)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)
            columns = {r[1] for r in self._db.execute("pragma table_info(conversation_scenes)")}
            if "source" not in columns:  # 老库里没有这一列：以前记的都是对话里说定的
                self._db.execute(
                    "ALTER TABLE conversation_scenes ADD COLUMN source TEXT NOT NULL DEFAULT 'chat'"
                )

    def of(self, conversation_id: str) -> str | None:
        """这段对话搬去的场景；从没搬过就是 None。"""
        picked = self.picked(conversation_id)
        return picked[0] if picked else None

    def picked(self, conversation_id: str) -> tuple[str, str] | None:
        """这段对话现在在哪个场景、怎么来的（`chat` 或 `manual`）；没搬过就是 None。"""
        with self._lock:
            row = self._db.execute(
                "SELECT scene_id, source FROM conversation_scenes WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def keep(
        self, conversation_id: str, scene_id: str, at: str, source: str = "chat"
    ) -> None:
        """记下这段对话现在在 `scene_id`，以及是 `chat` 说定的还是 `manual` 选的。"""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversation_scenes (conversation_id, scene_id, updated_at, source)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(conversation_id) DO UPDATE SET"
                " scene_id = excluded.scene_id, updated_at = excluded.updated_at,"
                " source = excluded.source",
                (conversation_id, scene_id, at, source),
            )

    def forget(self, conversation_id: str) -> None:
        """不再记这段对话在哪儿：回到排期表算出来的地方。"""
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM conversation_scenes WHERE conversation_id = ?", (conversation_id,)
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()
