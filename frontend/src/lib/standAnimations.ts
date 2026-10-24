// What the stand should look like (the stand direction, spec「立绘指令」) and which of an
// outfit's animations show it on each track (spec「选动画」). Every fallback lives here, in one
// pure function; the engine only plays what it is given.

/** Her emotion (GLOSSARY.md「情绪」): 平静、开心、害羞、惊讶、难过、生气、思考. */
export type Emotion = "calm" | "happy" | "shy" | "surprised" | "sad" | "angry" | "thinking";

/** A nod (`yes`) or a shake of the head (`no`); each gets a new id, so it is played once. */
export type Nod = { kind: "yes" | "no"; id: number };

/** How she should look right now, with no word of which animations do it. */
export type StandDirection = {
  /** Her emotion over the call so far; calm when it starts. */
  mood: Emotion;
  /** Her mouth is moving. */
  speaking: boolean;
  /** She looks at the user. */
  looking: boolean;
  nod: Nod | null;
};

/** How she looks when a call starts. */
export const CALM: StandDirection = { mood: "calm", speaking: false, looking: false, nod: null };

/** What each track should play, by name; null leaves the track empty. */
export type TrackAnimations = {
  /** Track 0, looped. */
  body: string;
  /** Track 1, looped; `blank` hands the face back to the body's own expression. */
  face: string;
  /** Track 5: her talking mouth, looping while open and held on its first frame while shut;
   * null if the outfit has none. */
  mouth: { name: string; open: boolean } | null;
  /** Track 2, played once. */
  nod: { name: string; id: number } | null;
  /** Track 3. */
  eye: string | null;
};

/** Body animations for each emotion, the first the outfit has being played; `wait` if none. */
const BODY: Record<Emotion, string[]> = {
  calm: ["wait"],
  happy: ["smile1", "smile2"],
  shy: ["shy1", "shy2", "smile2"],
  surprised: ["surp1", "surp2"],
  sad: ["sad1", "sad2"],
  angry: ["anger1", "anger2"],
  thinking: ["think", "think1", "think2", "wait4", "wait"],
};

/** Faces for each emotion; `blank` if none, the face `face_wait` being only for `wait` bodies. */
const FACE: Record<Emotion, string[]> = {
  calm: ["face_wait"],
  happy: ["face_smile", "face_smile1", "face_smile2"],
  shy: ["face_shy", "face_shy2"],
  surprised: ["face_surp"],
  sad: ["face_sad"],
  angry: ["face_anger", "face_anger1", "face_anger2"],
  thinking: ["face_serious"],
};

/** The `<k>` of each emotion's talking mouth, `lip_<k>`. */
const LIP: Record<Emotion, string> = {
  calm: "wait",
  happy: "smile",
  shy: "shy",
  surprised: "surp",
  sad: "sad",
  angry: "anger",
  thinking: "serious",
};

/**
 * Which animations show `direction` in an outfit with these `animations` (name → duration in
 * seconds). With reduced motion the body is always the idle one (`wait`); faces, mouth, nods and
 * gaze go on.
 */
export function pickAnimations(
  direction: StandDirection,
  animations: ReadonlyMap<string, number>,
  reducedMotion: boolean,
): TrackAnimations {
  const pick = (names: string[]) => names.find((name) => animations.has(name));
  const { mood, nod } = direction;
  const k = LIP[mood];
  const mouth = pick([`lip_${k}`, `lip_${k}1`, `lip_${k}2`, "lip_smile", "lip_wait"]) ?? anyMouth(animations);
  const nodding = nod && pick([nod.kind, `${nod.kind}2`]);
  // An outfit need not have `wait` at all; stand still in `idle` or `stand` instead, or in
  // whatever it opens with, rather than leaving the body track empty.
  const idle = idleAnimation(animations) ?? "wait";
  return {
    body: reducedMotion ? idle : (pick(BODY[mood]) ?? idle),
    face: pick(FACE[mood]) ?? "blank",
    mouth: mouth ? { name: mouth, open: direction.speaking } : null,
    nod: nod && nodding ? { name: nodding, id: nod.id } : null,
    eye: direction.looking && animations.has("eye_front") ? "eye_front" : null,
  };
}

/** The animation she stands still in: `wait`, `idle`, `stand`, else the first the outfit has
 * (null only when it has none at all). */
export function idleAnimation(animations: ReadonlyMap<string, number>): string | null {
  for (const name of ["wait", "idle", "stand"]) if (animations.has(name)) return name;
  return animations.keys().next().value ?? null;
}

/** Any talking mouth that moves: not a still `lip_*_s`, nor `lip_a`. */
function anyMouth(animations: ReadonlyMap<string, number>): string | undefined {
  for (const [name, duration] of animations)
    if (name.startsWith("lip_") && !/_s\d*$/.test(name) && name !== "lip_a" && duration > 0) return name;
  return undefined;
}
