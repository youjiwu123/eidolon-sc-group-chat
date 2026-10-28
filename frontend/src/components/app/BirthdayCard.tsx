"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { copy } from "@/i18n";
import { birthdaySeenToday, keepBirthdaySeenToday, loadBirthdayEgg, type ActiveBirthday } from "@/lib/birthday";
import { herVars } from "@/theme/herVars";
import { Ja } from "@/theme/Ja";

const t = copy.birthday;

/**
 * 生日原声彩蛋（功能 2）：制作人生日那天进对话列表时弹的一次卡片。
 *
 * 只在对话列表页（`/conversations`）问后端，一次页面只问一次（`loadBirthdayEgg`）。是生日、
 * 而且这台设备今天还没看过时弹出来：她的头像、「今天是你的生日」和「播放她的祝福」；点开一次
 * 放一段（`lines` 按 `story`、行号排好，是一段连续的祝贺），放到哪段就把日语原句和中文字幕
 * 显示出来，一段放完接着放下一段。
 *
 * 关闭（右上角的 ✕ 或「收下这份祝福」）时停下，并在这台设备上记下今天看过了，当天不再弹；
 * 后端也记着一天只给一次。不是生日、原声表里还没有生日祝福、或者今天已经给过时什么也不显示。
 */
export function BirthdayCard({ userId }: { userId: string | null }) {
  const pathname = usePathname();
  const [egg, setEgg] = useState<ActiveBirthday | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [isPlaying, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!userId || pathname !== "/conversations") return;
    let live = true;
    loadBirthdayEgg(userId).then((found) => {
      if (!live || !found || birthdaySeenToday(userId)) return;
      setEgg(found);
      setIndex(0);
      setOpen(true);
      // 弹出来就算看过了：刷新、回到列表都不再弹；后端那边也已经只给一次。
      keepBirthdaySeenToday(userId);
    });
    return () => {
      live = false;
    };
  }, [userId, pathname]);

  // 离开页面时把声音停下（关卡片时另外停）。
  useEffect(() => {
    return () => {
      const element = audio.current;
      if (element) {
        element.pause();
        element.src = "";
      }
    };
  }, []);

  /** 停下正在放的那一段。 */
  const stop = () => {
    const element = audio.current;
    audio.current = null;
    if (element) {
      element.pause();
      element.src = "";
    }
    setPlaying(false);
  };

  /** 从第 `start` 段开始放，放完一段接着下一段，最后一段放完就停。在点击里直接建 Audio 并播放，
   * 手机上才不会把 play() 当成没有用户手势而拦下。 */
  const playFrom = (start: number) => {
    if (!egg) return;
    const before = audio.current;
    if (before) {
      before.pause();
      before.src = "";
    }
    const line = egg.lines[start];
    if (!line) {
      stop();
      return;
    }
    const element = new Audio(line.audio_url);
    audio.current = element;
    setIndex(start);
    setPlaying(true);
    const next = () => {
      if (audio.current !== element) return; // 已经换了一段或者关掉了
      audio.current = null;
      element.pause();
      if (start + 1 < egg.lines.length) playFrom(start + 1);
      else setPlaying(false);
    };
    element.addEventListener("ended", next);
    element.addEventListener("error", next);
    void element.play().catch(next);
  };

  const close = () => {
    stop();
    setOpen(false);
    if (userId) keepBirthdaySeenToday(userId);
  };

  if (!egg) return null;
  const name = egg.character.name_zh ?? egg.character.name;
  const line = egg.lines[index] ?? egg.lines[0];

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent
        style={herVars(egg.character.color)}
        className="items-center text-center sm:max-w-sm"
      >
        <DialogHeader className="items-center gap-2">
          <MarkedAvatar name={name} src={egg.character.avatar_url} size="call" />
          <DialogTitle>{t.title}</DialogTitle>
          <DialogDescription>{t.from(name)}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-28 w-full flex-col items-center justify-center gap-1 rounded-2xl bg-muted px-4 py-3">
          {isPlaying && line ? (
            <>
              <p className="text-japanese-line whitespace-pre-wrap">
                <Ja>{line.text}</Ja>
              </p>
              {line.subtitle && (
                <p className="text-subtitle text-muted-foreground">{line.subtitle}</p>
              )}
            </>
          ) : (
            <p className="text-body text-muted-foreground">{t.hint}</p>
          )}
        </div>

        <div className="flex w-full items-center justify-between gap-3">
          <span className="text-meta text-muted-foreground tabular-nums">
            {t.progress(index + 1, egg.lines.length)}
          </span>
          <Button onClick={() => (isPlaying ? stop() : playFrom(0))}>
            {isPlaying ? t.stop : t.play}
          </Button>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={close}>
            {t.thanks}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
