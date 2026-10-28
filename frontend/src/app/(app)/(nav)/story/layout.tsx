"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { StoryCatalogList } from "@/components/story/StoryCatalogList";
import { copy } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * 剧情回放的两栏外壳（DESIGN.md「剧情页」），和设置一样：
 * - 宽屏：左栏是分区和单元列表，右栏是选中单元的详情（`/story/<单元 id>`）或者还没选时的一句提示。
 * - 窄屏：两级页面，`/story` 只有列表，`/story/<单元 id>` 只有详情（页首返回键回到列表）。
 * 两种屏宽同一套路由，露哪一级只靠 CSS 断点，首屏不闪；换单元时列表不重新挂上。
 */
export default function StoryLayout({ children }: { children: ReactNode }) {
  const { unitId } = useParams<{ unitId?: string }>();
  return (
    <div className="flex h-full bg-background text-foreground">
      <nav
        aria-label={copy.story.title}
        className={cn(
          "flex min-h-0 w-80 shrink-0 flex-col border-r max-md:w-full max-md:border-r-0",
          unitId && "max-md:hidden",
        )}
      >
        <StoryCatalogList selectedId={unitId ?? null} />
      </nav>
      <div className={cn("min-w-0 flex-1", !unitId && "max-md:hidden")}>{children}</div>
    </div>
  );
}
