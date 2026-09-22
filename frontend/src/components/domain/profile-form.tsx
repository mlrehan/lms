"use client";

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Save, Undo2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { CountryResponse, PageCitySummary, UserResponse } from "@/lib/api/types";
import { GendersValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Switch } from "@/components/ui/primitives";
import { Field, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { AvatarUploader } from "@/components/domain/avatar-uploader";
import { CURRENT_USER_KEY } from "@/lib/auth/session";

const today = () => new Date().toISOString().slice(0, 10);

const profileSchema = z.object({
  email: z.string().trim().email("Enter a valid email address.").or(z.literal("")),
  first_name: z.string().trim().max(50, "Use 50 characters or fewer."),
  last_name: z.string().trim().max(50, "Use 50 characters or fewer."),
  title: z.string().trim().max(20, "Use 20 characters or fewer."),
  gender: z.enum(GendersValues).or(z.literal("")),
  date_of_birth: z
    .string()
    .trim()
    .refine((v) => v === "" || v <= today(), "A date of birth cannot be in the future."),
  phone_number: z.string().trim().max(75, "Use 75 characters or fewer."),
  mobile: z.string().trim().max(75, "Use 75 characters or fewer."),
  designation: z.string().trim().max(100, "Use 100 characters or fewer."),
  company: z.string().trim().max(255),
  web: z
    .string()
    .trim()
    .max(255)
    .refine((v) => v === "" || /^https?:\/\/\S+\.\S+/i.test(v), "Start with http:// or https://"),
  address: z.string().trim(),
  postcode: z.string().trim().max(35, "Use 35 characters or fewer."),
  timezone: z.string().trim(),
  country_id: z.string().trim(),
  city_id: z.string().trim(),
  bio: z.string().trim().max(2000, "Use 2,000 characters or fewer."),
  is_public: z.boolean(),
  emergency_contact_name: z.string().trim().max(150),
  emergency_contact_phone: z.string().trim().max(75),
  emergency_contact_relationship: z.string().trim().max(50),
});

type ProfileValues = z.infer<typeof profileSchema>;

/** `""` means "clear this field", which the API expresses as `null`. */
function blankToNull(value: string): string | null {
  return value.trim() === "" ? null : value.trim();
}

function toValues(user: UserResponse): ProfileValues {
  return {
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
  };
}

function timeZones(current: string): string[] {
  const supported =
    typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  const all = new Set(["UTC", ...supported]);
  if (current) all.add(current);
  return [...all].sort();
}

/**
 * The profile editor, shared by both routes to the same data.
 *
 * - `admin`: an administrator editing anyone (`PATCH /users/{id}`, needs
 *   `user.update`). May change the email address.
 * - `self`: a person editing their own profile (`PATCH /auth/me`). The email is
 *   shown but not editable -- it is the sign-in identifier and this deployment
 *   cannot verify a new one, so changing it is an administrator's decision.
 *
 * The form knows which endpoint to call; it does not decide who may. The
 * server checks that on every request either way.
 */
export function ProfileForm({
  user,
  mode,
  canEdit,
}: {
  user: UserResponse;
  mode: "admin" | "self";
  canEdit: boolean;
}) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    setError,
    formState: { errors, isDirty, dirtyFields },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: toValues(user),
  });

  const countryId = watch("country_id");
  const bio = watch("bio");
  const isPublic = watch("is_public");
  const timezone = watch("timezone");
  const zones = useMemo(() => timeZones(user.timezone ?? ""), [user.timezone]);
  const emailLocked = mode === "self";
  const dirtyCount = Object.keys(dirtyFields).length;

  // Leaving with unsaved edits is the one way this form silently loses work.
  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

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
    mutationFn: (values) => {
      const body: Record<string, unknown> = {
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
      };
      if (!emailLocked) body.email = blankToNull(values.email);
      const url = mode === "self" ? "/auth/me" : `/users/${segment(user.public_id)}`;
      return api.patch<UserResponse>(url, { body });
    },
    success: "Profile saved.",
    invalidate: [["users"], [...CURRENT_USER_KEY]],
    onSuccess: (updated) => reset(toValues(updated)),
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

  const disabled = !canEdit;
  const pictureEndpoint = mode === "self" ? "/auth/me/picture" : `/users/${segment(user.public_id)}/picture`;

  return (
    <form
      method="post"
      onSubmit={handleSubmit((values) => save.mutate(values))}
      noValidate
      className="space-y-5 pb-20"
    >
      <Card>
        <CardHeader title="Picture" description="Shown beside their name in lists, discussions and messages." />
        <CardBody>
          <AvatarUploader
            name={user.full_name || user.username}
            src={user.profile_picture}
            endpoint={pictureEndpoint}
            canEdit={canEdit}
            invalidate={[["users"], [...CURRENT_USER_KEY]]}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Identity" />
        <CardBody className="space-y-4">
          <FormGrid>
            <Field label="Username" hint="Usernames cannot be changed.">
              {({ id }) => <Input id={id} value={user.username} readOnly disabled />}
            </Field>
            <Field
              label="Email"
              error={errors.email?.message}
              hint={emailLocked ? "Ask an administrator to change your email address." : undefined}
            >
              {({ id }) => (
                <Input id={id} type="email" autoComplete="email" disabled={disabled || emailLocked} {...register("email")} />
              )}
            </Field>
            <Field label="Title" error={errors.title?.message}>
              {({ id }) => <Input id={id} placeholder="Mr, Ms, Dr…" disabled={disabled} {...register("title")} />}
            </Field>
            <Field label="Gender">
              {({ id }) => (
                <NativeSelect id={id} disabled={disabled} {...register("gender")}>
                  <option value="">Not stated</option>
                  {GendersValues.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="First name" error={errors.first_name?.message}>
              {({ id }) => <Input id={id} autoComplete="given-name" disabled={disabled} {...register("first_name")} />}
            </Field>
            <Field label="Last name" error={errors.last_name?.message}>
              {({ id }) => <Input id={id} autoComplete="family-name" disabled={disabled} {...register("last_name")} />}
            </Field>
            <Field label="Date of birth" error={errors.date_of_birth?.message}>
              {({ id }) => (
                <Input id={id} type="date" max={today()} autoComplete="bday" disabled={disabled} {...register("date_of_birth")} />
              )}
            </Field>
            <Field
              label="Timezone"
              hint="Used to show times in their own zone. Data is always stored in UTC."
              error={errors.timezone?.message}
            >
              {({ id }) => (
                <NativeSelect id={id} disabled={disabled} value={timezone} onChange={(event) => setValue("timezone", event.target.value, { shouldDirty: true })}>
                  <option value="">Not set</option>
                  {zones.map((zone) => (
                    <option key={zone} value={zone}>
                      {zone}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Contact" />
        <CardBody>
          <FormGrid>
            <Field label="Phone" error={errors.phone_number?.message}>
              {({ id }) => <Input id={id} type="tel" autoComplete="tel" disabled={disabled} {...register("phone_number")} />}
            </Field>
            <Field label="Mobile" error={errors.mobile?.message}>
              {({ id }) => <Input id={id} type="tel" disabled={disabled} {...register("mobile")} />}
            </Field>
            <Field label="Country">
              {({ id }) => (
                <NativeSelect
                  id={id}
                  disabled={disabled}
                  value={countryId}
                  onChange={(event) => {
                    setValue("country_id", event.target.value, { shouldDirty: true });
                    // A city from the previous country would fail the API's own
                    // consistency check; clearing it means the form cannot
                    // submit a pair that is knowably wrong.
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
            <Field label="City" error={errors.city_id?.message} hint={!countryId ? "Choose a country first." : undefined}>
              {({ id }) => (
                <NativeSelect id={id} disabled={disabled || !countryId} {...register("city_id")}>
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
              {({ id }) => <Input id={id} autoComplete="street-address" disabled={disabled} {...register("address")} />}
            </Field>
            <Field label="Postcode" error={errors.postcode?.message}>
              {({ id }) => <Input id={id} autoComplete="postal-code" disabled={disabled} {...register("postcode")} />}
            </Field>
            <Field label="Website" error={errors.web?.message}>
              {({ id }) => <Input id={id} type="url" placeholder="https://" disabled={disabled} {...register("web")} />}
            </Field>
            <Field label="Company">
              {({ id }) => <Input id={id} autoComplete="organization" disabled={disabled} {...register("company")} />}
            </Field>
            <Field label="Designation">
              {({ id }) => <Input id={id} disabled={disabled} {...register("designation")} />}
            </Field>
          </FormGrid>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Emergency contact" description="Who to call if something happens." />
        <CardBody>
          <FormGrid columns={3}>
            <Field label="Name">
              {({ id }) => <Input id={id} disabled={disabled} {...register("emergency_contact_name")} />}
            </Field>
            <Field label="Phone">
              {({ id }) => <Input id={id} type="tel" disabled={disabled} {...register("emergency_contact_phone")} />}
            </Field>
            <Field label="Relationship">
              {({ id }) => <Input id={id} disabled={disabled} {...register("emergency_contact_relationship")} />}
            </Field>
          </FormGrid>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="About" />
        <CardBody className="space-y-4">
          <Field label="Bio" error={errors.bio?.message} hint={`${bio.length.toLocaleString()} / 2,000`}>
            {({ id }) => <Textarea id={id} disabled={disabled} {...register("bio")} />}
          </Field>
          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={isPublic}
              disabled={disabled}
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
        <div
          className="sticky bottom-3 z-10 flex items-center justify-between gap-3 rounded-xl border border-border-subtle bg-surface/85 px-4 py-3 shadow-lg backdrop-blur-md"
          role="region"
          aria-label="Save changes"
        >
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {isDirty
              ? `${dirtyCount} unsaved change${dirtyCount === 1 ? "" : "s"}`
              : "All changes saved"}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => reset()} disabled={!isDirty || save.isPending}>
              <Undo2 /> Discard
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!isDirty}>
              <Save /> Save changes
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">You can view this profile but not change it.</p>
      )}
    </form>
  );
}
