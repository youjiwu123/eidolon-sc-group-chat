import { describe, expect, it } from "vitest";
import type { CallEvent } from "@/lib/api";
import { CALM, type Emotion, type StandDirection } from "@/lib/standAnimations";
import { directionOf, directStand, startingStand, withOpener, type StandEvent, type StandState } from "@/lib/standDirection";

/** The stand after these events in a call, from its start. */
function after(events: StandEvent[], options: { textOnly?: boolean } = {}): StandState {
  return events.reduce(directStand, startingStand(options.textOnly ?? false));
}

/** How she looks after these events in a call, from its start. */
function direction(events: StandEvent[], options: { textOnly?: boolean } = {}): StandDirection {
  return directionOf(after(events, options));
}

/** The judged emotion of segment `segment` of reply `reply`, with a nod if given. */
function emotion(
  reply: number,
  segment: number,
  feeling: Emotion,
  nod: "yes" | "no" | null = null,
  strength?: number,
): CallEvent {
  return { type: "emotion", reply, segment, emotion: feeling, nod, ...(strength === undefined ? {} : { strength }) };
}

function playing(reply: number, segment: number): CallEvent {
  return { type: "segment-playing", reply, segment };
}

/** The user's words taken up, as reply `reply` starts. */
function reply(number: number): CallEvent {
  return { type: "user", text: "你好", reply: number };
}

/** The call layer's line card moved on to this segment without her voice. */
function lineShown(reply: number, segment: number): StandEvent {
  return { type: "line-shown", reply, segment };
}

function subtitle(segment: number, text = "こんにちは"): CallEvent {
  return { type: "delta", segment, lang: "ja", text };
}

const botStarted: StandEvent = { type: "bot-started-speaking" };
const botStopped: StandEvent = { type: "bot-stopped-speaking" };
const userStarted: StandEvent = { type: "user-started-speaking" };
const userStopped: StandEvent = { type: "user-stopped-speaking" };
const typed: StandEvent = { type: "typed" };
const callOver: StandEvent = { type: "call-over" };

function textOnly(on: boolean): StandEvent {
  return { type: "text-only", textOnly: on };
}

describe("standDirection: who is speaking", () => {
  it("starts each call calm, looking ahead with her mouth shut", () => {
    expect(direction([])).toEqual(CALM);
    expect(direction([], { textOnly: true })).toEqual(CALM);
  });

  it("opens her mouth while her voice plays and shuts it when it stops", () => {
    expect(direction([botStarted]).speaking).toBe(true);
    expect(direction([botStarted, botStopped]).speaking).toBe(false);
  });

  it("keeps her mouth shut in text only, even when switched on while she speaks", () => {
    expect(direction([botStarted], { textOnly: true }).speaking).toBe(false);
    expect(direction([botStarted, textOnly(true)]).speaking).toBe(false);
    expect(direction([botStarted, textOnly(true), textOnly(false)]).speaking).toBe(true);
  });

  it("looks at the user while they speak, then nods once when they stop", () => {
    expect(direction([userStarted])).toMatchObject({ looking: true, nod: null });

    const first = direction([userStarted, userStopped]);
    expect(first).toMatchObject({ looking: false, nod: { kind: "yes" } });
    const second = direction([userStarted, userStopped, userStarted, userStopped]);
    expect(second.nod).toMatchObject({ kind: "yes" });
    expect(second.nod?.id).not.toBe(first.nod?.id);
  });

  it("looks at the user who interrupts by typing once her voice stops, until she speaks again", () => {
    expect(direction([botStarted, typed])).toMatchObject({ speaking: true, looking: false });
    expect(direction([botStarted, typed, botStopped])).toMatchObject({ mood: "calm", speaking: false, looking: true });
    expect(direction([botStarted, typed, botStopped, botStarted])).toMatchObject({ speaking: true, looking: false });
  });

  it("changes nothing for what is typed before she starts speaking", () => {
    expect(direction([reply(1), typed])).toEqual(CALM);
    expect(direction([reply(1), typed, botStarted, botStopped]).looking).toBe(false);
  });

  it("gives the same direction while nothing about it changes", () => {
    const before = after([userStarted, reply(1), subtitle(0), playing(1, 0), emotion(1, 0, "happy")]);
    const unchanged: StandEvent[] = [
      userStarted,
      subtitle(0, "！"),
      { type: "delta", segment: 0, lang: "zh", text: "你好" },
      emotion(0, 0, "sad"), // an earlier reply's, dropped
      { type: "done", message: { id: 1, role: "character", text: null, ja: null, zh: null, segments: [], created_at: "", affinity: null }, affinity: null },
      { type: "error", message: "角色暂时无法回复" },
      { type: "ended", reason: "duration_limit", message: "", counts: true },
      typed,
      textOnly(false),
    ];

    for (const event of unchanged) expect(directionOf(directStand(before, event))).toBe(directionOf(before));
  });

  it("keeps text only when the call is over, and nods on with new ids", () => {
    const nodded = after([userStarted, userStopped], { textOnly: true });
    const over = directStand(nodded, callOver);

    expect(directionOf(directStand(over, botStarted)).speaking).toBe(false);
    const next = directionOf([userStarted, userStopped].reduce(directStand, over));
    expect(next.nod).toMatchObject({ kind: "yes" });
    expect(next.nod?.id).not.toBe(directionOf(nodded).nod?.id);
  });
});

describe("standDirection: 开场白", () => {
  it("开场白在放的时候她动嘴，停了就不动，只看文字也不动", () => {
    const calm = direction([]);

    expect(withOpener(calm, true, false).speaking).toBe(true);
    expect(withOpener(calm, false, false).speaking).toBe(false);
    expect(withOpener(calm, true, true).speaking).toBe(false);
  });

  it("开场白判出来的语气照着摆，点头用这一通电话的编号", () => {
    const calm = direction([]);
    const mood = { emotion: "sad" as const, nod: "yes" as const, strength: 0.92 };

    expect(withOpener(calm, true, false, mood, 7)).toMatchObject({
      speaking: true,
      mood: "sad",
      strength: 0.92,
      nod: { kind: "yes", id: 7 },
    });
    // 只看文字时表情也不换
    expect(withOpener(calm, true, true, mood, 7)).toBe(calm);
    expect(withOpener(calm, true, false, null, 7)).toMatchObject({ speaking: true, mood: "calm" });
  });
});

describe("standDirection: her emotions", () => {
  it("changes as her voice starts playing the segment, not before", () => {
    const judged = [reply(1), subtitle(0), emotion(1, 0, "happy")];

    expect(direction(judged).mood).toBe("calm");
    expect(direction([...judged, playing(1, 0)]).mood).toBe("happy");
  });

  it("carries how sure the judge was, for the stronger variant to play", () => {
    const judged = [reply(1), subtitle(0), emotion(1, 0, "sad", null, 0.92), playing(1, 0)];

    expect(direction(judged).strength).toBe(0.92);
    // 平静的那一段沿用原来的心情，也就沿用原来的把握
    expect(direction([...judged, playing(1, 1), emotion(1, 1, "calm", null, 0.4), botStarted]).strength).toBe(0.92);
  });

  it("changes on a late emotion while the segment is still playing", () => {
    expect(direction([reply(1), subtitle(0), playing(1, 0), botStarted, emotion(1, 0, "sad")]).mood).toBe("sad");
  });

  it("drops an emotion that comes once the segment has been said", () => {
    const said = [reply(1), playing(1, 0), botStarted, playing(1, 1)];

    expect(direction([...said, emotion(1, 0, "sad")]).mood).toBe("calm");
    expect(direction([...said, emotion(1, 0, "sad"), botStopped, emotion(1, 1, "angry")]).mood).toBe("calm");
  });

  it("drops an emotion that comes once the next turn was taken up", () => {
    expect(direction([reply(1), playing(1, 0), reply(2), emotion(1, 0, "sad")]).mood).toBe("calm");
  });

  it("keeps an emotion for a segment whose voice starts right after the last one stopped", () => {
    const said = [reply(1), playing(1, 0), botStarted, playing(1, 1)];

    // Her voice stops just after the next segment's message, and starts again.
    expect(direction([...said, botStopped, botStarted, emotion(1, 1, "shy")]).mood).toBe("shy");
  });

  it("keeps her mood through calm segments, until a reply starts calm", () => {
    const first = [reply(1), emotion(1, 0, "happy"), emotion(1, 1, "calm"), playing(1, 0), playing(1, 1)];
    expect(direction(first).mood).toBe("happy");

    expect(direction([...first, reply(2), emotion(2, 0, "calm"), playing(2, 0)]).mood).toBe("calm");
  });

  it("nods or shakes her head along with the emotion, once each", () => {
    const judged = [reply(1), emotion(1, 0, "happy", "yes"), emotion(1, 1, "calm", "no")];
    expect(direction(judged).nod).toBeNull();

    const nod = direction([...judged, playing(1, 0)]).nod;
    expect(nod).toMatchObject({ kind: "yes" });
    const shake = direction([...judged, playing(1, 0), playing(1, 1)]).nod;
    expect(shake).toMatchObject({ kind: "no" });
    expect(shake?.id).not.toBe(nod?.id);
  });

  it("gives a nod along with an emotion an id past the user's nods", () => {
    const nodded = [userStarted, userStopped];
    const user = direction(nodded).nod;

    const own = direction([...nodded, reply(1), emotion(1, 0, "happy", "yes"), playing(1, 0)]).nod;

    expect(own?.id).not.toBe(user?.id);
  });

  it("takes up each segment's emotion though the line card moves on without her voice before it is judged, text only or not", () => {
    // A reply without her voice is still played at her pace once text only is switched off.
    const shown = [reply(1), lineShown(1, 0), lineShown(1, 1)];
    expect(direction([...shown, emotion(1, 0, "happy")]).mood).toBe("happy");

    // The later one came first.
    const both = [...shown, emotion(1, 0, "happy"), lineShown(1, 2), emotion(1, 2, "sad"), emotion(1, 1, "angry")];
    expect(direction(both).mood).toBe("sad");
  });

  it("keeps an emotion only for the reply it was judged in", () => {
    // The reply was dropped for a follow-on before that segment played.
    expect(direction([reply(1), emotion(1, 1, "sad"), reply(2), playing(2, 0), playing(2, 1)]).mood).toBe("calm");
  });

  it("does not go back to a segment she is past", () => {
    const past = [reply(1), playing(1, 1), playing(1, 0), emotion(1, 0, "sad")];

    expect(direction(past).mood).toBe("calm");
  });

  it("leaves her mood alone when she is interrupted, shutting her mouth as soon as her voice stops and looking at the user", () => {
    const events = [reply(1), emotion(1, 0, "happy"), playing(1, 0), botStarted];

    expect(direction([...events, userStarted, botStopped, emotion(1, 1, "sad")])).toMatchObject({
      mood: "happy",
      speaking: false,
      looking: true,
    });
  });

  it("forgets all of the last call when it is over: who was speaking, typing, and her emotions", () => {
    const speaking = [botStarted, userStarted, userStopped, userStarted, typed];
    expect(direction([...speaking, callOver])).toEqual(CALM);

    const events = [reply(1), emotion(1, 0, "happy"), playing(1, 0), emotion(1, 1, "sad")];
    expect(direction(events).mood).toBe("happy");

    expect(direction([...events, callOver])).toEqual(CALM);
    expect(direction([...events, callOver, reply(1), playing(1, 1)]).mood).toBe("calm");
  });

  it("forgets in text only which segment's emotion she showed last call", () => {
    const events = [reply(1), lineShown(1, 0), lineShown(1, 1), emotion(1, 1, "sad")];
    expect(direction(events, { textOnly: true }).mood).toBe("sad");

    const next = [...events, callOver, reply(1), lineShown(1, 0), lineShown(1, 1), emotion(1, 0, "happy")];
    expect(direction(next, { textOnly: true }).mood).toBe("happy");
  });
});
