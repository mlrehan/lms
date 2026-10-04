"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { KeyRound, Lock, Trash2, Unlock } from "lucide-react";
import { api } from "@/lib/api/client";
import type {
  RoleResponse,
  UnlockResponse,
  UserResponse,
} from "@/lib/api/types";
import type { UserLoginAccessResponse } from "@/lib/api/types";
import { UserStatusValues } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Switch, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, Input} from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { ProfileForm } from "@/components/domain/profile-form";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatCalendarDate } from "@/lib/format/datetime";
import { segment } from "@/lib/api/client";

function RolesTab({ user }: { user: UserResponse }) {
  const { permissions } = useSession();
  const canEdit = permissions.has("user.update");
  const held = user.roles ?? [];
  const [selected, setSelected] = useState<string[]>(held);

  // Re-seed when the saved roles change underneath the checkboxes. Adjusting
  // during render rather than in an effect avoids rendering the stale set
  // once first, which on this screen would briefly show the old answer to
  // "what can this person do".
  const [seed, setSeed] = useState(user.roles);
  if (seed !== user.roles) {
    setSeed(user.roles);
    setSelected(held);
  }

  const { data: roles } = useQuery({
    queryKey: ["roles"],
    queryFn: () => api.get<RoleResponse[]>("/roles"),
    enabled: permissions.has("role.read"),
    staleTime: 5 * 60_000,
  });

  const save = useApiMutation<UserResponse, string[]>({
    mutationFn: (next) =>
      api.put<UserResponse>(`/users/${segment(user.public_id)}/roles`, { body: { roles: next } }),
    success: "Roles updated.",
    invalidate: [["users"], ["auth", "me"]],
  });

  const current = new Set(user.roles ?? []);
  const changed =
    selected.length !== current.size || selected.some((name) => !current.has(name));

  return (
    <Card>
      <CardHeader
        title="Roles"
        description="Roles are the whole of this person's authority. The set you save replaces what they hold now."
      />
      <CardBody className="space-y-4">
        {!roles ? (
          <p className="text-sm text-muted-foreground">
            You cannot list the role catalog, so roles can only be shown, not changed. This account
            holds: {(user.roles ?? []).join(", ") || "none"}.
          </p>
        ) : (
          <div className="space-y-2">
            {roles.map((role) => {
              const checked = selected.includes(role.name);
              return (
                <label
                  key={role.name}
                  className="flex items-start gap-3 rounded-lg border border-border-subtle p-3"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 accent-[var(--primary)]"
                    checked={checked}
                    disabled={!canEdit}
                    onChange={(event) =>
                      setSelected((previous) =>
                        event.target.checked
                          ? [...previous, role.name]
                          : previous.filter((name) => name !== role.name),
                      )
                    }
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{role.name}</span>
                    {role.description ? (
                      <span className="block text-xs text-muted-foreground">{role.description}</span>
                    ) : null}
                    {role.permissions ? (
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {role.permissions.length} permissions
                      </span>
                    ) : null}
                  </span>
                </label>
              );
            })}
          </div>
        )}

        {canEdit && roles ? (
          <FormActions>
            <Button variant="ghost" onClick={() => setSelected(user.roles ?? [])} disabled={!changed}>
              Reset
            </Button>
            <Button
              loading={save.isPending}
              disabled={!changed}
              onClick={() => save.mutate(selected)}
            >
              Save roles
            </Button>
          </FormActions>
        ) : null}
      </CardBody>
    </Card>
  );
}

function SecurityTab({ user }: { user: UserResponse }) {
  const router = useRouter();
  const { permissions, user: me } = useSession();
  const timeZone = useDisplayTimeZone();
  const [password, setPassword] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isSelf = me?.public_id === user.public_id;

  const setStatus = useApiMutation<UserResponse, string>({
    mutationFn: (status) =>
      api.put<UserResponse>(`/users/${segment(user.public_id)}/status`, { body: { status } }),
    success: "Status updated.",
    invalidate: [["users"]],
  });

  const setPasswordMutation = useApiMutation<void, string>({
    mutationFn: (next) =>
      api.put<void>(`/users/${segment(user.public_id)}/password`, {
        body: { new_password: next },
      }),
    success: "Password set. Pass it on through a channel you trust.",
    onSuccess: () => setPassword(""),
  });

  const setLoginAccess = useApiMutation<UserLoginAccessResponse, boolean>({
    mutationFn: (canLogin) =>
      api.put<UserLoginAccessResponse>(`/users/${segment(user.public_id)}/login-access`, {
        body: { can_login: canLogin },
      }),
    success: (result) =>
      result.can_login
        ? result.default_password_in_use
          ? "Sign-in enabled. This account still has the shared default password — set a new one before passing it on."
          : "Sign-in enabled."
        : "Sign-in disabled. Any open session was ended.",
    invalidate: [["users"]],
  });

  const unlock = useApiMutation<UnlockResponse, void>({
    mutationFn: () =>
      api.post<UnlockResponse>(`/security/accounts/${segment(user.public_id)}/unlock`),
    success: "Account unlocked.",
    invalidate: [["users"], ["security"]],
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/users/${segment(user.public_id)}`),
    success: "Account deleted.",
    invalidate: [["users"]],
    onSuccess: () => router.push("/users"),
  });

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Account state" />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge value={user.status} kind="user" />
            {user.is_locked ? <Badge tone="danger">Locked out</Badge> : null}
            {!user.can_login ? <Badge tone="warning">Sign-in off</Badge> : null}
            {user.is_synced ? <Badge>Provisioned from LAIT</Badge> : null}
            <span className="text-xs text-muted-foreground">
              Last signed in {formatDateTime(user.last_login, { timeZone })} · created{" "}
              {formatDateTime(user.created_at, { timeZone })}
            </span>
          </div>

          {permissions.has("user.update") ? (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Set status" className="min-w-40">
                {({ id }) => (
                  <Select
                    id={id}
                    value={user.status}
                    disabled={setStatus.isPending}
                    onValueChange={(next) => setStatus.mutate((next ?? ""))}
                   options={optionsFromValues(UserStatusValues)} />
                )}
              </Field>
              {isSelf ? (
                <p className="pb-2 text-xs text-warning">
                  This is your own account. Suspending it will sign you out.
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="flex items-start justify-between gap-4 rounded-lg border border-border-subtle p-3">
            <div className="space-y-1">
              <p className="text-sm font-medium">Allow this person to sign in</p>
              <p className="text-xs text-muted-foreground">
                {user.is_synced
                  ? "Accounts provisioned from LAIT start with sign-in off and a shared default password. Turn this on only once you have set a password of their own, or told them to reset it."
                  : "Off blocks every sign-in and ends their open sessions, without changing their status or roles."}
              </p>
              {isSelf ? <p className="text-xs text-warning">You cannot change your own sign-in access.</p> : null}
            </div>
            <Switch
              aria-label="Allow sign-in"
              checked={user.can_login ?? true}
              disabled={!permissions.has("user.allow_login") || isSelf || setLoginAccess.isPending}
              onCheckedChange={(next) => setLoginAccess.mutate(next)}
            />
          </div>

          {user.is_locked && permissions.has("security.manage") ? (
            <Button variant="secondary" loading={unlock.isPending} onClick={() => unlock.mutate()}>
              <Unlock /> Clear the lockout
            </Button>
          ) : null}
        </CardBody>
      </Card>

      {permissions.has("user.update") ? (
        <Card>
          <CardHeader
            title="Set a new password"
            description="Sets the password directly. There is no self-service reset in this deployment, so this is how a locked-out person gets back in."
          />
          <CardBody className="space-y-3">
            <Field
              label="New password"
              hint="Shown once, here. It is never stored by the console and cannot be retrieved afterwards."
            >
              {({ id }) => (
                <Input
                  id={id}
                  type="text"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              )}
            </Field>
            <FormActions>
              <Button
                loading={setPasswordMutation.isPending}
                disabled={password.length < 8}
                onClick={() => setPasswordMutation.mutate(password)}
              >
                <KeyRound /> Set password
              </Button>
            </FormActions>
          </CardBody>
        </Card>
      ) : null}

      {permissions.has("security.manage") ? (
        <Card>
          <CardHeader
            title="Sessions"
            description="Signing this account out everywhere revokes every refresh token it holds."
          />
          <CardBody>
            <RevokeSessionsButton userId={user.public_id} />
          </CardBody>
        </Card>
      ) : null}

      {permissions.has("user.delete") ? (
        <Card className="border-danger/40">
          <CardHeader
            title="Delete this account"
            description="A soft delete: the row is kept because the audit trail references it, and the account moves to DELETED and can no longer sign in."
          />
          <CardBody>
            <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={isSelf}>
              <Trash2 /> Delete account
            </Button>
            {isSelf ? (
              <p className="mt-2 text-xs text-muted-foreground">
                You cannot delete your own account.
              </p>
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this account?"
        description={`${user.full_name || user.username} will no longer be able to sign in.`}
        confirmPhrase={user.username}
        confirmLabel="Delete account"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

function RevokeSessionsButton({ userId }: { userId: string }) {
  const [open, setOpen] = useState(false);
  const revoke = useApiMutation<{ revoked?: number }, void>({
    mutationFn: () =>
      api.post<{ revoked?: number }>(`/security/accounts/${segment(userId)}/sessions/revoke-all`),
    success: (result) => `Revoked ${result.revoked ?? 0} session(s).`,
    invalidate: [["security"]],
    onSuccess: () => setOpen(false),
  });

  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Lock /> Sign out everywhere
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        destructive
        title="Revoke every session?"
        description="They will have to sign in again on every device."
        confirmLabel="Revoke sessions"
        pending={revoke.isPending}
        onConfirm={() => revoke.mutate()}
      />
    </>
  );
}

export default function UserDetailPage({ params }: { params: Promise<{ userId: string }> }) {
  const { userId } = use(params);
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["users", "detail", userId],
    queryFn: () => api.get<UserResponse>(`/users/${segment(userId)}`),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Users", href: "/users" }, { label: data.username }]}
        title={data.full_name || data.username}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge value={data.status} kind="user" />
            {(data.roles ?? []).map((role) => (
              <Badge key={role} tone="primary">
                {role}
              </Badge>
            ))}
            <span className="text-xs">
              Date of birth {formatCalendarDate(data.date_of_birth)} · joined{" "}
              {formatDateTime(data.created_at, { timeZone })}
            </span>
          </span>
        }
      />

      <Tabs defaultValue="profile">
        <TabsList>
          <TabsTab value="profile">Profile</TabsTab>
          <TabsTab value="roles">Roles</TabsTab>
          <TabsTab value="security">Security</TabsTab>
        </TabsList>
        <TabsPanel value="profile">
          <ProfileForm key={data.public_id} user={data} mode="admin" canEdit={permissions.has("user.update")} />
        </TabsPanel>
        <TabsPanel value="roles">
          <RolesTab user={data} />
        </TabsPanel>
        <TabsPanel value="security">
          <SecurityTab user={data} />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
