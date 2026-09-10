"use client";

import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { KeyRound, LogOut, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button, buttonVariants } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, Input } from "@/components/ui/form";
import { StatusBadge } from "@/components/domain/status-badge";
import { useSession, useSignOut } from "@/lib/auth/session";
import { usePreferences, useDisplayTimeZone } from "@/lib/preferences";
import { describeTimeZone, formatDateTime } from "@/lib/format/datetime";

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password."),
    new_password: z.string().min(8, "Use at least 8 characters."),
    confirm: z.string().min(1, "Repeat the new password."),
  })
  .refine((values) => values.new_password === values.confirm, {
    path: ["confirm"],
    message: "The two passwords do not match.",
  });

type PasswordValues = z.infer<typeof passwordSchema>;

function ChangePassword() {
  const [banner, setBanner] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema) });

  const change = useApiMutation<void, PasswordValues>({
    mutationFn: (values) =>
      api.post<void>("/auth/password/change", {
        body: {
          current_password: values.current_password,
          new_password: values.new_password,
        },
      }),
    success: "Password changed.",
    onSuccess: () => {
      reset();
      setBanner(null);
    },
    onError: (error) => {
      if (!applyFieldErrors<PasswordValues>(error, setError, ["current_password", "new_password"])) {
        setBanner(error.message);
      }
    },
  });

  return (
    <Card>
      <CardHeader
        title="Change your password"
        description="Changing it does not sign you out of this device. Use 'Sign out everywhere' below if you think someone else has your password."
      />
      <CardBody>
        <form
          method="post"
          className="max-w-md space-y-4"
          onSubmit={handleSubmit((values) => change.mutate(values))}
          noValidate
        >
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Current password" error={errors.current_password?.message} required>
            {({ id }) => (
              <Input id={id} type="password" autoComplete="current-password" {...register("current_password")} />
            )}
          </Field>
          <Field label="New password" error={errors.new_password?.message} required>
            {({ id }) => (
              <Input id={id} type="password" autoComplete="new-password" {...register("new_password")} />
            )}
          </Field>
          <Field label="Repeat new password" error={errors.confirm?.message} required>
            {({ id }) => (
              <Input id={id} type="password" autoComplete="new-password" {...register("confirm")} />
            )}
          </Field>
          <FormActions>
            <Button type="submit" loading={change.isPending}>
              <KeyRound /> Change password
            </Button>
          </FormActions>
        </form>
      </CardBody>
    </Card>
  );
}

function ReadOnlyRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="min-w-0 text-sm font-medium">{value || "—"}</span>
    </div>
  );
}

export default function AccountPage() {
  const { user, roles, permissions } = useSession();
  const signOut = useSignOut();
  const timeZone = useDisplayTimeZone();
  const { density, setDensity } = usePreferences();
  const [confirmGlobalSignOut, setConfirmGlobalSignOut] = useState(false);

  if (!user) return null;

  const canEditOwnProfile = permissions.has("user.update");

  return (
    <div className="space-y-5">
      <PageHeader
        title="My account"
        description="Your profile, password and preferences."
        actions={
          canEditOwnProfile ? (
            <Link
              href={`/users/${user.public_id}`}
              className={buttonVariants({ variant: "secondary" })}
            >
              Edit my profile
            </Link>
          ) : null
        }
      />

      <Card>
        <CardHeader
          title={user.full_name || user.username}
          description={user.email ?? undefined}
          actions={
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge value={user.status} kind="user" />
              {roles.map((role) => (
                <Badge key={role} tone="primary">
                  {role}
                </Badge>
              ))}
            </div>
          }
        />
        <div className="divide-y divide-border">
          <ReadOnlyRow label="Username" value={<span className="font-mono text-xs">{user.username}</span>} />
          <ReadOnlyRow label="Phone" value={user.phone_number ?? user.mobile} />
          <ReadOnlyRow label="Country" value={user.country?.name} />
          <ReadOnlyRow label="City" value={user.city?.name} />
          <ReadOnlyRow
            label="Profile timezone"
            value={user.timezone ? describeTimeZone(user.timezone) : "Not set"}
          />
          <ReadOnlyRow label="Last sign-in" value={formatDateTime(user.last_login, { timeZone })} />
          <ReadOnlyRow label="Account created" value={formatDateTime(user.created_at, { timeZone })} />
        </div>
      </Card>

      {!canEditOwnProfile ? (
        <p className="flex items-start gap-2 rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-muted-foreground">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            This deployment has no &ldquo;edit my own profile&rdquo; endpoint: profile changes go
            through <code className="font-mono text-xs">PATCH /users/&#123;id&#125;</code>, which needs
            the <code className="font-mono text-xs">user.update</code> permission. Ask an
            administrator to make changes for you. Recorded in{" "}
            <code className="font-mono text-xs">docs/BACKEND-GAPS.md</code>.
          </span>
        </p>
      ) : null}

      <ChangePassword />

      <Card>
        <CardHeader title="Display" description="Applies to this browser only." />
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Display timezone</p>
              <p className="text-xs text-muted-foreground">
                Currently {describeTimeZone(timeZone)}. Change it from the globe in the top bar.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Table density</p>
              <p className="text-xs text-muted-foreground">Comfortable rows, or more rows per screen.</p>
            </div>
            <div className="flex gap-1">
              {(["comfortable", "compact"] as const).map((option) => (
                <Button
                  key={option}
                  size="sm"
                  variant={density === option ? "primary" : "secondary"}
                  onClick={() => setDensity(option)}
                >
                  {option === "comfortable" ? "Comfortable" : "Compact"}
                </Button>
              ))}
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Sessions"
          description="Every device signed in as you."
          actions={
            <Link
              href="/account/sessions"
              className={buttonVariants({ variant: "secondary", size: "sm" })}
            >
              Manage sessions
            </Link>
          }
        />
        <CardBody>
          <Button variant="danger" onClick={() => setConfirmGlobalSignOut(true)}>
            <LogOut /> Sign out everywhere
          </Button>
        </CardBody>
      </Card>

      <ConfirmDialog
        open={confirmGlobalSignOut}
        onOpenChange={setConfirmGlobalSignOut}
        destructive
        title="Sign out on every device?"
        description="Every session, including this one, ends immediately. You will need to sign in again."
        confirmLabel="Sign out everywhere"
        onConfirm={() => signOut({ everywhere: true })}
      />
    </div>
  );
}
