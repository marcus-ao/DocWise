import { PageBack } from "@/components/layout/page-back"
import { ChatConsole } from "@/components/chat/chat-console"

export default function DynamicChatPage({
  params,
  searchParams,
}: {
  params: { id: string }
  searchParams?: { from?: string }
}) {
  const fromArchive = searchParams?.from === "archive"

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border bg-background px-6 py-4">
        <PageBack label={fromArchive ? "返回存档对话" : "返回历史对话"} href={fromArchive ? "/archive" : "/history"} />
      </div>
      <div className="min-h-0 flex-1">
        <ChatConsole conversationId={params.id} />
      </div>
    </div>
  )
}
