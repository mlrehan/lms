"use client";

import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Check, Copy, Eye, EyeOff, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import type { RoleResponse, UserResponse } from "@/lib/api/types";
import { GendersValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input } from "@/components/ui/form";
import { FormSelect } from "@/components/ui/form-controls";
import { Switch } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/** Mirrors the server: `Password` is 12-128 characters, `Username` is 3-50 of [A-Za-z0-9._-]. */
export const PASSWORD_MIN = 12;

const schema = z.object({
  email: z.string().trim().email("Enter a valid email address."),
  username: z
    .string()
    .trim()
    .min(3, "Use at least 3 characters.")
    .max(50, "Use 50 characters or fewer.")
    .regex(/^[A-Za-z0-9._-]+$/, "Letters, numbers, dots, dashes and underscores only."),
  first_name: z.string().trim().max(50),
  last_name: z.string().trim().max(50),
  title: z.string().trim().max(20),
  gender: z.enum(GendersValues),
  phone_number: z.string().trim().max(75),
  password: z
    .string()
    .min(PASSWORD_MIN, `Use at least ${PASSWORD_MIN} characters.`)
    .max(128, "Use 128 characters or fewer."),
  can_login: z.boolean(),
  roles: z.array(z.string()).min(1, "Choose at least one role."),
});

type Values = z.infer<typeof schema>;

const EMPTY: Values = {
  email: "",
  username: "",
  first_name: "",
  last_name: "",
  title: "",
  gender: "MALE",
  phone_number: "",
  password: "",
  can_login: true,
  roles: [],
};

/** A username suggested from an email's local part, within the server's character set. */
export function suggestUsername(email: string): string {
  const local = email.split("@")[0] ?? "";
  return local.replace(/[^A-Za-z0-9._-]/g, "").toLowerCase().slice(0, 50);
}

/** Cryptographically random, and guaranteed to contain each character class. */
export function generatePassword(length = 16): string {
  const sets = ["abcdefghijkmnopqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789", "!@#$%*-_+="];
  const all = sets.join("");
  const pick = (chars: string): string => {
    // Rejection sampling: `% length` alone would favour early characters.
    const limit = 256 - (256 % chars.length);
    for (;;) {
      const byte = crypto.getRandomValues(new Uint8Array(1))[0] ?? 255;
      if (byte < limit) return chars.charAt(byte % chars.length);
    }
  };
  const out = sets.map(pick);
  while (out.length < length) out.push(pick(all));
  for (let i = out.length - 1; i > 0; i--) {
    const j = (crypto.getRandomValues(new Uint32Array(1))[0] ?? 0) % (i + 1);
    const tmp = out[i] as string;
    out[i] = out[j] as string;
    out[j] = tmp;
  }
  return out.join("");
}

/** 0-4. Length dominates; variety adds; obvious repetition subtracts. Advisory only -- the server decides. */
export function passwordStrength(password: string): { score: 0 | 1 | 2 | 3 | 4; label: string } {
  if (!password) return { score: 0, label: "" };
  let score = 0;
  if (password.length >= PASSWORD_MIN) score++;
  if (password.length >= 16) score++;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (classes >= 3) score++;
  if (classes === 4 && password.length >= 14) score++;
  if (/^(.)\1+$/.test(password) || /(password|123456|qwerty)/i.test(password)) score = Math.min(score, 1);
  if (password.length < PASSWORD_MIN) score = Math.min(score, 1);
  const s = Math.max(0, Math.min(4, score)) as 0 | 1 | 2 | 3 | 4;
  return { score: s, label: ["", "Weak", "Fair", "Good", "Strong"][s] ?? "" };
}

const METER = ["bg-border", "bg-danger", "bg-warning", "bg-primary", "bg-success"];

function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      type="button"
      variant="ghost"
      aria-label={`Copy ${label}`}
      disabled={!value}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          toast.error("Copying is blocked in this browser. Select the text and copy it manually.");
        }
      }}
    >
      {done ? <Check /> : <Copy />}
    </Button>
  );
}

export function CreateUserDialog({
  open,
  onOpenChange,
  roles,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roles: RoleResponse[];
}) {
  const [banner, setBanner] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [usernameTouched, setUsernameTouched] = useState(false);
  const [created, setCreated] = useState<{ user: UserResponse; password: string; canLogin: boolean } | null>(null);

  const {
    register,
    handleSubmit,
    control,
    reset,
    setValue,
    setError,
    watch,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });

  const selectedRoles = watch("roles");
  const password = watch("password");
  const canLogin = watch("can_login");
  const strength = passwordStrength(password);

  function close(next: boolean) {
    if (!next) {
      reset(EMPTY);
      setBanner(null);
      setCreated(null);
      setUsernameTouched(false);
      setShowPassword(false);
    }
    onOpenChange(next);
  }

  const create = useApiMutation<UserResponse, Values>({
    mutationFn: (values) =>
      api.post<UserResponse>("/users", {
        body: {
          ...values,
          first_name: values.first_name || null,
          last_name: values.last_name || null,
          title: values.title || null,
          phone_number: values.phone_number || null,
        },
      }),
    invalidate: [["users"]],
    onSuccess: (user, values) => {
      setCreated({ user, password: values.password, canLogin: values.can_login });
      setBanner(null);
    },
    onError: (error) => {
      const known = ["username", "email", "password", "roles"] as const;
      if (!applyFieldErrors<Values>(error, setError, known)) setBanner(error.message);
      else setBanner(null);
    },
  });

  if (created) {
    return (
      <Dialog open={open} onOpenChange={close}>
        <DialogContent size="md">
          <DialogHeader
            title="Account created"
            description="Pass these details on through a channel you trust. The password is shown only now: the console does not keep it and cannot show it again."
          />
          <dl className="space-y-3 rounded-lg border border-border-subtle bg-surface-muted p-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Username</dt>
              <dd className="flex items-center gap-1 font-mono">
                {created.user.username} <CopyButton value={created.user.username} label="username" />
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Email</dt>
              <dd className="font-mono">{created.user.email}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Password</dt>
              <dd className="flex items-center gap-1 font-mono">
                {created.password} <CopyButton value={created.password} label="password" />
              </dd>
            </div>
          </dl>
          {!created.canLogin ? (
            <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
              Sign-in is switched off for this account, so these details will not work until it is enabled on their Security tab.
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                reset(EMPTY);
                setCreated(null);
                setUsernameTouched(false);
                setShowPassword(false);
              }}
            >
              Create another
            </Button>
            <Link
              href={`/users/${created.user.public_id}`}
              className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90"
              onClick={() => close(false)}
            >
              Open profile
            </Link>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="lg">
        <DialogHeader
          title="Create an account"
          description="This deployment sends no email, so there is no invitation step: you are the vouching step, and you pass the password on yourself."
        />
        <form
          method="post"
          className="space-y-6"
          onSubmit={handleSubmit((values) => create.mutate(values))}
          noValidate
        >
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}

          <section className="space-y-3" aria-labelledby="cu-account">
            <h3 id="cu-account" className="text-sm font-semibold">Account</h3>
            <FormGrid>
              <Field label="Email" error={errors.email?.message} required>
                {({ id }) => (
                  <Input
                    id={id}
                    type="email"
                    autoComplete="off"
                    autoFocus
                    {...register("email", {
                      onChange: (event) => {
                        if (!usernameTouched) {
                          setValue("username", suggestUsername(event.target.value), { shouldValidate: false });
                        }
                      },
                    })}
                  />
                )}
              </Field>
              <Field
                label="Username"
                error={errors.username?.message}
                hint={usernameTouched ? undefined : "Suggested from the email; change it if you like."}
                required
              >
                {({ id }) => (
                  <Input
                    id={id}
                    autoComplete="off"
                    {...register("username", { onChange: () => setUsernameTouched(true) })}
                  />
                )}
              </Field>
            </FormGrid>
          </section>

          <section className="space-y-3" aria-labelledby="cu-person">
            <h3 id="cu-person" className="text-sm font-semibold">
              Person <span className="font-normal text-muted-foreground">— everything else can be filled in later</span>
            </h3>
            <FormGrid>
              <Field label="Title" error={errors.title?.message}>
                {({ id }) => <Input id={id} placeholder="Mr, Ms, Dr…" {...register("title")} />}
              </Field>
              <Field label="Gender">
                {({ id }) => (
                  <FormSelect id={id}  control={control} name="gender" options={GendersValues.map((value) => ({ value: value, label: value }))} />
                )}
              </Field>
              <Field label="First name" error={errors.first_name?.message}>
                {({ id }) => <Input id={id} {...register("first_name")} />}
              </Field>
              <Field label="Last name" error={errors.last_name?.message}>
                {({ id }) => <Input id={id} {...register("last_name")} />}
              </Field>
              <Field label="Phone" error={errors.phone_number?.message}>
                {({ id }) => <Input id={id} type="tel" {...register("phone_number")} />}
              </Field>
            </FormGrid>
          </section>

          <section className="space-y-3" aria-labelledby="cu-access">
            <h3 id="cu-access" className="text-sm font-semibold">Access</h3>

            <Field label="Roles" error={errors.roles?.message} required hint="What this person can do. You can change it later.">
              <div className="grid gap-2 sm:grid-cols-2">
                {roles.map((role) => {
                  const checked = selectedRoles.includes(role.name);
                  return (
                    <label
                      key={role.name}
                      className={cn(
                        "flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm transition-colors focus-within:ring-2 focus-within:ring-primary/40",
                        checked ? "border-primary bg-accent" : "border-border-subtle hover:border-border-strong",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4 accent-[var(--color-primary)]"
                        checked={checked}
                        onChange={(event) =>
                          setValue(
                            "roles",
                            event.target.checked
                              ? [...selectedRoles, role.name]
                              : selectedRoles.filter((name) => name !== role.name),
                            { shouldValidate: true },
                          )
                        }
                      />
                      <span>
                        <span className="font-medium">{role.name.replace(/_/g, " ")}</span>
                        {role.description ? (
                          <span className="block text-xs text-muted-foreground">{role.description}</span>
                        ) : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            </Field>

            <Field label="Initial password" error={errors.password?.message} required>
              {({ id }) => (
                <div className="space-y-2">
                  <div className="flex gap-1.5">
                    <Input
                      id={id}
                      type={showPassword ? "text" : "password"}
                      autoComplete="new-password"
                      className="font-mono"
                      {...register("password")}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      onClick={() => setShowPassword((v) => !v)}
                    >
                      {showPassword ? <EyeOff /> : <Eye />}
                    </Button>
                    <CopyButton value={password} label="password" />
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        setValue("password", generatePassword(), { shouldValidate: true, shouldDirty: true });
                        setShowPassword(true);
                      }}
                    >
                      <Wand2 /> Generate
                    </Button>
                  </div>
                  <div className="flex items-center gap-2" aria-live="polite">
                    <div className="flex h-1.5 flex-1 gap-1" aria-hidden>
                      {[1, 2, 3, 4].map((step) => (
                        <span
                          key={step}
                          className={cn("flex-1 rounded-full", strength.score >= step ? METER[strength.score] : "bg-border")}
                        />
                      ))}
                    </div>
                    <span className="w-14 text-right text-xs text-muted-foreground">{strength.label}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    At least {PASSWORD_MIN} characters. Shown once after creation; the console does not keep it.
                  </p>
                </div>
              )}
            </Field>

            <label className="flex items-start justify-between gap-4 rounded-lg border border-border-subtle p-3 text-sm">
              <span>
                <span className="font-medium">Allow this person to sign in</span>
                <span className="block text-xs text-muted-foreground">
                  On by default because you are setting the password yourself. Turn it off to prepare the account and enable it later.
                </span>
              </span>
              <Switch
                aria-label="Allow sign-in"
                checked={canLogin}
                onCheckedChange={(next) => setValue("can_login", next)}
              />
            </label>
          </section>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
