"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import type { User, UserRole } from "@/types";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Button,
  Input,
  Label,
  Badge,
} from "@/components/ui";
import {
  Search,
  Trash2,
  RotateCcw,
  Shield,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertTriangle,
  Plus,
  X,
  Pencil,
  KeyRound,
  Eye,
  EyeOff,
} from "lucide-react";

interface PaginatedUsers {
  items: User[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

interface CreateUserForm {
  email: string;
  password: string;
  full_name: string;
  role: UserRole;
}

export default function AdminUsersPage() {
  const { user, isAuthenticated } = useAuth();
  const router = useRouter();
  
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Pagination
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  
  // Filters
  const [search, setSearch] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [roleFilter, setRoleFilter] = useState<string>("");
  
  // Action states
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  
  // Create user modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState<CreateUserForm>({
    email: "",
    password: "",
    full_name: "",
    role: "user",
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  
  // Edit role
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [editRole, setEditRole] = useState<UserRole>("user");

  // Reset password modal
  const [resetPasswordUserId, setResetPasswordUserId] = useState<string | null>(null);
  const [resetPasswordEmail, setResetPasswordEmail] = useState<string>("");
  const [newPassword, setNewPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  const isAdmin = user?.role === "admin" || user?.is_superuser;

  const fetchUsers = useCallback(async () => {
    if (!isAdmin) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const params: Record<string, string> = {
        page: String(page),
        size: "20",
      };
      
      if (includeDeleted) params.include_deleted = "true";
      if (search) params.search = search;
      if (roleFilter) params.role = roleFilter;
      
      const data = await apiClient.get<PaginatedUsers>("/admin/users", { params });
      setUsers(data.items);
      setTotalPages(data.pages);
      setTotal(data.total);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to fetch users");
      }
    } finally {
      setLoading(false);
    }
  }, [isAdmin, page, includeDeleted, search, roleFilter]);

  useEffect(() => {
    if (!isAuthenticated) {
      router.push(ROUTES.LOGIN);
      return;
    }
    
    if (user && !isAdmin) {
      router.push(ROUTES.DASHBOARD);
      return;
    }
    
    fetchUsers();
  }, [isAuthenticated, user, isAdmin, router, fetchUsers]);

  const handleDelete = async (userId: string) => {
    if (confirmDelete !== userId) {
      setConfirmDelete(userId);
      return;
    }
    
    setActionLoading(userId);
    try {
      await apiClient.delete(`/admin/users/${userId}`);
      await fetchUsers();
    } catch (err) {
      console.error("Failed to delete user:", err);
    } finally {
      setActionLoading(null);
      setConfirmDelete(null);
    }
  };

  const handleRestore = async (userId: string) => {
    setActionLoading(userId);
    try {
      await apiClient.post(`/admin/users/${userId}/restore`);
      await fetchUsers();
    } catch (err) {
      console.error("Failed to restore user:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchUsers();
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateLoading(true);
    setCreateError(null);
    
    try {
      await apiClient.post("/admin/users", createForm);
      setShowCreateModal(false);
      setCreateForm({ email: "", password: "", full_name: "", role: "user" });
      await fetchUsers();
    } catch (err) {
      if (err instanceof ApiError) {
        setCreateError(err.message);
      } else {
        setCreateError("Failed to create user");
      }
    } finally {
      setCreateLoading(false);
    }
  };

  const handleEditRole = async (userId: string) => {
    setActionLoading(userId);
    try {
      await apiClient.patch(`/admin/users/${userId}`, { role: editRole });
      setEditingUserId(null);
      await fetchUsers();
    } catch (err) {
      console.error("Failed to update user role:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const startEditRole = (u: User) => {
    setEditingUserId(u.id);
    setEditRole((u.role as UserRole) || "user");
  };

  const openResetPasswordModal = (u: User) => {
    setResetPasswordUserId(u.id);
    setResetPasswordEmail(u.email);
    setNewPassword("");
    setShowPassword(false);
    setResetError(null);
  };

  const closeResetPasswordModal = () => {
    setResetPasswordUserId(null);
    setResetPasswordEmail("");
    setNewPassword("");
    setShowPassword(false);
    setResetError(null);
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetPasswordUserId) return;

    setResetLoading(true);
    setResetError(null);

    try {
      await apiClient.patch(`/admin/users/${resetPasswordUserId}`, {
        password: newPassword,
      });
      closeResetPasswordModal();
    } catch (err) {
      if (err instanceof ApiError) {
        setResetError(err.message);
      } else {
        setResetError("Failed to reset password");
      }
    } finally {
      setResetLoading(false);
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold">User Management</h1>
          <p className="text-sm sm:text-base text-muted-foreground">
            Manage user accounts and permissions
          </p>
        </div>
        <Button onClick={() => setShowCreateModal(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add User
        </Button>
      </div>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-full max-w-md mx-4">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Create New User</CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowCreateModal(false);
                  setCreateError(null);
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleCreateUser} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={createForm.email}
                    onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                    required
                    disabled={createLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="full_name">Full Name</Label>
                  <Input
                    id="full_name"
                    type="text"
                    value={createForm.full_name}
                    onChange={(e) => setCreateForm({ ...createForm, full_name: e.target.value })}
                    disabled={createLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    value={createForm.password}
                    onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                    required
                    minLength={8}
                    disabled={createLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="role">Role</Label>
                  <select
                    id="role"
                    value={createForm.role}
                    onChange={(e) => setCreateForm({ ...createForm, role: e.target.value as UserRole })}
                    className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
                    disabled={createLoading}
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                {createError && (
                  <p className="text-sm text-destructive">{createError}</p>
                )}
                <div className="flex gap-2 justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setShowCreateModal(false);
                      setCreateError(null);
                    }}
                    disabled={createLoading}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={createLoading}>
                    {createLoading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      "Create User"
                    )}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Reset Password Modal */}
      {resetPasswordUserId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-full max-w-md mx-4">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Reset Password</CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={closeResetPasswordModal}
              >
                <X className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleResetPassword} className="space-y-4">
                <div className="space-y-2">
                  <Label>User</Label>
                  <p className="text-sm text-muted-foreground">{resetPasswordEmail}</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="new_password">New Password</Label>
                  <div className="relative">
                    <Input
                      id="new_password"
                      type={showPassword ? "text" : "password"}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      required
                      minLength={8}
                      disabled={resetLoading}
                      placeholder="Minimum 8 characters"
                      className="pr-10"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                      onClick={() => setShowPassword(!showPassword)}
                      disabled={resetLoading}
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <Eye className="h-4 w-4 text-muted-foreground" />
                      )}
                    </Button>
                  </div>
                </div>
                {resetError && (
                  <p className="text-sm text-destructive">{resetError}</p>
                )}
                <div className="flex gap-2 justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={closeResetPasswordModal}
                    disabled={resetLoading}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={resetLoading}>
                    {resetLoading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Resetting...
                      </>
                    ) : (
                      "Reset Password"
                    )}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters */}
      <Card className="p-4">
        <form onSubmit={handleSearch} className="flex flex-wrap gap-4">
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by email or name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>
          
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">All Roles</option>
            <option value="admin">Admin</option>
            <option value="user">User</option>
          </select>
          
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeDeleted}
              onChange={(e) => {
                setIncludeDeleted(e.target.checked);
                setPage(1);
              }}
              className="h-4 w-4 rounded border-input"
            />
            Show deleted
          </label>
          
          <Button type="submit" variant="default">
            Search
          </Button>
        </form>
      </Card>

      {/* Error State */}
      {error && (
        <Card className="p-4 border-destructive">
          <p className="text-destructive">{error}</p>
        </Card>
      )}

      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Users ({total})</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : users.length === 0 ? (
            <p className="text-center py-8 text-muted-foreground">
              No users found
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-3 px-2">Email</th>
                    <th className="text-left py-3 px-2">Name</th>
                    <th className="text-left py-3 px-2">Role</th>
                    <th className="text-left py-3 px-2">Status</th>
                    <th className="text-left py-3 px-2">Created</th>
                    <th className="text-right py-3 px-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-b hover:bg-muted/50">
                      <td className="py-3 px-2">
                        <span className="font-medium">{u.email}</span>
                      </td>
                      <td className="py-3 px-2">
                        {u.full_name || u.name || "-"}
                      </td>
                      <td className="py-3 px-2">
                        {editingUserId === u.id ? (
                          <div className="flex items-center gap-2">
                            <select
                              value={editRole}
                              onChange={(e) => setEditRole(e.target.value as UserRole)}
                              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                            >
                              <option value="user">User</option>
                              <option value="admin">Admin</option>
                            </select>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleEditRole(u.id)}
                              disabled={actionLoading === u.id}
                            >
                              {actionLoading === u.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                "Save"
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setEditingUserId(null)}
                            >
                              <X className="h-4 w-4" />
                            </Button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            {u.role === "admin" || u.is_superuser ? (
                              <Badge variant="secondary">
                                <Shield className="mr-1 h-3 w-3" />
                                Admin
                              </Badge>
                            ) : (
                              <Badge variant="outline">User</Badge>
                            )}
                            {u.id !== user?.id && u.is_active && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => startEditRole(u)}
                                className="h-6 w-6 p-0"
                              >
                                <Pencil className="h-3 w-3" />
                              </Button>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-2">
                        {u.is_active ? (
                          <Badge variant="outline" className="text-green-600 border-green-600">
                            Active
                          </Badge>
                        ) : (
                          <Badge variant="destructive">Deleted</Badge>
                        )}
                      </td>
                      <td className="py-3 px-2 text-muted-foreground">
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 px-2 text-right">
                        {u.id !== user?.id && (
                          <div className="flex justify-end gap-2">
                            {u.is_active ? (
                              <>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => openResetPasswordModal(u)}
                                  title="Reset Password"
                                >
                                  <KeyRound className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleDelete(u.id)}
                                  disabled={actionLoading === u.id}
                                  className={confirmDelete === u.id ? "text-destructive" : ""}
                                >
                                  {actionLoading === u.id ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <>
                                      <Trash2 className="h-4 w-4" />
                                      {confirmDelete === u.id ? "Confirm?" : ""}
                                    </>
                                  )}
                                </Button>
                              </>
                            ) : (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRestore(u.id)}
                                disabled={actionLoading === u.id}
                              >
                                {actionLoading === u.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <>
                                    <RotateCcw className="h-4 w-4 mr-1" />
                                    Restore
                                  </>
                                )}
                              </Button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4 border-t mt-4">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1 || loading}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages || loading}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
