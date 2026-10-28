import { describe, expect, it } from "vitest";

import { CALM, pickAnimations, type Emotion, type StandDirection } from "@/lib/standAnimations";

// 镜像（shinycolors-spine）里真实衣装的动画名单，只取名字；口型另记时长，`lip_*_s` 的时长是 0。

/** 真乃【ナチュラルモード】（stand/1030010010）：没有 face_serious、lip_wait、lip_shy、lip_surp，有 yes2/no2。 */
const MANO = outfit(
  "anger1 anger2 anger3 arm_down arm_down_R arm_down_surp arm_up_R blank eye_front eye_left eye_right face_anger face_anger2 face_close face_close2 face_cry face_sad face_shy face_smile face_smile2 face_smile3 face_surp face_wait hello no no2 sad1 sad2 shy1 shy2 skill1 smile1 smile2 smile3 surp1 surp2 think touch wait wait1 wait2 wait3 wait4 wait_return_L wait_return_R yes yes2",
  { lip_anger: 1.5, lip_anger2: 1.5, lip_anger_s: 0, lip_anger_s2: 0, lip_sad: 1.767, lip_sad_s: 0, lip_sad_s2: 0, lip_smile: 1.5, lip_smile2: 1.5, lip_smile_s: 0, lip_smile_s2: 0, lip_smile_s3: 0, lip_surp_s: 0, lip_trouble: 1.5, lip_trouble_s: 0 },
);

/** 真乃【こころ、みちびく。ゆかり】（stand/3000010580）：没有 shy1/shy2、face_shy。 */
const MANO_NO_SHY = outfit(
  "anger1 anger2 arm_down arm_down_R blank eye_front eye_left eye_right face_anger face_close face_close2 face_close3 face_close4 face_close5 face_cry face_sad face_smile face_smile2 face_smile3 face_surp face_wait no no2 sad1 smile1 smile2 surp1 think wait wait1 wait2 wait3 wait4 yes yes2",
  { lip_anger: 1.5, lip_anger_s: 0, lip_sad: 1.767, lip_sad_s: 0, lip_smile: 1.5, lip_smile_s: 0, lip_trouble: 1.5, lip_trouble_s: 0 },
);

/** 恋钟【ばってん長崎恋岬】（stand/1030040010）：没有 face_surp、lip_serious，有 lip_a；没有 yes2/no2。 */
const KOGANE = outfit(
  "anger1 anger2 arm_down arm_down_L arm_down_R arm_shy1 blank cheek_red eye_front eye_left eye_right face_anger face_close face_close2 face_cry face_doya face_sad face_serious face_shy face_shy2 face_smile face_wait no sad1 sad2 shy1 shy2 skill1 smile1 smile2 smile3 smile4 surp1 surp2 think touch wait wait1 wait2 wait3 wait4 wait5 yes",
  { lip_a: 10, lip_anger: 1.567, lip_sad: 1.567, lip_sad_s: 0, lip_shy: 1.567, lip_smile: 1.567, lip_smile_s: 0, lip_surp: 1.567, lip_surp_s: 0, lip_wait: 1.567, lip_wait_s: 0 },
);

/** 恋钟（stand/3000040580）：没有 sad1/sad2。 */
const KOGANE_NO_SAD = outfit(
  "anger1 arm_down arm_down_L arm_down_R arm_shy1 blank eye_front eye_left eye_right face_anger face_close face_close2 face_close3 face_close4 face_cry face_doya face_sad face_shy face_smile face_surp face_wait no shy1 smile1 smile2 surp1 think wait wait1 wait2 wait3 wait4 wait5 yes",
  { lip_anger: 1.567, lip_anger_s: 0, lip_sad: 1.567, lip_sad2: 1.567, lip_sad_s: 0, lip_shy: 1.567, lip_smile: 1.567, lip_smile_s: 0, lip_surp: 1.567, lip_surp_s: 0, lip_wait: 1.567, lip_wait_s: 0 },
);

function outfit(names: string, lips: Record<string, number>): ReadonlyMap<string, number> {
  return new Map([...names.split(" ").map((name): [string, number] => [name, 1]), ...Object.entries(lips)]);
}

/** 从一套真实衣装里去掉几个动画，走到替代链更靠后的一级。 */
function without(animations: ReadonlyMap<string, number>, ...names: string[]): ReadonlyMap<string, number> {
  return new Map([...animations].filter(([name]) => !names.includes(name)));
}

function direction(change: Partial<StandDirection> = {}): StandDirection {
  return { ...CALM, ...change };
}

function pick(animations: ReadonlyMap<string, number>, change: Partial<StandDirection> = {}, reducedMotion = false) {
  return pickAnimations(direction(change), animations, reducedMotion);
}

describe("pickAnimations：身体、表情和口型", () => {
  it.each<[Emotion, string, string, string]>([
    ["calm", "wait", "face_wait", "lip_wait"],
    ["happy", "smile1", "face_smile", "lip_smile"],
    ["shy", "shy1", "face_shy", "lip_shy"],
    ["surprised", "surp1", "blank", "lip_surp"], // 这套没有 face_surp
    ["sad", "sad1", "face_sad", "lip_sad"],
    ["angry", "anger1", "face_anger", "lip_anger"],
    ["thinking", "think", "face_serious", "lip_smile"], // 没有 lip_serious
  ])("恋钟【ばってん長崎恋岬】%s：身体 %s、表情 %s，说话时用 %s", (mood, body, face, name) => {
    expect(pick(KOGANE, { mood, speaking: true })).toMatchObject({ body, face, mouth: { name, open: true } });
  });

  it("害羞缺 shy1、shy2 时用 smile2，缺 face_shy 时用 blank", () => {
    expect(pick(MANO_NO_SHY, { mood: "shy" })).toMatchObject({ body: "smile2", face: "blank" });
  });

  it("难过找不到身体动作时用 wait", () => {
    expect(pick(KOGANE_NO_SAD, { mood: "sad" })).toMatchObject({ body: "wait", face: "face_sad" });
  });

  it("没有 wait 的衣装：待机用 idle、stand，都没有就用第一个动画", () => {
    const idle = new Map([["idle", 1], ["smile1", 1]]);
    expect(pickAnimations(direction({ mood: "sad" }), idle, false).body).toBe("idle");
    expect(pickAnimations(direction({ mood: "sad" }), idle, true).body).toBe("idle");
    const stand = new Map([["stand", 1], ["smile1", 1]]);
    expect(pickAnimations(direction({ mood: "sad" }), stand, false).body).toBe("stand");
    const first = new Map([["smile1", 1], ["surp1", 1]]);
    expect(pickAnimations(direction({ mood: "sad" }), first, false).body).toBe("smile1");
    expect(pickAnimations(direction({ mood: "sad" }), new Map(), false).body).toBe("wait");
  });

  it("逐级往后找：开心 smile1 → smile2，表情 face_smile → face_smile2", () => {
    expect(pick(without(MANO, "smile1", "face_smile"), { mood: "happy" })).toMatchObject({
      body: "smile2",
      face: "face_smile2",
    });
  });

  it("惊讶 surp1 → surp2，生气 anger1 → anger2、face_anger → face_anger2", () => {
    const trimmed = without(MANO, "surp1", "anger1", "face_anger");
    expect(pick(trimmed, { mood: "surprised" })).toMatchObject({ body: "surp2", face: "face_surp" });
    expect(pick(trimmed, { mood: "angry" })).toMatchObject({ body: "anger2", face: "face_anger2" });
  });

  it("害羞 shy1 → shy2，表情 face_shy → face_shy2", () => {
    expect(pick(without(KOGANE, "shy1", "face_shy"), { mood: "shy" })).toMatchObject({
      body: "shy2",
      face: "face_shy2",
    });
  });

  it("思考没有 think 时依次找 wait4、wait", () => {
    expect(pick(without(KOGANE, "think"), { mood: "thinking" }).body).toBe("wait4");
    expect(pick(without(KOGANE, "think", "wait4"), { mood: "thinking" }).body).toBe("wait");
  });

  it("判得很确定时用更夸张的那一版，拿不准时用温和的那一版", () => {
    expect(pick(KOGANE, { mood: "happy", strength: 0.7 })).toMatchObject({ body: "smile4", face: "face_smile" });
    expect(pick(KOGANE, { mood: "happy", strength: 0.3 })).toMatchObject({ body: "smile1" });
    expect(pick(MANO, { mood: "sad", strength: 0.7 })).toMatchObject({ body: "sad2", face: "face_sad" });
    expect(pick(MANO, { mood: "shy", strength: 0.7 }).body).toBe("shy2");
    expect(pick(KOGANE, { mood: "shy", strength: 0.7 }).face).toBe("face_shy2");
    // 几乎可以确定时用最夸张的那张脸：哭、笑到闭眼
    expect(pick(MANO, { mood: "sad", strength: 0.95 })).toMatchObject({ body: "sad2", face: "face_cry" });
    expect(pick(MANO, { mood: "happy", strength: 0.95 })).toMatchObject({ face: "face_close" });
    // 小台词自带的那一套优先，不受把握程度影响
    expect(pick(MANO, { mood: "sad", strength: 0.95, body: "smile2", face: "face_close" })).toMatchObject({
      body: "smile2",
      face: "face_close",
    });
  });

  it("减少动态效果时，身体一律用 wait，表情、口型和点头照常", () => {
    expect(pick(KOGANE, { mood: "angry" }, true)).toMatchObject({ body: "wait", face: "face_anger" });
    expect(pick(MANO, { mood: "happy" }, true)).toMatchObject({ body: "wait", face: "face_smile" });
    expect(pick(KOGANE, { mood: "sad", speaking: true }, true).mouth).toEqual({ name: "lip_sad", open: true });
    expect(pick(MANO, { nod: { kind: "yes", id: 1 } }, true).nod).toEqual({ name: "yes", id: 1 });
  });

  it("她这一句自带的身体和表情：衣装里有就照着播，没有就按心情挑", () => {
    expect(pick(MANO, { mood: "sad", body: "smile2", face: "face_close" })).toMatchObject({
      body: "smile2",
      face: "face_close",
    });
    // 恋钟这套没有 face_surp，身体动作也没有这个：都回到按心情挑
    expect(pick(KOGANE, { mood: "sad", body: "没有的动作", face: "face_surp" })).toMatchObject({
      body: "sad1",
      face: "face_sad",
    });
    // 减少动态效果时身体照旧用 wait，但这一句的脸还是那一张
    expect(pick(MANO, { mood: "sad", body: "smile2", face: "face_close" }, true)).toMatchObject({
      body: "wait",
      face: "face_close",
    });
  });
});

describe("pickAnimations：口型", () => {
  it("找不到这种情绪的口型时退到 lip_smile：真乃没有 lip_wait、lip_shy、lip_surp", () => {
    for (const mood of ["calm", "shy", "surprised"] as const)
      expect(pick(MANO, { mood, speaking: true }).mouth?.name).toBe("lip_smile");
  });

  it("找 lip_<k>1、lip_<k>2", () => {
    expect(pick(without(KOGANE_NO_SAD, "lip_sad"), { mood: "sad", speaking: true }).mouth?.name).toBe("lip_sad2");
  });

  it("lip_smile 也没有时用 lip_wait", () => {
    expect(pick(without(KOGANE, "lip_anger", "lip_smile"), { mood: "angry", speaking: true }).mouth?.name).toBe(
      "lip_wait",
    );
  });

  it("再找不到就用任意一个时长不为 0 的口型，不用 lip_*_s 和 lip_a", () => {
    const trimmed = without(MANO, "lip_smile", "lip_smile2");
    expect(pick(trimmed, { mood: "calm", speaking: true }).mouth?.name).toMatch(/^lip_(anger|anger2|sad|trouble)$/);
    const onlyStops = without(KOGANE, "lip_anger", "lip_sad", "lip_shy", "lip_smile", "lip_surp", "lip_wait");
    expect(pick(onlyStops, { mood: "calm", speaking: true }).mouth).toBeNull();
  });

  it("闭嘴时用同一个说话口型，只是不开", () => {
    expect(pick(KOGANE, { mood: "happy", speaking: false }).mouth).toEqual({ name: "lip_smile", open: false });
  });
});

describe("pickAnimations：点头和视线", () => {
  it("点头用 yes，摇头用 no，带上这次的编号；没有点头时这条轨道什么都不放", () => {
    expect(pick(MANO, { nod: { kind: "yes", id: 3 } }).nod).toEqual({ name: "yes", id: 3 });
    expect(pick(KOGANE, { nod: { kind: "no", id: 4 } }).nod).toEqual({ name: "no", id: 4 });
    expect(pick(MANO).nod).toBeNull();
  });

  it("没有 yes、no 时用 yes2、no2，都没有就不点", () => {
    expect(pick(without(MANO, "yes", "no"), { nod: { kind: "yes", id: 1 } }).nod).toEqual({ name: "yes2", id: 1 });
    expect(pick(without(MANO, "yes", "no"), { nod: { kind: "no", id: 2 } }).nod).toEqual({ name: "no2", id: 2 });
    expect(pick(without(KOGANE, "no"), { nod: { kind: "no", id: 5 } }).nod).toBeNull();
  });

  it("看向用户时用 eye_front，不看时清空", () => {
    expect(pick(KOGANE, { looking: true }).eye).toBe("eye_front");
    expect(pick(KOGANE, { looking: false }).eye).toBeNull();
    expect(pick(without(KOGANE, "eye_front"), { looking: true }).eye).toBeNull();
  });
});
