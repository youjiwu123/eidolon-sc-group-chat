import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { copy } from "@/i18n";
import { StoryIcon } from "@/theme/icons";

const t = copy.story;

/**
 * 剧情回放的目录页（`/story`）：宽屏上右栏还没选单元，给一句提示；窄屏上右栏不露，左栏就是整页。
 * 单元自己的页面在 `/story/<单元 id>`。
 */
export default function StoryIndexPage() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Empty className="border-none">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <StoryIcon />
          </EmptyMedia>
          <EmptyTitle>{t.pick}</EmptyTitle>
          <EmptyDescription>{t.pickHint}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}
