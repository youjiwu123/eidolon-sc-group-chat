"use client";

import { useParams } from "next/navigation";

import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { GroupCallStage } from "@/components/conversations/GroupCallStage";
import { Spinner } from "@/components/ui/spinner";

/** 一个群的语音通话：几个人同时站在几个格子里。 */
export default function GroupCallPage() {
  const { groupId } = useParams<{ groupId: string }>();
  const { characters } = useDirectory();
  if (characters === null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    );
  }
  return <GroupCallStage groupId={groupId} characters={characters} />;
}
