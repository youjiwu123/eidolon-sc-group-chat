/**
 * 原声（官方音源）的播放器：对话页气泡旁那个「原声」键从这里放。
 *
 * 一段原声就是一个 mp3（`/api/voices/...`），不合成、不缓存到后端；一次只放一段，换一段就
 * 停掉上一段。状态放模块里，好让同一段原声的几个按钮共用一个播放器。
 * 和「朗读这条回复」（lib/messageSpeech）共用一个耳朵：开始放原声时停下朗读，反过来也一样
 * （调用处先 `stopVoiceLine()` 再朗读）。
 */

import { stopSpeech } from "@/lib/messageSpeech";

export type ClipState = { key: string; phase: "loading" | "playing" } | null;

let state: ClipState = null;
let audio: HTMLAudioElement | null = null;
const listeners = new Set<() => void>();

function publish(next: ClipState) {
  state = next;
  for (const listener of listeners) listener();
}

export function subscribeVoiceLine(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function voiceLineState(): ClipState {
  return state;
}

export function stopVoiceLine() {
  if (audio) {
    audio.pause();
    audio.src = "";
    audio = null;
  }
  if (state !== null) publish(null);
}

/** 放 `url` 那段原声，`key` 是它在页面上的身份（同一段就停下）。 */
export function toggleVoiceLine(key: string, url: string) {
  if (state?.key === key) {
    stopVoiceLine();
    return;
  }
  stopVoiceLine();
  stopSpeech(); // 和「朗读这条回复」共用一个耳朵：只放一个。
  publish({ key, phase: "loading" });
  const element = new Audio(url);
  audio = element;
  element.addEventListener("playing", () => publish({ key, phase: "playing" }));
  element.addEventListener("ended", stopVoiceLine);
  element.addEventListener("error", stopVoiceLine);
  void element.play().catch(stopVoiceLine);
}
