"use client";

import { useEffect, useState, type ComponentProps, type ReactElement, type ReactNode } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { getScenes, type SceneEntry } from "@/lib/api";

const t = copy.place;

type Props = {
  /** 现在的地点（场景表里的 id）；null 是自己没挑：单聊按作息表算、群聊没设置。 */
  sceneId: string | null;
  /** 菜单里「取消自己挑的」那一项怎么写：「跟随作息」（单聊）或「不设置」（群聊）。 */
  clearLabel: string;
  /** 页首的触发键（Base UI 的 render 元素）：单聊是「现在」胶囊，群聊是地点键。 */
  trigger: ReactElement;
  /** 触发键里写的话。 */
  children: ReactNode;
  /** 浮层挂到哪棵子树里：对话页要她的颜色和深色模式（DESIGN.md「The Scoped Colour Rule」）。 */
  container?: ComponentProps<typeof DropdownMenuContent>["container"];
  align?: ComponentProps<typeof DropdownMenuContent>["align"];
  /** 挑了一处（null 是取消自己挑的）：调接口、把页首换过去；失败时抛出，菜单里写出原因。 */
  onPick: (sceneId: string | null) => Promise<void>;
};

/**
 * 页首的地点下拉栏（DESIGN.md「通话场景」）：点开是场景表里所有能挑的地方，名字下面一句 hint，
 * 当前那一处打勾；最上面一项取消自己挑的，回到按作息表算的地方（群聊是「不设置」）。
 *
 * 场景表在第一次点开时才读（页首不点开就不问），读到了就留着；换地点失败时菜单不收起，
 * 把后端说的原因写在最下面，可以再挑一次。
 */
export function PlacePicker({ sceneId, clearLabel, trigger, children, container, align = "start", onPick }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  /** 场景表：还没读到是 null；读不到时留在 null，下次点开再试。 */
  const [scenes, setScenes] = useState<SceneEntry[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  /** 正在换地点：换完以前不能挑下一处，免得两个请求谁后到谁说话。 */
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isOpen || scenes !== null) return;
    setFailure(null);
    let alive = true;
    getScenes()
      .then((next) => {
        if (alive) setScenes(next);
      })
      .catch((error: unknown) => {
        if (alive) setFailure(error instanceof Error ? error.message : t.loadFailed);
      });
    return () => {
      alive = false;
    };
  }, [isOpen, scenes]);

  const choose = async (value: unknown): Promise<void> => {
    if (saving) return;
    const next = value === null ? null : String(value);
    // 挑的就是现在这一处：只把菜单收起来，不问后端。
    if (next === sceneId) {
      setIsOpen(false);
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      await onPick(next);
      setIsOpen(false);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : t.pickFailed);
    } finally {
      setSaving(false);
    }
  };

  // 重新点开时把上一次的原因清掉（换地点失败的那个还在菜单最下面）。
  const openChange = (open: boolean): void => {
    if (open) setFailure(null);
    setIsOpen(open);
  };

  return (
    <DropdownMenu open={isOpen} onOpenChange={openChange}>
      <DropdownMenuTrigger render={trigger}>{children}</DropdownMenuTrigger>
      {/* 菜单比触发键宽：页首的胶囊和地点键都只写地名，放不下名字加 hint */}
      <DropdownMenuContent container={container} align={align} className="min-w-56">
        <DropdownMenuRadioGroup value={sceneId} onValueChange={(value) => void choose(value)} disabled={saving}>
          <DropdownMenuLabel>{t.title}</DropdownMenuLabel>
          <DropdownMenuRadioItem value={null}>{clearLabel}</DropdownMenuRadioItem>
          <DropdownMenuSeparator />
          {scenes === null ? (
            <div className="flex items-center gap-2 px-1.5 py-1 text-meta text-muted-foreground">
              {failure === null && <Spinner className="size-3" />}
              {failure ?? t.loading}
            </div>
          ) : (
            scenes.map((scene) => (
              <DropdownMenuRadioItem key={scene.id} value={scene.id}>
                <span className="flex min-w-0 flex-col">
                  <span className="truncate">{scene.name}</span>
                  {scene.hint && <span className="truncate text-meta text-muted-foreground">{scene.hint}</span>}
                </span>
              </DropdownMenuRadioItem>
            ))
          )}
        </DropdownMenuRadioGroup>
        {/* 换地点没换过去：原因写在菜单里，菜单不收起，就近再挑一次 */}
        {failure !== null && scenes !== null && (
          <>
            <DropdownMenuSeparator />
            <p role="status" className="px-1.5 py-1 text-meta text-destructive">
              {failure}
            </p>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
