import { ChatConsole } from "@/components/chat/chat-console"

export default function DynamicChatPage({ params }: { params: { id: string } }) {
  return <ChatConsole conversationId={params.id} />
}
