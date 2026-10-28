"use client";

import NextLink from "next/link";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ComponentType,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";

import { UnseenDot } from "@/components/app/AchievementLine";
import { FailureNotice, SignInButton } from "@/components/app/FailureNotice";
import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Message, MessageContent, MessageHeader } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { copy } from "@/i18n";
import { cueText, changeNote, untilText } from "@/lib/affinity";
import { getConversationNow, sceneImageUrl, setConversationPlace, type Character, type NowScene } from "@/lib/api";
import type { Entry } from "@/lib/conversationLog";
import type { Failure } from "@/lib/failure";
import { giftsHref } from "@/lib/gifts";
import { isLive, NOT_OPEN, type LiveConversation, type Trophy } from "@/lib/liveConversation";
import { linesOf, type Line } from "@/lib/messageLines";
import { pastDay } from "@/lib/pastConversations";
import { photosUsedUpText } from "@/lib/photoFailure";
import { loadStandHidden, saveStandHidden } from "@/lib/standVisibility";
import { hearVoice, startRecording, type Recording } from "@/lib/voiceMessage";
import { speechState, subscribeSpeech, toggleSpeech } from "@/lib/messageSpeech";
import { stopVoiceLine, subscribeVoiceLine, toggleVoiceLine, voiceLineState } from "@/lib/voiceLine";
import { cn } from "@/lib/utils";
import { herVars } from "@/theme/herVars";
import {
  AchievementsIcon,
  AffinityHeartIcon,
  AttachImageIcon,
  BackIcon,
  CloseIcon,
  CooldownIcon,
  EndedIcon,
  GiftIcon,
  MoreIcon,
  MicIcon,
  NewConversationIcon,
  OutfitIcon,
  PastConversationsIcon,
  PhoneIcon,
  PhotosUsedUpIcon,
  SendIcon,
  SpeakIcon,
  VoiceIcon,
} from "@/theme/icons";
import { Ja } from "@/theme/Ja";

import { AchievementsPanel } from "./AchievementsPanel";
import { AdminAffinityDialog } from "./AdminAffinityDialog";
import { AffinityBadge, CueArrowIcon } from "./AffinityBadge";
import { CallBar } from "./CallBar";
import { ChatCompanion } from "./ChatCompanion";
import { EVENT_ICONS, eventText } from "./EventIcon";
import { LiveCallLayer } from "./CallLayer";
import { OutfitPicker } from "./OutfitPicker";
import { PastConversations } from "./PastConversations";
import { PhotoBlock } from "./PhotoBlock";
import { PlaceBackdrop } from "./PlaceBackdrop";
import { PlacePicker } from "./PlacePicker";
import { useDirectory, useWide } from "./ConversationDirectory";
import { useFocusBack } from "./useFocusBack";
import { useHerAchievements } from "./useHerAchievements";
import { usePastConversation, type Viewing } from "./usePastConversation";
import { useProducerTimezone } from "./useProducerTimezone";
import { useStandOutfits } from "./useStandOutfits";

const t = copy.conversation;

const notOpen = () => NOT_OPEN;
const noSubscription = () => () => {};

/**
 * 和一位角色的 IM 对话页（DESIGN.md「Layout」「Chat bubbles」）：页首和消息区铺她的壁纸，
 * 成组的 22px 圆角气泡，实底的输入栏。对话的状态全在 LiveConversation 里，这里只画它的快照、把操作交给它。
 * 整个子树注入她的颜色（herVars），浮层（更多菜单）的 container 指回这棵子树。
 *
 * 页首的电话键打开通话层并开始呼叫（spec「通话层」）；通话层可以收起回到这里，页首下面出现通话条，
 * 电话键变成实心的「回到通话」。对话的实时状态（连同通话）由导航外壳持有（ADR-0018）：这一页打开时向外壳要她那一份，
 * 离开时交回；通话中离开这一页，通话留在外壳里，回来时一切照旧。她的声音、电话本身的声音和切换麦克风的面板也在外壳里。
 * 她有立绘时，更多菜单里有「换衣装」（spec「衣装与换衣装」）。
 * 好感度可用时，电话键和更多菜单之间是好感度标识（GLOSSARY.md「好感度」）；不可用时读到 null，不显示。
 * 她在冷却中（GLOSSARY.md「冷却」）时，输入栏换成一行说明和「送她一件礼物」、电话键禁用，到点自己恢复。
 * 她结束了这个对话（GLOSSARY.md「已结束的对话」）时，输入栏换成结束卡「她结束了对话」和「开个新对话」、电话键禁用，只能往上翻看；她还在冷却中时，结束卡写上解除时刻、加「送她一件礼物」。
 * 送礼的入口（冷却时的输入栏、标识的说明末尾、冷却版结束卡）都跳到礼物页，带上她（spec「打开好感度藏起的送礼入口」），
 * 礼物一律记进当前对话；好感度和礼物同一个开关，好感度读不到时这些入口都不在。
 *
 * 更多菜单依次是「新对话」「历史对话」「换衣装」「成就」。「成就」打开她的成就面板（`AchievementsPanel`），「好感度和礼物」关着时没有；
 * 她有没看过的解锁时，更多菜单键右上角和「成就」后面各一个点（`useHerAchievements`）。这一页上的回合解锁了她的阶段、
 * 通话层没盖着页首时，好感度标识左边跳出奖杯和「+n」，约 3 秒收起（快照的 `trophy`）。
 * 「历史对话」打开面板（`PastConversations`），点一段就看那段历史对话
 * （地址带 `?c=`，`usePastConversation`）：消息区照平时画、只读，页首名字下面写「{日期}的对话」，电话键禁用
 * （通话中也禁用，回通话走通话条），输入栏换成只读卡「回到当前对话」；窄屏页首的返回键、只读卡的按钮都回到当前对话。
 * 历史对话不碰 LiveConversation：通话和正在进行的回复照旧在当前对话里，回去就看得到。在历史对话里点「新对话」先回到当前对话再开。
 */
export function ConversationView({
  userId,
  character,
  onBack,
}: {
  /** 登录的用户：发回合时带上浏览器里存的、这位用户的自带 LLM。 */
  userId: string;
  character: Character;
  onBack?: () => void;
}) {
  const { open, close, go, guard, account, appearance, showPast } = useDirectory();
  const isFullScreen = !useWide();
  const isReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)", false);
  const [live, setLive] = useState<LiveConversation | null>(null);
  const snapshot = useSyncExternalStore(live?.subscribe ?? noSubscription, live?.snapshot ?? notOpen, notOpen);
  const { conversation, entries, call, layer, hearing, draft, failure } = snapshot;
  const outfits = useStandOutfits(character);
  // 立绘在这一条对话里被临时收起来了吗（DESIGN.md「对话页的立绘小人」）：和外观里全局的「对话页显示立绘」分开，
  // 按对话记在这台设备上，刷新、重开还在；全局开关关着时这条不起作用。
  const conversationId = conversation.status === "open" ? conversation.id : null;
  const standHiddenKey = conversationId === null ? null : `chatStandHidden:${conversationId}`;
  const [standHidden, setStandHidden] = useState(false);
  useEffect(() => {
    setStandHidden(standHiddenKey === null ? false : loadStandHidden(standHiddenKey));
  }, [standHiddenKey]);
  const hideStand = () => {
    if (standHiddenKey === null) return;
    setStandHidden(true);
    saveStandHidden(standHiddenKey, true);
  };
  const restoreStand = () => {
    if (standHiddenKey === null) return;
    setStandHidden(false);
    saveStandHidden(standHiddenKey, false);
  };
  const [pickingOutfit, setPickingOutfit] = useState(false);
  const [pickingPast, setPickingPast] = useState(false);
  // 她现在在哪（不打电话也看得到）：页首的小胶囊；后端按（角色、日期、时段）固定，同一格不变。
  const [nowScene, setNowScene] = useState<NowScene | null>(null);
  const [adjustingAffinity, setAdjustingAffinity] = useState(false);
  // 这一轮要发给她的图片：选中的 data URL，发出去或取消后清空。
  const [picture, setPicture] = useState<string | null>(null);
  const pictureInput = useRef<HTMLInputElement>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceFailure, setVoiceFailure] = useState<string | null>(null);
  const { viewing, view, backToCurrent } = usePastConversation(character.id);
  const subtree = useRef<HTMLDivElement>(null);
  // 她现在对制作人的好感度；读不到（好感度关着、没配判断模型或请求失败）就不显示标识，也不出变化胶囊。
  const { affinity, affinityCue, cooling, ended, trophy } = snapshot;
  const achievements = useHerAchievements(character.id, userId, snapshot.herUnlockedAt);
  // 解除时刻按制作人的时区写成今天或明天。
  const timeZone = useProducerTimezone();
  // 她最后一条回复：正在写，还是刚写完（右下角的小立绘据此想事情、动一会儿嘴）。
  const lastReply = useMemo(() => {
    for (let i = entries.length - 1; i >= 0; i--) {
      const entry = entries[i];
      if (entry.kind !== "character") continue;
      if (entry.pending) return { isReplying: true, said: null };
      const characters = entry.segments.reduce((sum, segment) => sum + segment.ja.length, 0);
      return { isReplying: false, said: { key: entry.key, characters } };
    }
    return { isReplying: false, said: null };
  }, [entries]);
  // 正在朗读的那条回复：小立绘头顶的气泡里显示它在念的那一段。
  const speaking = useSyncExternalStore(subscribeSpeech, speechState, speechState);
  const spoken = useMemo(() => {
    if (!speaking) return null;
    const entry = entries.find(
      (candidate) =>
        candidate.kind === "character" &&
        /^[mr]\d+$/.test(candidate.key) &&
        Number(candidate.key.slice(1)) === speaking.messageId,
    );
    if (!entry || entry.kind !== "character" || entry.segments.length === 0) return null;
    return {
      ja: entry.segments.map((segment) => segment.ja).join("\n"),
      zh: entry.segments
        .map((segment) => segment.zh)
        .filter(Boolean)
        .join(" "),
    };
  }, [speaking, entries]);

  // 向外壳要她的对话（外壳里留着她的通话就用那一份，否则打开她最新的一个，从没聊过就开一个新的）；
  // 离开这一页时交回：通话还在进行就留在外壳里，否则就此告别。
  useEffect(() => {
    const conversation = open(character.id, userId);
    setLive(conversation);
    return () => close(conversation);
  }, [character.id, userId, open, close]);

  // 看历史对话时她的当前对话不在屏幕上：外壳照常标她没看过的搭话，也不替这一页重读。
  const isPastShown = viewing !== null;
  useEffect(() => {
    showPast(isPastShown);
  }, [isPastShown, showPast]);

  // 她现在在哪（不打电话也看得到）：进页面问一次，到这一格结束再问一次；看历史对话时不问。
  // 后端按（角色、日期、时段）固定，同一格刷新几次都是同一张，不会闪。
  useEffect(() => {
    if (conversationId === null || isPastShown) {
      setNowScene(null);
      return;
    }
    let live = true;
    let timer: number | undefined;
    const load = (): void => {
      getConversationNow(conversationId)
        .then((next) => {
          if (!live) return;
          setNowScene(next);
          const wait = Date.parse(next.until) - Date.now() + 1000;
          if (Number.isFinite(wait) && wait > 0) timer = window.setTimeout(load, wait);
        })
        .catch(() => {
          if (live) setNowScene(null);
        });
    };
    load();
    return () => {
      live = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [conversationId, isPastShown]);

  // 页首的下拉栏里自己挑一处地方：接口回来的就是新的「现在」，页首立刻换过去，不用等 `/now` 再问。
  // 对话里说定的那处（`movedScene`）也一起换掉，否则它还盖在轮询来的那张上面。
  const pickPlace = async (sceneId: string | null): Promise<void> => {
    if (conversationId === null) return;
    const next = await setConversationPlace(conversationId, sceneId);
    setNowScene(next);
    live?.pickPlace(sceneId === null ? null : next.scene);
  };

  // 收起时到的照片就在这页的对话记录里：外壳顶上通话条的「新照片」到这里就算看过了。
  useEffect(() => {
    if (snapshot.newPhoto) live?.photoSeen();
  }, [snapshot.newPhoto, live]);

  const isOpen = conversation.status === "open";
  // 送礼入口去的礼物页：只带她，礼物一律记进当前对话（历史对话里点的也一样）。
  const gifts = giftsHref(character.id);
  // 在历史对话里开新对话：先回到当前对话。
  const startNew = () => {
    if (viewing) backToCurrent();
    void live?.startNewConversation();
  };
  const inCall = isLive(call);
  // 要在这次点击里同步调用：她的声音趁这一下唤醒 AudioContext。
  const dial = () => void live?.startCall();

  // 通话层展开时盖住整栏：底下的页首和对话不能再被 Tab 或屏幕阅读器摸到。快照里的 layer
  // 已经管着「画哪一通、收没收起」；通话条只在通话中、通话层收着时出现。
  const isCovered = layer !== null && !layer.collapsed;
  const barShown = isLive(call) && layer?.collapsed === true;
  const focus = useFocusBack({ layerOpen: isCovered, noteShown: barShown });

  // 页首的图标键：手机上触控目标不小于 44px（DESIGN.md「Layout」）。
  const headerKey = "max-md:size-11";
  // 页首的那张「现在」：对话里说定搬过去（`movedScene`）、或者刚在页首的下拉栏里自己挑的，先盖住
  // 轮询来的那张，都是同一个地方；`pinned` 说这一处是不是自己挑的（不是就按她的作息表算）。
  const shownNow =
    snapshot.movedScene !== null
      ? { id: snapshot.movedScene.id, name: snapshot.movedScene.name, activity: "", pinned: true }
      : nowScene === null
        ? null
        : {
            id: nowScene.scene.id,
            name: nowScene.scene.name,
            activity: nowScene.activity,
            // `chat` 是对话里说定的、`manual` 是页首下拉栏里自己挑的，两种都记在这段对话上。
            pinned: nowScene.source === "manual" || nowScene.source === "chat",
          };
  // 消息区背后的地点图（DESIGN.md「通话场景」）：对话里说定搬过去的（`movedScene`，刚搬的那一下）优先，
  // 否则铺她这会儿在的地方——按她的作息表算出来的（slot、holiday、behavior 这些）也铺，不挑 `source`。
  // 看历史对话时仍然不铺。
  const placeScene = snapshot.movedScene ?? nowScene?.scene ?? null;
  const placeImage = placeScene === null || isPastShown ? null : placeScene.image_url || sceneImageUrl(placeScene.id);
  // 历史对话里拨不出去，通话中也一样（回到通话走通话条）；通话中换成实心的「回到通话」。
  const phone: { tip: string; label: string; disabled?: boolean; onClick?: () => void; filled?: boolean } = viewing
    ? { tip: t.past.callTooltip, label: t.call(character.name), disabled: true }
    : inCall
      ? { tip: copy.call.expand, label: copy.call.expand, onClick: () => live?.expand(), filled: true }
      : { tip: t.callTooltip, label: t.call(character.name), disabled: !snapshot.canDial, onClick: dial };
  const phoneKey = (
    <HeaderTip label={phone.tip}>
      <Button
        ref={focus.phoneKey}
        variant="ghost"
        size="icon-lg"
        className={headerKey}
        aria-label={phone.label}
        disabled={phone.disabled}
        focusableWhenDisabled
        onClick={phone.onClick}
      >
        <PhoneIcon className={cn("size-5 text-her-mark", phone.filled && "fill-current")} />
      </Button>
    </HeaderTip>
  );

  const header = (
    <header inert={isCovered} className="flex h-14 shrink-0 items-center gap-1 px-2">
      {onBack && (
        // 历史对话里返回键回到当前对话，不退到对话列表。
        <Button
          variant="ghost"
          size="icon-lg"
          className={headerKey}
          aria-label={viewing ? t.past.backToCurrent : t.back}
          onClick={viewing ? backToCurrent : onBack}
        >
          <BackIcon className="size-6" />
        </Button>
      )}
      <div className="flex min-w-0 flex-1 flex-col px-2">
        <h1 className="truncate text-header">{character.name}</h1>
        {viewing?.status === "open" ? (
          <p className="truncate text-meta text-muted-foreground">{t.past.heading(pastDay(viewing.at, new Date()))}</p>
        ) : (
          shownNow && (
            // 她现在在哪：小胶囊只写场景名（活动放在悬停提示里；窄屏放不下时截断），点开是地点下拉栏，
            // 可以自己挑一处，或者回到按她的作息表算的地方。
            <PlacePicker
              sceneId={shownNow.pinned ? shownNow.id : null}
              clearLabel={copy.place.follow}
              trigger={
                <button
                  type="button"
                  title={shownNow.activity || undefined}
                  className="inline-block w-fit max-w-full truncate rounded-full bg-foreground/10 px-2 py-0.5 text-meta text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              }
              container={subtree}
              onPick={pickPlace}
            >
              {t.now(shownNow.name)}
            </PlacePicker>
          )
        )}
      </div>
      {/* 立绘收起来时页首的「显示立绘」胶囊：点一下恢复（通话中、看历史对话时立绘本就不画，不出这个胶囊） */}
      {appearance.chatStand && standHidden && !layer && !viewing && standHiddenKey !== null && (
        <Button variant="pill" className="max-md:h-11" onClick={restoreStand}>
          {t.showStand}
        </Button>
      )}
      {phoneKey}
      {trophy && <TrophyCue key={trophy.key} trophy={trophy} isReducedMotion={isReducedMotion} />}
      {/* 礼貌的 live region 一直在，奖杯出现时读「成就，抽奖 +n」；按 key 换节点，同样的 n 再来一次也读 */}
      <span role="status" className="sr-only">
        {trophy && <span key={trophy.key}>{copy.achievements.trophy(trophy.draws)}</span>}
      </span>
      {affinity && (
        <AffinityBadge
          status={affinity}
          cue={affinityCue}
          name={character.name}
          timeZone={timeZone}
          gifts={gifts}
          characterId={character.id}
          subtree={subtree}
        />
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-lg"
              className={cn(headerKey, "relative")}
              aria-label={achievements.isUnseen ? t.menuUnseen : t.menu}
            />
          }
        >
          <MoreIcon className="size-5" />
          {achievements.isUnseen && (
            <span aria-hidden className="absolute top-2 right-2 size-1.5 rounded-full bg-foreground" />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent container={subtree} align="end">
          {/* 菜单项里的图标默认 16px、跟着菜单文字的颜色，不用她的颜色 */}
          <DropdownMenuItem disabled={!snapshot.canStartNew} onClick={startNew}>
            <NewConversationIcon aria-hidden />
            {t.newConversation}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setPickingPast(true)}>
            <PastConversationsIcon aria-hidden />
            {t.past.open}
          </DropdownMenuItem>
          {outfits && (
            <DropdownMenuItem onClick={() => setPickingOutfit(true)}>
              <OutfitIcon aria-hidden />
              {t.outfits.open}
            </DropdownMenuItem>
          )}
          {achievements.her && (
            <DropdownMenuItem onClick={() => achievements.setPanelOpen(true)}>
              <AchievementsIcon aria-hidden />
              {copy.achievements.open}
              {achievements.isUnseen && <UnseenDot className="ml-auto" />}
            </DropdownMenuItem>
          )}
          {/* 管理者才能手动设定好感度：普通用户看不到，接口本身也只认管理员。 */}
          {account?.is_admin && affinity && (
            <DropdownMenuItem onClick={() => setAdjustingAffinity(true)}>
              <AffinityHeartIcon aria-hidden />
              {t.affinity.adjust}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );

  if (conversation.status === "failed") {
    return (
      <Frame character={character} subtree={subtree} header={header}>
        <Empty>
          <EmptyHeader>
            <EmptyTitle>{t.loadFailed}</EmptyTitle>
            <EmptyDescription>{conversation.failure.message}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            {conversation.failure.signedOut ? (
              <SignInButton />
            ) : (
              onBack && (
                <Button variant="outline" onClick={onBack}>
                  {t.backToList}
                </Button>
              )
            )}
          </EmptyContent>
        </Empty>
      </Frame>
    );
  }

  const canSend = isOpen && (draft.trim() !== "" || picture !== null);
  /**
   * 点一下开始录，再点一下停下并发送：录到的声音交给后端听成文字，当普通消息发出去。
   * 浏览器只在安全来源下给麦克风，所以纯 HTTP 的局域网地址上会失败，提示用户换地址。
   */
  const toggleVoice = async () => {
    if (transcribing) return;
    if (recording === null) {
      setVoiceFailure(null);
      try {
        setRecording(await startRecording());
      } catch {
        setVoiceFailure(t.voiceBlocked);
      }
      return;
    }
    const captured = await recording.stop();
    setRecording(null);
    if (captured === null) return;
    setTranscribing(true);
    try {
      const heard = await hearVoice(captured);
      live?.setDraft(heard);
      await live?.submit(picture);
      setPicture(null);
    } catch (e) {
      setVoiceFailure(e instanceof Error ? e.message : t.voiceBlocked);
    } finally {
      setTranscribing(false);
    }
  };
  const cooldownUntil = cooling ? affinity?.cooldown_until : null;
  // 冷却中的解除时刻和去礼物页的「送她一件礼物」：冷却那一行和冷却版结束卡共用。
  const until = cooldownUntil ? untilText(new Date(cooldownUntil), new Date(), timeZone) : null;
  const giveHer = (
    <Button variant="outline" size="lg" nativeButton={false} render={<NextLink href={gifts} onClick={guard(gifts)} />}>
      <GiftIcon data-icon="inline-start" />
      {copy.gifts.giveHer}
    </Button>
  );
  const composer = viewing ? (
    <ReadOnlyCard viewing={viewing} inert={isCovered} onBackToCurrent={backToCurrent} />
  ) : ended ? (
    // 已结束：结束卡代替输入框，右边「开个新对话」走更多菜单里的「新对话」，正在开时不可用。
    // 冷却中再写上解除时刻，「开个新对话」前面加「送她一件礼物」；一行放不下时按钮换到下一行、靠右。
    <ComposerCard
      inert={isCovered}
      icon={EndedIcon}
      text={until ? t.ended.cooling(character.name, until) : t.events.ended(character.name)}
    >
      {until && giveHer}
      <Button size="lg" disabled={!snapshot.canStartNew} onClick={() => void live?.startNewConversation()}>
        {t.ended.newConversation}
      </Button>
    </ComposerCard>
  ) : until ? (
    // 冷却中：一行说明代替输入框，右边是去礼物页的「送她一件礼物」；草稿留着，到点换回输入框时还在。
    <div inert={isCovered} className="flex min-h-14 shrink-0 items-center gap-3 border-t bg-background px-3 py-2">
      <div role="status" className="flex min-w-0 flex-1 items-center gap-2 text-body text-muted-foreground">
        <CooldownIcon aria-hidden className="size-4 shrink-0" />
        <p>{t.affinity.coolingComposer(character.name, until)}</p>
      </div>
      {giveHer}
    </div>
  ) : (
    <form
      inert={isCovered}
      className="flex shrink-0 flex-col gap-2 border-t bg-background px-3 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        void live?.submit(picture);
        setPicture(null);
      }}
    >
      {/* 失败的原因（没登录时带去登录的入口）；通话层盖着时整栏 inert，Tab 摸不到 */}
      {failure && <FailureNotice failure={{ ...failure, message: failureText(failure) }} />}
      {voiceFailure && (
        <p role="status" className="px-1 text-meta text-destructive">
          {voiceFailure}
        </p>
      )}
      {picture && (
        <div className="flex items-start gap-2">
          <img src={picture} alt={t.imageAttached} className="max-h-24 rounded-bubble border object-contain" />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t.removeImage}
            onClick={() => setPicture(null)}
          >
            <CloseIcon className="size-4" />
          </Button>
        </div>
      )}
      <div className="flex items-end gap-2">
        <input
          ref={pictureInput}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            const reader = new FileReader();
            reader.onload = () => setPicture(typeof reader.result === "string" ? reader.result : null);
            reader.readAsDataURL(file);
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-lg"
          aria-label={t.attachImage}
          disabled={!isOpen}
          onClick={() => pictureInput.current?.click()}
        >
          <AttachImageIcon className="size-5" />
        </Button>
        <Textarea
          variant="composer"
          rows={1}
          value={draft}
          onChange={(e) => live?.setDraft(e.target.value)}
          onKeyDown={(e) => {
            // 回车发送，Shift+回车换行；输入法选字时的回车不算。
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void live?.submit(picture);
              setPicture(null);
            }
          }}
          placeholder={t.placeholder}
          aria-label={t.placeholder}
          disabled={!isOpen}
          className="flex-1"
        />
        {/* 发语音：点一下开始录，再点一下停下并发送。录音时按键变成红实底并呼吸，
            这样不看图标也知道正在录；识别中显示转圈。 */}
        <Button
          type="button"
          variant={recording === null ? "ghost" : "destructive"}
          size="icon-lg"
          aria-label={recording === null ? t.voiceStart : t.voiceStop}
          aria-pressed={recording !== null}
          disabled={!isOpen || transcribing}
          onClick={() => void toggleVoice()}
          className={recording === null ? undefined : "animate-pulse"}
        >
          {transcribing ? <Spinner className="size-5" /> : <MicIcon className="size-5" />}
        </Button>
        {/* 按下时不抢输入框的焦点：手机上一失焦键盘就收、dock 冒出来，输入栏跟着跳走，这一下点击落空 */}
        <Button
          type="submit"
          variant="her"
          size="icon-lg"
          aria-label={t.send}
          disabled={!canSend}
          onMouseDown={(e) => e.preventDefault()}
        >
          <SendIcon className="size-5" />
        </Button>
      </div>
    </form>
  );

  return (
    <Frame character={character} subtree={subtree} header={header}>
      {barShown && <CallBar ref={focus.note} call={call} onExpand={() => live?.expand()} />}
      <div inert={isCovered} className="relative isolate min-h-0 flex-1">
        {/* 地点图在最底下（-z-10）：页首、消息、输入栏都在它上面，不接点击 */}
        <PlaceBackdrop imageUrl={placeImage} />
        {/* 历史对话：读到之前转圈；换一段时消息区重来，停在最底 */}
        {viewing ? (
          viewing.status === "open" ? (
            <Messages
              key={viewing.id}
              entries={viewing.entries}
              hearing=""
              character={character}
              affinityOn={affinity !== null}
              timeZone={timeZone}
            />
          ) : viewing.status === "failed" ? (
            <Empty className="h-full">
              <EmptyHeader>
                <EmptyTitle>{t.past.openFailed}</EmptyTitle>
                <EmptyDescription>{viewing.failure.message}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex h-full items-center justify-center">
              <Spinner className="size-6 text-muted-foreground" aria-label={t.past.opening} />
            </div>
          )
        ) : /* 开新对话的过程中也是 opening：旧对话留在原处，只是发送键和电话键禁用 */
        !isOpen && entries.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <Spinner className="size-6 text-muted-foreground" aria-label={t.loading} />
          </div>
        ) : entries.length === 0 && !hearing ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyTitle>{t.emptyTitle(character.name)}</EmptyTitle>
              {/* 冷却时输入栏换成说明、电话键禁用，「打字，或者点电话」不对 */}
              {!cooling && <EmptyDescription>{t.emptyDescription}</EmptyDescription>}
            </EmptyHeader>
          </Empty>
        ) : (
          <Messages
            entries={entries}
            hearing={hearing}
            character={character}
            affinityOn={affinity !== null}
            timeZone={timeZone}
          />
        )}
        {/* 右下角站着的小立绘：通话层或者通话条在用时整块拿掉，免得和通话层的立绘重复；本地收起来了也不画 */}
        {appearance.chatStand && !layer && !viewing && outfits && !standHidden && (
          <ChatCompanion
            character={character}
            outfits={outfits.toTry}
            isReplying={lastReply.isReplying}
            said={lastReply.said}
            spoken={spoken}
            emotion={snapshot.lastEmotion}
            onHide={standHiddenKey === null ? undefined : hideStand}
            menuContainer={subtree}
          />
        )}
      </div>
      {composer}
      <PastConversations
        isOpen={pickingPast}
        onOpenChange={setPickingPast}
        isWide={!isFullScreen}
        character={character}
        viewingId={viewing?.id ?? null}
        onPick={(row) => {
          setPickingPast(false);
          if (row.isCurrent) {
            if (viewing) backToCurrent();
          } else if (row.conversation.id !== viewing?.id) {
            view(row.conversation.id);
          }
        }}
        onDeleted={(id) => {
          if (id === viewing?.id) backToCurrent();
        }}
      />
      <AchievementsPanel
        isOpen={achievements.isPanelOpen}
        onOpenChange={achievements.setPanelOpen}
        isWide={!isFullScreen}
        color={character.color}
        her={achievements.her}
        unseen={achievements.unseenRows}
      />
      <AdminAffinityDialog
        userId={userId}
        character={character}
        affinity={affinity}
        isOpen={adjustingAffinity}
        onOpenChange={setAdjustingAffinity}
        onSaved={() => void live?.refreshAffinity()}
      />
      {live && (
        <LiveCallLayer
          live={live}
          character={character}
          standOutfits={outfits?.toTry ?? []}
          layerRef={focus.layer}
          isFullScreen={isFullScreen}
          go={go}
          exemptingKeys={account?.exempting_keys ?? null}
        />
      )}
      {outfits && (
        <OutfitPicker
          isOpen={pickingOutfit}
          onOpenChange={setPickingOutfit}
          isWide={!isFullScreen}
          isReducedMotion={isReducedMotion}
          color={character.color}
          outfits={outfits}
        />
      )}
    </Frame>
  );
}

/**
 * 对话这一栏：注入她的颜色，铺她的壁纸（页首和消息区同一张，DESIGN.md「The Wallpaper Rule」），
 * 页首在上，其余填满。通话层绝对定位盖在上面。
 */
function Frame({
  character,
  subtree,
  header,
  children,
}: {
  character: Character;
  subtree: RefObject<HTMLDivElement | null>;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      ref={subtree}
      style={herVars(character.color)}
      className="relative flex h-full flex-col overflow-hidden bg-her-wall text-foreground"
    >
      {header}
      {children}
    </div>
  );
}

/**
 * 代替输入栏的一张卡（结束卡、只读卡）：左边 muted 的小图标加一句话，右边是按钮；一行放不下时按钮换到下一行、靠右。
 */
function ComposerCard({
  inert,
  icon: Icon,
  text,
  children,
}: {
  inert: boolean;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  text: string;
  children: ReactNode;
}) {
  return (
    <div
      inert={inert}
      className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-t bg-background px-3 py-2"
    >
      <div role="status" className="flex min-w-48 flex-1 items-center gap-2 text-body text-muted-foreground">
        <Icon aria-hidden className="size-4 shrink-0" />
        <p>{text}</p>
      </div>
      <div className="ml-auto flex gap-2">{children}</div>
    </div>
  );
}

/**
 * 历史对话换掉输入栏的只读卡（`ComposerCard`）：历史图标加「这是你们的历史对话」（她结束了的另有一句），
 * 右边描边的大号「回到当前对话」。
 */
/**
 * 页首好感度标识左边的奖杯（DESIGN.md「Buttons」）：解锁她的阶段时跳出来，奖杯加「+n」（这次到账的抽奖次数），
 * 弹出、停住、淡出共 3 秒（`animate-trophy`）；减少动态时只淡入淡出。读屏读旁边的 live region，这里藏起来。
 */
function TrophyCue({ trophy, isReducedMotion }: { trophy: Trophy; isReducedMotion: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center gap-1 px-1 text-sm tabular-nums",
        isReducedMotion ? "animate-trophy-fade" : "animate-trophy",
      )}
    >
      <AchievementsIcon className="size-4" />+{trophy.draws}
    </span>
  );
}

function ReadOnlyCard({
  viewing,
  inert,
  onBackToCurrent,
}: {
  viewing: Viewing;
  inert: boolean;
  onBackToCurrent: () => void;
}) {
  const ended = viewing.status === "open" && viewing.ended;
  return (
    <ComposerCard inert={inert} icon={PastConversationsIcon} text={ended ? t.past.readOnlyEnded : t.past.readOnly}>
      <Button variant="outline" size="lg" onClick={onBackToCurrent}>
        {t.past.backToCurrent}
      </Button>
    </ComposerCard>
  );
}

/** 页首图标键的提示。 */
function HeaderTip({ label, children }: { label: string; children: ReactElement }) {
  return (
    <Tooltip>
      <TooltipTrigger render={children} />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * 消息区：官方 Message Scroller，打开时停在最底，新消息和她正在说的话跟着往下滚（制作人往上翻时不抢）。
 * 消息从顶部开始排；气泡之间 4px，换人时多 8px。好感度可用时，改变了好感度的回复和送礼记录后面是一行变化胶囊。
 * 这一小时的照片用完时，她推掉的那条回复后面是一行同样的胶囊，几点以后可以再要按制作人的时区（`timeZone`）写。
 * 对话事件占一整行分隔线。
 */
function Messages({
  entries,
  hearing,
  character,
  affinityOn,
  timeZone,
}: {
  entries: Entry[];
  hearing: string;
  character: Character;
  affinityOn: boolean;
  timeZone: string;
}) {
  const lines = linesOf(entries, new Date(), affinityOn);
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <MessageScroller>
        <MessageScrollerViewport>
          <MessageScrollerContent className="gap-1 px-3 pt-2 pb-4">
            {lines.map((line) =>
              line.kind === "day" ? (
                <MessageScrollerItem key={line.key} className="my-3 flex justify-center">
                  <span className="rounded-full bg-foreground/10 px-3 py-1 text-meta text-muted-foreground">
                    {line.label}
                  </span>
                </MessageScrollerItem>
              ) : line.kind === "cue" ? (
                <MessageScrollerItem key={line.key} className="mt-2 flex justify-center">
                  {/* 好感度的变化胶囊：一个升降小箭头加一句话；有判断模型的分级时，
                      后面补上「好感 -2 · 让她有点不舒服」，看得出为什么变 */}
                  <Capsule>
                    <CueArrowIcon up={line.change.up} className="size-3" />
                    {cueText(line.change, character.name)}
                    {line.change.step != null && (
                      <span className="text-muted-foreground">{changeNote(line.change)}</span>
                    )}
                  </Capsule>
                </MessageScrollerItem>
              ) : line.kind === "photos-used-up" ? (
                <MessageScrollerItem key={line.key} className="mt-2 flex justify-center">
                  {/* 照片用完的胶囊：不存进库，刷新后就没了 */}
                  <Capsule>
                    <PhotosUsedUpIcon aria-hidden className="size-3" />
                    {photosUsedUpText(line.retryAt, timeZone)}
                  </Capsule>
                </MessageScrollerItem>
              ) : line.entry.kind === "event" ? (
                <MessageScrollerItem key={line.entry.key} messageId={line.entry.key} className="my-3">
                  <EventLine entry={line.entry} name={character.name} />
                </MessageScrollerItem>
              ) : (
                <MessageScrollerItem key={line.entry.key} messageId={line.entry.key} className={cn(line.first && "mt-2")}>
                  <Bubbled line={line} entry={line.entry} character={character} />
                </MessageScrollerItem>
              ),
            )}
            {hearing && (
              <MessageScrollerItem key="hearing" className="mt-2">
                {/* 用户正在说、还没定稿的话：制作人那一侧，不成气泡 */}
                <Message align="end">
                  <Bubble variant="ghost" align="end">
                    <BubbleContent aria-label={t.hearing}>
                      <p className="text-body text-muted-foreground">{hearing}</p>
                    </BubbleContent>
                  </Bubble>
                </Message>
              </MessageScrollerItem>
            )}
          </MessageScrollerContent>
        </MessageScrollerViewport>
      </MessageScroller>
    </MessageScrollerProvider>
  );
}

/** 一条对话事件：两边细线，中间图标、一句话和时间；不用她的颜色。 */
function EventLine({ entry, name }: { entry: Extract<Entry, { kind: "event" }>; name: string }) {
  const Icon = EVENT_ICONS[entry.event];
  return (
    <div role="note" className="flex items-center gap-3 px-2 text-sm text-muted-foreground">
      <span aria-hidden className="h-px flex-1 bg-foreground/15" />
      <span className="flex shrink-0 items-center gap-1.5">
        <Icon aria-hidden className="size-4" />
        {eventText(entry.event, name, entry.gift)}
        <time className="text-meta tabular-nums">{clock(entry.at)}</time>
      </span>
      <span aria-hidden className="h-px flex-1 bg-foreground/15" />
    </div>
  );
}

/**
 * 一条消息。制作人的在右，深蓝墨水；她的在左，日语原文在上、中文字幕在下（The Original-Then-Subtitle Rule）。
 * 头像和名字只在一组的第一条，时间只在最后一条的外侧底部。
 */
function Bubbled({
  line: { first, last },
  entry,
  character,
}: {
  line: Extract<Line, { kind: "entry" }>;
  entry: Exclude<Entry, { kind: "event" }>;
  character: Character;
}) {
  const time = <time className="shrink-0 pb-0.5 text-meta text-muted-foreground tabular-nums">{clock(entry.at)}</time>;
  const speech = useSyncExternalStore(subscribeSpeech, speechState, speechState);
  // 这条回复说到的原声（功能 1）：放到哪一段、是不是正在放它；一段原声只放一个。
  const voice = entry.kind === "character" ? (entry.voice ?? null) : null;
  const clip = useSyncExternalStore(subscribeVoiceLine, voiceLineState, voiceLineState);
  const clipKey = `${entry.key}:${voice?.audio_url ?? ""}`;
  const playingVoice = voice !== null && clip?.key === clipKey;
  /** 这条回复在数据库里的编号（`m12`、搭话的 `r12`）；还没落库的聊天记录没有。 */
  const speechId = /^[mr]\d+$/.test(entry.key) ? Number(entry.key.slice(1)) : null;
  const speaker =
    speechId === null ? null : (
      <button
        type="button"
        onClick={() => {
          stopVoiceLine(); // 和「原声」共用一个耳朵
          toggleSpeech(speechId);
        }}
        aria-label={speech?.messageId === speechId ? t.speaking : t.speak}
        aria-pressed={speech?.messageId === speechId}
        className="shrink-0 pb-0.5 text-muted-foreground transition-colors hover:text-foreground"
      >
        {speech?.messageId === speechId && speech.phase === "loading" ? (
          <Spinner className="size-4" />
        ) : (
          <SpeakIcon className="size-4" />
        )}
      </button>
    );
  const originalVoice = voice === null ? null : (
    <button
      type="button"
      onClick={() => toggleVoiceLine(clipKey, voice.audio_url)}
      aria-label={playingVoice ? t.voiceOriginalStop : t.voiceOriginalPlay}
      aria-pressed={playingVoice}
      title={t.voiceOriginalPlay}
      className="flex shrink-0 items-center gap-0.5 pb-0.5 text-meta text-muted-foreground transition-colors hover:text-foreground"
    >
      {playingVoice && clip?.phase === "loading" ? (
        <Spinner className="size-3.5" />
      ) : (
        <VoiceIcon aria-hidden className="size-3.5" />
      )}
      {t.voiceOriginal}
    </button>
  );
  if (entry.kind === "user") {
    return (
      <Message align="end">
        <div className="flex min-w-0 flex-1 items-end justify-end gap-1.5">
          {last && time}
          <Bubble variant="producer" align="end" joinsPrevious={!first} joinsNext={!last}>
            <BubbleContent>
              {entry.image && (
                <img
                  src={entry.image}
                  alt=""
                  className="mb-1 max-h-64 rounded-bubble object-contain"
                />
              )}
              <p className="text-body whitespace-pre-wrap">{entry.text}</p>
            </BubbleContent>
          </Bubble>
        </div>
      </Message>
    );
  }
  return (
    <Message align="start">
      {first ? (
        <MarkedAvatar name={character.name} src={character.avatar_url} size="bubble" />
      ) : (
        <span aria-hidden className="w-bubble-avatar shrink-0" />
      )}
      <MessageContent className="gap-1">
        {first && <MessageHeader className="px-1">{character.name}</MessageHeader>}
        {entry.photo && <PhotoBlock photo={entry.photo} />}
        <div className="flex min-w-0 items-end gap-1.5">
          <Bubble variant="her" joinsPrevious={!first} joinsNext={!last}>
            <BubbleContent>
              {entry.segments.length === 0 ? (
                <Spinner className="my-1 text-muted-foreground" aria-label={t.replying(character.name)} />
              ) : (
                <div className="flex flex-col gap-2">
                  {entry.segments.map((segment, i) => (
                    <div key={i} className="flex flex-col gap-0.5">
                      <p className="text-japanese-line">
                        <Ja>{segment.ja}</Ja>
                      </p>
                      {segment.zh && <p className="text-subtitle text-muted-foreground">{segment.zh}</p>}
                    </div>
                  ))}
                </div>
              )}
            </BubbleContent>
          </Bubble>
          {last && !entry.pending && originalVoice}
          {last && !entry.pending && speaker}
          {last && !entry.pending && time}
        </div>
        {/* 原声正在放时的那段：日语原句在上、中文字幕在下（The Original-Then-Subtitle Rule）。 */}
        {playingVoice && voice && (
          <div className="flex max-w-[min(30rem,78vw)] flex-col gap-0.5 px-1">
            <p className="text-japanese-line whitespace-pre-wrap">
              <Ja>{voice.text}</Ja>
            </p>
            {voice.subtitle && <p className="text-subtitle text-muted-foreground">{voice.subtitle}</p>}
          </div>
        )}
      </MessageContent>
    </Message>
  );
}

/** 气泡旁的时刻，写成 8:49（和列表里今天的时间一样）。 */
function clock(at: string): string {
  const d = new Date(at);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 失败提示：后端给的原因；撞上限额时说带上自己的 LLM 就不受限额（按钮是「去设置自带密钥」），
 * 知道算不算限额时再加一句（GLOSSARY.md「限额」「免限额密钥」）。 */
function failureText(failure: Failure): string {
  return [failure.message, failure.toOwnKeys && t.ownLLMExempts, failure.countsTowardLimit === false && t.notCounted]
    .filter(Boolean)
    .join(" ");
}

/** 对话记录里居中的一颗胶囊（好感度的变化、照片用完）：样子和日期条一样，一个小图标加一句话，不用她的颜色。 */
function Capsule({ children }: { children: ReactNode }) {
  return (
    <span className="flex items-center gap-1 rounded-full bg-foreground/10 px-3 py-1 text-meta text-muted-foreground">
      {children}
    </span>
  );
}
