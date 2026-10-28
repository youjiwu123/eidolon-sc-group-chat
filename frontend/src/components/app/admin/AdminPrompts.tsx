"use client";

import { useEffect, useId, useMemo, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { AdminPage } from "@/components/app/admin/AdminPage";
import { Notice } from "@/components/app/admin/Notice";
import { Timestamp } from "@/components/app/admin/Timestamp";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { copy } from "@/i18n";
import { toFailure, type Failure } from "@/lib/failure";
import {
  createMode,
  deletePrompt,
  getPrompt,
  listPrompts,
  MAX_PROMPT_BYTES,
  saveModeFields,
  savePrompt,
  type ModeFields,
  type NewMode,
  type PromptDetail,
  type PromptEntry,
  type PromptKind,
} from "@/lib/prompts";
import { cn } from "@/lib/utils";

const t = copy.admin.prompts;

/**
 * 后台的「提示词」页：左边按组列出可编辑的提示词——角色提示词、特殊提示词（一个模式一格）、
 * 好感度提示词——右边用等宽字体改这一条的正文。特殊档可以单独删除：模式表里别的不动，她已经
 * 开着的那个开关一起关掉，删前先备份。保存会先备份、原子写入并重新加载，新的回合和通话立即
 * 用上；成功提示在右下角浮出，一会儿自己消失。窄屏时列表和编辑器上下排，列表只有一屏高。
 */
export function AdminPrompts() {
  const [prompts, setPrompts] = useState<PromptEntry[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<PromptDetail | null>(null);
  const [content, setContent] = useState("");
  const [fields, setFields] = useState<ModeFields | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [failure, setFailure] = useState<Failure | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const editorId = useId();
  const sizeId = useId();

  useEffect(() => {
    let cancelled = false;
    listPrompts().then(
      (listed) => {
        if (cancelled) return;
        setPrompts(listed);
        setSelected((current) => current ?? listed[0]?.key ?? null);
      },
      (e) => {
        if (!cancelled) setFailure(toFailure(e));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (selected === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setFailure(null);
    setNotice(null);
    getPrompt(selected).then(
      (found) => {
        if (cancelled) return;
        setDetail(found);
        setContent(found.content);
        setFields(found.fields ?? null);
        setLoading(false);
      },
      (e) => {
        if (cancelled) return;
        setFailure(toFailure(e));
        setDetail(null);
        setFields(null);
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [selected]);

  useEffect(() => {
    if (notice === null) return;
    const timer = window.setTimeout(() => setNotice(null), 5000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const selectedEntry = prompts?.find((item) => item.key === selected) ?? null;
  // 列表按三组排：角色提示词、特殊提示词（一个模式一格）、好感度提示词。
  const groups = [
    {
      id: "sheets",
      title: t.groups.sheets,
      items: prompts?.filter((item) => item.kind === "sheet") ?? [],
    },
    {
      id: "modes",
      title: t.groups.modes,
      items: prompts?.filter((item) => item.kind === "mode" || item.kind === "modes") ?? [],
    },
    {
      id: "affinity",
      title: t.groups.affinity,
      items: prompts?.filter((item) => item.kind === "affinity") ?? [],
    },
  ].filter((group) => group.items.length > 0);
  const bytes = useMemo(() => {
    if (fields !== null) return new TextEncoder().encode(fields.prompt).length;
    return new TextEncoder().encode(content).length;
  }, [content, fields]);
  const tooLarge = bytes > MAX_PROMPT_BYTES;
  const dirty =
    detail === null
      ? false
      : fields !== null && detail.fields !== undefined
        ? fields.name !== detail.fields.name ||
          fields.description !== detail.fields.description ||
          fields.prompt !== detail.fields.prompt
        : content !== detail.content;
  const empty = fields !== null ? fields.prompt.trim() === "" : content.trim() === "";
  const canSave = detail !== null && dirty && !empty && !tooLarge && !saving;

  function choose(key: string) {
    if (key === selected || saving) return;
    if (dirty && !window.confirm(t.unsavedConfirm)) return;
    setSelected(key);
  }

  function reset() {
    if (detail === null) return;
    setContent(detail.content);
    setFields(detail.fields ?? null);
    setFailure(null);
  }

  async function save() {
    if (detail === null) return;
    setSaving(true);
    setFailure(null);
    setNotice(null);
    try {
      // 特殊档按三栏存（名字、说明、提示词），不用手写 TOML；别的种类存整份正文。
      const saved =
        fields !== null ? await saveModeFields(detail.key, fields) : await savePrompt(detail.key, content);
      setDetail(saved);
      setContent(saved.content);
      setFields(saved.fields ?? null);
      setPrompts(
        (current) =>
          current?.map((item) =>
            item.key === saved.key
              ? { ...item, label: saved.label, bytes: saved.bytes, updated_at: saved.updated_at }
              : item,
          ) ?? null,
      );
      setNotice(saved.reload_required ? t.savedReload : t.saved);
    } catch (e) {
      setFailure(toFailure(e));
    } finally {
      setSaving(false);
    }
  }

  async function makeMode(mode: NewMode) {
    const made = await createMode(mode);
    setNotice(t.newMode.created(made.name));
    // 新建的那一格排在模式表的最后：列表重读一遍，然后直接选中它。
    setPrompts(await listPrompts());
    setSelected(`modes/${made.id}`);
  }

  async function remove() {
    if (detail === null || detail.kind !== "mode") return;
    if (!window.confirm(t.deleteConfirm(detail.label))) return;
    setDeleting(true);
    setFailure(null);
    try {
      await deletePrompt(detail.key);
      const listed = await listPrompts();
      setPrompts(listed);
      const next = listed.find((item) => item.kind === "mode") ?? listed[0] ?? null;
      setSelected(next?.key ?? null);
      setNotice(t.deleted(detail.label));
    } catch (e) {
      setFailure(toFailure(e));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AdminPage width="wide" title={copy.admin.pages.prompts} intro={t.intro}>
      <p className="rounded-lg border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">{t.hint}</p>
      {failure && <FailureNotice failure={failure} />}

      {prompts === null && failure === null && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          {t.loading}
        </p>
      )}

      {prompts !== null && prompts.length === 0 && (
        <p className="text-sm text-muted-foreground">{t.empty}</p>
      )}

      {prompts !== null && prompts.length > 0 && (
        <div className="grid items-start gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <Card size="sm" className="min-w-0">
            <CardHeader className="border-b">
              <CardTitle>
                <h2>{t.listTitle}</h2>
              </CardTitle>
              <CardDescription>{t.listHint}</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="max-h-80 overflow-y-auto lg:max-h-[65vh]">
                {groups.map((group) => {
                  const open = !collapsed[group.id];
                  return (
                    <div key={group.id} className="border-b last:border-b-0">
                      <button
                        type="button"
                        aria-expanded={open}
                        onClick={() =>
                          setCollapsed((now) => ({ ...now, [group.id]: open }))
                        }
                        className="flex w-full items-center justify-between gap-2 bg-muted/40 px-4 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/70"
                      >
                        <span>{group.title}</span>
                        <span className="flex items-center gap-2 tabular-nums">
                          {group.items.length}
                          <span aria-hidden>{open ? "▾" : "▸"}</span>
                        </span>
                      </button>
                      {open && (
                        <ul aria-label={group.title}>
                          {group.items.map((item) => (
                            <li key={item.key}>
                              <button
                                type="button"
                                onClick={() => choose(item.key)}
                                aria-current={item.key === selected ? "true" : undefined}
                                disabled={saving || deleting}
                                className={cn(
                                  "flex w-full flex-col gap-1.5 px-4 py-3 pl-7 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60",
                                  item.key === selected ? "bg-muted" : "hover:bg-muted/50",
                                )}
                              >
                                <span className="min-w-0 font-medium break-words">{item.label}</span>
                                <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                                  <span className="tabular-nums">{t.bytes(item.bytes)}</span>
                                  <span aria-hidden>·</span>
                                  {item.updated_at ? (
                                    <Timestamp value={item.updated_at} format="auto" />
                                  ) : (
                                    <span>{t.neverSaved}</span>
                                  )}
                                </span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <Card className="min-w-0">
            <CardHeader className="border-b">
              <CardTitle className="flex flex-wrap items-center gap-2">
                <h2 className="min-w-0 break-words">{selectedEntry?.label}</h2>
                {selectedEntry && <KindBadge kind={selectedEntry.kind} />}
              </CardTitle>
              <CardDescription className="font-mono break-all">{selectedEntry?.key}</CardDescription>
            </CardHeader>
            <CardContent className="flex min-h-64 flex-col gap-3">
              {loading && (
                <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Spinner />
                  {t.loading}
                </p>
              )}
              {!loading && detail === null && (
                <p className="text-sm text-muted-foreground">{t.select}</p>
              )}
              {!loading && detail !== null && fields !== null && (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`${editorId}-name`}>{t.fields.name}</Label>
                    <Input
                      id={`${editorId}-name`}
                      value={fields.name}
                      onChange={(event) => setFields({ ...fields, name: event.target.value })}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`${editorId}-description`}>{t.fields.description}</Label>
                    <Input
                      id={`${editorId}-description`}
                      value={fields.description}
                      placeholder={t.fields.descriptionPlaceholder}
                      onChange={(event) => setFields({ ...fields, description: event.target.value })}
                    />
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Label htmlFor={editorId}>{t.fields.prompt}</Label>
                    <span id={sizeId} className="text-xs text-muted-foreground tabular-nums">
                      {t.bytes(bytes)}
                    </span>
                  </div>
                  <Textarea
                    id={editorId}
                    value={fields.prompt}
                    onChange={(event) => setFields({ ...fields, prompt: event.target.value })}
                    aria-describedby={sizeId}
                    aria-invalid={tooLarge || (dirty && empty) || undefined}
                    className="max-h-[65vh] min-h-64 resize-y text-sm leading-relaxed lg:min-h-96"
                  />
                  {tooLarge && (
                    <p role="alert" className="text-sm text-destructive">
                      {t.tooLarge}
                    </p>
                  )}
                  {!tooLarge && dirty && empty && (
                    <p role="alert" className="text-sm text-destructive">
                      {t.emptyContent}
                    </p>
                  )}
                </div>
              )}
              {!loading && detail !== null && fields === null && (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Label htmlFor={editorId}>{t.contentLabel}</Label>
                    <span id={sizeId} className="text-xs text-muted-foreground tabular-nums">
                      {t.bytes(bytes)}
                    </span>
                  </div>
                  <Textarea
                    id={editorId}
                    value={content}
                    onChange={(event) => setContent(event.target.value)}
                    spellCheck={false}
                    aria-describedby={sizeId}
                    aria-invalid={tooLarge || (dirty && empty) || undefined}
                    className="max-h-[65vh] min-h-64 resize-y font-mono text-sm leading-relaxed lg:min-h-96"
                  />
                  {tooLarge && (
                    <p role="alert" className="text-sm text-destructive">
                      {t.tooLarge}
                    </p>
                  )}
                  {!tooLarge && dirty && empty && (
                    <p role="alert" className="text-sm text-destructive">
                      {t.emptyContent}
                    </p>
                  )}
                </>
              )}
            </CardContent>
            {!loading && detail !== null && (
              <CardFooter className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">{dirty ? t.unsaved : t.unchanged}</span>
                <div className="flex flex-wrap gap-2">
                  {selectedEntry?.kind === "mode" && (
                    <Button variant="outline" onClick={remove} disabled={saving || deleting}>
                      {deleting ? t.deleting : t.delete}
                    </Button>
                  )}
                  <Button variant="outline" onClick={reset} disabled={!dirty || saving}>
                    {t.reset}
                  </Button>
                  <Button onClick={save} disabled={!canSave}>
                    {saving && <Spinner data-icon="inline-start" />}
                    {saving ? t.saving : t.save}
                  </Button>
                </div>
              </CardFooter>
            )}
          </Card>
        </div>
      )}

      <NewModeCard blocked={dirty} onCreate={makeMode} />

      {notice && (
        <div className="fixed right-4 bottom-4 left-4 z-50 sm:left-auto sm:w-96">
          <Notice text={notice} onDismiss={() => setNotice(null)} />
        </div>
      )}
    </AdminPage>
  );
}

function KindBadge({ kind }: { kind: PromptKind }) {
  return <Badge variant="outline">{t.kinds[kind]}</Badge>;
}

/**
 * 在模式表下面新建一条自己写的特殊档：名字、说明、提示词，提交后后端追加进 `modes.toml`
 * 并热加载；聊天界面好感度弹层里的开关就是照这张表列的。模式表里有没保存的改动时先不让新建，
 * 免得写盘的那份和编辑器里那份对不上。
 */
function NewModeCard({
  blocked,
  onCreate,
}: {
  blocked: boolean;
  onCreate: (mode: NewMode) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const nameId = useId();
  const descriptionId = useId();
  const promptId = useId();
  const canCreate = !creating && !blocked && name.trim() !== "" && prompt.trim() !== "";

  async function create() {
    setCreating(true);
    setFailure(null);
    try {
      await onCreate({ name: name.trim(), description: description.trim(), prompt: prompt.trim() });
      setName("");
      setDescription("");
      setPrompt("");
    } catch (e) {
      setFailure(toFailure(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Card size="sm" className="min-w-0">
      <CardHeader className="border-b">
        <CardTitle>
          <h2>{t.newMode.title}</h2>
        </CardTitle>
        <CardDescription>{t.newMode.hint}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={nameId}>{t.newMode.name}</Label>
            <Input
              id={nameId}
              value={name}
              placeholder={t.newMode.namePlaceholder}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={descriptionId}>{t.newMode.description}</Label>
            <Input
              id={descriptionId}
              value={description}
              placeholder={t.newMode.descriptionPlaceholder}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={promptId}>{t.newMode.prompt}</Label>
          <Textarea
            id={promptId}
            value={prompt}
            placeholder={t.newMode.promptPlaceholder}
            onChange={(event) => setPrompt(event.target.value)}
            className="min-h-24 font-mono text-sm leading-relaxed"
          />
        </div>
        {blocked && (
          <p role="status" className="text-sm text-muted-foreground">
            {t.newMode.saveFirst}
          </p>
        )}
        {failure && <FailureNotice failure={failure} />}
      </CardContent>
      <CardFooter className="justify-end">
        <Button onClick={create} disabled={!canCreate}>
          {creating && <Spinner data-icon="inline-start" />}
          {creating ? t.newMode.creating : t.newMode.create}
        </Button>
      </CardFooter>
    </Card>
  );
}
