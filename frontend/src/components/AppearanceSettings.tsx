"use client";

import { useId } from "react";

import { SettingsSection } from "@/components/app/SettingsSection";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { Field, FieldContent, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/i18n";

const t = copy.settings.appearance;

/**
 * 设置「外观」：「SCSP 头像」（GLOSSARY.md「SCSP 头像」）和「对话页显示立绘」（对话页右下角站着的小人，
 * DESIGN.md「对话页的立绘小人」），都记在这台设备上、按用户分开。
 * 值由导航外壳持有，一拨开关，登录后应用里的头像、对话页上的小人和一级「外观」的摘要都马上跟着换。
 */
export function AppearanceSettings() {
  const { account, appearance, changeAppearance } = useDirectory();
  const id = useId();

  if (!account) return null;

  return (
    <SettingsSection>
      <FieldGroup>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor={`${id}-scsp`}>{t.scspAvatars}</FieldLabel>
          </FieldContent>
          <Switch
            id={`${id}-scsp`}
            checked={appearance.scspAvatars}
            onCheckedChange={(scspAvatars) => changeAppearance({ ...appearance, scspAvatars })}
          />
        </Field>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor={`${id}-chat-stand`}>{t.chatStand}</FieldLabel>
          </FieldContent>
          <Switch
            id={`${id}-chat-stand`}
            checked={appearance.chatStand}
            onCheckedChange={(chatStand) => changeAppearance({ ...appearance, chatStand })}
          />
        </Field>
      </FieldGroup>
    </SettingsSection>
  );
}
