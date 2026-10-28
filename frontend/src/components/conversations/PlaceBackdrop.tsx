"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

type Props = {
  /** 地点图的地址（`/api/scenes/<id>`）；null 是不铺图：群聊没选地点、看历史对话时。 */
  imageUrl: string | null;
};

/**
 * 消息区背后的地点图（DESIGN.md「通话场景」）：选定的那一处按 `object-cover` 铺满，上面压一层
 * `--background` 的渐变，气泡、名字和时间仍然读得清；它是最底下的一层（`-z-10`，父容器 `isolate`），
 * 不接点击，也不报给屏幕阅读器。
 *
 * 换图时旧图先留在下面，新图读到了才换上来并淡入（`transition-opacity`），中间不会先空一下；
 * 图读不到就当没有，消息区回到原来的壁纸。
 */
export function PlaceBackdrop({ imageUrl }: Props) {
  /** 铺着的那张；新的读到以前一直是它。 */
  const [current, setCurrent] = useState<string | null>(null);
  /** 上一张：新图淡入的时候垫在下面，换的时候不闪。 */
  const [previous, setPrevious] = useState<string | null>(null);
  /** 这一张的透明度打开了没：挂上来先透明，下一帧再打开，`transition-opacity` 才有得过渡。 */
  const [drawn, setDrawn] = useState(false);

  // 新图先读出来，读到了才换：换的时候不出现半张图。
  useEffect(() => {
    if (imageUrl === null) {
      setPrevious(null);
      setCurrent(null);
      return;
    }
    if (imageUrl === current) return;
    let alive = true;
    const image = new Image();
    image.onload = () => {
      if (!alive) return;
      setPrevious(current);
      setCurrent(imageUrl);
      setDrawn(false);
    };
    image.onerror = () => {
      // 读不到就当作没有地点图，回到壁纸。
      if (!alive) return;
      setPrevious(null);
      setCurrent(null);
    };
    image.src = imageUrl;
    return () => {
      alive = false;
    };
  }, [imageUrl, current]);

  // 换上来以后下一帧再打开透明度：一次淡入。
  useEffect(() => {
    if (current === null) return;
    const frame = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(frame);
  }, [current]);

  if (current === null) return null;
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      {previous !== null && (
        <img src={previous} alt="" className="absolute inset-0 size-full object-cover" />
      )}
      {/* 换一张时按地址重新挂上来：新的一张从透明淡入，旧的一张垫在下面，中间不空 */}
      <img
        key={current}
        src={current}
        alt=""
        className={cn(
          "absolute inset-0 size-full object-cover transition-opacity duration-500 motion-reduce:transition-none",
          drawn ? "opacity-100" : "opacity-0",
        )}
      />
      {/* 压一层页面底色（深色模式下就是压暗）：她的白底气泡和正文在图上照样清楚，图还看得见 */}
      <div className="absolute inset-0 bg-linear-to-b from-background/80 via-background/70 to-background/85" />
    </div>
  );
}
