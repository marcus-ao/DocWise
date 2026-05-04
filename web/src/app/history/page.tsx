import { ConversationList } from "@/components/history/conversation-list"

export default function HistoryPage() {
  return (
    <ConversationList
      title="历史对话"
      description="查看、整理和管理已落库的 Agent 会话。"
      archived={false}
      backHref="/chat"
      backLabel="返回对话"
      emptyText="暂时没有历史对话。完成一轮真实问答后，这里会自动出现记录。"
    />
  )
}

