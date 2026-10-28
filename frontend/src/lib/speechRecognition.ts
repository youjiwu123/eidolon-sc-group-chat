// 群聊语音房的听写：用浏览器自带的语音识别（Chrome / Edge 的 Web Speech API）。
// 这是语音房 v1 的取巧处——不用另接服务端 STT；浏览器不支持（Safari、Firefox）时
// 语音房退回打字，按钮不出现，也不假装能听。

/** 浏览器给的一条识别结果。 */
export type Heard = {
  /** 这句话说完时是 true（中途的结果是 false）。 */
  final: boolean;
  text: string;
};

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: RecognitionResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

type RecognitionResultEvent = {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: { isFinal: boolean; 0: { transcript: string } };
  };
};

type RecognitionConstructor = new () => Recognition;

/** 这台浏览器能不能听写；不能时语音房只用打字。 */
export function speechRecognition(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const found = (window as unknown as Record<string, unknown>).SpeechRecognition ??
    (window as unknown as Record<string, unknown>).webkitSpeechRecognition;
  return typeof found === "function" ? (found as RecognitionConstructor) : null;
}

/** 开始听；每说出一句（`final`）就交给 `onHeard`，出错交给 `onError`。停的时候调 `stop`。 */
export function listen(
  language: string,
  onHeard: (heard: Heard) => void,
  onError: (error: string) => void,
): { stop(): void } {
  const Constructor = speechRecognition();
  if (!Constructor) throw new Error("这个浏览器不能语音识别");
  let stopped = false;
  let recognition: Recognition | null = null;
  let restart: number | undefined;

  /** 说话是连续的：识别到一句就自己接着听，直到主动停。浏览器停掉（静音太久、切后台）时
   * 稍等一会儿再开，别把整场语音房丢在半路。 */
  const start = () => {
    if (stopped) return;
    const next = new Constructor();
    recognition = next;
    next.lang = language;
    next.continuous = true;
    next.interimResults = true;
    next.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0]?.transcript?.trim() ?? "";
        if (text) onHeard({ final: result.isFinal, text });
      }
    };
    next.onerror = (event) => {
      // 没说话、被打断这类自己会恢复；权限、服务不可用要告诉用户，不再重开。
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        stopped = true;
        onError(event.error);
        return;
      }
      if (event.error === "no-speech" || event.error === "aborted") return;
      onError(event.error);
    };
    next.onend = () => {
      if (stopped) return;
      window.clearTimeout(restart);
      restart = window.setTimeout(start, 200);
    };
    try {
      next.start();
    } catch {
      // 已经在跑：等它自己结束
    }
  };

  start();
  return {
    stop() {
      stopped = true;
      window.clearTimeout(restart);
      try {
        recognition?.stop();
      } catch {
        // 已经停了
      }
      recognition = null;
    },
  };
}
