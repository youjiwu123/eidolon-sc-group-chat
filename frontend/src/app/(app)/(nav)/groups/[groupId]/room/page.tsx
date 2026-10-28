"use client";

import { useParams } from "next/navigation";

import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { GroupRoom } from "@/components/conversations/GroupRoom";
import { Spinner } from "@/components/ui/spinner";

/** 一个群的语音房：对着麦克风说话，她们用各自的声音接话。 */
export default function GroupRoomPage() {
  const { groupId } = useParams<{ groupId: string }>();
  const { characters } = useDirectory();
  if (characters === null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    );
  }
  return <GroupRoom groupId={groupId} characters={characters} />;
}
