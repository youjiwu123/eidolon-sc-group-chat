import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clampStandPlace,
  clampStandWidth,
  DEFAULT_PLACE,
  loadStandPlace,
  loadStandWidth,
  MAX_STAND_WIDTH,
  MIN_STAND_WIDTH,
  saveStandPlace,
  saveStandWidth,
  STAND_WIDTH,
} from "@/lib/chatCompanion";

/** 这个浏览器的 localStorage，放在内存里。 */
function storage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
  });
  return items;
}

afterEach(() => vi.unstubAllGlobals());

describe("对话页小立绘的大小", () => {
  it("没存过时是 120px", () => {
    storage();
    expect(loadStandWidth()).toBe(STAND_WIDTH);
  });

  it("存下的大小读得回来，拖过头时收在 80–480px", () => {
    storage();
    saveStandWidth(360);
    expect(loadStandWidth()).toBe(360);
    saveStandWidth(9999);
    expect(loadStandWidth()).toBe(MAX_STAND_WIDTH);
    saveStandWidth(1);
    expect(loadStandWidth()).toBe(MIN_STAND_WIDTH);
    expect(clampStandWidth(Number.NaN)).toBe(STAND_WIDTH);
  });

  it("存的值坏了当作默认", () => {
    storage({ "eidolon.chatCompanionWidth": "oops" });
    expect(loadStandWidth()).toBe(STAND_WIDTH);
  });

  it("存不进去时不抛错", () => {
    vi.stubGlobal("localStorage", {
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    });
    expect(() => saveStandWidth(150)).not.toThrow();
  });
});

describe("对话页小立绘站在哪儿", () => {
  it("没存过时在右下角", () => {
    storage();
    expect(loadStandPlace()).toEqual(DEFAULT_PLACE);
  });

  it("存下的位置读得回来，出了消息区时收回来", () => {
    storage();
    saveStandPlace({ x: 0.25, y: 0.5 });
    expect(loadStandPlace()).toEqual({ x: 0.25, y: 0.5 });
    expect(clampStandPlace({ x: -1, y: 2 })).toEqual({ x: 0, y: 1 });
    expect(clampStandPlace({ x: Number.NaN, y: Number.NaN })).toEqual(DEFAULT_PLACE);
  });

  it("存的值坏了当作默认", () => {
    storage({ "eidolon.chatCompanionPlace": "{oops" });
    expect(loadStandPlace()).toEqual(DEFAULT_PLACE);
    storage({ "eidolon.chatCompanionPlace": '{"x":"left","y":null}' });
    expect(loadStandPlace()).toEqual(DEFAULT_PLACE);
  });
});
