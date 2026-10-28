// Her stand direction in a call (spec「立绘指令」, GLOSSARY.md「立绘指令」): how she should look,
// kept up to date from the call's events, from what the user types and from text only.
//
// - Her mouth moves while her voice plays, but not in text only.
// - She looks at the user while they speak, and nods when they stop. Her voice stops at once
//   when she is interrupted: if the user interrupted her by typing, she looks at them once it
//   stops, until she speaks again. What is typed before she speaks changes nothing.
// - Her mood follows the segment she is saying: the one her voice last started playing, or the
//   one the call screen's line card moved on to without her voice (in text only, or when her
//   voice stopped short). An emotion judged before the segment is said is kept until it
//   is; one judged while it is said is taken up at once; one judged after it has been said is
//   dropped. Through a calm segment her mood stays as it was, unless the segment opens her
//   reply. A nod or shake of the head goes with the emotion.
// - When the call is over, all is forgotten and the next call starts calm; text only is kept,
//   and nods go on counting, so that no two share an id.

import type { CallEvent, SegmentEmotion, SegmentPlaying } from "@/lib/api";
import { SPEAKING, type Speaking } from "@/lib/call";
import { CALM, type Emotion, type Nod, type StandDirection } from "@/lib/standAnimations";

/** A segment of one of her replies in the call. */
type SegmentAt = Pick<SegmentPlaying, "reply" | "segment">;

export type StandState = {
  /** Show her replies as text only (GLOSSARY.md「只看文字」); a preference, not the call's. */
  textOnly: boolean;
  /** Her voice is playing in the call. */
  voicing: boolean;
  /** The user is speaking in the call. */
  userSpeaking: boolean;
  /** The user interrupted her by typing while her voice played. */
  interruptedByTyping: boolean;
  /** The segment she is saying, which her mood follows. `over` once it has been said: her voice
   * stopped (until it starts again), or the next turn was taken up. `paced` if the line card
   * moved on to it without her voice. Null until one starts. */
  saying: (SegmentAt & { over: boolean; paced: boolean }) | null;
  /** Emotions judged for segments she has yet to say in this call, by `reply:segment`. */
  judged: ReadonlyMap<string, SegmentEmotion>;
  /** The last segment whose emotion she has shown in this call; null until one. */
  shown: SegmentEmotion | null;
  /** How many nods she has given, to tell each one from the last. */
  nods: number;
  /** How she should look, as `directionOf` gives it. */
  direction: StandDirection;
};

export type StandEvent =
  /** Of the call's events, who is speaking, which segment her voice started playing, a segment's
   * emotion and the user's words taken up count; the rest change nothing. */
  | CallEvent
  /** The user typed something in the call. */
  | { type: "typed" }
  /** The call screen's line card moved on to this segment without her voice: in text only, or
   * playing out the rest of a reply her voice stopped short of. */
  | ({ type: "line-shown" } & SegmentAt)
  /** Text only was switched. */
  | { type: "text-only"; textOnly: boolean }
  /** The call was hung up or dropped. */
  | { type: "call-over" };

/** As a call starts, with text only as the preferences have it. */
export function startingStand(textOnly: boolean): StandState {
  return {
    textOnly,
    voicing: false,
    userSpeaking: false,
    interruptedByTyping: false,
    saying: null,
    judged: new Map(),
    shown: null,
    nods: 0,
    direction: CALM,
  };
}

export function directStand(state: StandState, event: StandEvent): StandState {
  return withSpeakingAndLooking(moved(state, event));
}

/** How she should look. The same object while nothing about it changes. */
export function directionOf(state: StandState): StandDirection {
  return state.direction;
}

function moved(state: StandState, event: StandEvent): StandState {
  if (isSpeaking(event)) return onSpeaking(state, event);
  switch (event.type) {
    case "segment-playing":
    case "line-shown":
      return startSaying(state, event, event.type === "line-shown");
    case "emotion":
      return onEmotion(state, event);
    case "user":
      return { ...state, saying: state.saying && { ...state.saying, over: true } };
    case "typed":
      return state.voicing ? { ...state, interruptedByTyping: true } : state;
    case "text-only":
      return { ...state, textOnly: event.textOnly };
    case "call-over":
      return { ...startingStand(state.textOnly), nods: state.nods };
    default:
      return state;
  }
}

function onSpeaking(state: StandState, { type }: Speaking): StandState {
  const { saying } = state;
  switch (type) {
    case "bot-started-speaking":
      return { ...state, voicing: true, interruptedByTyping: false, saying: saying && { ...saying, over: false } };
    case "bot-stopped-speaking":
      return { ...state, voicing: false, saying: saying && { ...saying, over: true } };
    case "user-started-speaking":
      return { ...state, userSpeaking: true };
    case "user-stopped-speaking":
      return nodded({ ...state, userSpeaking: false }, "yes");
  }
}

/** She nods or shakes her head, with an id no nod has had. */
function nodded(state: StandState, kind: Nod["kind"]): StandState {
  const nods = state.nods + 1;
  return { ...state, nods, direction: { ...state.direction, nod: { kind, id: nods } } };
}

/** She starts saying this segment, with her voice or as the line card moves on to it at her pace
 * (`paced`), unless she is past it already: her mood follows it if it has been judged. */
function startSaying(state: StandState, at: SegmentAt, paced: boolean): StandState {
  const { saying } = state;
  if (saying && !follows(at, saying)) return state;
  const emotion = state.judged.get(key(at));
  const judged = new Map([...state.judged].filter(([, later]) => follows(later, at)));
  const next = { ...state, judged, saying: { reply: at.reply, segment: at.segment, over: false, paced } };
  return emotion ? showEmotion(next, emotion) : next;
}

/** A segment's emotion is judged: kept until she says it, taken up at once while she is saying
 * it, and dropped once she has said it. Without her voice a segment is judged once it is
 * complete, by when the line card may have moved on to the next: there it is taken up still,
 * until the reply is over, unless a later segment's emotion shows already. */
function onEmotion(state: StandState, emotion: SegmentEmotion): StandState {
  const { saying, shown } = state;
  if (!saying || follows(emotion, saying)) return { ...state, judged: new Map(state.judged).set(key(emotion), emotion) };
  if (saying.over || emotion.reply !== saying.reply) return state;
  const current = emotion.segment === saying.segment;
  if (current || (saying.paced && (!shown || follows(emotion, shown)))) return showEmotion(state, emotion);
  return state;
}

/** Her mood follows the segment she is saying, but through a calm one it stays as it was, unless
 * the segment opens her reply; a nod or shake of the head goes with it. */
function showEmotion(state: StandState, judged: SegmentEmotion): StandState {
  const { emotion, segment, nod } = judged;
  const { direction } = state;
  const mood = emotion === "calm" && segment > 0 ? direction.mood : emotion;
  // 判得多有把握跟着一起走：换了心情才换把握程度，平静那一段沿用原来的。
  const strength = mood === direction.mood ? direction.strength : judged.strength;
  const shown = { ...state, shown: judged, direction: { ...direction, mood, strength } };
  return nod ? nodded(shown, nod) : shown;
}

/** Her mouth moves while her voice plays, but not in text only; she looks at the user while they
 * speak, and once her voice stops after they interrupted her by typing. The direction stays the
 * same object while nothing about it changes. */
function withSpeakingAndLooking(state: StandState): StandState {
  const speaking = state.voicing && !state.textOnly;
  const looking = state.userSpeaking || (state.interruptedByTyping && !state.voicing);
  if (speaking === state.direction.speaking && looking === state.direction.looking) return state;
  return { ...state, direction: { ...state.direction, speaking, looking } };
}

/** 她的开场白在放的时候（DESIGN.md「开场白」）：那一段是事先备好的音频，不走通话的语音管线，
 * 立绘得自己知道她正在说——嘴跟着动，表情和动作照判出来的那一次来，和回完一条回复时一样。
 * 只看文字时不动嘴、也不换表情，和别的时候一样。 */
export function withOpener(
  direction: StandDirection,
  voicing: boolean,
  textOnly: boolean,
  mood?: { emotion: Emotion; nod: "yes" | "no" | null; strength: number } | null,
  nodId?: number,
): StandDirection {
  if (!voicing || textOnly) return direction;
  const next: StandDirection = { ...direction, speaking: true };
  if (!mood) return next;
  return {
    ...next,
    mood: mood.emotion,
    strength: mood.strength,
    nod: mood.nod && nodId !== undefined ? { kind: mood.nod, id: nodId } : null,
  };
}

function key({ reply, segment }: SegmentAt): string {
  return `${reply}:${segment}`;
}

/** Whether segment `a` comes after segment `b` in the call. */
function follows(a: SegmentAt, b: SegmentAt): boolean {
  return a.reply > b.reply || (a.reply === b.reply && a.segment > b.segment);
}

function isSpeaking(event: StandEvent): event is Speaking {
  return (SPEAKING as readonly string[]).includes(event.type);
}
