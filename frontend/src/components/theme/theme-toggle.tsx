
"use client";

import { useEffect, useState } from "react";
import { Moon, Sun, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useThemeStore, Theme, getResolvedTheme } from "@/stores/theme-store";
import { cn } from "@/lib/utils";

interface ThemeToggleProps {
  variant?: "icon" | "dropdown" | "sidebar";
  className?: string;
  isCollapsed?: boolean;
}

export function ThemeToggle({ variant = "icon", className, isCollapsed = false }: ThemeToggleProps) {
  const { theme, setTheme } = useThemeStore();
  const [mounted, setMounted] = useState(false);

  // Prevent hydration mismatch by only rendering after mount
  useEffect(() => {
    setMounted(true);
  }, []);

  const resolvedTheme = getResolvedTheme(theme);

  const cycleTheme = () => {
    const themes: Theme[] = ["light", "dark", "system"];
    const currentIndex = themes.indexOf(theme);
    const nextIndex = (currentIndex + 1) % themes.length;
    setTheme(themes[nextIndex]);
  };

  const getThemeIcon = () => {
    switch (theme) {
      case "dark":
        return <Moon className="h-5 w-5 shrink-0" />;
      case "light":
        return <Sun className="h-5 w-5 shrink-0" />;
      default:
        return <Monitor className="h-5 w-5 shrink-0" />;
    }
  };

  const getThemeLabel = () => {
    switch (theme) {
      case "dark":
        return "Dark";
      case "light":
        return "Light";
      default:
        return "System";
    }
  };

  // Render placeholder during SSR to prevent hydration mismatch
  if (!mounted) {
    if (variant === "sidebar") {
      return (
        <button
          className={cn(
            "flex w-full items-center rounded-lg text-sm font-medium transition-colors",
            "min-h-[44px]",
            isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
            "text-muted-foreground",
            className
          )}
          aria-label="Toggle theme"
        >
          <Sun className="h-5 w-5 shrink-0" />
          {!isCollapsed && <span className="whitespace-nowrap">Light</span>}
        </button>
      );
    }
    return (
      <Button
        variant="ghost"
        size="icon"
        className={className}
        aria-label="Toggle theme"
      >
        <Sun className="h-5 w-5" />
      </Button>
    );
  }

  if (variant === "sidebar") {
    return (
      <button
        onClick={cycleTheme}
        title={isCollapsed ? `Theme: ${getThemeLabel()}` : undefined}
        className={cn(
          "flex w-full items-center rounded-lg text-sm font-medium transition-colors",
          "min-h-[44px]",
          isCollapsed ? "justify-center p-2" : "gap-3 px-3 py-3",
          "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground",
          className
        )}
        aria-label={`Switch theme (current: ${theme})`}
      >
        {getThemeIcon()}
        {!isCollapsed && <span className="whitespace-nowrap">{getThemeLabel()}</span>}
      </button>
    );
  }

  if (variant === "icon") {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={cycleTheme}
        className={className}
        aria-label={`Switch theme (current: ${theme})`}
        title={`Theme: ${theme}`}
      >
        {getThemeIcon()}
      </Button>
    );
  }

  return (
    <div className={cn("flex gap-1", className)}>
      <Button
        variant={theme === "light" ? "default" : "ghost"}
        size="icon"
        onClick={() => setTheme("light")}
        aria-label="Light mode"
        title="Light mode"
      >
        <Sun className="h-4 w-4" />
      </Button>
      <Button
        variant={theme === "dark" ? "default" : "ghost"}
        size="icon"
        onClick={() => setTheme("dark")}
        aria-label="Dark mode"
        title="Dark mode"
      >
        <Moon className="h-4 w-4" />
      </Button>
      <Button
        variant={theme === "system" ? "default" : "ghost"}
        size="icon"
        onClick={() => setTheme("system")}
        aria-label="System theme"
        title="System theme"
      >
        <Monitor className="h-4 w-4" />
      </Button>
    </div>
  );
}
