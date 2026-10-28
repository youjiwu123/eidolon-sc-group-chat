"use client";

import { useEffect, useId, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/i18n";
import { getCharacterModes, getModes, saveCharacterModes, type ProducerMode } from "@/lib/api";
import { toFailure, type Failure } from "@/lib/failure";

const t = copy.conversation.affinity.modes;

/**
 * 好感度说明下面的特殊档开关（GLOSSARY.md「特殊档」）：每个角色各有一份，开着的模式只在她
 * 自己的提示词里追加，好感各档都追加；别的角色一个字都不受影响。部署者没配模式表时什么都不画。
 * 拨一下马上存；存不上就拨回去，照原话说明。读不到只影响这一块，好感度本身照旧显示。
 */
export function AffinityModeSwitches({ characterId }: { characterId: string }) {
  const id = useId();
  const [modes, setModes] = useState<ProducerMode[] | null>(null);
  const [enabled, setEnabled] = useState<string[] | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let current = true;
    setFailure(null);
    Promise.all([getModes(), getCharacterModes(characterId)]).then(
      ([available, on]) => {
        if (!current) return;
        setModes(available);
        setEnabled(on);
      },
      (e) => current && setFailure(toFailure(e)),
    );
    return () => {
      current = false;
    };
  }, [characterId]);

  if (!modes || !enabled) {
    return failure ? <FailureNotice failure={failure} /> : null;
  }
  if (modes.length === 0) return null;

  const on = enabled;
  const change = (modeId: string, next: boolean) => {
    const before = on;
    const after = next ? [...on, modeId] : on.filter((each) => each !== modeId);
    setEnabled(after);
    setSaving(true);
    setFailure(null);
    saveCharacterModes(characterId, after).then(
      (saved) => {
        setEnabled(saved);
        setSaving(false);
      },
      (e) => {
        setEnabled(before);
        setFailure(toFailure(e));
        setSaving(false);
      },
    );
  };

  return (
    <FieldGroup className="border-t pt-2">
      <div className="flex flex-col gap-0.5">
        <p className="font-medium">{t.label}</p>
        <p className="text-meta text-muted-foreground">{t.hint}</p>
      </div>
      {modes.map((mode) => (
        <Field key={mode.id} orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor={`${id}-${mode.id}`}>{mode.name}</FieldLabel>
            <FieldDescription>{mode.description}</FieldDescription>
          </FieldContent>
          <Switch
            id={`${id}-${mode.id}`}
            checked={on.includes(mode.id)}
            disabled={saving}
            onCheckedChange={(checked) => change(mode.id, checked)}
          />
        </Field>
      ))}
      {failure && <FailureNotice failure={failure} />}
    </FieldGroup>
  );
}
