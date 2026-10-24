"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { useMediaQuery } from "@/hooks/useMediaQuery";
import { copy } from "@/i18n";
import type { Character, Outfit } from "@/lib/api";
import { speechState, subscribeSpeech } from "@/lib/messageSpeech";
import { CALM, type Emotion, type StandDirection } from "@/lib/standAnimations";
import { cn } from "@/lib/utils";

import { Stand } from "./stand/Stand";

const t = copy.conversation.companion;

/** 画布的宽（DESIGN.md「对话页的立绘小人」）；高按她整个人（骨架初始姿势量出来的）的宽高比算。 */
const WIDTH = 120;
/** 点一下她以后，这个表情留多久（毫秒）。 */
const REACTION_MS = 1800;
/** 她说完一条回复以后嘴动多久：按她说的字数估，再给一点底（毫秒）。 */
const TALK_BASE_MS = 1400;
const TALK_PER_CHARACTER_MS = 45;
const TALK_MAX_MS = 5000;
/** 点她一下随机换上的表情：不要难过和生气，那是做得不对的时候的事。 */
const REACTIONS: readonly Emotion[] = ["happy", "shy", "surprised"];

type Props = {
  character: Character;
  /** 立绘依次试的衣装：她穿的那套，再是默认衣装。 */
  outfits: readonly Outfit[];
  /** 她正在写这条回复（那条回复还没说完）：这会儿她在想。 */
  isReplying: boolean;
  /** 她刚说完的那条回复：编号和日语的字数。换了就动一会儿嘴，像刚说完这句话。 */
  said: { key: string; characters: number } | null;
};

/**
 * 对话页右下角站着的她（DESIGN.md「对话页的立绘小人」）：一个 120px 宽的小立绘，待机循环，
 * 点一下随机换一个表情，她说完了话嘴动一会儿，正在写回复时是一副想事情的样子。
 *
 * 复用通话层的 `Stand`：取景用「全身」，高矮按载入后量出的整个人定，所以不同角色、不同衣装都不会被拉扁或裁掉。
 * 加载中、素材缺失、这台设备画不了 WebGL 时整块什么也不留（`Stand` 自己什么都不画，这里不给画布留位置），
 * 也不挡着底下的消息：只有画布本身收点击，手势照常能上下滚。页面切到后台时不画。
 * 通话时（通话层、收起后的通话条在用时）由画它的那一页整个拿掉，免得和通话层的立绘重复。
 */
export function ChatCompanion({ character, outfits, isReplying, said }: Props) {
  const isReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)", false);
  const speech = useSyncExternalStore(subscribeSpeech, speechState, speechState);
  /** 她整个人高是宽的几倍；载入之后才知道。 */
  const [heightRatio, setHeightRatio] = useState<number | null>(null);
  const [reaction, setReaction] = useState<Emotion | null>(null);
  const [isTalking, setIsTalking] = useState(false);
  const [isPageHidden, setIsPageHidden] = useState(false);

  // 页面切到后台时不画：这一块挂在对话页上，看不见的时候不必占着 GPU。
  useEffect(() => {
    const update = () => setIsPageHidden(document.visibilityState === "hidden");
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  // 点出来的表情过一会儿回到待机。
  useEffect(() => {
    if (!reaction) return;
    const timer = window.setTimeout(() => setReaction(null), REACTION_MS);
    return () => window.clearTimeout(timer);
  }, [reaction]);

  // 她说完一条回复：嘴动一会儿。打开对话页时已经有的那条不补演，所以只看「刚才还在写、现在写完了」。
  const saidKey = said?.key ?? null;
  const saidCharacters = said?.characters ?? 0;
  const wasReplying = useRef(isReplying);
  useEffect(() => {
    const finished = wasReplying.current && !isReplying;
    wasReplying.current = isReplying;
    if (!finished || saidKey === null) return;
    setIsTalking(true);
    const timer = window.setTimeout(
      () => setIsTalking(false),
      Math.min(TALK_MAX_MS, TALK_BASE_MS + saidCharacters * TALK_PER_CHARACTER_MS),
    );
    return () => window.clearTimeout(timer);
  }, [isReplying, saidKey, saidCharacters]);

  // 嘴：刚说完这句话，或者正在放她的语音（她那条回复旁的「朗读」）。
  const isSpeaking = isTalking || speech?.phase === "playing";
  const direction = useMemo<StandDirection>(() => {
    const mood: Emotion = reaction ?? (isReplying ? "thinking" : CALM.mood);
    // 她一直看着制作人：角上的小人是冲着这个页面站着的。
    return { ...CALM, mood, speaking: isSpeaking, looking: true };
  }, [reaction, isReplying, isSpeaking]);

  // 高矮按量出来的整个人定；还没有量到（加载中、加载不到）时画布不留位置。
  const height = heightRatio === null ? 0 : Math.round(WIDTH * heightRatio);
  const measure = (size: { width: number; height: number }) => {
    if (size.width > 0) setHeightRatio(size.height / size.width);
  };

  return (
    <div className="pointer-events-none absolute inset-y-0 right-4 z-10 flex items-end max-md:right-2">
      <button
        type="button"
        // 读屏里就是一个按钮：点一下（或者按回车、空格）她换一个表情。
        aria-label={t.poke(character.name)}
        onClick={() => setReaction(REACTIONS[Math.floor(Math.random() * REACTIONS.length)])}
        className={cn(
          "pointer-events-auto block max-h-full w-30 cursor-pointer touch-pan-y rounded-2xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          height === 0 && "invisible",
        )}
        style={{ height }}
      >
        <Stand
          outfits={outfits}
          framing="full"
          isPaused={isPageHidden}
          entrance="fade"
          direction={direction}
          isReducedMotion={isReducedMotion}
          onMeasured={measure}
        />
      </button>
    </div>
  );
}
