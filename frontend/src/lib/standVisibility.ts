// 立绘在这台设备上的临时隐藏状态：和设置·外观里那个全局的「对话页显示立绘」（lib/appearance）分开，
// 按页面记（单聊按对话，群聊按群），刷新、重开还在。全局开关关着时这一条不起作用，由调用方判断。
// 存不进去（隐私模式等）时不抛错，改动只影响这一次页面。

/** 这一页的立绘被收起来了吗；没存过、存坏了、存储不可用时都当作没收起。 */
export function loadStandHidden(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

/** 记下这一页的立绘收没收起：收起来写 1，恢复时把这条删掉；存不进去时什么也不做。 */
export function saveStandHidden(key: string, hidden: boolean): void {
  try {
    if (hidden) localStorage.setItem(key, "1");
    else localStorage.removeItem(key);
  } catch {
    // 存储不可用：这次改动只在这次页面里生效。
  }
}
