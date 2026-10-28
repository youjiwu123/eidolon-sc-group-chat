import { afterEach, describe, expect, it, vi } from "vitest";

import { loadStandHidden, saveStandHidden } from "@/lib/standVisibility";

/** 这个浏览器的 localStorage，放在内存里。 */
function storage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  });
  return items;
}

afterEach(() => vi.unstubAllGlobals());

describe("立绘的本地隐藏", () => {
  it("没存过时没收起", () => {
    storage();
    expect(loadStandHidden("chatStandHidden:1")).toBe(false);
  });

  it("收起和恢复都记得住，恢复时删掉这条", () => {
    const items = storage();
    saveStandHidden("chatStandHidden:1", true);
    expect(loadStandHidden("chatStandHidden:1")).toBe(true);
    expect(items.get("chatStandHidden:1")).toBe("1");
    saveStandHidden("chatStandHidden:1", false);
    expect(loadStandHidden("chatStandHidden:1")).toBe(false);
    expect(items.has("chatStandHidden:1")).toBe(false);
  });

  it("单聊、群聊、各条对话分开记", () => {
    storage();
    saveStandHidden("chatStandHidden:1", true);
    saveStandHidden("chatStandHidden:2", false);
    saveStandHidden("groupStandHidden:g1", true);
    expect(loadStandHidden("chatStandHidden:1")).toBe(true);
    expect(loadStandHidden("chatStandHidden:2")).toBe(false);
    expect(loadStandHidden("groupStandHidden:g1")).toBe(true);
    expect(loadStandHidden("chatStandHidden:3")).toBe(false);
    expect(loadStandHidden("groupStandHidden:g2")).toBe(false);
  });

  it("存的值不是 1 时当作没收起", () => {
    storage({ "chatStandHidden:1": "oops" });
    expect(loadStandHidden("chatStandHidden:1")).toBe(false);
  });

  it("存储不可用时不抛错，当作没收起", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
      removeItem: () => {
        throw new Error("SecurityError");
      },
    });
    expect(loadStandHidden("chatStandHidden:1")).toBe(false);
    expect(() => saveStandHidden("chatStandHidden:1", true)).not.toThrow();
    expect(() => saveStandHidden("chatStandHidden:1", false)).not.toThrow();
  });
});
