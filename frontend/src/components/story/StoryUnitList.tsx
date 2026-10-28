"use client";

import NextLink from "next/link";

import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { copy } from "@/i18n";
import type { StoryGroup } from "@/lib/story";
import { cn } from "@/lib/utils";

const t = copy.story;

/**
 * 左栏的单元列表：有分组的（培育路线按路线、卡面按角色）先出一行组名，再列这一组的单元；
 * 没有分组的（活动、特别企划、主页营业、SCSP、其他）直接列。每个单元是去 `/story/<单元 id>` 的链接，
 * 当前这一个铺中性 `bg-muted`、标 `aria-current="page"`，其余悬停 `bg-muted/60`。
 * 组名在这一栏滚动时停在顶上，长列表里也知道自己在哪一组。
 */
export function StoryUnitList({
  groups,
  selectedId,
}: {
  groups: StoryGroup[];
  selectedId: string | null;
}) {
  const { guard } = useDirectory();
  return (
    <div className="flex flex-col">
      {groups.map((group) => (
        <section key={group.id ?? "all"} aria-label={group.label || undefined}>
          {group.label && (
            <h2 className="sticky top-0 z-10 bg-background px-4 pt-3 pb-1 text-meta text-muted-foreground">
              {group.label}
            </h2>
          )}
          <ul>
            {group.units.map((unit) => {
              const href = `/story/${unit.id}`;
              const isCurrent = unit.id === selectedId;
              return (
                <li key={unit.id}>
                  <NextLink
                    href={href}
                    onClick={guard(href)}
                    aria-current={isCurrent ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 items-center gap-2 px-4 py-2 outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
                      isCurrent && "bg-muted hover:bg-muted",
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-body">{unit.name || unit.id}</span>
                    <span className="shrink-0 text-meta text-muted-foreground tabular-nums">
                      {t.episodes(unit.episodes)}
                    </span>
                  </NextLink>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
