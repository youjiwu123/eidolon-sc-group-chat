"use client";

import type { ComponentProps, RefObject } from "react";

import { ShellLink } from "@/components/app/ShellLink";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/i18n";
import { TierHeart } from "@/components/app/TierHeart";
import { badgeOf, TIERS, type AffinityStatus } from "@/lib/affinity";
import type { AffinityCue } from "@/lib/liveConversation";
import { cn } from "@/lib/utils";
import { AffinityDownIcon, AffinityUpIcon, CooldownIcon, GiftIcon } from "@/theme/icons";

import { AffinityModeSwitches } from "./AffinityModeSwitches";

const t = copy.conversation.affinity;

/**
 * 页首的好感度标识（DESIGN.md「Buttons」的好感度标识）：电话键右边、更多菜单左边的 ghost 键，
 * 心形（她的颜色）加档名；冷却中换成 muted 的沙漏加解除时刻。点开是说明，container 指回对话子树。
 * 宽度跟着内容走，手机上高度不小于 44px；挤不下时名字截断，不挤压电话键和更多菜单。
 * 一个回合刚改变了好感度（`cue`）时，心形跳一下、右上角叠一个升降小箭头（「升」用她的按钮色）。
 * 说明末尾是「送她一件礼物」的链接，平时和冷却中都有，跳到礼物页（`gifts`）。好感度和礼物同一个开关，
 * 这个标识在就是开放着。说明最后是这个角色的特殊档开关（`AffinityModeSwitches`），每个角色各一份。
 */
export function AffinityBadge({
  status,
  cue,
  name,
  timeZone,
  gifts,
  characterId,
  subtree,
}: {
  status: AffinityStatus;
  /** 刚刚的变化，显示约 2.6 秒；没有就是 null。 */
  cue: AffinityCue | null;
  /** 她的名字，冷却中的读屏名字和说明里用。 */
  name: string;
  /** 制作人的时区：解除时刻按它写成今天或明天。 */
  timeZone: string;
  /** 送礼链接去的礼物页，带着她（`giftsHref`）。 */
  gifts: string;
  /** 这位角色的 id：她的特殊档开关各自一份，按它存。 */
  characterId: string;
  subtree: RefObject<HTMLDivElement | null>;
}) {
  const badge = badgeOf(status, name, new Date(), timeZone);
  const cooling = badge.kind === "cooldown";
  return (
    <Popover>
      <PopoverTrigger
        render={<Button variant="ghost" size="lg" className="min-w-0 shrink max-md:h-11" aria-label={badge.label} />}
      >
        <span key={cue?.key} aria-hidden className={cn("relative flex", cue && "motion-safe:animate-jump")}>
          {cooling ? (
            <CooldownIcon className="size-5 text-muted-foreground" />
          ) : (
            <TierHeart heart={badge.heart} tone="her" size="badge" />
          )}
          {cue && <CueArrow up={cue.change.up} />}
        </span>
        <span className={cn("truncate tabular-nums", cooling && "text-muted-foreground")}>{badge.text}</span>
      </PopoverTrigger>
      <PopoverContent container={subtree} align="end">
        <div className="flex flex-col gap-0.5">
          <p className="font-medium">{cooling ? t.cooling(name) : t.title(badge.text)}</p>
          <p className="text-muted-foreground">{cooling ? t.coolingNote(badge.text) : t.notes[badge.tier]}</p>
        </div>
        <ol className="flex gap-1" aria-label={t.tiersLabel}>
          {TIERS.map((tier) => {
            const current = !cooling && tier === badge.tier;
            return (
              <li
                key={tier}
                aria-current={current ? "true" : undefined}
                className={cn(
                  "flex-1 rounded-md py-1 text-center text-meta",
                  current ? "bg-foreground text-background" : "bg-muted text-muted-foreground",
                )}
              >
                {t.tiers[tier]}
              </li>
            );
          })}
        </ol>
        <p className="text-meta text-muted-foreground">{t.rule}</p>
        <ShellLink href={gifts} isStandalone className="flex items-center gap-1.5 self-start">
          <GiftIcon aria-hidden className="size-4" />
          {copy.gifts.giveHer}
        </ShellLink>
        <AffinityModeSwitches characterId={characterId} />
      </PopoverContent>
    </Popover>
  );
}

/** 好感度变化的升降小箭头：心形上、变化胶囊里、通话层状态行里都是它。 */
export function CueArrowIcon({ up, ...props }: { up: boolean } & ComponentProps<typeof AffinityUpIcon>) {
  const Icon = up ? AffinityUpIcon : AffinityDownIcon;
  return <Icon aria-hidden {...props} />;
}

/** 心形右上角的升降小箭头：「升」是她的按钮色底，「降」是中性前景色底。 */
function CueArrow({ up }: { up: boolean }) {
  return (
    <span
      className={cn(
        "absolute -top-1.5 -right-1.5 flex size-3.5 items-center justify-center rounded-full",
        up ? "bg-her-button text-her-button-fg" : "bg-foreground text-background",
      )}
    >
      <CueArrowIcon up={up} className="size-2.5" strokeWidth={3} />
    </span>
  );
}
