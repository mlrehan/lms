"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { KeyRound, Lock, Trash2, Unlock } from "lucide-react";
import { api } from "@/lib/api/client";
import type {
  CountryResponse,
  PageCitySummary,
  RoleResponse,
  UnlockResponse,
  UserResponse,
} from "@/lib/api/types";
import { GendersValues, UserStatusValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Switch, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatCalendarDate } from "@/lib/format/datetime";
import { segment } from "@/lib/api/client";

const profileSchema = z.object({
  email: z.string().trim().email("Enter a valid email address.").or(z.literal("")),
  first_name: z.string().trim(),
  last_name: z.string().trim(),
  title: z.string().trim(),
  gender: z.enum(GendersValues).or(z.literal("")),
  date_of_birth: z.string().trim(),
  phone_number: z.string().trim(),
  mobile: z.string().trim(),
  designation: z.string().trim(),
  company: z.string().trim(),
  web: z.string().trim(),
  address: z.string().trim(),
  postcode: z.string().trim(),
  timezone: z.string().trim(),
  country_id: z.string().trim(),
  city_id: z.string().trim(),
  bio: z.string().trim(),
  is_public: z.boolean(),
  emergency_contact_name: z.string().trim(),
  emergency_contact_phone: z.string().trim(),
  emergency_contact_relationship: z.string().trim(),
});

type ProfileValues = z.infer<typeof profileSchema>;

/** `""` means "clear this field", which the API expresses as `null`. */
function blankToNull(value: string): string | null {
  return value.trim() === "" ? null : value.trim();
}

function ProfileTab({ user, canEdit }: { user: UserResponse; canEdit: boolean }) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    setError,
    formState: { errors, isDirty },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      email: user.email ?? "",
      first_name: user.first_name ?? "",
      last_name: user.last_name ?? "",
      title: user.title ?? "",
      gender: user.gender ?? "",
      date_of_birth: user.date_of_birth?.slice(0, 10) ?? "",
      phone_number: user.phone_number ?? "",
      mobile: user.mobile ?? "",
      designation: user.designation ?? "",
      company: user.company ?? "",
      web: user.web ?? "",
      address: user.address ?? "",
      postcode: user.postcode ?? "",
      timezone: user.timezone ?? "",
      country_id: user.country?.public_id ?? "",
      city_id: user.city?.public_id ?? "",
      bio: user.bio ?? "",
      is_public: user.is_public,
      emergency_contact_name: user.emergency_contact_name ?? "",
      emergency_contact_phone: user.emergency_contact_phone ?? "",
      emergency_contact_relationship: user.emergency_contact_relationship ?? "",
    },
  });

  const countryId = watch("country_id");

  const { data: countries } = useQuery({
    queryKey: ["geo", "countries"],
    queryFn: () => api.get<CountryResponse[]>("/geo/countries"),
    staleTime: 24 * 60 * 60 * 1000,
  });

  const { data: cities } = useQuery({
    queryKey: ["geo", "cities", countryId],
    queryFn: () =>
      api.get<PageCitySummary>(`/geo/countries/${segment(countryId)}/cities`, {
        query: { limit: 500 },
      }),
    enabled: Boolean(countryId),
    staleTime: 60 * 60 * 1000,
  });

  const save = useApiMutation<UserResponse, ProfileValues>({
    mutationFn: (values) =>
      api.patch<UserResponse>(`/users/${segment(user.public_id)}`, {
        body: {
          email: blankToNull(values.email),
          first_name: blankToNull(values.first_name),
          last_name: blankToNull(values.last_name),
          title: blankToNull(values.title),
          gender: values.gender === "" ? null : values.gender,
          date_of_birth: blankToNull(values.date_of_birth),
          phone_number: blankToNull(values.phone_number),
          mobile: blankToNull(values.mobile),
          designation: blankToNull(values.designation),
          company: blankToNull(values.company),
          web: blankToNull(values.web),
          address: blankToNull(values.address),
          postcode: blankToNull(values.postcode),
          timezone: blankToNull(values.timezone),
          country_id: blankToNull(values.country_id),
          city_id: blankToNull(values.city_id),
          bio: blankToNull(values.bio),
          is_public: values.is_public,
          emergency_contact_name: blankToNull(values.emergency_contact_name),
          emergency_contact_phone: blankToNull(values.emergency_contact_phone),
          emergency_contact_relationship: blankToNull(values.emergency_contact_relationship),
        },
      }),
    success: "Profile saved.",
    invalidate: [["users"], ["auth", "me"]],
    onSuccess: (updated) => {
      reset({
        email: updated.email ?? "",
        first_name: updated.first_name ?? "",
        last_name: updated.last_name ?? "",
        title: updated.title ?? "",
        gender: updated.gender ?? "",
        date_of_birth: updated.date_of_birth?.slice(0, 10) ?? "",
        phone_number: updated.phone_number ?? "",
        mobile: updated.mobile ?? "",
        designation: updated.designation ?? "",
        company: updated.company ?? "",
        web: updated.web ?? "",
        address: updated.address ?? "",
        postcode: updated.postcode ?? "",
        timezone: updated.timezone ?? "",
        country_id: updated.country?.public_id ?? "",
        city_id: updated.city?.public_id ?? "",
        bio: updated.bio ?? "",
        is_public: updated.is_public,
        emergency_contact_name: updated.emergency_contact_name ?? "",
        emergency_contact_phone: updated.emergency_contact_phone ?? "",
        emergency_contact_relationship: updated.emergency_contact_relationship ?? "",
      });
    },
    onError: (error) => {
      applyFieldErrors<ProfileValues>(error, setError, [
        "email",
        "date_of_birth",
        "country_id",
        "city_id",
        "timezone",
        "web",
      ]);
    },
  });

  const isPublic = watch("is_public");

  return (
    <form onSubmit={handleSubmit((values) => save.mutate(values))} noValidate className="space-y-5">
      <Card>
        <CardHeader title="Identity" />
        <CardBody className="space-y-4">
          <FormGrid>
            <Field label="Username">
              {({ id }) => (
                <Input
                  id={id}
                  value={user.username}
                  readOnly
                  disabled
                  // The API has no rename endpoint, so this is displayed
                  // rather than offered. An editable field that silently does
                  // nothing is worse than a disabled one.
                />
              )}
            </Field>
            <Field label="Email" error={errors.email?.message}>
              {({ id }) => <Input id={id} type="email" disabled={!canEdit} {...register("email")} />}
            </Field>
            <Field label="Title">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("title")} />}
            </Field>
            <Field label="Gender">
              {({ id }) => (
                <NativeSelect id={id} disabled={!canEdit} {...register("gender")}>
                  <option value="">Not stated</option>
                  {GendersValues.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="First name">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("first_name")} />}
            </Field>
            <Field label="Last name">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("last_name")} />}
            </Field>
            <Field label="Date of birth" error={errors.date_of_birth?.message}>
              {({ id }) => (
                <Input id={id} type="date" disabled={!canEdit} {...register("date_of_birth")} />
              )}
            </Field>
            <Field
              label="Timezone"
              hint="Their default for displaying times. Data is always stored in UTC."
              error={errors.timezone?.message}
            >
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("timezone")} />}
            </Field>
          </FormGrid>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Contact" />
        <CardBody>
          <FormGrid>
            <Field label="Phone">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("phone_number")} />}
            </Field>
            <Field label="Mobile">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("mobile")} />}
            </Field>
            <Field label="Country">
              {({ id }) => (
                <NativeSelect
                  id={id}
                  disabled={!canEdit}
                  value={countryId}
                  onChange={(event) => {
                    setValue("country_id", event.target.value, { shouldDirty: true });
                    // A city from the previous country would fail the API's
                    // own consistency check; clearing it here means the form
                    // cannot submit a pair that is knowably wrong.
                    setValue("city_id", "", { shouldDirty: true });
                  }}
                >
                  <option value="">Not stated</option>
                  {(countries ?? []).map((country) => (
                    <option key={country.public_id} value={country.public_id}>
                      {country.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="City" error={errors.city_id?.message}>
              {({ id }) => (
                <NativeSelect id={id} disabled={!canEdit || !countryId} {...register("city_id")}>
                  <option value="">Not stated</option>
                  {(cities?.items ?? []).map((city) => (
                    <option key={city.public_id} value={city.public_id}>
                      {city.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Address">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("address")} />}
            </Field>
            <Field label="Postcode">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("postcode")} />}
            </Field>
            <Field label="Website" error={errors.web?.message}>
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("web")} />}
            </Field>
            <Field label="Company">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("company")} />}
            </Field>
            <Field label="Designation">
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("designation")} />}
            </Field>
          </FormGrid>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Emergency contact" />
        <CardBody>
          <FormGrid columns={3}>
            <Field label="Name">
              {({ id }) => (
                <Input id={id} disabled={!canEdit} {...register("emergency_contact_name")} />
              )}
            </Field>
            <Field label="Phone">
              {({ id }) => (
                <Input id={id} disabled={!canEdit} {...register("emergency_contact_phone")} />
              )}
            </Field>
            <Field label="Relationship">
              {({ id }) => (
                <Input
                  id={id}
                  disabled={!canEdit}
                  {...register("emergency_contact_relationship")}
                />
              )}
            </Field>
          </FormGrid>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Profile" />
        <CardBody className="space-y-4">
          <Field label="Bio">
            {({ id }) => <Textarea id={id} disabled={!canEdit} {...register("bio")} />}
          </Field>
          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={isPublic}
              disabled={!canEdit}
              onCheckedChange={(checked) => setValue("is_public", checked, { shouldDirty: true })}
            />
            <span>
              Visible to other members of the institution
              <span className="block text-xs text-muted-foreground">
                Turning this off does not hide the account from administrators.
              </span>
            </span>
          </label>
        </CardBody>
      </Card>

      {canEdit ? (
        <FormActions>
          <Button type="button" variant="ghost" onClick={() => reset()} disabled={!isDirty}>
            Discard changes
          </Button>
          <Button type="submit" loading={save.isPending} disabled={!isDirty}>
            Save profile
          </Button>
        </FormActions>
      ) : (
        <p className="text-xs text-muted-foreground">
          You can view this profile but not change it.
        </p>
      )}
    </form>
  );
}

function RolesTab({ user }: { user: UserResponse }) {
  const { permissions } = useSession();
  const canEdit = permissions.has("user.update");
  const [selected, setSelected] = useState<string[]>(user.roles ?? []);

  useEffect(() => setSelected(user.roles ?? []), [user.roles]);

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
                  className="flex items-start gap-3 rounded-lg border border-border p-3"
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
            <span className="text-xs text-muted-foreground">
              Last signed in {formatDateTime(user.last_login, { timeZone })} · created{" "}
              {formatDateTime(user.created_at, { timeZone })}
            </span>
          </div>

          {permissions.has("user.update") ? (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Set status" className="min-w-40">
                {({ id }) => (
                  <NativeSelect
                    id={id}
                    value={user.status}
                    disabled={setStatus.isPending}
                    onChange={(event) => setStatus.mutate(event.target.value)}
                  >
                    {UserStatusValues.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </NativeSelect>
                )}
              </Field>
              {isSelf ? (
                <p className="pb-2 text-xs text-warning">
                  This is your own account. Suspending it will sign you out.
                </p>
              ) : null}
            </div>
          ) : null}

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
          <ProfileTab user={data} canEdit={permissions.has("user.update")} />
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
