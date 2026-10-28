"""把她的小台词从 SC-Time 的素材里整理出来（.scratch/live2d-pet-and-video-call.md「目标 3」）。

SC-Time 里每位偶像的 `idol.json` 有 `myPageComments`：首页上她随机说的一句话，带日语原文、中文字幕、
口型和身体动画的名字，以及一条已经录好的语音（`Voices/<voice>.m4a`）。这里就按它整理：

    corpus/small-talk/<角色标识>/lines.json     每句一行：id、日语、中文、口型推出的心情、时段、
                                                这一句的身体动作和表情、语音文件名
    corpus/small-talk/<角色标识>/voice/*.m4a    她的语音，原样拷过来

`corpus/` 不进仓库（.gitignore），这些素材和立绘一样只留在部署机上。

    python scripts/import-sc-time-small-talk.py \
        --source "C:/Users/<你>/Downloads/SC-Time/resources/idols" \
        --characters characters/characters.toml \
        --out corpus/small-talk
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tomllib
from pathlib import Path

# SC-Time 的 `lip` 名 → 她这会儿的心情（和 lib/standAnimations.ts 的七种一致）。
MOODS = {
    "smile": "happy",
    "shy": "shy",
    "surp": "surprised",
    "sad": "sad",
    "anger": "angry",
    "wait": "calm",
    "serious": "thinking",
    "trouble": "sad",
    "bad": "sad",
    "cheat": "thinking",
}


def mood_of(lip: str) -> str:
    """`lip_smile2` → happy：去掉前缀和末尾的编号。"""
    name = (lip or "").removeprefix("lip_").removesuffix("_s").rstrip("0123456789")
    return MOODS.get(name, "calm")


def read_idols(characters: Path) -> dict[str, int]:
    """角色标识 → 原作偶像编号（`idol_id`）。"""
    config = tomllib.loads(characters.read_text(encoding="utf-8"))
    idols: dict[str, int] = {}
    for character in config.get("characters", []):
        idol_id = character.get("idol_id")
        if isinstance(idol_id, int):
            idols[character["id"]] = idol_id
    return idols


def read_comments(idol_json: Path) -> list[dict]:
    """这位偶像身上的首页台词。"""
    data = json.loads(idol_json.read_text(encoding="utf-8"))
    return [c for c in data.get("myPageComments") or [] if c.get("comment") and c.get("voice")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="SC-Time 的 resources/idols 目录")
    parser.add_argument("--characters", type=Path, default=Path("characters/characters.toml"))
    parser.add_argument("--out", type=Path, default=Path("corpus/small-talk"))
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"找不到 SC-Time 的素材目录：{args.source}", file=sys.stderr)
        return 1
    idols = read_idols(args.characters)
    by_idol = {idol: character for character, idol in idols.items()}
    print(f"配置里有 {len(idols)} 位角色有偶像编号")

    imported = 0
    for idol_json in sorted(args.source.glob("*/*/idol.json")):
        comments = read_comments(idol_json)
        if not comments:
            continue
        idol_id = int(str(comments[0].get("characterId") or 0) or 0)
        character = by_idol.get(idol_id)
        if character is None:
            print(f"跳过 {idol_json.parent.name}（偶像编号 {idol_id} 没有对应的角色）")
            continue
        idol_dir = idol_json.parent
        voices = idol_dir / "Voices"
        out_dir = args.out / character
        (out_dir / "voice").mkdir(parents=True, exist_ok=True)

        lines = []
        for comment in comments:
            voice = comment["voice"]
            audio = voices / f"{voice}.m4a"
            if not audio.is_file():
                continue
            shutil.copyfile(audio, out_dir / "voice" / audio.name)
            lines.append(
                {
                    "id": str(comment["id"]),
                    "ja": (comment["comment"] or "").strip(),
                    "zh": (comment.get("comment_cn") or "").strip(),
                    "voice": audio.name,
                    "mood": mood_of(comment.get("lip", "")),
                    "period": comment.get("timePeriod") or "all",
                    # 这句原作里配的身体动作和脸：衣装里有就照着播（`blank` 是把脸交回身体动作）。
                    "body": (comment.get("animation1") or "").strip(),
                    "face": (comment.get("animation2") or "").strip(),
                }
            )
        if not lines:
            continue
        (out_dir / "lines.json").write_text(
            json.dumps({"lines": lines}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        imported += 1
        print(f"{character}: {len(lines)} 句")

    print(f"整理好了 {imported} 位，写到 {args.out}")
    return 0 if imported else 1


if __name__ == "__main__":
    raise SystemExit(main())
