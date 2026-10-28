"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ComponentProps,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { copy } from "@/i18n";
import { getMessageEmotion, getSmallTalk, type Character, type Outfit, type SmallTalkLine } from "@/lib/api";
import {
  clampStandPlace,
  clampStandWidth,
  DEFAULT_PLACE,
  loadStandHeight,
  loadStandWidth,
  saveStandHeight,
  saveStandPlace,
  saveStandWidth,
  STAND_HEIGHT,
  storedStandPlace,
  STAND_DRAG_THRESHOLD,
  STAND_WIDTH,
  STAND_WIDTH_STEP,
  type StandPlace,
} from "@/lib/chatCompanion";
import { speechState, subscribeSpeech } from "@/lib/messageSpeech";
import { CALM, type Emotion, type StandDirection } from "@/lib/standAnimations";
import { cn } from "@/lib/utils";
import { MoreIcon, ResizeIcon } from "@/theme/icons";
import { Ja } from "@/theme/Ja";

import { Stand } from "./stand/Stand";

const t = copy.conversation.companion;

/** 她离消息区的边多远（px）。 */
const MARGIN = 12;
/** 气泡最多多宽（px）、离她的头多高（px）、给她留的竖直空间（px）。 */
const BUBBLE_MAX_WIDTH = 256;
const BUBBLE_GAP = 8;
const BUBBLE_ALLOWANCE = 96;
/** 点一下她以后，这个表情留多久（毫秒）。 */
const REACTION_MS = 1800;
/** 她说完一条回复以后嘴动多久：按她说的字数估，再给一点底（毫秒）。 */
const TALK_BASE_MS = 1400;
const TALK_PER_CHARACTER_MS = 45;
const TALK_MAX_MS = 5000;
/** 判出来的语气摆多久（毫秒）：够看清，又不至于一直挂着一张脸。 */
const EMOTION_CUE_MS = 15000;
/** 小台词说完以后，气泡再留一会儿（毫秒）；没有声音时按这句的长度估一个停留时间。 */
const BUBBLE_LINGER_MS = 1600;
const BUBBLE_BASE_MS = 2400;
const BUBBLE_PER_CHARACTER_MS = 90;
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
  /** 正在放她那条回复的「朗读」时，念的是哪一句：气泡里显示它。 */
  spoken: { ja: string; zh: string } | null;
  /** 她刚才那句话是什么语气（判得多有把握也带着，越有把握越夸张），判断模型说完以后判的。 */
  emotion: { mood: Emotion; nod: "yes" | "no" | null; strength?: number; at: number } | null;
  /** 朗读能不能问这一句的语气（群聊的消息不在单聊的表里，问不到）：默认能。 */
  canJudgeSpeech?: boolean;
  /** 大小和位置记在哪个名字下：群聊里每位小人各记各的。不给就是单聊那一位。 */
  storeKey?: string;
  /** 没存过位置时站哪儿（0 贴右、1 贴左）；群聊里按人数摊开。 */
  defaultX?: number;
  defaultY?: number;
  /** 按「多高」来站（群聊里几位一样高）：给了它就不按宽度算，拖把手改的也是高度。 */
  heightTarget?: number;
  /** 点了「隐藏立绘」：这一位（群聊里是整群）的立绘收起来。不给就不出这个菜单。 */
  onHide?: () => void;
  /** 菜单里那句话：群聊传群那一套文案，不给就用单聊的。 */
  hideLabel?: string;
  /** 浮层挂到哪棵子树里：单聊指回对话子树，菜单才拿得到她的颜色。 */
  menuContainer?: ComponentProps<typeof DropdownMenuContent>["container"];
};

/**
 * 对话页右下角站着的她（DESIGN.md「对话页的立绘小人」）：一个小立绘，待机循环，点一下换一个表情、
 * 随机说一句她的小台词（头顶的气泡里是这句话），她说完了话嘴动一会儿，正在写回复时是一副想事情的样子。
 *
 * 复用通话层的 `Stand`：取景用「全身」，高矮按载入后量出的整个人定，所以不同角色、不同衣装都不会被拉扁或裁掉。
 * 她多大、站在消息区的哪儿都由人定：拖脚边的把手改大小，拖她本人换位置，都存在本机；放不下时按消息区
 * 缩回来，不拉扁，也不会跑出消息区。加载中、素材缺失、这台设备画不了 WebGL 时整块什么也不留
 * （`Stand` 自己什么都不画，这里不给画布留位置）。页面切到后台时不画。
 * 收起来：悬停她时脚边的「⋯」（手机上一直在）里只有「隐藏立绘」一项，收没收起由调用方记
 * （`lib/standVisibility`），这一块只管把话交出去。
 * 通话时（通话层、收起后的通话条在用时）由画它的那一页整个拿掉，免得和通话层的立绘重复。
 */
export function ChatCompanion({
  character,
  outfits,
  isReplying,
  said,
  spoken,
  emotion,
  canJudgeSpeech = true,
  storeKey,
  defaultX = 0,
  defaultY = 0,
  heightTarget,
  onHide,
  hideLabel,
  menuContainer,
}: Props) {
  const sized = heightTarget !== undefined;
  const isReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)", false);
  const speech = useSyncExternalStore(subscribeSpeech, speechState, speechState);
  /** 她整个人高是宽的几倍；载入之后才知道。 */
  const [heightRatio, setHeightRatio] = useState<number | null>(null);
  const [width, setWidth] = useState(STAND_WIDTH);
  /** 群聊里她多高（`heightTarget` 给了才用）。 */
  const [height, setHeight] = useState(heightTarget ?? STAND_HEIGHT);
  const [place, setPlace] = useState<StandPlace>(DEFAULT_PLACE);
  /** 消息区有多大：她的大小和位置都按它收。 */
  const [area, setArea] = useState({ width: 0, height: 0 });
  const [reaction, setReaction] = useState<Emotion | null>(null);
  /** 她刚才那句话的语气，判出来以后摆一会儿。 */
  const [cue, setCue] = useState<{ mood: Emotion; nod: "yes" | "no" | null; id: number; strength: number } | null>(null);
  /** 正在朗读的那条回复的语气：念的时候照它摆，念完回待机。 */
  const [speechCue, setSpeechCue] = useState<{
    mood: Emotion;
    nod: "yes" | "no" | null;
    id: number;
    strength: number;
  } | null>(null);
  const cues = useRef(0);
  const [isTalking, setIsTalking] = useState(false);
  const [isPageHidden, setIsPageHidden] = useState(false);
  /** 这一会儿她在说的那句小台词；没有时说完了。 */
  const [line, setLine] = useState<SmallTalkLine | null>(null);
  const [isSaying, setIsSaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const bubbleTimer = useRef(0);
  /** 她这一块（画布和把手），用来量消息区。 */
  const box = useRef<HTMLDivElement>(null);

  // 拖她：按下的位置和当时站的位置。拖动超过一点距离才算挪她，不然就是点她一下。
  const drag = useRef<{ x: number; y: number; place: StandPlace } | null>(null);
  const dragged = useRef(false);
  const placeNow = useRef(place);
  placeNow.current = place;
  // 拖脚边的把手改大小。
  const resize = useRef<{ x: number; width: number } | null>(null);

  useEffect(() => {
    setWidth(loadStandWidth(storeKey));
    setHeight(loadStandHeight(storeKey));
    setPlace(storedStandPlace(storeKey) ?? clampStandPlace({ x: defaultX, y: defaultY }));
  }, [storeKey, defaultX, defaultY]);

  // 消息区有多大；窗口缩放、手机上键盘弹起时跟着变。
  useEffect(() => {
    const parent = box.current?.parentElement;
    if (!parent) return;
    const measure = () => setArea({ width: parent.clientWidth, height: parent.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

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

  // 离开这一页、换一位角色时，声音和气泡一起收掉。
  useEffect(() => {
    return () => {
      audio.current?.pause();
      window.clearTimeout(bubbleTimer.current);
    };
  }, [character.id]);

  // 她说完一条回复，判断模型给她刚才那句话判了语气：照着摆一会儿，同意或否定时点一下头。
  useEffect(() => {
    if (!emotion) return;
    cues.current += 1;
    setCue({ mood: emotion.mood, nod: emotion.nod, id: cues.current, strength: emotion.strength ?? 0 });
    const timer = window.setTimeout(() => setCue(null), EMOTION_CUE_MS);
    return () => window.clearTimeout(timer);
  }, [emotion]);

  // 复读她的语音：念哪一条就问一下那一条的语气，念的这段时间一直照着摆（长度跟着语音走）。
  const speechId = speech?.messageId ?? null;
  useEffect(() => {
    if (speechId === null || !canJudgeSpeech) {
      setSpeechCue(null);
      return;
    }
    let cancelled = false;
    void getMessageEmotion(speechId)
      .catch(() => null)
      .then((answer) => {
        if (cancelled || !answer) return;
        cues.current += 1;
        setSpeechCue({ mood: answer.emotion, nod: answer.nod, id: cues.current, strength: answer.strength ?? 0 });
      });
    return () => {
      cancelled = true;
    };
  }, [speechId]);

  // 嘴：刚说完这句话、正在放她的语音（她那条回复旁的「朗读」），或者正在说一句小台词。
  const isSpeaking = isTalking || isSaying || speech?.phase === "playing";
  const direction = useMemo<StandDirection>(() => {
    const mood: Emotion =
      line?.mood ?? speechCue?.mood ?? cue?.mood ?? reaction ?? (isReplying ? "thinking" : CALM.mood);
    const nod = speechCue?.nod ?? cue?.nod ?? null;
    const id = speechCue?.nod ? speechCue.id : cue?.id;
    // 她一直看着制作人：角上的小人是冲着这个页面站着的。说小台词时，身体和脸照原作里这一句的来。
    return {
      ...CALM,
      mood,
      speaking: isSpeaking,
      looking: true,
      body: line?.body || undefined,
      face: line?.face || undefined,
      strength: speechCue?.strength ?? cue?.strength,
      nod: nod && id !== undefined ? { kind: nod, id } : null,
    };
  }, [line, speechCue, cue, reaction, isReplying, isSpeaking]);

  // 她多方正：宽是她整个人，高按量出来的宽高比；放不下时按消息区缩回来，不拉扁。
  // 群聊里反过来：先定她多高（几个人一样高），宽按量出来的比例算。
  const ratio = heightRatio ?? 0;
  const size = useMemo(() => {
    if (!ratio || !area.width || !area.height) return { width: 0, height: 0 };
    let w = sized ? height / ratio : width;
    let h = sized ? height : w * ratio;
    if (h > area.height) {
      h = area.height;
      w = h / ratio;
    }
    if (w > area.width) {
      w = area.width;
      h = w * ratio;
    }
    return { width: Math.round(w), height: Math.round(h) };
  }, [width, height, sized, ratio, area]);

  const measured = (measuredSize: { width: number; height: number }) => {
    if (measuredSize.width > 0) setHeightRatio(measuredSize.height / measuredSize.width);
  };

  // 她能挪的余地：消息区去掉她自己的大小和两边的空；她大得快占满了时就只能贴着中间。
  const slackX = Math.max(0, area.width - size.width);
  const slackY = Math.max(0, area.height - size.height);
  const roomX = Math.max(0, slackX - 2 * MARGIN);
  const roomY = Math.max(0, slackY - 2 * MARGIN);
  const right = roomX > 0 ? MARGIN + Math.round(place.x * roomX) : Math.round(slackX / 2);
  const bottom = roomY > 0 ? MARGIN + Math.round(place.y * roomY) : Math.round(slackY / 2);

  // 气泡往地方大的那一边展开，别出消息区；她高得头快顶到顶时，气泡落在她的头上一点。
  const roomOnLeft = area.width - right - 8;
  const roomOnRight = right + size.width - 8;
  const bubbleToLeft = roomOnLeft >= roomOnRight;
  const bubbleWidth = Math.max(140, Math.min(BUBBLE_MAX_WIDTH, bubbleToLeft ? roomOnLeft : roomOnRight));
  const bubbleBottom = Math.max(
    0,
    Math.min(size.height + BUBBLE_GAP, area.height - bottom - BUBBLE_GAP - BUBBLE_ALLOWANCE),
  );

  /** 气泡收起来：说完以后再留一会儿，让她这句话待得久一点。 */
  const hideBubbleSoon = (characters: number) => {
    window.clearTimeout(bubbleTimer.current);
    const hold = Math.max(BUBBLE_LINGER_MS, BUBBLE_BASE_MS + characters * BUBBLE_PER_CHARACTER_MS);
    bubbleTimer.current = window.setTimeout(() => setLine(null), hold);
  };

  /** 点她一下：随机说一句她的小台词，没有台词（或者正在说话）时只换一个表情。 */
  const poke = () => {
    if (isSaying || speech?.phase === "playing") return;
    setReaction(REACTIONS[Math.floor(Math.random() * REACTIONS.length)]);
    void getSmallTalk(character.id)
      .catch(() => null)
      .then((next) => {
        if (!next) return;
        setIsTalking(false);
        window.clearTimeout(bubbleTimer.current);
        setLine(next);
        audio.current?.pause();
        const element = new Audio(next.voice);
        audio.current = element;
        setIsSaying(true);
        const done = () => {
          setIsSaying(false);
          hideBubbleSoon([...next.ja].length);
        };
        element.addEventListener("ended", done);
        element.addEventListener("error", done);
        void element.play().catch(done);
      });
  };

  // 拖她本人：超过一点距离才算挪她，松手时记下来；没挪动的那一下就是点她。
  const startMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragged.current = false;
    drag.current = { x: event.clientX, y: event.clientY, place };
  };
  const move = (event: PointerEvent<HTMLButtonElement>) => {
    const start = drag.current;
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (!dragged.current) {
      if (Math.hypot(dx, dy) < STAND_DRAG_THRESHOLD) return;
      dragged.current = true;
    }
    setPlace(
      clampStandPlace({
        x: start.place.x - dx / Math.max(1, roomX),
        y: start.place.y - dy / Math.max(1, roomY),
      }),
    );
  };
  const endMove = () => {
    if (!drag.current) return;
    drag.current = null;
    if (dragged.current) saveStandPlace(placeNow.current, storeKey);
  };

  // 拖脚边的把手：往左拖变大、往右拖变小。群聊里改的是高度。
  const startResize = (event: PointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resize.current = { x: event.clientX, width: sized ? height : width };
  };
  const dragResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (!resize.current) return;
    const next = clampStandWidth(resize.current.width + (resize.current.x - event.clientX));
    if (sized) setHeight(next);
    else setWidth(next);
  };
  const endResize = () => {
    if (!resize.current) return;
    resize.current = null;
    if (sized) saveStandHeight(height, storeKey);
    else saveStandWidth(width, storeKey);
  };
  const keyResize = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowLeft" ? STAND_WIDTH_STEP : -STAND_WIDTH_STEP;
    const next = clampStandWidth((sized ? height : width) + step);
    if (sized) {
      setHeight(next);
      saveStandHeight(next, storeKey);
    } else {
      setWidth(next);
      saveStandWidth(next, storeKey);
    }
  };

  // 头顶气泡里的话：正在说的小台词，或者正在放的「朗读」那一段。
  const bubble = line ?? spoken;

  return (
    <div
      ref={box}
      className="group pointer-events-none absolute z-10"
      style={{ right, bottom }}
    >
      {/* 她说的话在头顶：气泡只读，不挡点击 */}
      {bubble && (
        <div
          role="status"
          className={cn(
            "pointer-events-none absolute rounded-2xl border bg-background px-3 py-2 text-left",
            bubbleToLeft ? "right-0" : "left-0",
          )}
          style={{ bottom: bubbleBottom, maxWidth: bubbleWidth }}
        >
          <p className="text-body whitespace-pre-line">
            <Ja>{bubble.ja}</Ja>
          </p>
          {bubble.zh && <p className="mt-0.5 text-subtitle text-muted-foreground">{bubble.zh}</p>}
        </div>
      )}
      <button
        type="button"
        // 读屏里就是一个按钮：点一下（或者按回车、空格）她换一个表情、说一句；拖她换个位置。
        aria-label={t.poke(character.name)}
        onClick={() => {
          if (dragged.current) {
            dragged.current = false;
            return;
          }
          poke();
        }}
        onPointerDown={startMove}
        onPointerMove={move}
        onPointerUp={endMove}
        onPointerCancel={endMove}
        className={cn(
          "pointer-events-auto block cursor-grab touch-none rounded-2xl outline-none active:cursor-grabbing focus-visible:ring-3 focus-visible:ring-ring/50",
          size.height === 0 && "invisible",
        )}
        style={{ width: size.width, height: size.height }}
      >
        <Stand
          outfits={outfits}
          framing="full"
          isPaused={isPageHidden}
          entrance="fade"
          direction={direction}
          isReducedMotion={isReducedMotion}
          onMeasured={measured}
        />
      </button>
      {/* 她脚边的把手：拖一下就能把她放大、缩小（键盘上是左右方向键），大小记在本机 */}
      {size.height > 0 && (
        <button
          type="button"
          aria-label={t.resize}
          onPointerDown={startResize}
          onPointerMove={dragResize}
          onPointerUp={endResize}
          onPointerCancel={endResize}
          onKeyDown={keyResize}
          className="pointer-events-auto absolute flex size-6 cursor-ew-resize touch-none items-center justify-center rounded-full border bg-background text-muted-foreground opacity-0 outline-none transition-opacity group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-3 focus-visible:ring-ring/50 max-md:opacity-100"
          style={{ right: size.width - 12, bottom: 0 }}
        >
          <ResizeIcon className="size-3.5" />
        </button>
      )}
      {/* 把手旁边的「⋯」：点开只有「隐藏立绘」。手机上一直在；电脑上悬停她时才出来，焦点落在它上面时也出来 */}
      {onHide && size.height > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={t.menu}
            className="pointer-events-none absolute flex size-6 items-center justify-center rounded-full border bg-background text-muted-foreground opacity-0 outline-none transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100 focus-visible:ring-3 focus-visible:ring-ring/50 max-md:pointer-events-auto max-md:opacity-100"
            style={{ right: size.width - 40, bottom: 0 }}
          >
            <MoreIcon className="size-3.5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent container={menuContainer} side="top" align="end">
            <DropdownMenuItem onClick={onHide}>{hideLabel ?? copy.conversation.hideStand}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}
