"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { getGroupScene, type CallScene, type Character } from "@/lib/api";
import { copy } from "@/i18n";
import { startGroupCall, type GroupCall, type GroupCallEvent } from "@/lib/groupCall";
import { CALM, type Emotion } from "@/lib/standAnimations";
import { cn } from "@/lib/utils";

import { Stand } from "./stand/Stand";
import { useStandOutfits } from "./useStandOutfits";

/** 群里的一位，占一个格子：她整个人站在格子里，轮到她说话时格子亮起来。 */
function Cell({
  character,
  speaking,
  mood,
  strength,
  scene,
  isReducedMotion,
}: {
  character: Character;
  speaking: boolean;
  mood: Emotion;
  strength: number;
  /** 大家身后的场景（通话接通前问出来的一张）。 */
  scene: CallScene | null;
  isReducedMotion: boolean;
}) {
  const outfits = useStandOutfits(character);
  return (
    <div
      className={cn(
        "relative flex min-h-0 flex-col overflow-hidden rounded-xl border bg-muted/40 transition-colors",
        speaking ? "border-primary ring-2 ring-primary/40" : "border-border",
      )}
    >
      <div className="relative min-h-0 flex-1">
        {scene && (
          <img
            src={scene.image_url}
            alt=""
            aria-hidden
            className="pointer-events-none absolute inset-0 size-full object-cover"
          />
        )}
        {scene && <div aria-hidden className="pointer-events-none absolute inset-0 bg-black/10" />}
        {outfits && (
          <Stand
            outfits={outfits.toTry}
            framing="waist"
            entrance="fade"
            isPaused={false}
            isReducedMotion={isReducedMotion}
            direction={{ ...CALM, mood, strength, speaking, looking: true }}
          />
        )}
      </div>
      <div className="flex items-center gap-1.5 border-t bg-background/70 px-2 py-1">
        <MarkedAvatar name={character.name} src={character.avatar_url} size="sm" />
        <span className="min-w-0 flex-1 truncate text-meta">{character.name_zh ?? character.name}</span>
        {speaking && <span className="text-meta text-muted-foreground">{copy.groups.callSpeaking}</span>}
      </div>
    </div>
  );
}

/**
 * 群通话（DESIGN.md「群聊语音房」的真·多人版）：打进一个群，几个人**同时**占几个格子站在台上，
 * 谁在说话谁的格子亮起来；声音是 WebRTC 那一条，不用一条条点播放。
 */
export function GroupCallStage({ groupId, characters }: { groupId: string; characters: Character[] }) {
  const router = useRouter();
  const isReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)", false);
  const [phase, setPhase] = useState<"dialing" | "connected" | "failed">("dialing");
  const [speaker, setSpeaker] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [micOn, setMicOn] = useState(true);
  const [hearing, setHearing] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  /** 每个人现在这张脸：她这一句判出来的语气。 */
  const [moods, setMoods] = useState<Record<string, { mood: Emotion; strength: number }>>({});
  /** 打电话时大家身后的场景。 */
  const [scene, setScene] = useState<CallScene | null>(null);
  /** 格子下面那行字幕：最近的几句。 */
  const [lines, setLines] = useState<{ id: number; speaker: string; ja: string; zh: string }[]>([]);
  const call = useRef<GroupCall | null>(null);
  const audio = useRef<HTMLAudioElement>(null);

  // 接通前问一次该在什么场景（DESIGN.md「通话场景」）：接到就换，问不到就照旧用底色。
  useEffect(() => {
    let cancelled = false;
    void getGroupScene(groupId)
      .catch(() => null)
      .then((picked) => {
        if (!cancelled && picked) setScene(picked);
      });
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  // 群里是哪几位：从群里拿，和 `/api/groups` 那份一致。
  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`/api/groups/${encodeURIComponent(groupId)}/messages`);
        if (!res.ok) return;
        const body = (await res.json()) as { group?: { participants?: string[] } };
        setMembers(body.group?.participants ?? []);
      } catch {
        // 拿不到就按目录里的顺序站
      }
    })();
  }, [groupId]);

  useEffect(() => {
    let cancelled = false;
    const handle = (event: GroupCallEvent) => {
      if (cancelled) return;
      if (event.type === "connected") setPhase("connected");
      else if (event.type === "dropped") setPhase("failed");
      else if (event.type === "speaker") setSpeaker(event.speaker);
      else if (event.type === "hearing") setHearing(event.text);
      else if (event.type === "line") {
        setLines((current) => [
          ...current.slice(-5),
          { id: Date.now() + Math.random(), speaker: event.speaker, ja: event.ja, zh: event.zh },
        ]);
        setSpeaker(event.speaker);
      } else if (event.type === "emotion") {
        setMoods((current) => ({
          ...current,
          [event.speaker]: { mood: event.mood, strength: event.strength },
        }));
      }
    };
    void startGroupCall(groupId, {
      onEvent: handle,
      onAudio: (track) => {
        if (!audio.current) return;
        audio.current.srcObject = new MediaStream([track]);
        void audio.current.play().catch(() => undefined);
      },
    })
      .then((started) => {
        if (cancelled) {
          void started.hangUp();
          return;
        }
        call.current = started;
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setPhase("failed");
        setFailure(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
      void call.current?.hangUp();
      call.current = null;
    };
  }, [groupId]);

  const hangUp = async () => {
    await call.current?.hangUp();
    call.current = null;
    router.push(`/groups/${groupId}`);
  };

  const listed = members.length
    ? members.map((id) => characters.find((candidate) => candidate.id === id)).filter((c): c is Character => Boolean(c))
    : characters.slice(0, 3);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Link href={`/groups/${groupId}`} className="text-meta text-muted-foreground hover:underline">
          {copy.groups.back}
        </Link>
        <p className="min-w-0 flex-1 truncate text-base">{copy.groups.call}</p>
        <span className="text-meta text-muted-foreground" aria-live="polite">
          {hearing
            ? copy.groups.roomHearing(hearing)
            : speaker
              ? copy.groups.roomSpeaking(nameOf(listed, speaker))
              : phase === "connected"
                ? copy.groups.callConnected
                : phase === "dialing"
                  ? copy.groups.callDialing
                  : copy.groups.callFailed}
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {phase === "failed" ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-meta text-muted-foreground">{failure ?? copy.groups.callFailed}</p>
            <Button variant="outline" onClick={() => router.push(`/groups/${groupId}`)}>
              {copy.groups.back}
            </Button>
          </div>
        ) : (
          <div className="grid h-full grid-cols-2 auto-rows-fr gap-2 sm:grid-cols-3">
            {listed.map((character) => (
              <Cell
                key={character.id}
                character={character}
                speaking={phase === "connected" && speaker === character.id}
                scene={scene}
                mood={moods[character.id]?.mood ?? CALM.mood}
                strength={moods[character.id]?.strength ?? 0}
                isReducedMotion={isReducedMotion}
              />
            ))}
          </div>
        )}
      </div>

      <div
        className="h-20 shrink-0 space-y-0.5 overflow-y-auto border-t px-3 py-1.5 text-meta"
        aria-live="polite"
      >
        {lines.length === 0 && <p className="text-muted-foreground">{copy.groups.callSubtitleHint}</p>}
        {lines.map((line) => (
          <p key={line.id}>
            <span className="mr-1 font-medium">{nameOf(listed, line.speaker)}：</span>
            {line.ja || line.zh}
            {line.ja && line.zh && <span className="ml-1 text-muted-foreground">{line.zh}</span>}
          </p>
        ))}
      </div>

      <audio ref={audio} className="hidden" />

      <div className="flex items-center justify-center gap-3 border-t p-3">
        {phase === "dialing" && <Spinner className="size-4 text-muted-foreground" />}
        <Button
          variant={micOn ? "outline" : "secondary"}
          aria-pressed={micOn}
          onClick={() => {
            const next = !micOn;
            setMicOn(next);
            call.current?.setMicEnabled(next);
          }}
        >
          {micOn ? copy.groups.callMicOn : copy.groups.callMicOff}
        </Button>
        <Button variant="destructive" onClick={() => void hangUp()}>
          {copy.groups.callHangUp}
        </Button>
      </div>
    </div>
  );
}

function nameOf(roster: Character[], id: string): string {
  const found = roster.find((character) => character.id === id);
  return found ? (found.name_zh ?? found.name) : id;
}
