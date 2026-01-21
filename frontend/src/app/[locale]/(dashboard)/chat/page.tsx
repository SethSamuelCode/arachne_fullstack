
"use client";

import { ChatContainer, ConversationSidebar, LocalConversationSidebar, ChatSidebarToggle } from "@/components/chat";
import { useAuthStore } from "@/stores";

export default function ChatPage() {
  const { isAuthenticated } = useAuthStore();

  const Sidebar = isAuthenticated ? ConversationSidebar : LocalConversationSidebar;

  return (
    <div className="flex h-full -m-3 sm:-m-6 sm:pb-0">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex h-10 items-center gap-2 px-2 border-b md:hidden">
          <ChatSidebarToggle />
          <span className="text-sm font-medium">Chat</span>
        </div>
        <div className="flex-1 min-h-0">
          <ChatContainer />
        </div>
      </div>
    </div>
  );
}
