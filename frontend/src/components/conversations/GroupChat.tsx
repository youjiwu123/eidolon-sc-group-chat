"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { PhoneIcon, SpeakIcon } from "@/theme/icons";
import { speechState, stopSpeech, subscribeSpeech, toggleSpeech } from "@/lib/messageSpeech";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { getGroupPlace, sceneImageUrl, setGroupPlace, type Character, type GroupPlace } from "@/lib/api";
import {
  getGroup,
  inviteMember,
  renameGroup,
  startChatter,
  sendGroupTurn,
  groupSpeechUrl,
  startWelcome,
  getGroupMessageEmotion,
  type Group,
  type GroupMessage,
} from "@/lib/groups";
import { loadStandHidden, saveStandHidden } from "@/lib/standVisibility";
import { copy } from "@/i18n";
import { useDirectory } from "./ConversationDirectory";
import { GroupCompanion, type GroupEmotion } from "./GroupCompanion";
import { PlaceBackdrop } from "./PlaceBackdrop";
import { PlacePicker } from "./PlacePicker";

function nameOf(characters: Character[] | null, id: string): string {
  const found = characters?.find((c) => c.id === id);
  return found ? (found.name_zh ?? found.name) : id;
}

function avatarOf(characters: Character[] | null, id: string): string | null {
  return characters?.find((c) => c.id === id)?.avatar_url ?? null;
}

/** 一个群的对话：谁说的、说了什么；发一句话，她们接着回。 */
export function GroupChat({ groupId, characters }: { groupId: string; characters: Character[] | null }) {
  const [group, setGroup] = useState<Group | null>(null);
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [typing, setTyping] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [autoChat, setAutoChatState] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  /** 群里现在的地点（页首的地点下拉栏，DESIGN.md「通话场景」）：还没挑是 null。 */
  const [place, setPlace] = useState<GroupPlace | null>(null);
  /** 群里的立绘被整群临时收起来了吗：和外观里全局的「对话页显示立绘」分开，按群记在这台设备上。 */
  const [standHidden, setStandHidden] = useState(false);
  const standHiddenKey = `groupStandHidden:${groupId}`;
  const speech = useSyncExternalStore(subscribeSpeech, speechState, speechState);
  const { appearance } = useDirectory();
  /** 连续朗读：她的回复一条接一条自动念下去。 */
  const [listening, setListening] = useState(false);
  /** 下一条要念的是第几条（按消息列表的下标）。 */
  const nextLine = useRef(0);
  /** 每位刚才那一句的语气：她的小人照它摆。 */
  const [cues, setCues] = useState<Record<string, GroupEmotion>>({});
  /** 判过语气（或者打开页面时就已经存在）的消息，不重复判。 */
  const judged = useRef<Set<number> | null>(null);
  const busy = useRef(false);
  const sendingRef = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await getGroup(groupId);
      setGroup(data.group);
      setMessages(data.messages);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    }
  }, [groupId]);

  useEffect(() => {
    void load();
    setAutoChatState(window.localStorage.getItem(`group-auto-${groupId}`) === "1");
  }, [load, groupId]);

  // 群里现在的地点（页首的地点下拉栏）：进来问一次，挑一个以后用接口回来的更新。
  useEffect(() => {
    let alive = true;
    getGroupPlace(groupId)
      .then((next) => {
        if (alive) setPlace(next);
      })
      .catch(() => {
        if (alive) setPlace(null);
      });
    return () => {
      alive = false;
    };
  }, [groupId]);

  // 本地收起来过的话，重新打开这个群还是收起的。
  useEffect(() => {
    setStandHidden(loadStandHidden(standHiddenKey));
  }, [standHiddenKey]);

  // 自动聊天跟着这个页面走：开着就每 20 秒让她们聊一轮，关掉网页、锁屏就停。
  // 依赖里只放开关和群——把 typing 放进来会让计时器不停重建，收到的消息被丢掉。
  useEffect(() => {
    if (!autoChat) return;
    let stopped = false;
    const run = async () => {
      if (stopped || busy.current || sendingRef.current) return;
      busy.current = true;
      try {
        await startChatter(groupId, (event) => {
          if (event.type === "thinking") setTyping(event.speaker_id);
          else if (event.type === "message") {
            setTyping(null);
            setMessages((current) => [...current, event.message]);
          } else if (event.type === "done") setTyping(null);
        });
      } catch (error) {
        if (String(error).includes("429")) {
          setAutoChatState(false);
          setFailure(copy.groups.quotaOut);
        }
      } finally {
        busy.current = false;
      }
    };
    const timer = setInterval(() => void run(), 20000);
    // 开满 20 分钟自己关掉，免得忘了它还开着。
    const stop = setTimeout(() => {
      setAutoChatState(false);
      setFailure(copy.groups.autoStopped);
    }, 20 * 60 * 1000);
    return () => {
      stopped = true;
      clearInterval(timer);
      clearTimeout(stop);
      setTyping(null);
    };
  }, [autoChat, groupId]);

  // 连续朗读：一条念完，接着念下一条她说的；没有下一条就自己关掉。
  useEffect(() => {
    if (!listening || speech !== null) return;
    for (let i = nextLine.current; i < messages.length; i++) {
      const message = messages[i];
      if (message.role !== "character" || message.segments.every((segment) => !segment.ja)) continue;
      nextLine.current = i + 1;
      toggleSpeech(message.id, groupSpeechUrl(groupId, message.id));
      return;
    }
    setListening(false);
  }, [listening, speech, messages, groupId]);

  /** 开/关连续朗读：开的时候从这一轮她们的回话开始念，念完再听新的。 */
  const toggleListen = () => {
    if (listening) {
      setListening(false);
      stopSpeech();
      return;
    }
    const lastUser = messages.reduce((at, message, index) => (message.role === "user" ? index : at), -1);
    const first = messages.findIndex((message, index) => index > lastUser && message.role === "character");
    nextLine.current = first >= 0 ? first : messages.length;
    setListening(true);
  };
  // 每 15 秒对一次账：别的窗口、别的设备、或者漏掉的事件，都靠它补上。
  useEffect(() => {
    const pull = async () => {
      if (busy.current || sendingRef.current) return;
      try {
        const data = await getGroup(groupId);
        setGroup(data.group);
        setMessages((current) => (data.messages.length > current.length ? data.messages : current));
      } catch {
        /* 下一轮再试 */
      }
    };
    const timer = setInterval(() => void pull(), 15000);
    return () => clearInterval(timer);
  }, [groupId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  /** 解析开头的 `/名字`：给谁说的。名字按中文名、日文名或 id 前缀认。 */
  const parseTarget = (raw: string): { text: string; targetId: string | null } => {
    const match = raw.match(/^\/([^\s/]+)\s+([\s\S]+)$/);
    if (!match) return { text: raw, targetId: null };
    const wanted = match[1];
    const found = (characters ?? []).find(
      (c) =>
        c.id === wanted ||
        c.name === wanted ||
        c.name_zh === wanted ||
        c.name.startsWith(wanted) ||
        (c.name_zh?.startsWith(wanted) ?? false),
    );
    if (!found || !members.includes(found.id)) return { text: raw, targetId: null };
    return { text: match[2].trim(), targetId: found.id };
  };

  // 群里「插话」用：她们还在说时按 Enter，先把这一轮掐掉、紧接着把你新打的一句发出去。
  // 每一轮拿一个号，被掐掉的那一轮晚到的 catch/finally 看到号变了就不再动状态。
  const turn = useRef(0);

  const send = async (interrupt = false) => {
    const parsed = parseTarget(draft.trim());
    const text = parsed.text.trim();
    if (!text) return;
    if (sending) {
      // 没让插话（比如点了按钮以外的地方）就照旧不重发；插话才掐断。
      if (!interrupt) return;
      abort.current?.abort();
    }
    const mine = ++turn.current;
    setSending(true);
    sendingRef.current = true;
    setFailure(null);
    setTyping(null);
    const optimistic: GroupMessage = {
      id: -Date.now(),
      role: "user",
      speaker_id: null,
      segments: [{ ja: "", zh: text }],
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    setDraft("");
    abort.current = new AbortController();
    try {
      await sendGroupTurn(groupId, text, (event) => {
        if (event.type === "thinking") setTyping(event.speaker_id);
        else if (event.type === "message") {
          setTyping(null);
          setMessages((current) => [...current, event.message]);
        } else if (event.type === "done") setTyping(null);
      }, parsed.targetId, abort.current.signal);
    } catch (error) {
      // 自己掐掉的那一轮不算失败：插话时旧请求会以 AbortError 结束。
      const aborted = error instanceof DOMException && error.name === "AbortError";
      if (turn.current === mine && !aborted) {
        setFailure(error instanceof Error ? error.message : String(error));
      }
    } finally {
      // 号变了说明这一轮已经被掐掉、换成了新的一句，别把新那一轮的状态盖回去。
      if (turn.current === mine) {
        setTyping(null);
        setSending(false);
        sendingRef.current = false;
      }
    }
  };

  // 兜底：真卡住了也不要一直禁用发送键。
  useEffect(() => {
    if (!sending) return;
    const guard = setTimeout(() => {
      setSending(false);
      sendingRef.current = false;
      setTyping(null);
    }, 90000);
    return () => clearTimeout(guard);
  }, [sending]);

  // 页首的下拉栏里挑一处地方：接口回来的就是群里现在的地点，页首立刻换过去（null 是不设置）。
  const pickPlace = async (sceneId: string | null): Promise<void> => {
    setPlace(await setGroupPlace(groupId, sceneId));
  };

  // 消息区背后的地点图（DESIGN.md「通话场景」）：群里选了地点才铺，没选就保持现在的页面底色。
  const placeImage = place === null ? null : place.image_url || sceneImageUrl(place.id);

  const members = group?.participants ?? [];

  // 每来一条她说的消息就问一次语气：答回来以后，她那一位小人照着摆一会儿。
  useEffect(() => {
    if (judged.current === null) {
      // 打开这一页时已经有的消息不补判，从新来的开始。
      judged.current = new Set(messages.map((message) => message.id));
      return;
    }
    for (const message of messages) {
      if (message.role !== "character" || !message.speaker_id || judged.current.has(message.id)) continue;
      judged.current.add(message.id);
      const speaker = message.speaker_id;
      void getGroupMessageEmotion(groupId, message.id)
        .catch(() => null)
        .then((answer) => {
          if (!answer) return;
          setCues((current) => ({
            ...current,
            [speaker]: { mood: answer.emotion, nod: answer.nod, strength: answer.strength, at: Date.now() },
          }));
        });
    }
  }, [messages, groupId]);
  // 群聊里的立绘：群里几位就站几位，各站各的；外观里关掉了、或者在这一群里本地收起来了，就都不站。
  const companions = useMemo(() => {
    if (!appearance.chatStand || standHidden || !characters) return [];
    return members
      .map((id) => characters.find((candidate) => candidate.id === id))
      .filter((candidate): candidate is Character => candidate !== undefined);
  }, [appearance.chatStand, standHidden, characters, members]);
  /** 任意一位的「⋯」都收整群；页首的「显示立绘」恢复。 */
  const hideStands = () => {
    setStandHidden(true);
    saveStandHidden(standHiddenKey, true);
  };
  const restoreStands = () => {
    setStandHidden(false);
    saveStandHidden(standHiddenKey, false);
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Link href="/groups" className="text-meta text-muted-foreground hover:underline">
          {copy.groups.back}
        </Link>
        <div className="flex -space-x-2">
          {members.slice(0, 3).map((id) => (
            <MarkedAvatar key={id} name={nameOf(characters, id)} src={avatarOf(characters, id)} size="sm" />
          ))}
        </div>
        {renaming ? (
          <div className="flex flex-1 items-center gap-2">
            <Input
              autoFocus
              value={nameDraft}
              onChange={(event) => setNameDraft(event.target.value)}
              maxLength={40}
              className="h-8 flex-1"
            />
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const updated = await renameGroup(groupId, nameDraft.trim());
                  setGroup((current) => (current ? { ...current, title: updated.title } : current));
                } catch (error) {
                  setFailure(error instanceof Error ? error.message : String(error));
                } finally {
                  setRenaming(false);
                }
              }}
            >
              {copy.groups.saveName}
            </Button>
          </div>
        ) : (
          <button
            type="button"
            className="min-w-0 flex-1 truncate text-left text-base hover:underline"
            onClick={() => {
              setNameDraft(group?.title ?? members.map((id) => nameOf(characters, id)).join("、"));
              setRenaming(true);
            }}
          >
            {group?.title ?? members.map((id) => nameOf(characters, id)).join("、")}
          </button>
        )}
        {/* 群里现在的地点（DESIGN.md「通话场景」）：点开挑一处，或者不设置；还没挑时写「选地点」 */}
        <PlacePicker
          sceneId={place?.id ?? null}
          clearLabel={copy.place.none}
          trigger={<Button size="sm" variant="ghost" className="max-w-40" />}
          onPick={pickPlace}
        >
          <span className="min-w-0 truncate">
            {place === null ? copy.groups.place.pick : copy.groups.place.current(place.name)}
          </span>
        </PlacePicker>
        {/* 整群的立绘收起来时页首的「显示立绘」胶囊：点一下她们都回来 */}
        {appearance.chatStand && standHidden && (
          <Button variant="pill" className="max-md:h-11" onClick={restoreStands}>
            {copy.groups.showStand}
          </Button>
        )}
        <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
          <DialogTrigger render={<Button size="sm" variant="ghost" />}>{copy.groups.invite}</DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{copy.groups.invite}</DialogTitle>
              <DialogDescription>{copy.groups.inviteHint}</DialogDescription>
            </DialogHeader>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {(characters ?? [])
                .filter((c) => !members.includes(c.id))
                .map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-muted"
                    onClick={async () => {
                      try {
                        const updated = await inviteMember(groupId, c.id);
                        setGroup((current) =>
                          current ? { ...current, participants: updated.participants } : current,
                        );
                        setInviteOpen(false);
                        if (updated.notice) {
                          setMessages((current) => [...current, updated.notice as GroupMessage]);
                        }
                        setSending(true);
                        await startWelcome(groupId, c.id, (event) => {
                          if (event.type === "thinking") setTyping(event.speaker_id);
                          else if (event.type === "message") {
                            setTyping(null);
                            setMessages((current) => [...current, event.message]);
                          } else if (event.type === "done") setTyping(null);
                        });
                      } catch (error) {
                        setFailure(error instanceof Error ? error.message : String(error));
                      } finally {
                        setTyping(null);
                        setSending(false);
                      }
                    }}
                  >
                    <MarkedAvatar name={c.name} src={c.avatar_url} size="sm" />
                    <span className="text-base">{c.name_zh ?? c.name}</span>
                  </button>
                ))}
            </div>
          </DialogContent>
        </Dialog>
        <Button size="sm" variant="ghost" className="gap-1" render={<Link href={`/groups/${groupId}/call`} />}>
          <PhoneIcon aria-hidden className="size-3.5" />
          {copy.groups.call}
        </Button>
        <Button size="sm" variant="ghost" className="gap-1" render={<Link href={`/groups/${groupId}/room`} />}>
          <PhoneIcon aria-hidden className="size-3.5" />
          {copy.groups.room}
        </Button>
        <Button size="sm" variant={listening ? "secondary" : "ghost"} className="gap-1" onClick={toggleListen}>
          <SpeakIcon aria-hidden className="size-3.5" />
          {listening ? copy.groups.stopListening : copy.groups.listen}
        </Button>
        <label className="flex shrink-0 items-center gap-2 text-meta text-muted-foreground">
          <Switch
            checked={autoChat}
            onCheckedChange={(next) => {
              setAutoChatState(next);
              window.localStorage.setItem(`group-auto-${groupId}`, next ? "1" : "0");
            }}
          />
          {copy.groups.chatter}
        </label>
      </header>

      <div className="relative isolate min-h-0 flex-1">
      {/* 地点图在最底下（-z-10）：消息、她们的小人、输入栏都在它上面，不接点击 */}
      <PlaceBackdrop imageUrl={placeImage} />
      <div className="h-full space-y-3 overflow-y-auto px-3 py-4">
        {messages.map((message) =>
          message.role === "system" ? (
            <p key={message.id} className="py-1 text-center text-meta text-muted-foreground">
              {message.segments[0]?.zh || message.segments[0]?.ja}
            </p>
          ) : message.role === "user" ? (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl bg-primary px-3 py-2 text-primary-foreground">
                {(message.segments[0]?.zh || message.segments[0]?.ja) ?? ""}
              </div>
            </div>
          ) : (
            <div key={message.id} className="flex gap-2">
              <MarkedAvatar
                name={nameOf(characters, message.speaker_id ?? "")}
                src={message.speaker_id ? avatarOf(characters, message.speaker_id) : null}
                size="bubble"
              />
              <div className="max-w-[80%] space-y-1">
                <p className="text-meta text-muted-foreground">
                  {message.speaker_id ? nameOf(characters, message.speaker_id) : ""}
                </p>
                <div className="space-y-1 rounded-2xl bg-muted px-3 py-2">
                  {message.segments.map((segment, index) => (
                    <div key={index}>
                      {segment.ja && <p className="text-base">{segment.ja}</p>}
                      {segment.zh && <p className="text-meta text-muted-foreground">{segment.zh}</p>}
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  aria-label={copy.groups.speak}
                  className="flex items-center gap-1 text-meta text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    // 手动点某一条：连续朗读从这一条的下一条接着念。
                    const at = messages.findIndex((item) => item.id === message.id);
                    if (at >= 0) nextLine.current = at + 1;
                    toggleSpeech(message.id, groupSpeechUrl(groupId, message.id));
                  }}
                >
                  <SpeakIcon aria-hidden className="size-3.5" />
                  {speech?.messageId === message.id
                    ? speech.phase === "loading"
                      ? copy.groups.speakingLoading
                      : copy.groups.speaking
                    : copy.groups.speak}
                </button>
              </div>
            </div>
          ),
        )}
        {typing && (
          <div className="flex items-center gap-2 text-meta text-muted-foreground">
            <Spinner className="size-4" />
            {copy.groups.typing(nameOf(characters, typing))}
          </div>
        )}
        {failure && <p className="text-meta text-destructive">{failure}</p>}
        <div ref={bottom} />
      </div>
        {companions.map((character, index) => (
          <GroupCompanion
            key={character.id}
            groupId={groupId}
            character={character}
            index={index}
            count={companions.length}
            isTyping={typing === character.id}
            messages={messages}
            speech={speech}
            emotion={cues[character.id] ?? null}
            onHide={hideStands}
            hideLabel={copy.groups.hideStand}
          />
        ))}
      </div>

      <div className="flex items-end gap-2 border-t p-3">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              // 她们还在说就直接插话：掐掉这一轮，马上把新的一句发出去。
              void send(true);
            }
          }}
          placeholder={copy.groups.placeholderHint}
          className="min-h-10 flex-1 resize-none"
          rows={1}
        />
        <Button
          variant={sending ? "destructive" : "outline"}
          disabled={!sending && !draft.trim()}
          className="disabled:bg-background disabled:text-muted-foreground disabled:opacity-60"
          onClick={() => {
            if (sending) {
              turn.current += 1; // 这一轮作废，晚到的 catch/finally 不再动状态
              abort.current?.abort();
              setSending(false);
              sendingRef.current = false;
              setTyping(null);
              return;
            }
            void send();
          }}
        >
          {sending ? copy.groups.stop : copy.groups.send}
        </Button>
      </div>
    </div>
  );
}
