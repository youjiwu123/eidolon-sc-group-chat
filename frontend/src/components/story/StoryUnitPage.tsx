"use client";

import { useEffect, useMemo, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { StoryUnitView } from "@/components/story/StoryUnitView";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { copy } from "@/i18n";
import { toFailure, type Failure } from "@/lib/failure";
import { getStoryUnit, type StoryUnitDetail } from "@/lib/story";

const t = copy.story;

/**
 * 一个剧情单元的详情页（`/story/<单元 id>`，DESIGN.md「剧情页」）：进来读这一个单元，读完画总述和每一话。
 * 读的时候和读不到时都在同一栏里说明，手机上照样有返回键回单元列表。
 * 出场角色的名字从导航外壳的角色目录来（它是全应用共用的一份）：不在目录里的只有制作人和社长，用文案补上。
 */
export function StoryUnitPage({ unitId }: { unitId: string }) {
  const { characters } = useDirectory();
  const [detail, setDetail] = useState<StoryUnitDetail | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    let current = true;
    setDetail(null);
    setFailure(null);
    getStoryUnit(unitId).then(
      (got) => current && setDetail(got),
      (e) => current && setFailure(toFailure(e)),
    );
    return () => {
      current = false;
    };
  }, [unitId]);

  const names = useMemo(() => {
    const lookup = new Map<string, string>();
    for (const character of characters ?? []) lookup.set(character.id, character.name_zh ?? character.name);
    lookup.set("producer", t.producer);
    lookup.set("tenjou", t.president);
    return lookup;
  }, [characters]);

  if (failure !== null) {
    return (
      <PageShell
        isInShell
        width="full"
        header={<SubpageHeader title={t.title} backHref="/story" isBackNarrowOnly />}
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
          <FailureNotice failure={failure} />
        </div>
      </PageShell>
    );
  }
  if (detail === null) {
    return (
      <PageShell
        isInShell
        width="full"
        header={<SubpageHeader title={t.title} backHref="/story" isBackNarrowOnly />}
      >
        <p className="mx-auto w-full max-w-3xl px-4 py-6 text-body text-muted-foreground">{t.loading}</p>
      </PageShell>
    );
  }
  return <StoryUnitView detail={detail} names={names} />;
}
