"""生日原声彩蛋（GLOSSARY.md「生日」）：今天是制作人的生日时，她那段生日祝福。

生日的判断和角色平时知道的一样，只看制作人档案里的月和日，按制作人所在时区的日期算
（2 月 29 日在平年算 2 月 28 日，`producer.is_birthday`）。没有档案、或者没有填生日的，不
是生日。

是哪位角色的哪几句由原声表（`voices.py`）里 `kind = "birthday"` 的条目决定：同一句原声是
她说的，就挑那位；几位都有时挑字数最多的那位（几句合起来算），同一角色的几段全给，按
`story`、`line` 排好。一位都没有时这一天就没有彩蛋，不挑别人凑数。

每个用户一天只“触发”一次：`BirthdayTriggers` 在进程里记着（不建表）。重启后当天的标记会
没有，同一天可能再弹一次；前端在这台设备上也记着当天看过了（localStorage），所以实际看到
的还是只有一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from eidolon.characters import Character, in_idol_order
from eidolon.producer import ProducerProfile, effective_timezone, is_birthday, local_date
from eidolon.voices import VoicesCatalog, VoiceLine

BIRTHDAY_KIND = "birthday"
"""生日祝福在原声表里的 `kind`。"""


def is_producer_birthday(
    profile: ProducerProfile, now: datetime, device_timezone: str | None = None
) -> bool:
    """`now` 这一刻在制作人所在的时区是不是他的生日；没填生日、或者没有档案时不是。"""
    if profile.birthday is None:
        return False
    return is_birthday(profile.birthday, local_date(now, effective_timezone(profile, device_timezone)))


def day_of(profile: ProducerProfile, now: datetime, device_timezone: str | None = None) -> date:
    """制作人所在时区的今天：一天只触发一次的那个“一天”。"""
    return local_date(now, effective_timezone(profile, device_timezone))


@dataclass(frozen=True)
class BirthdayGreeting:
    """今天该他听的那份生日祝福：谁说的，和她说的那几段。"""

    character: Character
    lines: tuple[VoiceLine, ...]


def pick_birthday(
    catalog: VoicesCatalog, characters: dict[str, Character]
) -> BirthdayGreeting | None:
    """挑生日祝福的那位角色：原声表里 `kind = "birthday"` 的条目，按角色合起来字数最多的
    那位（并列时按偶像顺序取前一位），她的几段按 `story`、行号的数值排好（`by_source`）：
    同一位角色的几条是一段连续的祝贺。一句都没有、或者那位角色已经不在配置里时是 None。"""
    grouped: dict[str, list[VoiceLine]] = {}
    for line in catalog.of_kind(BIRTHDAY_KIND):
        grouped.setdefault(line.character, []).append(line)
    known = [character for character in in_idol_order(characters.values()) if character.id in grouped]
    if not known:
        return None

    def characters_spoken(character: Character) -> int:
        return sum(len(line.spoken) for line in grouped[character.id])

    chosen = max(known, key=characters_spoken)
    lines = tuple(sorted(grouped[chosen.id], key=by_source))
    return BirthdayGreeting(chosen, lines)


def by_source(line: VoiceLine) -> tuple[str, int, str]:
    """按 `story`、行号的数值排：同一位角色的几条是一段连续的祝贺（行号是四位数字，按数值比
    免得 `0090` 和 `0100` 弄反）；不是数字的排在后面。"""
    number = int(line.line) if line.line.isdigit() else 0
    return (line.story, number, line.line)


class BirthdayTriggers:
    """每个用户一天只触发一次生日彩蛋：进程里记着（不建表，重启会重放，可以接受）。"""

    def __init__(self) -> None:
        self._days: dict[str, date] = {}

    def claim(self, user_id: str, day: date) -> bool:
        """`day` 这一天的彩蛋还没给他看过时记下并返回 True；已经看过时返回 False。"""
        if self._days.get(user_id) == day:
            return False
        self._days[user_id] = day
        return True
