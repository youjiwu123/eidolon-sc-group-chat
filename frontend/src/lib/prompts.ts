// 后台的提示词编辑器：可编辑的只有角色配置里点名的人设文件（sheets/<id>.md）、模式表里的每个
// 特殊档（一个模式一格）、以及好感度各档的那几段（affinity.toml）。这些提示词改完就重新加载，
// 新的回合和通话立即用上；保存前后端会把原文备份一份。

import { api, json } from "@/lib/api";

/** 后端允许的一条提示词最多多少字节，和 `prompt_admin.MAX_PROMPT_BYTES` 一致。 */
export const MAX_PROMPT_BYTES = 200 * 1024;

export type PromptKind = "sheet" | "modes" | "mode" | "affinity";

/** 列表里的一条：键（相对路径）、种类、显示名、字节数和最后修改时间。 */
export type PromptEntry = {
  key: string;
  kind: PromptKind;
  label: string;
  bytes: number;
  /** 还没保存过（模式表缺失）时是 null。 */
  updated_at: string | null;
};

/** 一个特殊档的三栏：名字、设置里给她看的一句说明、追加到提示词里的正文。 */
export type ModeFields = { name: string; description: string; prompt: string };

export type PromptDetail = PromptEntry & {
  content: string;
  /** 特殊档才有：三栏本身，编辑器按表单显示，不用手写 TOML。 */
  fields?: ModeFields;
};

/** 保存后的这条，`reload_required` 为 true 时得重启后端才生效。 */
export type SavedPrompt = PromptDetail & { reload_required: boolean };

/** 一条提示词的地址。键里的 `/` 留在路径上，其余各段分别转义，避免把键当成任意路径。 */
export function promptPath(key: string): string {
  return key.split("/").map(encodeURIComponent).join("/");
}

export async function listPrompts(): Promise<PromptEntry[]> {
  return json(await api("/api/admin/prompts"));
}

export async function getPrompt(key: string): Promise<PromptDetail> {
  return json(await api(`/api/admin/prompts/${promptPath(key)}`));
}

/** 保存整份提示词；后端会先备份、原子写入并立即重新加载。 */
export async function savePrompt(key: string, content: string): Promise<SavedPrompt> {
  return json(
    await api(`/api/admin/prompts/${promptPath(key)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  );
}

/** 删除一条自己写的特殊档（`modes/<id>`）：别的特殊档和模式表开头的注释都留着，先备份再原子
 * 写入并热加载；聊天界面里已经开着的这个开关也一起关掉。别的种类（人设、好感度）不能删。 */
export async function deletePrompt(key: string): Promise<void> {
  await json<{ key: string; deleted: boolean }>(
    await api(`/api/admin/prompts/${promptPath(key)}`, { method: "DELETE" }),
  );
}

/** 只存一个特殊档的三栏；后端把它写回模式表里那一条，别的模式不动，先备份再热加载。 */
export async function saveModeFields(key: string, fields: ModeFields): Promise<SavedPrompt> {
  return json(
    await api(`/api/admin/prompts/${promptPath(key)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(fields),
    }),
  );
}

/** 一条自己写的特殊档：名字、设置里给她看的一句说明，和追加到提示词里的正文。 */
export type NewMode = {
  name: string;
  description: string;
  prompt: string;
};

/** 新建一条特殊档：后端把它追加进模式表（先备份再原子写入）并热加载，
 * 之后聊天界面的好感度弹层里就多一个开关。id 由后端生成，只在爱意档生效。 */
export async function createMode(mode: NewMode): Promise<{ id: string; name: string }> {
  return json(
    await api("/api/admin/modes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(mode),
    }),
  );
}
