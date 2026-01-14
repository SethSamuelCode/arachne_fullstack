"use client";

import Link from "next/link";
import { useAuth } from "@/hooks";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import {
  LayoutDashboard,
  MessageSquare,
  Users,
  Settings,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useSidebarStore, useAuthStore } from "@/stores";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose, Button } from "@/components/ui";
import { ThemeToggle } from "@/components/theme";
import { LogOut, User } from "lucide-react";

const navigation = [
  { name: "Dashboard", href: ROUTES.DASHBOARD, icon: LayoutDashboard },
  { name: "Chat", href: ROUTES.CHAT, icon: MessageSquare },
];

const adminNavigation = [
  { name: "Users", href: ROUTES.ADMIN_USERS, icon: Users },
  { name: "Settings", href: ROUTES.ADMIN_SETTINGS, icon: Settings },
];

function NavLinks({
  onNavigate,
  isCollapsed = false,
}: {
  onNavigate?: () => void;
  isCollapsed?: boolean;
}) {
  const { user, isAuthenticated, logout } = useAuth();
  const pathname = usePathname();
  const isAdmin = user?.role === "admin" || user?.is_superuser;

  return (
    <nav className={cn("flex flex-1 flex-col", isCollapsed ? "p-2" : "p-4")}>
      <div className="space-y-1">
      {navigation.map((item) => {
        const isActive = pathname === item.href;
        return (
          <Link
            key={item.name}
            href={item.href}
            onClick={onNavigate}
            title={isCollapsed ? item.name : undefined}
            className={cn(
              "flex items-center rounded-lg text-sm font-medium transition-colors",
              "min-h-[44px]",
              isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
              isActive
                ? "bg-secondary text-secondary-foreground"
                : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground"
            )}
          >
            <item.icon className="h-5 w-5 shrink-0" />
            {!isCollapsed && <span className="whitespace-nowrap">{item.name}</span>}
          </Link>
        );
      })}

      {isAdmin && (
        <>
          {!isCollapsed && (
            <div className="pt-4 pb-2">
              <p className="px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Admin
              </p>
            </div>
          )}
          {isCollapsed && <div className="my-2 border-t" />}
          {adminNavigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={onNavigate}
                title={isCollapsed ? item.name : undefined}
                className={cn(
                  "flex items-center rounded-lg text-sm font-medium transition-colors",
                  "min-h-[44px]",
                  isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
                  isActive
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground"
                )}
              >
                <item.icon className="h-5 w-5 shrink-0" />
                {!isCollapsed && <span className="whitespace-nowrap">{item.name}</span>}
              </Link>
            );
          })}
        </>
      )}
      </div>

      {/* Spacer to push user section to bottom */}
      <div className="flex-1" />

      {/* User section */}
      <div className={cn("border-t mt-2 pt-2 space-y-1", isCollapsed ? "px-2" : "")}>
        <ThemeToggle variant="sidebar" isCollapsed={isCollapsed} />
        {isAuthenticated ? (
          <>
            <Link
              href={ROUTES.PROFILE}
              onClick={onNavigate}
              title={isCollapsed ? user?.email : undefined}
              className={cn(
                "flex items-center rounded-lg text-sm font-medium transition-colors",
                "min-h-[44px]",
                isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
                "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground"
              )}
            >
              <User className="h-5 w-5 shrink-0" />
              {!isCollapsed && (
                <span className="whitespace-nowrap truncate max-w-32">{user?.email}</span>
              )}
            </Link>
            <button
              onClick={() => {
                logout();
                onNavigate?.();
              }}
              title={isCollapsed ? "Logout" : undefined}
              className={cn(
                "flex w-full items-center rounded-lg text-sm font-medium transition-colors",
                "min-h-[44px]",
                isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
                "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground"
              )}
            >
              <LogOut className="h-5 w-5 shrink-0" />
              {!isCollapsed && <span className="whitespace-nowrap">Logout</span>}
            </button>
          </>
        ) : (
          <>
            <Link
              href={ROUTES.LOGIN}
              onClick={onNavigate}
              title={isCollapsed ? "Login" : undefined}
              className={cn(
                "flex items-center rounded-lg text-sm font-medium transition-colors",
                "min-h-[44px]",
                isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
                "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground"
              )}
            >
              <User className="h-5 w-5 shrink-0" />
              {!isCollapsed && <span className="whitespace-nowrap">Login</span>}
            </Link>
          </>
        )}
      </div>
    </nav>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center border-b px-4">
        <Link
          href={ROUTES.HOME}
          className="flex items-center gap-2 font-semibold"
          onClick={onNavigate}
        >
          <span>{"Arachne"}</span>
        </Link>
      </div>
      <NavLinks onNavigate={onNavigate} />
    </div>
  );
}

function DesktopSidebar() {
  const { isCollapsed, toggleCollapsed } = useSidebarStore();

  return (
    <aside
      className={cn(
        "hidden shrink-0 border-r bg-background md:flex flex-col transition-all duration-200 overflow-hidden",
        isCollapsed ? "w-14" : "w-64"
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center border-b",
          isCollapsed ? "justify-center px-2" : "px-4"
        )}
      >
        <Link
          href={ROUTES.HOME}
          className="flex items-center gap-2 font-semibold"
          title={isCollapsed ? "Arachne" : undefined}
        >
          {isCollapsed ? (
            <span className="text-lg">🕷️</span>
          ) : (
            <span className="whitespace-nowrap">{"Arachne"}</span>
          )}
        </Link>
      </div>

      <NavLinks isCollapsed={isCollapsed} />

      <div className={cn("border-t p-2", isCollapsed ? "px-2" : "")}>
        <button
          onClick={toggleCollapsed}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "flex w-full items-center rounded-lg text-sm font-medium transition-colors",
            "min-h-[44px]",
            isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
            "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground"
          )}
        >
          {isCollapsed ? (
            <ChevronRight className="h-5 w-5 shrink-0" />
          ) : (
            <>
              <ChevronLeft className="h-5 w-5 shrink-0" />
              {/* <span className="whitespace-nowrap">Collapse</span> */}
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

export function Sidebar() {
  const { isOpen, close } = useSidebarStore();

  return (
    <>
      <DesktopSidebar />

      <Sheet open={isOpen} onOpenChange={close}>
        <SheetContent side="left" className="w-72 p-0">
          <SheetHeader className="h-14 px-4">
            <SheetTitle>{"arachne_fullstack"}</SheetTitle>
            <SheetClose onClick={close} />
          </SheetHeader>
          <NavLinks onNavigate={close} />
        </SheetContent>
      </Sheet>
    </>
  );
}
