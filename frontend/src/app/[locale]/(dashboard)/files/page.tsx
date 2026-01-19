"use client";

import { FilesSidebar } from "@/components/files";

export default function FilesPage() {
  return (
    <div className="flex h-full -m-3 sm:-m-6 sm:pb-0">
      <div className="flex-1 min-w-0 flex flex-col">
        <FilesSidebar />
      </div>
    </div>
  );
}
