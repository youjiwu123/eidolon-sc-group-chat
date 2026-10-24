// 外观（设置「外观」）：「SCSP 头像」（GLOSSARY.md「SCSP 头像」）和对话页右下角的小立绘
// （DESIGN.md「对话页的立绘小人」）两个开关。只存在这台设备上，在 localStorage 里按用户分开存
// （键为 eidolon.appearance.<用户 ID>）。读不到或数据坏了当作默认（SCSP 头像关、小立绘开；
// 老数据里没有小立绘那一项，所以它一直是开的）；存不进去（隐私模式等）时不抛错，改动只留在页面内存里。

import type { Character } from "@/lib/api";

export type Appearance = {
  /** 登录后的应用里，头像换成她们在 SCSP 里的那一套。 */
  scspAvatars: boolean;
  /** 她的对话页右下角站一个她的立绘小人。 */
  chatStand: boolean;
};

export const DEFAULT_APPEARANCE: Appearance = { scspAvatars: false, chatStand: true };

function storageKey(userId: string): string {
  return `eidolon.appearance.${userId}`;
}

/** 这位用户在这台设备上的外观。 */
export function loadAppearance(userId: string): Appearance {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey(userId)) ?? "{}");
    return { scspAvatars: stored?.scspAvatars === true, chatStand: stored?.chatStand !== false };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

/** 存下这位用户的外观；存不进去时什么也不做。 */
export function keepAppearance(userId: string, appearance: Appearance): void {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(appearance));
  } catch {
    // 存储不可用：这次存不下，改动只在这次页面里生效。
  }
}

/** 按外观换掉每位的头像：打开 SCSP 头像时用她的 SCSP 头像，她没有的照旧。 */
export function withAppearance(characters: Character[], appearance: Appearance): Character[] {
  if (!appearance.scspAvatars) return characters;
  return characters.map((c) => (c.scsp_avatar_url ? { ...c, avatar_url: c.scsp_avatar_url } : c));
}
