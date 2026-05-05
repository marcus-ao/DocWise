import { ConversationList } from "@/components/history/conversation-list"

export default function ArchivePage() {
  return (
    <ConversationList
      title="存档对话"
      description="集中查看已归档的会话，必要时可以恢复到历史列表。"
      archived={true}
      backHref="/"
      backLabel="返回控制台"
      emptyText="暂时没有已存档的对话。"
    />
  )
}

