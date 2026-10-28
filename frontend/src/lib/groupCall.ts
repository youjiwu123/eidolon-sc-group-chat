// 群通话：一条 WebRTC 连接里几个人轮流说，各自用自己的音色（`call.py` 的 `GroupLiveCall`）。
// 和单聊通话同一个 Pipecat 客户端，只是信令走 `/api/groups/<群>/call`；这台前端只关心两件事：
// 谁在说（`segment-playing` 里的 `speaker`）和她的声音往哪放。

import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

import { apiHeaders, getGroupCallSetup } from "@/lib/api";
import { Microphone } from "@/lib/microphone";
import type { Emotion } from "@/lib/standAnimations";

export type GroupCallEvent =
  | { type: "connected" }
  /** 连接断了（不是我们挂的）。 */
  | { type: "dropped" }
  /** 现在轮到谁说话：群成员的 id。 */
  | { type: "speaker"; speaker: string }
  /** 你正说着（临时结果，给字幕用）。 */
  | { type: "hearing"; text: string }
  /** 这一句是谁说的、说了什么：格子下面那行字幕。 */
  | { type: "line"; speaker: string; ja: string; zh: string }
  /** 她这一句的语气：格子里那张脸照它变。 */
  | { type: "emotion"; speaker: string; mood: Emotion; strength: number };

export type GroupCall = {
  hangUp: () => Promise<void>;
  setMicEnabled: (enabled: boolean) => void;
};

/**
 * 打进一个群：拿 ICE 服务器、开麦克风、连 `/api/groups/<群>/call`，接通后把她的声音交给
 * `onAudio`（页面挂到一个 `<audio>` 上），谁在说话交给 `onEvent`。
 */
export async function startGroupCall(
  groupId: string,
  handlers: {
    onEvent: (event: GroupCallEvent) => void;
    onAudio: (track: MediaStreamTrack) => void;
  },
): Promise<GroupCall> {
  const { iceServers } = await getGroupCallSetup(groupId);
  const microphone = await Microphone.open("");
  const transport = new SmallWebRTCTransport({ iceServers, mediaManager: microphone });
  const client = new PipecatClient({
    transport,
    enableMic: true,
    enableCam: false,
    callbacks: {
      onServerMessage: (data) => {
        const message = data as {
          type?: string;
          speaker?: string | null;
          ja?: string;
          zh?: string;
          emotion?: string;
          strength?: number;
        };
        if (message?.type === "segment-playing" && message.speaker) {
          handlers.onEvent({ type: "speaker", speaker: message.speaker });
        } else if (message?.type === "line" && message.speaker) {
          handlers.onEvent({
            type: "line",
            speaker: message.speaker,
            ja: String(message.ja ?? ""),
            zh: String(message.zh ?? ""),
          });
        } else if (message?.type === "emotion" && message.speaker && message.emotion) {
          handlers.onEvent({
            type: "emotion",
            speaker: message.speaker,
            mood: message.emotion as Emotion,
            strength: Number(message.strength ?? 0),
          });
        }
      },
      onTrackStarted: (track, participant) => {
        if (!participant?.local && track.kind === "audio") handlers.onAudio(track);
      },
      onUserTranscript: (data) =>
        handlers.onEvent({ type: "hearing", text: data.final ? "" : data.text }),
      onDisconnected: () => handlers.onEvent({ type: "dropped" }),
    },
  });
  try {
    await client.connect({
      webrtcRequestParams: {
        endpoint: `/api/groups/${encodeURIComponent(groupId)}/call`,
        headers: apiHeaders(),
        requestData: {},
      },
    });
  } catch (error) {
    await client.disconnect().catch(() => {});
    await microphone.disconnect();
    throw error;
  }
  handlers.onEvent({ type: "connected" });
  return {
    hangUp: async () => {
      await client.disconnect().catch(() => {});
      await microphone.disconnect();
    },
    setMicEnabled: (enabled) => microphone.enableMic(enabled),
  };
}
