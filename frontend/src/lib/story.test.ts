import { describe, expect, it } from "vitest";

import {
  castNames,
  storySectionOf,
  storySections,
  STORY_SECTIONS,
  type StoryUnitSummary,
} from "@/lib/story";

function unit(overrides: Partial<StoryUnitSummary> & Pick<StoryUnitSummary, "id">): StoryUnitSummary {
  return {
    kind: "event",
    name: overrides.id,
    episodes: 1,
    group: null,
    group_label: null,
    ...overrides,
  };
}

describe("剧情单元的分区", () => {
  it("营业剧情和零星的 other 都归到「其他」", () => {
    expect(storySectionOf("bu")).toBe("other");
    expect(storySectionOf("other")).toBe("other");
    expect(storySectionOf("card")).toBe("card");
  });

  it("按固定的七区排，不是按接口给的先后", () => {
    const sections = storySections([
      unit({ id: "s1", kind: "scsp" }),
      unit({ id: "r1", kind: "route", group: "route-wing", group_label: "W.I.N.G.編" }),
      unit({ id: "x1", kind: "other" }),
    ]);

    expect(sections.map((section) => section.kind)).toEqual(["route", "scsp", "other"]);
    expect(sections.map((section) => section.kind)).toEqual(
      STORY_SECTIONS.filter((kind) => sections.some((section) => section.kind === kind)),
    );
  });

  it("没有任何单元的分区不出现", () => {
    expect(storySections([])).toEqual([]);
    expect(storySections([unit({ id: "e1", kind: "event" })]).map((section) => section.kind)).toEqual(["event"]);
  });
});

describe("剧情单元的分组", () => {
  it("卡面按角色分组，组的先后跟着第一次出现", () => {
    const [cards] = storySections([
      unit({ id: "c1", kind: "card", group: "char-mano", group_label: "樱木真乃" }),
      unit({ id: "c2", kind: "card", group: "char-hiori", group_label: "风野灯织" }),
      unit({ id: "c3", kind: "card", group: "char-mano", group_label: "樱木真乃" }),
    ]);

    expect(cards.groups).toHaveLength(2);
    expect(cards.groups.map((group) => group.label)).toEqual(["樱木真乃", "风野灯织"]);
    expect(cards.groups[0].units.map((entry) => entry.id)).toEqual(["c1", "c3"]);
  });

  it("没有分组的单元收在一个没有组名的组里", () => {
    const [events] = storySections([unit({ id: "e1", episodes: 8 }), unit({ id: "e2", episodes: 2 })]);

    expect(events.groups).toEqual([{ id: null, label: "", units: events.units }]);
  });

  it("分区的话数是它下面单元的和", () => {
    const [cards] = storySections([
      unit({ id: "c1", kind: "card", group: "char-mano", group_label: "樱木真乃", episodes: 3 }),
      unit({ id: "c2", kind: "card", group: "char-hiori", group_label: "风野灯织", episodes: 5 }),
    ]);

    expect(cards.episodes).toBe(8);
    expect(cards.units).toHaveLength(2);
  });
});

describe("出场角色的名字", () => {
  const names = new Map([
    ["mano", "樱木真乃"],
    ["producer", "制作人"],
    ["hiori", "风野灯织"],
  ]);

  it("按顺序换成名字", () => {
    expect(castNames(["hiori", "mano"], names)).toEqual(["风野灯织", "樱木真乃"]);
  });

  it("查不到的 id 跳过，重复的只留一次", () => {
    expect(castNames(["mano", "nobody", "producer", "mano"], names)).toEqual(["樱木真乃", "制作人"]);
  });
});
