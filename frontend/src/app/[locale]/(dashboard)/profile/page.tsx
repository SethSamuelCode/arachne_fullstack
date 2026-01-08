
"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@/hooks";
import { useAuthStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import type { User as UserProfile } from "@/types";
import { Button, Card, Input, Label, Badge } from "@/components/ui";
import { ThemeToggle } from "@/components/theme";
import { User, Mail, Calendar, Shield, Settings, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ProfilePage() {
  const { user, isAuthenticated, logout } = useAuth();
  const setUser = useAuthStore((state) => state.setUser);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");

  useEffect(() => {
    if (user) {
      setSystemPrompt(user.default_system_prompt || "");
    }
  }, [user]);

  const handleSave = async () => {
    if (!user) return;
    setIsSaving(true);
    try {
      const updatedUser = await apiClient.patch<UserProfile>("/users/me", {
        default_system_prompt: systemPrompt,
      });
      // Merge the response (which is the updated user) into the store
      setUser({ ...user, ...updatedUser }); 
      setIsEditing(false);
    } catch (error) {
      console.error("Failed to update profile", error);
    } finally {
      setIsSaving(false);
    }
  };

  if (!isAuthenticated || !user) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Card className="p-6 sm:p-8 text-center mx-4">
          <p className="text-muted-foreground">Please log in to view your profile.</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-4xl">
      <div className="mb-6 sm:mb-8">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Profile</h1>
        <p className="text-sm sm:text-base text-muted-foreground">
          Manage your account settings and preferences
        </p>
      </div>

      <div className="grid gap-4 sm:gap-6">
        <Card className="p-4 sm:p-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-center gap-3 sm:gap-4">
              <div className="flex h-12 w-12 sm:h-16 sm:w-16 items-center justify-center rounded-full bg-primary/10 shrink-0">
                <User className="h-6 w-6 sm:h-8 sm:w-8 text-primary" />
              </div>
              <div className="min-w-0">
                <h2 className="text-lg sm:text-xl font-semibold truncate">{user.email}</h2>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  {user.is_superuser && (
                    <Badge variant="secondary">
                      <Shield className="mr-1 h-3 w-3" />
                      Admin
                    </Badge>
                  )}
                  {user.is_active && (
                    <Badge variant="outline" className="text-green-600">
                      Active
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsEditing(!isEditing)}
              className="self-start h-10"
            >
              <Settings className="mr-2 h-4 w-4" />
              {isEditing ? "Cancel" : "Edit"}
            </Button>
          </div>
        </Card>

        <Card className="p-4 sm:p-6">
          <h3 className="mb-4 text-base sm:text-lg font-semibold">Account Information</h3>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="email" className="flex items-center gap-2 text-sm">
                <Mail className="h-4 w-4 text-muted-foreground" />
                Email Address
              </Label>
              <Input
                id="email"
                type="email"
                value={user.email}
                disabled={!isEditing}
                className={!isEditing ? "bg-muted" : ""}
              />
            </div>

            {user.created_at && (
              <div className="flex items-center gap-2 text-xs sm:text-sm text-muted-foreground">
                <Calendar className="h-4 w-4 shrink-0" />
                <span>Member since {new Date(user.created_at).toLocaleDateString()}</span>
              </div>
            )}

            <div className="grid gap-2 pt-2 border-t mt-2">
              <Label htmlFor="systemPrompt" className="flex items-center gap-2 text-sm">
                <MessageSquare className="h-4 w-4 text-muted-foreground" />
                Default System Prompt
              </Label>
              <textarea
                id="systemPrompt"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                disabled={!isEditing}
                className={cn(
                  "flex min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm resize-y",
                  !isEditing && "bg-muted"
                )}
                placeholder="You are a helpful AI assistant..."
              />
              <p className="text-xs text-muted-foreground">
                This prompt will be used as the default for all new conversations.
              </p>
            </div>
          </div>

          {isEditing && (
            <div className="mt-4 flex flex-col sm:flex-row justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setIsEditing(false);
                  setSystemPrompt(user.default_system_prompt || "");
                }}
                className="h-10"
                disabled={isSaving}
              >
                Cancel
              </Button>
              <Button className="h-10" onClick={handleSave} disabled={isSaving}>
                {isSaving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          )}
        </Card>

        <Card className="p-4 sm:p-6">
          <h3 className="mb-4 text-base sm:text-lg font-semibold">Preferences</h3>
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="font-medium text-sm sm:text-base">Theme</p>
              <p className="text-xs sm:text-sm text-muted-foreground">
                Choose your preferred color scheme
              </p>
            </div>
            <ThemeToggle variant="dropdown" />
          </div>
        </Card>

        <Card className="border-destructive/50 p-4 sm:p-6">
          <h3 className="mb-4 text-base sm:text-lg font-semibold text-destructive">
            Danger Zone
          </h3>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="font-medium text-sm sm:text-base">Sign out</p>
              <p className="text-xs sm:text-sm text-muted-foreground">
                Sign out from your account on this device
              </p>
            </div>
            <Button variant="destructive" onClick={logout} className="h-10 self-start sm:self-auto">
              Sign Out
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
