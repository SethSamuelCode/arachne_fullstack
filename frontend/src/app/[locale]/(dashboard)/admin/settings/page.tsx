"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
  Button,
} from "@/components/ui";
import {
  Settings,
  UserPlus,
  UserMinus,
  Loader2,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";

interface RuntimeSettings {
  registration_enabled: boolean;
}

export default function AdminSettingsPage() {
  const { user, isAuthenticated } = useAuth();
  const router = useRouter();
  
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isAdmin = user?.role === "admin" || user?.is_superuser;

  const fetchSettings = useCallback(async () => {
    if (!isAdmin) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const data = await apiClient.get<RuntimeSettings>("/admin/settings");
      setSettings(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to fetch settings");
      }
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    // Middleware handles auth/admin redirects - just fetch data
    if (isAdmin) {
      fetchSettings();
    }
  }, [isAdmin, fetchSettings]);

  const handleToggleRegistration = async () => {
    if (!settings) return;
    
    setSaving(true);
    setError(null);
    setSuccess(null);
    
    try {
      const newValue = !settings.registration_enabled;
      const data = await apiClient.patch<RuntimeSettings>("/admin/settings", {
        registration_enabled: newValue,
      });
      setSettings(data);
      setSuccess(
        newValue
          ? "Registration has been enabled"
          : "Registration has been disabled"
      );
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to update settings");
      }
    } finally {
      setSaving(false);
    }
  };

  if (!isAuthenticated || !isAdmin) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Card className="p-6 text-center">
          <AlertTriangle className="mx-auto h-12 w-12 text-yellow-500 mb-4" />
          <p className="text-muted-foreground">
            You don&apos;t have permission to access this page.
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-2">
          <Settings className="h-8 w-8" />
          Admin Settings
        </h1>
        <p className="text-sm sm:text-base text-muted-foreground">
          Configure application-wide settings
        </p>
      </div>

      {/* Success Message */}
      {success && (
        <Card className="p-4 border-green-500 bg-green-50 dark:bg-green-950/20">
          <div className="flex items-center gap-2 text-green-700 dark:text-green-400">
            <CheckCircle className="h-5 w-5" />
            <p>{success}</p>
          </div>
        </Card>
      )}

      {/* Error Message */}
      {error && (
        <Card className="p-4 border-destructive">
          <p className="text-destructive">{error}</p>
        </Card>
      )}

      {/* Registration Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {settings?.registration_enabled ? (
              <UserPlus className="h-5 w-5 text-green-500" />
            ) : (
              <UserMinus className="h-5 w-5 text-red-500" />
            )}
            User Registration
          </CardTitle>
          <CardDescription>
            Control whether new users can register for accounts
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading settings...
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 rounded-lg border">
                <div>
                  <p className="font-medium">Public Registration</p>
                  <p className="text-sm text-muted-foreground">
                    {settings?.registration_enabled
                      ? "New users can create accounts via the registration page"
                      : "Registration is disabled. Only admins can create new users."}
                  </p>
                </div>
                <Button
                  variant={settings?.registration_enabled ? "destructive" : "default"}
                  onClick={handleToggleRegistration}
                  disabled={saving}
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : settings?.registration_enabled ? (
                    <UserMinus className="h-4 w-4 mr-2" />
                  ) : (
                    <UserPlus className="h-4 w-4 mr-2" />
                  )}
                  {settings?.registration_enabled ? "Disable" : "Enable"}
                </Button>
              </div>

              <p className="text-xs text-muted-foreground">
                Note: This setting takes effect immediately. When disabled, the
                registration page will show a message that registration is not
                available.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
