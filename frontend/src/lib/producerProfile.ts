// 设置页里编辑制作人档案用的草稿：空白表示这一项沿用默认（GLOSSARY.md「制作人档案」），
// 保存时存成 null 交回后端。

import type { Gender, ProducerProfile } from "@/lib/api";

/** 和后端的 MAX_FORM_OF_ADDRESS_LENGTH 一致，按字数（Python 的 len）计算。 */
export const MAX_FORM_OF_ADDRESS = 20;

/** 生日的月和日分开选，没选的是 null；只选了月、没选日的草稿不能保存（见 missingBirthDay）。 */
export type Draft = {
  formOfAddress: string;
  gender: Gender | "";
  timezone: string;
  birthMonth: number | null;
  birthDay: number | null;
};

export function toDraft(profile: ProducerProfile): Draft {
  return {
    formOfAddress: profile.form_of_address ?? "",
    gender: profile.gender ?? "",
    timezone: profile.timezone ?? "",
    birthMonth: profile.birthday?.month ?? null,
    birthDay: profile.birthday?.day ?? null,
  };
}

/** 先用 missingBirthDay 挡下半个生日；传进来只选了月的草稿会抛错，不会把它存成清空。
 * 模式不在这张表单里，单独保存，所以这里不带 special_mode。 */
export function fromDraft(draft: Draft): Omit<ProducerProfile, "special_mode"> {
  if (missingBirthDay(draft)) throw new Error("birthday has a month but no day");
  return {
    form_of_address: draft.formOfAddress.trim() || null,
    gender: draft.gender || null,
    timezone: draft.timezone || null,
    birthday:
      draft.birthMonth !== null && draft.birthDay !== null
        ? { month: draft.birthMonth, day: draft.birthDay }
        : null,
  };
}

/** 选生日的月份。原来选的日期在新月份里不存在时清掉，让用户重选，不悄悄换成另一天；
 * 月份改成不填时日期也一起清掉。 */
export function chooseBirthMonth(draft: Draft, month: number | null): Draft {
  const keepDay = month !== null && draft.birthDay !== null && draft.birthDay <= daysInMonth(month);
  return { ...draft, birthMonth: month, birthDay: keepDay ? draft.birthDay : null };
}

/** 只选了生日的月、还没选日：这样的草稿不能保存，要提示补上日期。 */
export function missingBirthDay(draft: Draft): boolean {
  return draft.birthMonth !== null && draft.birthDay === null;
}

/** 两份草稿存下去是否一样（称呼两端的空白保存时会去掉，不算改动）。 */
export function sameDraft(a: Draft, b: Draft): boolean {
  return (
    a.formOfAddress.trim() === b.formOfAddress.trim() &&
    a.gender === b.gender &&
    a.timezone === b.timezone &&
    a.birthMonth === b.birthMonth &&
    a.birthDay === b.birthDay
  );
}

/** 称呼最多 MAX_FORM_OF_ADDRESS 个字；按字截，不会把一个字切成两半。 */
export function clampFormOfAddress(value: string): string {
  const chars = Array.from(value);
  return chars.length > MAX_FORM_OF_ADDRESS ? chars.slice(0, MAX_FORM_OF_ADDRESS).join("") : value;
}

/** 生日这个月最多到几日。不含年份，2 月按闰年算到 29 日（和后端的校验一致）。 */
export function daysInMonth(month: number): number {
  return new Date(Date.UTC(2000, month, 0)).getUTCDate();
}
