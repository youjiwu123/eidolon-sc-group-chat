import { describe, expect, it } from "vitest";
import {
  chooseBirthMonth,
  clampFormOfAddress,
  daysInMonth,
  fromDraft,
  MAX_FORM_OF_ADDRESS,
  missingBirthDay,
  sameDraft,
  toDraft,
} from "@/lib/producerProfile";

const blank = { formOfAddress: "", gender: "" as const, timezone: "", birthMonth: null, birthDay: null };

describe("toDraft", () => {
  it("把没有设置的项变成空白，表示沿用默认", () => {
    expect(
      toDraft({
        form_of_address: null,
        gender: null,
        timezone: null,
        birthday: null,
        special_mode: "",
      }),
    ).toEqual({
      formOfAddress: "",
      gender: "",
      timezone: "",
      birthMonth: null,
      birthDay: null,
    });
  });

  it("保留已经设置的项", () => {
    expect(
      toDraft({
        form_of_address: "小林さん",
        gender: "female",
        timezone: "Asia/Tokyo",
        birthday: { month: 2, day: 29 },
        special_mode: "special",
      }),
    ).toEqual({
      formOfAddress: "小林さん",
      gender: "female",
      timezone: "Asia/Tokyo",
      birthMonth: 2,
      birthDay: 29,
    });
  });
});

describe("fromDraft", () => {
  it("空白的项存成 null，交回默认；月日都不填就是没有生日", () => {
    expect(fromDraft({ ...blank, formOfAddress: "  " })).toEqual({
      form_of_address: null,
      gender: null,
      timezone: null,
      birthday: null,
    });
  });

  it("去掉称呼两端的空白，月日都选了就存成生日", () => {
    expect(
      fromDraft({ formOfAddress: " 小林さん ", gender: "male", timezone: "Asia/Tokyo", birthMonth: 5, birthDay: 3 }),
    ).toEqual({
      form_of_address: "小林さん",
      gender: "male",
      timezone: "Asia/Tokyo",
      birthday: { month: 5, day: 3 },
    });
  });

  it("只选了月的半个生日不会被悄悄存成清空", () => {
    expect(() => fromDraft({ ...blank, birthMonth: 5 })).toThrow();
  });
});

describe("missingBirthDay", () => {
  it("只选了月、没选日时要补上日期", () => {
    expect(missingBirthDay({ ...blank, birthMonth: 5 })).toBe(true);
    expect(missingBirthDay(blank)).toBe(false);
    expect(missingBirthDay({ ...blank, birthMonth: 5, birthDay: 3 })).toBe(false);
  });
});

describe("chooseBirthMonth", () => {
  const draft = { formOfAddress: "", gender: "" as const, timezone: "", birthMonth: 1, birthDay: 31 };

  it("换到没有这一日的月份时清掉日期，要重选，而不是变成另一天", () => {
    expect(chooseBirthMonth(draft, 4)).toEqual({ ...draft, birthMonth: 4, birthDay: null });
  });

  it("日期在新月份里还在就留着", () => {
    expect(chooseBirthMonth({ ...draft, birthDay: 29 }, 2)).toEqual({ ...draft, birthMonth: 2, birthDay: 29 });
  });

  it("月份改成不填时日期一起清掉", () => {
    expect(chooseBirthMonth(draft, null)).toEqual({ ...draft, birthMonth: null, birthDay: null });
  });
});

describe("sameDraft", () => {
  const saved = { formOfAddress: "小林さん", gender: "" as const, timezone: "", birthMonth: 5, birthDay: 3 };

  it("只差称呼两端空白的不算改动", () => {
    expect(sameDraft({ ...saved, formOfAddress: " 小林さん " }, saved)).toBe(true);
  });

  it("任何一项不同都算改动", () => {
    expect(sameDraft({ ...saved, formOfAddress: "小林" }, saved)).toBe(false);
    expect(sameDraft({ ...saved, gender: "female" }, saved)).toBe(false);
    expect(sameDraft({ ...saved, timezone: "Asia/Tokyo" }, saved)).toBe(false);
    expect(sameDraft({ ...saved, birthMonth: 6 }, saved)).toBe(false);
    expect(sameDraft({ ...saved, birthDay: null }, saved)).toBe(false);
  });
});

describe("clampFormOfAddress", () => {
  it("和后端一样最多 20 个字", () => {
    expect(MAX_FORM_OF_ADDRESS).toBe(20);
    expect(clampFormOfAddress("あ".repeat(25))).toBe("あ".repeat(20));
    expect(clampFormOfAddress("小林さん")).toBe("小林さん");
  });

  it("按字数而不是 UTF-16 码元截断，不会切开一个字", () => {
    const clamped = clampFormOfAddress("𠮷".repeat(21));
    expect(Array.from(clamped)).toHaveLength(20);
    expect(clamped).toBe("𠮷".repeat(20));
  });
});

describe("daysInMonth", () => {
  it("给出这个月最多能选到几日，2 月按闰年算到 29 日", () => {
    expect(daysInMonth(1)).toBe(31);
    expect(daysInMonth(2)).toBe(29);
    expect(daysInMonth(4)).toBe(30);
    expect(daysInMonth(12)).toBe(31);
  });
});
