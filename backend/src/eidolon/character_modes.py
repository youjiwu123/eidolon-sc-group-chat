"""The special modes each user turns on for each character (特殊档等): hers alone.

What a mode is is the mode table's business (`characters/modes.toml`, `modes.load_modes`);
what is kept here is only which of those one user turned on for one character. Each
character's are her own: the same user may have 夜之魅魔 on for one and nothing for another,
and turning one on for her says nothing of the rest.

What is kept is appended to her prompt beside her affinity, in the order the mode table
lists them, whatever her tier: at every tier the chosen modes are added, and with the
deployment's affinity off they still are, as long as they are on. Deleting the user deletes
them (`database.USER_DATA`).
"""

import threading
from collections.abc import Iterable
from pathlib import Path

from eidolon.database import connect

_SCHEMA = """
-- One row per user, character and mode the user turned on for her; no row for a mode is off.
CREATE TABLE IF NOT EXISTS character_modes (
    user_id TEXT NOT NULL REFERENCES users(id),
    character_id TEXT NOT NULL,
    mode_id TEXT NOT NULL,
    PRIMARY KEY (user_id, character_id, mode_id)
);
"""


class CharacterModes:
    """Which modes each user turned on for each character, by their ids in the mode table."""

    def __init__(self, database_path: Path) -> None:
        self._db = connect(database_path)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def of(self, user_id: str, character_id: str) -> tuple[str, ...]:
        """The modes she has on with the user, by id, in no particular order; empty for none."""
        with self._lock:
            rows = self._db.execute(
                "SELECT mode_id FROM character_modes WHERE user_id = ? AND character_id = ?",
                (user_id, character_id),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def set(self, user_id: str, character_id: str, mode_ids: Iterable[str]) -> tuple[str, ...]:
        """Turn exactly `mode_ids` on for her, every other off; empty turns all of them off.

        Repeated ids are kept once, in the order given; an id that is not in the mode table
        is kept as it is (the caller refuses those), and reads as no line if it is not."""
        wanted = tuple(dict.fromkeys(mode_id for mode_id in mode_ids if mode_id))
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM character_modes WHERE user_id = ? AND character_id = ?",
                (user_id, character_id),
            )
            self._db.executemany(
                "INSERT INTO character_modes (user_id, character_id, mode_id) VALUES (?, ?, ?)",
                [(user_id, character_id, mode_id) for mode_id in wanted],
            )
        return wanted

    def forget(self, mode_id: str) -> int:
        """Turn it off for everyone who had it on, as deleting it from the mode table does;
        the switches it left are gone. Returns how many there were."""
        with self._lock, self._db:
            [found] = self._db.execute(
                "SELECT COUNT(*) FROM character_modes WHERE mode_id = ?", (mode_id,)
            ).fetchone()
            self._db.execute("DELETE FROM character_modes WHERE mode_id = ?", (mode_id,))
        return int(found)

    def close(self) -> None:
        with self._lock:
            self._db.close()
