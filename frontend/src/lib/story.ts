// 剧情回放（功能 4）：把 12,624 话剧情摘要按「作品 → 单元 → 话」浏览。数据由
// `backend/scripts/build_story_data.py` 生成到 `characters/story/`，接口是 `/api/story`（全部单元）
// 和 `/api/story/<unit id>`（一个单元的总述和每一话）。
//
// 单元就是导出里的那个：一位偶像的一条培育路线、一期活动、一个特别企划、一张卡的剧情、一段主页
// 剧情，或一个 SCSP 剧本组。页面上分七区，其中「其他」收着导出里的营业剧情（`bu`）和零星的 `other`；
// 路线按路线名分组，卡面按角色分组，卡面里认不出角色的那几张单独一组。

import { api, json } from "@/lib/api";

/** 单元的类型，取自导出；`bu`（营业剧情）和 `other` 在页面上归到「其他」。 */
export type StoryKind = "route" | "event" | "special" | "card" | "mypage" | "scsp" | "bu" | "other";

/** 页面的七个分区，从上到下。 */
export type StorySectionKind = "route" | "event" | "special" | "card" | "mypage" | "scsp" | "other";

export const STORY_SECTIONS: readonly StorySectionKind[] = [
  "route",
  "event",
  "special",
  "card",
  "mypage",
  "scsp",
  "other",
];

/** 分区里的一组（一条路线、一位角色的卡面），组名是那一组的标题。 */
export type StoryGroup = {
  /** 分组的 id；没有分组的单元（活动、特别企划、SCSP……）是 null。 */
  id: string | null;
  /** 组标题；没有分组时是空字符串。 */
  label: string;
  units: StoryUnitSummary[];
};

/** 列表里的一个单元：名字、话数、它属于哪一组。 */
export type StoryUnitSummary = {
  id: string;
  kind: StoryKind;
  name: string;
  episodes: number;
  group: string | null;
  group_label: string | null;
};

/** 一个分区：它的单元（按顺序）、按组分好的样子，和话数合计。 */
export type StorySection = {
  kind: StorySectionKind;
  units: StoryUnitSummary[];
  groups: StoryGroup[];
  episodes: number;
};

/** 一话（SCSP 的一章里含几话时，是这个数组里的一项）。 */
export type StoryEpisode = {
  id: string;
  title: string;
  cast: string[];
};

/** 一张卡：一话，或者一章（含它底下的几话）。 */
export type StoryChapter = {
  id: string;
  title: string;
  summary: string;
  cast: string[];
  /** 日文章节名，出处；SCSP 的章没有。 */
  ja?: string;
  /** 这一章底下的几话；只有把几话收成一章的单元（SCSP）才有。 */
  episodes?: StoryEpisode[];
};

/** 一个单元的详情：总述、主题、出场角色和每一话。 */
export type StoryUnitDetail = StoryUnitSummary & {
  label: string;
  gist: string;
  shape: string;
  themes: string[];
  cast: string[];
  src: "browser" | "scsp";
  /** 导出里原来的单元键；只在核对数据和测试时用。 */
  unit: string;
  chapters: StoryChapter[];
};

/** `/api/story` 的返回：全部单元和话数合计。 */
export type StoryIndex = {
  total_episodes: number;
  units: StoryUnitSummary[];
};

/** 一个单元归到哪个分区。 */
export function storySectionOf(kind: StoryKind): StorySectionKind {
  if (kind === "bu" || kind === "other") return "other";
  return kind;
}

/** 按页面上的分区和分组排好：分区次序固定（`STORY_SECTIONS`），组按第一次出现的顺序，
 * 组里和没有组的单元都按接口给的顺序（导出里就是页面上要的顺序）。 */
export function storySections(units: readonly StoryUnitSummary[]): StorySection[] {
  const sections = new Map<StorySectionKind, StoryUnitSummary[]>();
  for (const unit of units) {
    const kind = storySectionOf(unit.kind);
    const listed = sections.get(kind);
    if (listed) listed.push(unit);
    else sections.set(kind, [unit]);
  }
  return STORY_SECTIONS.flatMap((kind) => {
    const listed = sections.get(kind);
    if (!listed || listed.length === 0) return [];
    const groups = new Map<string, StoryGroup>();
    for (const unit of listed) {
      const id = unit.group;
      const key = id ?? "";
      const group = groups.get(key);
      if (group) group.units.push(unit);
      else groups.set(key, { id, label: unit.group_label ?? "", units: [unit] });
    }
    return [
      {
        kind,
        units: listed,
        groups: [...groups.values()],
        episodes: listed.reduce((total, unit) => total + unit.episodes, 0),
      },
    ];
  });
}

/** 一个单元的出场角色，按顺序；`names` 是角色 id 到名字，查不到的 id 跳过。 */
export function castNames(cast: readonly string[], names: ReadonlyMap<string, string>): string[] {
  return [...new Set(cast.map((id) => names.get(id)).filter((name): name is string => !!name))];
}

/** 全部单元；接口不让未登录的人读，`api()` 会把他送回登录页。 */
export async function getStoryIndex(): Promise<StoryIndex> {
  return json(await api("/api/story"));
}

/** 一个单元的总述和每一话；没有这个单元时抛 ApiError（404）。 */
export async function getStoryUnit(unitId: string): Promise<StoryUnitDetail> {
  return json(await api(`/api/story/${encodeURIComponent(unitId)}`));
}
