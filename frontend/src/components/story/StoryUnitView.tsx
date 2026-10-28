"use client";

import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { copy } from "@/i18n";
import { castNames, type StoryChapter, type StoryUnitDetail } from "@/lib/story";
import { StoryIcon } from "@/theme/icons";
import { Ja } from "@/theme/Ja";

const t = copy.story;

/** 单元详情的一栏宽度：和礼物页一样，手机上铺满。 */
const COLUMN = "mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6";

/**
 * 一个剧情单元的详情（DESIGN.md「剧情页」的那一栏）：页首是它的名字和话数，手机上左边一个返回键
 * 回到单元列表（电脑上和列表并排，不要返回键）。下面是「出处」、总述、主题、出场角色和每一话：
 * 一话一张卡，左边一个占着场景图位置的色块，右边是标题、日文章节名（出处）、一句摘要和出场角色；
 * SCSP 的一章收着几话时，章是一张卡，几话按顺序排在它下面。
 */
export function StoryUnitView({
  detail,
  names,
}: {
  detail: StoryUnitDetail;
  names: ReadonlyMap<string, string>;
}) {
  const cast = castNames(detail.cast, names);
  const provenance = provenanceOf(detail);
  return (
    <PageShell
      isInShell
      width="full"
      header={
        <SubpageHeader
          title={detail.name}
          backHref="/story"
          isBackNarrowOnly
          end={
            <span className="shrink-0 text-meta text-muted-foreground tabular-nums">
              {t.episodes(detail.episodes)}
            </span>
          }
        />
      }
    >
      <div className={COLUMN}>
        <header className="flex flex-col gap-2">
          {provenance && <p className="text-subtitle text-muted-foreground">{provenance}</p>}
          {detail.gist && <p className="text-body">{detail.gist}</p>}
          {detail.themes.length > 0 && (
            <ul aria-label={t.themes} className="flex flex-wrap gap-1.5">
              {detail.themes.map((theme) => (
                <li key={theme} className="rounded-full bg-muted px-2.5 py-0.5 text-meta text-muted-foreground">
                  {theme}
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-col gap-0.5">
            {detail.shape && <p className="text-meta text-muted-foreground">{detail.shape}</p>}
            {cast.length > 0 && (
              <p className="text-meta text-muted-foreground">
                {t.cast(cast.join(copy.serviceList.separator))}
              </p>
            )}
          </div>
        </header>
        <ol className="flex flex-col">
          {detail.chapters.map((chapter, index) => (
            <StoryCard key={chapter.id} chapter={chapter} number={index + 1} names={names} />
          ))}
        </ol>
      </div>
    </PageShell>
  );
}

/** 单元的一行「出处」：卡面和路线写它来自哪张卡、哪位偶像的哪条路线；名字和它一样时不重复写；
 * SCSP 剧本组写它的组号（`s02`），只有那篇不属于任何编号组的短篇例外。 */
function provenanceOf(detail: StoryUnitDetail): string {
  if (detail.kind === "scsp") {
    return detail.unit === "other" ? t.sections.scsp : t.scspGroup(detail.unit);
  }
  return detail.label === detail.name ? "" : detail.label;
}

/** 一话一张卡：场景图的位置先铺一块中性色块，接着是「第几话 · 出处」、标题、摘要和出场角色。 */
function StoryCard({
  chapter,
  number,
  names,
}: {
  chapter: StoryChapter;
  number: number;
  names: ReadonlyMap<string, string>;
}) {
  const cast = castNames(chapter.cast, names);
  const episodes = chapter.episodes ?? [];
  return (
    <li className="flex gap-3 border-b py-4 last:border-b-0">
      <span
        aria-hidden
        className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"
      >
        <StoryIcon className="size-5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-meta text-muted-foreground">
          <span className="tabular-nums">{episodes.length > 0 ? t.chapterNo(number) : t.cardNo(number)}</span>
          {episodes.length > 1 && (
            <>
              <span aria-hidden> · </span>
              <span className="tabular-nums">{t.chapterEpisodes(episodes.length)}</span>
            </>
          )}
          {chapter.ja && (
            <>
              <span aria-hidden> · </span>
              <Ja>{chapter.ja}</Ja>
            </>
          )}
        </p>
        <h2 className="text-header">{chapter.title}</h2>
        {chapter.summary && <p className="text-body">{chapter.summary}</p>}
        {episodes.length > 0 && (
          <ol className="mt-1 flex flex-col gap-1 border-l pl-3">
            {episodes.map((episode, index) => (
              <li key={episode.id} className="text-sm text-muted-foreground">
                <span className="tabular-nums">{index + 1}.</span> {episode.title}
              </li>
            ))}
          </ol>
        )}
        {cast.length > 0 && (
          <p className="text-meta text-muted-foreground">{t.cast(cast.join(copy.serviceList.separator))}</p>
        )}
      </div>
    </li>
  );
}
