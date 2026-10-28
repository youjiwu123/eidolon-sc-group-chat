// 对话页右下角的小立绘（DESIGN.md「对话页的立绘小人」）：她多大、站在哪儿，都只记在这台设备上。
// 拖她脚边的把手改大小（键盘上是左右方向键），拖她本人换位置；位置按消息区里空出来的地方的比例记，
// 换窗口大小、换设备都不会把她放到框外。存不进去（隐私模式等）时不抛错，改动只影响这一次。

/** 默认宽度（px）。 */
export const STAND_WIDTH = 120;
export const MIN_STAND_WIDTH = 80;
/** 最大宽度（px）；放不下时按消息区的高度缩回来，不会拉扁。 */
export const MAX_STAND_WIDTH = 480;
/** 一次方向键改多少（px）。 */
export const STAND_WIDTH_STEP = 8;
/** 拖动时算「在挪她」而不是「点她一下」的距离（px）。 */
export const STAND_DRAG_THRESHOLD = 4;

/** 她站在消息区的哪儿：0 是贴右边（或下边），1 是贴左边（或上边）。 */
export type StandPlace = { x: number; y: number };

export const DEFAULT_PLACE: StandPlace = { x: 0, y: 0 };

const WIDTH_KEY = "eidolon.chatCompanionWidth";
const HEIGHT_KEY = "eidolon.chatCompanionHeight";
const PLACE_KEY = "eidolon.chatCompanionPlace";

/** 群聊里按高度站（几个人一样高），默认多高（px）。 */
export const STAND_HEIGHT = 300;

/** 群聊里有好几位小人，各记各的：键后面挂上是谁的。没有 `key` 就是单聊那一位。 */
function key(base: string, at?: string): string {
  return at ? `${base}:${at}` : base;
}

/** 她在这台设备上有多大；没存过、存的值坏了时是默认宽度。 */
export function loadStandWidth(at?: string): number {
  try {
    const stored = Number(localStorage.getItem(key(WIDTH_KEY, at)));
    return Number.isFinite(stored) && stored > 0 ? clampStandWidth(stored) : STAND_WIDTH;
  } catch {
    return STAND_WIDTH;
  }
}

/** 存下她的大小；存不进去时什么也不做。 */
export function saveStandWidth(width: number, at?: string): void {
  try {
    localStorage.setItem(key(WIDTH_KEY, at), String(clampStandWidth(width)));
  } catch {
    // 存储不可用：这次改动只在这次页面里生效。
  }
}

/** 拖到范围外的宽度收回到 80–480px；不是个数（拖坏了）时回到默认宽度。 */
export function clampStandWidth(width: number): number {
  if (!Number.isFinite(width)) return STAND_WIDTH;
  return Math.min(MAX_STAND_WIDTH, Math.max(MIN_STAND_WIDTH, Math.round(width)));
}

/** 她站在这台设备的哪儿；没存过、存的值坏了时在右下角。 */
export function loadStandPlace(at?: string): StandPlace {
  return storedStandPlace(at) ?? DEFAULT_PLACE;
}

/** 她存过的那位置；没存过（或者存的值坏了）时 null，交给调用方用默认的位置。 */
export function loadStandHeight(at?: string): number {
  try {
    const stored = Number(localStorage.getItem(key(HEIGHT_KEY, at)));
    return Number.isFinite(stored) && stored > 0 ? clampStandWidth(stored) : STAND_HEIGHT;
  } catch {
    return STAND_HEIGHT;
  }
}

export function saveStandHeight(height: number, at?: string): void {
  try {
    localStorage.setItem(key(HEIGHT_KEY, at), String(clampStandWidth(height)));
  } catch {
    // 存储不可用：这次改动只在这次页面里生效。
  }
}

export function storedStandPlace(at?: string): StandPlace | null {
  try {
    const stored = JSON.parse(localStorage.getItem(key(PLACE_KEY, at)) ?? "null");
    if (typeof stored?.x !== "number" || typeof stored?.y !== "number") return null;
    return clampStandPlace({ x: stored.x, y: stored.y });
  } catch {
    return null;
  }
}

/** 存下她站的位置；存不进去时什么也不做。 */
export function saveStandPlace(place: StandPlace, at?: string): void {
  try {
    localStorage.setItem(key(PLACE_KEY, at), JSON.stringify(clampStandPlace(place)));
  } catch {
    // 存储不可用：这次改动只在这次页面里生效。
  }
}

/** 把位置收在消息区里：0（贴右、贴下）到 1（贴左、贴上）；不是个数时回到右下角。 */
export function clampStandPlace(place: StandPlace): StandPlace {
  const clamp = (value: number) => (Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0);
  return { x: clamp(place.x), y: clamp(place.y) };
}
