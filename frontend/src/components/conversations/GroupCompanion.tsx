"use client";

import { useMemo } from "react";

import type { Character } from "@/lib/api";
import type { GroupMessage } from "@/lib/groups";
import type { SpeechState } from "@/lib/messageSpeech";
import type { Emotion } from "@/lib/standAnimations";

import { ChatCompanion } from "./ChatCompanion";
import { useStandOutfits } from "./useStandOutfits";

/** 群聊里几位站得一样高（px）；拖把手改的就是这个高度，各记各的。 */
const GROUP_PET_HEIGHT = 260;

/** 她这一句的语气，判出来以后给宠物摆。 */
export type GroupEmotion = {
  mood: Emotion;
  nod: "yes" | "no" | null;
  strength?: number;
  at: number;
};

/** 她这一句说完没有：`said` 给宠物判断「刚说完，动一会儿嘴」用。 */
function saidOf(messages: readonly GroupMessage[], characterId: string) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "character" || message.speaker_id !== characterId) continue;
    const characters = message.segments.reduce((sum, segment) => sum + segment.ja.length, 0);
    return { key: `g${message.id}`, characters };
  }
  return null;
}

/** 正在放的那条群消息是不是她说的：是的话宠物跟着动嘴，气泡里显示这段话。 */
function spokenOf(messages: readonly GroupMessage[], speech: SpeechState, characterId: string) {
  if (!speech) return null;
  const message = messages.find((candidate) => candidate.id === speech.messageId);
  if (!message || message.role !== "character" || message.speaker_id !== characterId) return null;
  return {
    ja: message.segments.map((segment) => segment.ja).join("\n"),
    zh: message.segments
      .map((segment) => segment.zh)
      .filter(Boolean)
      .join(" "),
  };
}

/**
 * 群聊里站着的一位（DESIGN.md「对话页的立绘小人」的群聊版）：几个人就站几个，各站各的、
 * 各记各的大小和位置，按她这一句判出来的语气换表情和动作。
 */
export function GroupCompanion({
  groupId,
  character,
  index,
  count,
  isTyping,
  messages,
  speech,
  emotion,
  onHide,
  hideLabel,
}: {
  groupId: string;
  character: Character;
  /** 在群里排第几（按摊开的位置算），一共几位。 */
  index: number;
  count: number;
  /** 她正在写这一句。 */
  isTyping: boolean;
  messages: readonly GroupMessage[];
  speech: SpeechState;
  /** 她这一句的语气（判出来以后）。 */
  emotion: GroupEmotion | null;
  /** 隐藏群里所有立绘（页首的「显示立绘」恢复）：任一位置上的「⋯」都交同一个回调。 */
  onHide?: () => void;
  /** 「隐藏立绘」那句话（群聊用自己的文案）。 */
  hideLabel?: string;
}) {
  const outfits = useStandOutfits(character);
  const said = useMemo(() => saidOf(messages, character.id), [messages, character.id]);
  const spoken = useMemo(() => spokenOf(messages, speech, character.id), [messages, speech, character.id]);
  // 几个人沿下边摊开：第一个贴着右边，最后一个往左挪。
  const defaultX = count > 1 ? Math.min(0.85, (index * 0.85) / (count - 1)) : 0;
  if (!outfits) return null;
  return (
    <ChatCompanion
      character={character}
      outfits={outfits.toTry}
      isReplying={isTyping}
      said={said}
      spoken={spoken}
      emotion={emotion}
      canJudgeSpeech={false}
      storeKey={`g:${groupId}:${character.id}`}
      defaultX={defaultX}
      defaultY={0}
      heightTarget={GROUP_PET_HEIGHT}
      onHide={onHide}
      hideLabel={hideLabel}
    />
  );
}
