"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { Character } from "@/lib/api";
import { copy } from "@/i18n";
import {
  getGroup,
  getGroupMessageEmotion,
  groupSpeechUrl,
  sendGroupTurn,
  startChatter,
  type Group,
  type GroupMessage,
} from "@/lib/groups";
import { speechState, stopSpeech, subscribeSpeech, toggleSpeech } from "@/lib/messageSpeech";
import { listen, speechRecognition, type Heard } from "@/lib/speechRecognition";
import type { Emotion } from "@/lib/standAnimations";
import { MicIcon } from "@/theme/icons";

import { GroupCompanion, type GroupEmotion } from "./GroupCompanion";

/** 一条说过的（或者正在说的）话，接在字幕条里。 */
type Said = { id: number; speaker: string; text: string };

/** 两句话有多像（共同的字符占比）：用来认出「麦克风听见的其实是她自己的声音」。 */
function alike(a: string, b: string): number {
  const norm = (text: string) => text.replace(/[\s、。,.!?！？…「」『』（）()〜~・ー\-—:：;；]/g, "");
  const x = norm(a);
  const y = norm(b);
  if (!x || !y) return 0;
  const characters = new Set(y);
  let hit = 0;
  for (const character of x) if (characters.has(character)) hit += 1;
  return hit / x.length;
}

/** 安静多久以后让她们自己聊起来（毫秒）。 */
const IDLE_CHATTER_MS = 25000;

/**
 * 群聊语音房（DESIGN.md「群聊语音房」）：几位站在台上，**免提**开着，你随时说话，
 * 浏览器把话听成文字（`lib/speechRecognition`），发出去以后她们各自用自己的声音接话，
 * 一条念完接着念下一条；念到谁，谁的小人动嘴、字幕条上是那段话。
 *
 * 多人感来自三件事：
 * - 免提一直听着，随时能开口；她说话时你插话会自动打断她（对着麦克风说就行，不用点）。
 * - 没人说话时她们自己聊几句（`startChatter`），念的时候一样有声音有表情。
 * - 每一句念完歇一小会儿再接下一句，谁接话由群里的判断决定，不是排好的顺序。
 *
 * 浏览器不能听写（Safari、Firefox）时只用打字，麦克风不出现。
 */
export function GroupRoom({ groupId, characters }: { groupId: string; characters: Character[] }) {
  const [group, setGroup] = useState<Group | null>(null);
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [typing, setTyping] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [cues, setCues] = useState<Record<string, GroupEmotion>>({});
  const [nowPlaying, setNowPlaying] = useState<number | null>(null);
  /** 进来就开免提（浏览器支持的话）：这是语音房，不是文字房。关掉麦克风她们也不再自己聊。 */
  const [handsFree, setHandsFree] = useState(() => speechRecognition() !== null);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const speech = useSyncExternalStore(subscribeSpeech, speechState, speechState);
  const [canListen] = useState(() => speechRecognition() !== null);
  const judged = useRef<Set<number> | null>(null);
  /** 每条消息判过的语气：念到它的时候再摆一次，判得早也不会过期。 */
  const answers = useRef(new Map<number, { emotion: Emotion; nod: "yes" | "no" | null; strength?: number }>());
  /** 还没念的那几条消息，按顺序念。 */
  const queue = useRef<number[]>([]);
  const mic = useRef<{ stop(): void } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  /** 正在念的那句原文：麦克风收到的和它太像时，那是她自己的回声。 */
  const playingLine = useRef("");
  const sendingNow = useRef(false);
  /** 她说的时候你又开口了：这一句等这一轮说完就发。 */
  const pending = useRef<string | null>(null);
  const idle = useRef(0);
  const chatterRunning = useRef(false);
  /** 你没开口时她们最多自己聊几轮，免得一直烧 token；你一说话就重新算。 */
  const chatterRounds = useRef(0);

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
  }, [load]);

  // 每条新来的她说的消息：问一次语气，她那一位小人照着摆；同时排进要念的队。
  useEffect(() => {
    if (judged.current === null) {
      judged.current = new Set(messages.map((message) => message.id));
      return;
    }
    for (const message of messages) {
      if (message.role !== "character" || !message.speaker_id || judged.current.has(message.id)) continue;
      judged.current.add(message.id);
      queue.current.push(message.id);
      const speaker = message.speaker_id;
      void getGroupMessageEmotion(groupId, message.id)
        .catch(() => null)
        .then((answer) => {
          if (!answer) return;
          answers.current.set(message.id, answer);
          setCues((current) => ({
            ...current,
            [speaker]: { mood: answer.emotion, nod: answer.nod, strength: answer.strength, at: Date.now() },
          }));
        });
    }
  }, [messages, groupId]);

  // 念到哪一条，就把这一条判出来的语气再摆一次：判得早的那次说不定已经过期了，
  // 念的时候她不只动嘴，身体和脸也跟着这一句。
  useEffect(() => {
    if (nowPlaying === null) return;
    const message = messages.find((candidate) => candidate.id === nowPlaying);
    const speaker = message?.speaker_id;
    if (!speaker) return;
    const answer = answers.current.get(nowPlaying);
    if (!answer) return;
    setCues((current) => ({
      ...current,
      [speaker]: {
        mood: answer.emotion,
        nod: answer.nod,
        strength: answer.strength,
        at: Date.now(),
      },
    }));
  }, [nowPlaying, messages]);

  // 念：一条念完（`speech` 回到 null）再念下一条；念完都没了就静下来。
  useEffect(() => {
    if (speech !== null) return;
    setNowPlaying(null);
    playingLine.current = "";
    const next = queue.current.shift();
    if (next === undefined) return;
    const message = messages.find((candidate) => candidate.id === next);
    playingLine.current = message ? message.segments.map((segment) => segment.ja).join("\n") : "";
    setNowPlaying(next);
    toggleSpeech(next, groupSpeechUrl(groupId, next));
  }, [speech, messages, groupId]);

  // 字幕条跟着最新的话走。
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages, nowPlaying]);

  const said = useMemo<Said[]>(() => {
    const lines: Said[] = [];
    for (const message of messages) {
      if (message.role === "user") {
        lines.push({ id: message.id, speaker: "", text: message.segments[0]?.zh ?? message.segments[0]?.ja ?? "" });
      } else if (message.role === "character" && message.speaker_id) {
        lines.push({
          id: message.id,
          speaker: message.speaker_id,
          text: message.segments.map((segment) => segment.zh || segment.ja).join(" "),
        });
      }
    }
    return lines.slice(-12);
  }, [messages]);

  const nameOf = (id: string) => {
    const found = characters.find((candidate) => candidate.id === id);
    return found ? (found.name_zh ?? found.name) : id;
  };

  /** 她正说着，你开口了：先把她的声音停下、把还没念的丢掉，再问这一句。 */
  const interrupt = useCallback(() => {
    queue.current = [];
    setNowPlaying(null);
    playingLine.current = "";
    stopSpeech();
  }, []);

  /** 发一句出去，她说完再接下一句；说的途中又有一句，等这一轮完了再发。 */
  const send = useCallback(
    async (text: string) => {
      const sentence = text.trim();
      if (!sentence) return;
      if (sendingNow.current) {
        pending.current = sentence;
        return;
      }
      sendingNow.current = true;
      chatterRounds.current = 0;
      setDraft("");
      setFailure(null);
      setSending(true);
      try {
        await sendGroupTurn(
          groupId,
          sentence,
          (event) => {
            if (event.type === "user") {
              setMessages((current) => [
                ...current,
                {
                  id: -Date.now(),
                  role: "user",
                  speaker_id: null,
                  segments: event.segments,
                  created_at: new Date().toISOString(),
                },
              ]);
            } else if (event.type === "thinking") setTyping(event.speaker_id);
            else if (event.type === "message") {
              setTyping(null);
              setMessages((current) => [...current, event.message]);
            } else if (event.type === "done") setTyping(null);
          },
          undefined,
        );
      } catch (error) {
        setFailure(error instanceof Error ? error.message : String(error));
      } finally {
        setTyping(null);
        setSending(false);
        sendingNow.current = false;
        const waiting = pending.current;
        pending.current = null;
        if (waiting) void send(waiting);
      }
    },
    [groupId],
  );

  /** 没人说话的时候她们自己聊一轮，一样念出来。 */
  const chatter = useCallback(async () => {
    if (chatterRunning.current || sendingNow.current || speechState() !== null) return;
    if (chatterRounds.current >= 3) return;
    chatterRunning.current = true;
    chatterRounds.current += 1;
    try {
      await startChatter(groupId, (event) => {
        if (event.type === "user") return;
        if (event.type === "thinking") setTyping(event.speaker_id);
        else if (event.type === "message") {
          setTyping(null);
          setMessages((current) => [...current, event.message]);
        } else if (event.type === "done") setTyping(null);
      });
    } catch {
      // 自动聊天失败不打扰用户：下次安静下来再试
    } finally {
      chatterRunning.current = false;
      setTyping(null);
      const waiting = pending.current;
      pending.current = null;
      if (waiting) void send(waiting);
    }
  }, [groupId, send]);

  /** 你开口说了一句（语音认出来的）。 */
  const utterance = useCallback(
    (text: string) => {
      const sentence = text.trim();
      if (!sentence) return;
      // 她正念着的那句被麦克风听回去了：不当成你插话。
      if (playingLine.current && alike(sentence, playingLine.current) >= 0.6) return;
      interrupt();
      // 她们正自己聊着：这一句等这一轮说完再发，免得两轮撞在一起。
      if (chatterRunning.current) {
        pending.current = sentence;
        return;
      }
      void send(sentence);
    },
    [interrupt, send],
  );

  // 免提：开着就一直听，识别到一句就发；切出去、关掉就停。
  const utteranceNow = useRef(utterance);
  utteranceNow.current = utterance;
  useEffect(() => {
    if (!canListen) return;
    if (!handsFree) {
      mic.current?.stop();
      mic.current = null;
      setListening(false);
      setHeard("");
      return;
    }
    setFailure(null);
    try {
      mic.current = listen(
        "ja-JP",
        (result: Heard) => {
          if (!result.final) {
            setHeard(result.text);
            return;
          }
          setHeard("");
          utteranceNow.current(result.text);
        },
        (error) => {
          setHandsFree(false);
          setHeard("");
          setFailure(
            error === "not-allowed" || error === "service-not-allowed"
              ? copy.groups.roomDenied
              : copy.groups.roomNoMic,
          );
        },
      );
      setListening(true);
    } catch {
      setHandsFree(false);
      setFailure(copy.groups.roomUnsupported);
    }
    return () => {
      mic.current?.stop();
      mic.current = null;
    };
  }, [handsFree, canListen]);

  // 安静一会儿就让她们自己聊：有人在说、有人在想、或者你刚说过，都不插嘴。
  useEffect(() => {
    if (!handsFree || chatterRounds.current >= 3) return;
    window.clearTimeout(idle.current);
    if (sending || speech !== null || typing) return;
    idle.current = window.setTimeout(() => void chatter(), IDLE_CHATTER_MS);
    return () => window.clearTimeout(idle.current);
  }, [handsFree, sending, speech, typing, messages.length, chatter]);

  // 离开语音房：停下正在念的、关掉麦克风。
  useEffect(() => {
    return () => {
      mic.current?.stop();
      mic.current = null;
      stopSpeech();
      queue.current = [];
    };
  }, []);

  const members = (group?.participants ?? []).filter((id) => characters.some((c) => c.id === id));
  const standing = members
    .map((id) => characters.find((candidate) => candidate.id === id))
    .filter((candidate): candidate is Character => candidate !== undefined);
  const speaking = nowPlaying === null ? null : messages.find((message) => message.id === nowPlaying)?.speaker_id ?? null;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Link href={`/groups/${groupId}`} className="text-meta text-muted-foreground hover:underline">
          {copy.groups.back}
        </Link>
        <div className="flex -space-x-2">
          {members.slice(0, 3).map((id) => (
            <MarkedAvatar key={id} name={nameOf(id)} src={characters.find((c) => c.id === id)?.avatar_url ?? null} size="sm" />
          ))}
        </div>
        <p className="min-w-0 flex-1 truncate text-base">{group?.title ?? copy.groups.room}</p>
        <span className="max-w-[45%] truncate text-meta text-muted-foreground" aria-live="polite">
          {speaking
            ? copy.groups.roomSpeaking(nameOf(speaking))
            : heard
              ? copy.groups.roomHearing(heard)
              : listening
                ? copy.groups.roomListening
                : copy.groups.roomMicOff}
        </span>
      </header>

      <div className="relative min-h-0 flex-1">
        <div className="absolute inset-0 bg-gradient-to-b from-muted/40 to-background" />
        {standing.map((character, index) => (
          <GroupCompanion
            key={character.id}
            groupId={groupId}
            character={character}
            index={index}
            count={standing.length}
            isTyping={typing === character.id}
            messages={messages}
            speech={speech}
            emotion={cues[character.id] ?? null}
          />
        ))}
        {typing && (
          <div className="absolute inset-x-0 top-3 flex items-center justify-center gap-2 text-meta text-muted-foreground">
            <Spinner className="size-4" />
            {copy.groups.typing(nameOf(typing))}
          </div>
        )}
        {listening && (
          <div className="absolute inset-x-0 bottom-2 flex justify-center">
            <span className="rounded-full bg-background/80 px-3 py-1 text-meta text-muted-foreground">
              {copy.groups.roomHandsFree}
            </span>
          </div>
        )}
      </div>

      <div
        ref={scroller}
        className="h-28 shrink-0 space-y-1 overflow-y-auto border-t px-3 py-2 text-meta"
        aria-live="polite"
      >
        {said.length === 0 && <p className="text-muted-foreground">{copy.groups.roomHint}</p>}
        {said.map((line) => (
          <p
            key={line.id}
            className={line.id === nowPlaying ? "text-body text-foreground" : "text-meta text-muted-foreground"}
          >
            {line.speaker && <span className="mr-1 font-medium">{nameOf(line.speaker)}：</span>}
            {line.text}
          </p>
        ))}
      </div>

      <div className="flex items-end gap-2 border-t p-3">
        {canListen && (
          <Button
            type="button"
            variant={handsFree ? "default" : "outline"}
            aria-label={handsFree ? copy.groups.roomHandsFreeOff : copy.groups.roomHandsFreeOn}
            aria-pressed={handsFree}
            className="size-10 shrink-0 rounded-full p-0"
            onClick={() => setHandsFree((current) => !current)}
          >
            <MicIcon aria-hidden className="size-4" />
          </Button>
        )}
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              const sentence = draft.trim();
              if (!sentence) return;
              interrupt();
              void send(sentence);
            }
          }}
          placeholder={canListen ? copy.groups.roomHint : copy.groups.roomUnsupported}
          className="flex-1"
        />
        <Button
          disabled={sending || !draft.trim()}
          onClick={() => {
            const sentence = draft.trim();
            if (!sentence) return;
            interrupt();
            void send(sentence);
          }}
        >
          {copy.groups.send}
        </Button>
      </div>
      {failure && <p className="px-3 pb-2 text-meta text-destructive">{failure}</p>}
    </div>
  );
}
