"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CircleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api/client";
import type { GoogleStatusResponse } from "@/lib/api/types";
import { buttonVariants } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/states";
import { GOOGLE_STATUS_KEY } from "@/components/domain/google-calendar-panel";
import Link from "next/link";

/**
 * Where Google sends the browser after consent (`?code=...&state=...`).
 *
 * The code is single-use and short-lived, and is forwarded straight to the API with the
 * signed-in person's session; the API checks `state` is one *it* issued to *this* person
 * before anything is sent to Google. The address bar is cleared as soon as the parameters have
 * been read, so the code does not linger in history.
 */
function Callback() {
  const params = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const started = useRef(false);
  // Captured once. The address bar is cleared below, which would otherwise change what
  // `useSearchParams` reports halfway through the exchange.
  const [captured] = useState(() => ({ code: params.get("code"), state: params.get("state"), denied: params.get("error") }));
  const [failure, setFailure] = useState<string | null>(null);

  const immediate = captured.denied
    ? captured.denied === "access_denied"
      ? "Google access was not granted."
      : `Google reported: ${captured.denied}.`
    : !captured.code || !captured.state
      ? "This page is where Google sends you after you sign in. Start from Integrations."
      : null;

  useEffect(() => {
    if (started.current) return; // React strict mode runs effects twice; a code can be used once
    started.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    if (immediate || !captured.code || !captured.state) return;

    api
      .post<GoogleStatusResponse>("/integrations/google/callback", { body: { code: captured.code, state: captured.state } })
      .then((status) => {
        void queryClient.invalidateQueries({ queryKey: [...GOOGLE_STATUS_KEY] });
        toast.success(`Google Calendar connected as ${status.account_email}.`);
        router.replace("/integrations");
      })
      .catch((error: unknown) => setFailure(error instanceof ApiError ? error.message : "Could not finish connecting Google."));
  }, [captured, immediate, router, queryClient]);

  const shown = immediate ?? failure;
  if (shown) {
    return (
      <div className="mx-auto mt-16 max-w-md space-y-4 text-center">
        <CircleAlert className="mx-auto size-10 text-danger" aria-hidden />
        <h1 className="text-lg font-semibold">Google Calendar was not connected</h1>
        <p role="alert" className="text-sm text-muted-foreground">
          {shown}
        </p>
        <Link href="/integrations" className={buttonVariants({ variant: "secondary" })}>
          Back to Integrations
        </Link>
      </div>
    );
  }
  return (
    <div className="mx-auto mt-16 max-w-md space-y-4 text-center">
      <CalendarCheck className="mx-auto size-10 text-primary" aria-hidden />
      <h1 className="text-lg font-semibold">Finishing the connection…</h1>
      <LoadingState rows={1} />
    </div>
  );
}

export default function GoogleCallbackPage() {
  return (
    <Suspense fallback={<LoadingState rows={1} />}>
      <Callback />
    </Suspense>
  );
}
