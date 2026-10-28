import { StoryUnitPage } from "@/components/story/StoryUnitPage";

/**
 * 一个剧情单元的详情（`/story/<单元 id>`）：宽屏上在左栏右边，窄屏上整页。
 * 单元 id 由数据构建时定下（`characters/story/index.json`），这里不预先列出来。
 */
export default async function StoryUnitRoute({ params }: PageProps<"/story/[unitId]">) {
  const { unitId } = await params;
  return <StoryUnitPage unitId={unitId} />;
}
