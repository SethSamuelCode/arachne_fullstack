"use client";

import { Menu } from "lucide-react";
import { Button } from "@/components/ui";
import { useSidebarStore } from "@/stores";

export function MobileMenuBar() {
  const { toggle } = useSidebarStore();

  return (
    <div className="sticky top-0 z-40 flex h-10 items-center border-b bg-background px-2 md:hidden">
      <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={toggle}>
        <Menu className="h-4 w-4" />
        <span className="sr-only">Open menu</span>
      </Button>
    </div>
  );
}
