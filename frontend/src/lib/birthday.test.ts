import { describe, expect, it } from "vitest";

import { dayKey } from "@/lib/birthday";

describe("生日彩蛋记的是哪一天", () => {
  it("按本机当地日期写成 YYYY-MM-DD，月和日补零", () => {
    expect(dayKey(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
    expect(dayKey(new Date(2026, 9, 26, 0, 0))).toBe("2026-10-26");
  });

  it("同一刻在别的时区的日期由本机时区决定，写法和 Date 的本地日期一致", () => {
    const at = new Date(2026, 9, 26, 12, 0);
    expect(dayKey(at)).toBe(`${at.getFullYear()}-10-26`);
  });
});
