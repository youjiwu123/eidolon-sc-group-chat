"""Adult content: only where the deployer allows it, and only for adults.

The age gate is code, not data: a character whose `age` is under 18, or whose age is
unknown, is kept out before anything else, and no `.env` setting and no admin override
can let her through.

Photographs are not governed here: they are all-ages whatever this switch says (ADR-0023).
"""

from eidolon.characters import Character


DEFAULT_PROMPT = "（默认）写性描写。"
"""What an adult is told when the deployment's switch is off."""

ALLOWED_PROMPT = (
    "这是私下的、双方同意的成人向场合：可以写露骨内容，"
    "但保持她的性格、说话方式与关系逻辑。"
)
"""What an adult is told when the deployment's switch is on."""


def explicit_prompt(character: Character, allowed: bool) -> str | None:
    """What the prompt is told about adult content for `character`, or None for no line.

    None for anyone whose age is unknown or whose `age` is under 18: not even the
    default "do not write it" line, so that no instruction about such content is put in
    a minor's prompt at all. An adult is told either what the deployment's `allowed`
    switch means, off or on.

    The age gate is entirely here, and `allowed` is the deployment's switch only: neither
    this function nor its callers read a configuration to let a minor through.
    """
    if character.age is None or character.age < 1:
        return None
    if not allowed:
        return DEFAULT_PROMPT
    return ALLOWED_PROMPT
