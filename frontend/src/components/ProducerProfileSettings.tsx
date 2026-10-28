"use client";

import { FormEvent, useEffect, useId, useMemo, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { SettingsSection } from "@/components/app/SettingsSection";
import { useSettingsValues } from "@/components/settings/SettingsValues";
import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxSelectTrigger,
} from "@/components/ui/combobox";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { saveProfile, type Gender } from "@/lib/api";
import { toFailure, type Failure } from "@/lib/failure";
import {
  chooseBirthMonth,
  clampFormOfAddress,
  daysInMonth,
  fromDraft,
  missingBirthDay,
  sameDraft,
  toDraft,
  type Draft,
} from "@/lib/producerProfile";
import { detectTimezone, listTimezones } from "@/lib/timezone";

const t = copy.settings.profile;

/** 「沿用默认」在选择框里用这个值代表（选择框的值不用空字符串），草稿里仍是空白。 */
const DEFAULT = "default";

/** 制作人档案：存在后端、跟着用户走，所有设备共用。档案和没保存的草稿挂在设置的 layout 上（SettingsValues），
 * 切到别的类别再回来草稿还在。 */
export function ProducerProfileSettings() {
  const { profile, profileFailure, retryProfile, editProfile, profileSaved } = useSettingsValues();
  const saved = profile?.saved ?? null;
  const draft = profile?.draft ?? null;
  const [saveFailure, setSaveFailure] = useState<Failure | null>(null);
  const failure = saveFailure ?? profileFailure;
  const [saving, setSaving] = useState(false);
  // 点过保存、被半个生日挡下之后才提示补日期；之后再动月或日，提示收起，等下次保存再判断。
  const [triedToSave, setTriedToSave] = useState(false);
  const [detected, setDetected] = useState("");
  const [timezones, setTimezones] = useState<string[]>([]);
  const id = useId();

  useEffect(() => {
    setDetected(detectTimezone());
    setTimezones(listTimezones());
  }, []);

  // 上次没读到档案（切到别的类别再回来）：打开档案页时再读一次，只在打开时。
  useEffect(() => {
    if (profileFailure) retryProfile();
  }, []);

  // 别的设备上存的时区，这个浏览器可能不认识；照样放进选项里。
  const timezoneOptions = useMemo(
    () => [
      { value: DEFAULT, label: t.timezoneAuto(detected || t.timezoneUnknown) },
      ...(draft?.timezone && !timezones.includes(draft.timezone) ? [draft.timezone] : []).map(asOption),
      ...timezones.map(asOption),
    ],
    [detected, draft?.timezone, timezones],
  );
  const timezoneLabels = useMemo(
    () => new Map(timezoneOptions.map((option) => [option.value, option.label])),
    [timezoneOptions],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    if (missingBirthDay(draft)) {
      setTriedToSave(true);
      return;
    }
    setTriedToSave(false);
    setSaving(true);
    setSaveFailure(null);
    try {
      profileSaved(toDraft(await saveProfile(fromDraft(draft))));
    } catch (e) {
      setSaveFailure(toFailure(e));
    } finally {
      setSaving(false);
    }
  }

  if (!draft || !saved) {
    return (
      <SettingsSection>
        {failure ? (
          <FailureNotice failure={failure} />
        ) : (
          <p className="text-body text-muted-foreground">{copy.settings.loading}</p>
        )}
      </SettingsSection>
    );
  }

  const update = (change: Partial<Draft>) => editProfile({ ...draft, ...change });
  const dirty = !sameDraft(draft, saved);
  const showDayMissing = triedToSave && missingBirthDay(draft);
  const monthOptions = [
    { value: DEFAULT, label: t.birthdayUnset },
    ...range(12).map((month) => ({ value: String(month), label: t.monthOption(String(month)) })),
  ];
  const dayOptions = [
    { value: DEFAULT, label: t.birthdayUnset },
    ...(draft.birthMonth === null ? [] : range(daysInMonth(draft.birthMonth))).map((day) => ({
      value: String(day),
      label: t.dayOption(String(day)),
    })),
  ];
  const genderOptions = [
    { value: DEFAULT, label: t.genderDefault },
    { value: "male", label: t.male },
    { value: "female", label: t.female },
  ];

  return (
    <SettingsSection>
      <form onSubmit={submit}>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor={`${id}-address`}>{t.formOfAddress}</FieldLabel>
            <Input
              id={`${id}-address`}
              value={draft.formOfAddress}
              onChange={(event) => update({ formOfAddress: clampFormOfAddress(event.target.value) })}
              placeholder={t.formOfAddressPlaceholder}
              autoComplete="off"
            />
            <FieldDescription>{t.formOfAddressHint}</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-gender`}>{t.gender}</FieldLabel>
            <Select
              items={genderOptions}
              value={draft.gender || DEFAULT}
              onValueChange={(value) => update({ gender: value === DEFAULT || !value ? "" : (value as Gender) })}
            >
              <SelectTrigger id={`${id}-gender`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {genderOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldDescription>{t.genderHint}</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-timezone`}>{t.timezone}</FieldLabel>
            <Combobox
              items={timezoneOptions.map((option) => option.value)}
              itemToStringLabel={(value: string) => timezoneLabels.get(value) ?? value}
              value={draft.timezone || DEFAULT}
              onValueChange={(value) => update({ timezone: value === DEFAULT || !value ? "" : value })}
            >
              <ComboboxSelectTrigger id={`${id}-timezone`} className="w-full" />
              <ComboboxContent>
                <ComboboxInput showTrigger={false} placeholder={t.timezoneSearch} />
                <ComboboxList>
                  {(value: string) => (
                    <ComboboxItem key={value} value={value}>
                      {timezoneLabels.get(value) ?? value}
                    </ComboboxItem>
                  )}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
            <FieldDescription>{t.timezoneHint}</FieldDescription>
          </Field>

          <Field aria-labelledby={`${id}-birthday`} data-invalid={showDayMissing || undefined}>
            <FieldLabel id={`${id}-birthday`} htmlFor={`${id}-birth-month`}>
              {t.birthday}
            </FieldLabel>
            <div className="grid grid-cols-2 gap-3">
              <Select
                items={monthOptions}
                value={draft.birthMonth === null ? DEFAULT : String(draft.birthMonth)}
                onValueChange={(value) => {
                  editProfile(chooseBirthMonth(draft, fromBirthdayOption(value)));
                  setTriedToSave(false);
                }}
              >
                <SelectTrigger id={`${id}-birth-month`} aria-label={t.birthMonth} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {monthOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                items={dayOptions}
                value={draft.birthDay === null ? DEFAULT : String(draft.birthDay)}
                onValueChange={(value) => {
                  update({ birthDay: fromBirthdayOption(value) });
                  setTriedToSave(false);
                }}
                disabled={draft.birthMonth === null}
              >
                <SelectTrigger
                  aria-label={t.birthDay}
                  aria-invalid={showDayMissing || undefined}
                  aria-describedby={showDayMissing ? `${id}-birthday-error` : undefined}
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {dayOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <FieldDescription>{t.birthdayHint}</FieldDescription>
            {showDayMissing && <FieldError id={`${id}-birthday-error`}>{t.birthDayMissing}</FieldError>}
          </Field>

          {failure && <FailureNotice failure={failure} />}

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!dirty || saving}>
              {saving && <Spinner data-icon="inline-start" />}
              {t.save}
            </Button>
            <p role="status" className="text-subtitle text-muted-foreground">
              {dirty ? t.unsaved : t.saved}
            </p>
          </div>
        </FieldGroup>
      </form>
    </SettingsSection>
  );
}

function asOption(zone: string) {
  return { value: zone, label: zone };
}

/** 1 到 n。 */
function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i + 1);
}

/** 生日选择框的值换回草稿里的数字，「不填」是 null。 */
function fromBirthdayOption(value: string | null): number | null {
  return value === DEFAULT || !value ? null : Number(value);
}
