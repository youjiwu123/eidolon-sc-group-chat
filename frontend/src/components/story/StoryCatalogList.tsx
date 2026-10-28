"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { StoryUnitList } from "@/components/story/StoryUnitList";
import { useWide } from "@/components/conversations/ConversationDirectory";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { copy } from "@/i18n";
import { toFailure, type Failure } from "@/lib/failure";
import {
  getStoryIndex,
  storySectionOf,
  storySections,
  type StoryIndex,
  type StorySectionKind,
} from "@/lib/story";

const t = copy.story;

/**
 * 剧情回放的左栏（DESIGN.md「剧情页」）：页首是「剧情」大标题和话数合计，下面七个分区的筛选，
 * 再下面一段是这一区几个单元、多少话，最后是这一区的单元列表（路线按路线、卡面按角色分组）。
 * 单元是链接：宽屏上点一个右边一栏换成它，窄屏上进它的详情页（左栏收起来，详情页首有返回键）。
 * 一区一个按钮：宽屏上点一区就翻到那一区的第一个单元（右边一栏正开着），窄屏上只换列表、不跳走。
 * 单元由这一层自己读：换单元时列表不重新读，也不重新挂上。
 */
export function StoryCatalogList({ selectedId }: { selectedId: string | null }) {
  const wide = useWide();
  const router = useRouter();
  const [index, setIndex] = useState<StoryIndex | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [chosen, setChosen] = useState<StorySectionKind | null>(null);

  useEffect(() => {
    let current = true;
    getStoryIndex().then(
      (got) => {
        if (!current) return;
        setIndex(got);
        setFailure(null);
      },
      (e) => current && setFailure(toFailure(e)),
    );
    return () => {
      current = false;
    };
  }, []);

  const sections = useMemo(() => (index ? storySections(index.units) : []), [index]);
  const selected = index?.units.find((unit) => unit.id === selectedId) ?? null;
  // 选中哪个单元就翻到它那一区（从别的页直接打开 `/story/<id>` 时也对得上）；没选中时看用户点的哪一区。
  const current = selected ? storySectionOf(selected.kind) : (chosen ?? sections[0]?.kind ?? null);
  const shown = sections.find((section) => section.kind === current) ?? null;

  useEffect(() => {
    if (selected) setChosen(storySectionOf(selected.kind));
  }, [selected?.id]);

  const chooseSection = (kind: StorySectionKind) => {
    setChosen(kind);
    const first = sections.find((section) => section.kind === kind)?.units[0];
    if (wide && first) router.push(`/story/${first.id}`);
  };

  return (
    <>
      <header className="flex min-h-14 shrink-0 items-center gap-2 px-4 pt-3 pb-2">
        <h1 className="text-list-title">{t.title}</h1>
        {index !== null && (
          <span className="ml-auto text-meta text-muted-foreground tabular-nums">
            {t.total(index.total_episodes)}
          </span>
        )}
      </header>
      {sections.length > 0 && (
        <div className="shrink-0 px-3 pb-2">
          <ToggleGroup
            aria-label={t.sectionsLabel}
            size="sm"
            className="w-full flex-wrap"
            value={current === null ? [] : [current]}
            onValueChange={(value: unknown[]) => {
              const next = value[0] as StorySectionKind | undefined;
              if (next && next !== current) chooseSection(next);
            }}
          >
            {sections.map((section) => (
              <ToggleGroupItem key={section.kind} value={section.kind}>
                {t.sections[section.kind]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      )}
      {shown && (
        <p className="shrink-0 px-4 pb-1 text-meta text-muted-foreground tabular-nums">
          {t.sectionSummary(shown.units.length, shown.episodes)}
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        {failure ? (
          <div className="px-3 py-2">
            <FailureNotice failure={failure} />
          </div>
        ) : index === null ? (
          <p className="px-4 py-3 text-body text-muted-foreground">{t.loading}</p>
        ) : shown ? (
          <StoryUnitList groups={shown.groups} selectedId={selectedId} />
        ) : (
          <div className="flex flex-col gap-1 px-4 py-6">
            <p className="text-body">{t.empty}</p>
            <p className="text-subtitle text-muted-foreground">{t.emptyHint}</p>
          </div>
        )}
      </div>
    </>
  );
}
