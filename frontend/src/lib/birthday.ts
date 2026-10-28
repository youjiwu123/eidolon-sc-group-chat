// 生日原声彩蛋（功能 2）：这台设备上「今天看过了」和同一次页面里只问后端一次。

import { getBirthdayEgg, type BirthdayEgg } from "@/lib/api";

/** 今天的生日彩蛋（后端说是生日时的那一份）。 */
export type ActiveBirthday = Extract<BirthdayEgg, { active: true }>;

const SEEN_PREFIX = "birthdaySeen:";

/** 本机当地日期的写法（`YYYY-MM-DD`），用来判断是不是同一天。 */
export function dayKey(at: Date): string {
  const month = String(at.getMonth() + 1).padStart(2, "0");
  const day = String(at.getDate()).padStart(2, "0");
  return `${at.getFullYear()}-${month}-${day}`;
}

/** 这台设备上今天已经看过她的生日彩蛋了吗。读不出（无痕浏览）时算没看过。 */
export function birthdaySeenToday(userId: string, at: Date = new Date()): boolean {
  try {
    return localStorage.getItem(SEEN_PREFIX + userId) === dayKey(at);
  } catch {
    return false;
  }
}

/** 记下这台设备上今天看过了；关掉以后当天不再弹。存不进去时只是这次页面里不记得。 */
export function keepBirthdaySeenToday(userId: string, at: Date = new Date()): void {
  try {
    localStorage.setItem(SEEN_PREFIX + userId, dayKey(at));
  } catch {
    // 无痕浏览：存不进去就算了，后端那边也已经只给一次。
  }
}

/** 同一次页面里只问一次后端：React 的开发模式会把刚挂上的组件挂两遍，而后端一天只给一次，
 * 问两次第二次就是“今天已经给过了”。失败也算问过，不再重试到把次数耗光。 */
let asked: { userId: string; egg: Promise<ActiveBirthday | null> } | null = null;

/** 今天的生日彩蛋；不是生日、今天已经给过、或者请求失败时是 null。 */
export function loadBirthdayEgg(userId: string): Promise<ActiveBirthday | null> {
  if (asked?.userId !== userId) {
    asked = {
      userId,
      egg: getBirthdayEgg().then(
        (egg) => (egg.active ? egg : null),
        () => null,
      ),
    };
  }
  return asked.egg;
}
