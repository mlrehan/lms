"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { GraduationCap } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Checkbox } from "@/components/ui/primitives";
import { safeRedirect } from "@/lib/redirect";

const schema = z.object({
  identifier: z.string().trim().min(1, "Enter your username or email address."),
  password: z.string().min(1, "Enter your password."),
  remember_me: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { identifier: "", password: "", remember_me: false },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(values),
      credentials: "same-origin",
    });

    if (!response.ok) {
      let message = "Sign-in failed. Please check your details and try again.";
      try {
        const payload = (await response.json()) as { message?: string };
        if (payload.message) message = payload.message;
      } catch {
        // A non-JSON error body is a proxy or gateway problem; the generic
        // message above is the honest thing to show.
      }
      setFormError(message);
      return;
    }

    // The cached "who am I" answer belongs to whoever was here before.
    queryClient.clear();
    router.replace(safeRedirect(params.get("next")));
    router.refresh();
  });

  const remember = watch("remember_me");

  return (
    <form
      onSubmit={onSubmit}
      /*
       * `method="post"` matters even though React handles the submit.
       *
       * A form with no method defaults to GET, and a submit that escapes
       * React -- a click landing before hydration, JavaScript failing to load
       * -- then serialises every field into the query string. That was
       * observed here during a slow dev rebuild: the password went into the
       * URL, and from there into browser history, the server's access log and
       * the `Referer` of the next request.
       *
       * With POST and no `action`, the same escaped submit posts to this page
       * and fails visibly instead of leaking a credential silently. The
       * credential never reaches a URL either way.
       */
      method="post"
      className="space-y-4"
      noValidate
    >
      {formError ? (
        <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {formError}
        </div>
      ) : null}

      <Field label="Username or email" error={errors.identifier?.message} required>
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            autoComplete="username"
            autoFocus
            {...register("identifier")}
          />
        )}
      </Field>

      <Field label="Password" error={errors.password?.message} required>
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="password"
            aria-describedby={describedBy}
            autoComplete="current-password"
            {...register("password")}
          />
        )}
      </Field>

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <Checkbox
          checked={remember}
          onCheckedChange={(checked) => setValue("remember_me", checked === true)}
        />
        Keep me signed in on this device
      </label>

      <Button type="submit" className="w-full" loading={isSubmitting}>
        Sign in
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-2 text-center">
          <div className="mx-auto flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <GraduationCap className="size-6" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Sign in to the LMS console</h1>
          <p className="text-sm text-muted-foreground">
            Use the account your institution issued you.
          </p>
        </div>

        <div className="rounded-card border border-border bg-surface p-5 shadow-sm">
          <Suspense fallback={<div className="h-64" />}>
            <LoginForm />
          </Suspense>
        </div>

        {/*
          There is deliberately no "Forgot password?" link. The backend has no
          password-reset endpoint and no email sender, so the link would lead
          to a page that could not do anything -- which is worse than saying
          plainly who can help. See docs/BACKEND-GAPS.md.
        */}
        <p className="text-center text-xs text-muted-foreground">
          Lost your password? An administrator can set a new one for you; this
          deployment has no self-service reset.
        </p>
      </div>
    </main>
  );
}
