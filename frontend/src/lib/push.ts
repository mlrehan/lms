"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { PushKeyResponse } from "@/lib/api/types";

/**
 * Subscribing this browser to notifications that arrive with the tab closed.
 *
 * Three things have to be true before the control is worth showing, and they
 * fail independently: the deployment has VAPID keys, the browser supports
 * service workers and the Push API, and the page is on a secure origin (Push
 * is refused on plain http, `localhost` excepted). `state` reports which of
 * those is missing, because "Subscribe did nothing" is the least actionable
 * failure a person can be handed.
 *
 * The permission prompt is **only** raised from a click. A prompt on page load
 * is the pattern browsers now penalise -- Chrome and Firefox both suppress
 * repeat prompts from an origin people dismissed -- so an unprompted ask can
 * permanently cost this deployment the ability to ever ask again.
 */

export type PushState =
  | "checking" // still working out which of the below applies
  | "unsupported" // no service worker or Push API in this browser
  | "insecure" // not https, and not localhost
  | "disabled" // the server has no VAPID keys
  | "denied" // the person said no; only they can undo it, in site settings
  | "subscribed"
  | "available";

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  // `applicationServerKey` wants raw bytes. The server sends the key
  // url-safe and unpadded, which is what the spec requires and what
  // `atob` cannot read without this conversion.
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  // Built over an explicit ArrayBuffer: `Uint8Array.from` is typed as
  // ArrayBufferLike, which `applicationServerKey` (a BufferSource over a real
  // ArrayBuffer) will not accept.
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function secure(): boolean {
  // `isSecureContext` already treats localhost as secure, which is what makes
  // this testable in development without a certificate.
  return typeof window !== "undefined" && window.isSecureContext;
}

export function usePushSubscription(): {
  state: PushState;
  busy: boolean;
  subscribe: () => Promise<void>;
  unsubscribe: () => Promise<void>;
  error: string | null;
} {
  // Starts as "checking" rather than a guess. The synchronous checks below
  // read `window`, which does not exist during server rendering -- seeding
  // state from them would render one answer on the server and a different one
  // in the browser, which is a hydration mismatch.
  const [state, setState] = useState<PushState>("checking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Works out which state applies. Returns it rather than setting it, so the
   *  effect below owns every write and can drop a late one. */
  const detect = useCallback(async (): Promise<PushState> => {
    if (!supported()) return "unsupported";
    if (!secure()) return "insecure";

    let key: PushKeyResponse;
    try {
      key = await api.get<PushKeyResponse>("/push/key");
    } catch {
      return "disabled";
    }
    if (!key.enabled || !key.public_key) return "disabled";
    if (Notification.permission === "denied") return "denied";

    const registration = await navigator.serviceWorker.getRegistration("/sw.js");
    const existing = await registration?.pushManager.getSubscription();
    return existing ? "subscribed" : "available";
  }, []);

  const refresh = useCallback(async () => {
    setState(await detect());
  }, [detect]);

  useEffect(() => {
    // `cancelled` matters because every path here awaits: navigating away
    // mid-check would otherwise set state on an unmounted component.
    let cancelled = false;
    void (async () => {
      const next = await detect();
      if (!cancelled) setState(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [detect]);

  const subscribe = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const key = await api.get<PushKeyResponse>("/push/key");
      if (!key.public_key) throw new Error("This server has no push keys configured.");

      const registration = await navigator.serviceWorker.register("/sw.js");
      // `ready` rather than the register() result: a worker that is installed
      // but not yet activated cannot receive a push, and subscribing before
      // then produces a subscription that silently drops the first messages.
      await navigator.serviceWorker.ready;

      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "available");
        return;
      }

      const subscription = await registration.pushManager.subscribe({
        // Required to be true by every browser that implements Push: a
        // subscription that might deliver a silent push is not allowed.
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key.public_key),
      });

      const json = subscription.toJSON() as {
        endpoint?: string;
        keys?: { p256dh?: string; auth?: string };
      };
      await api.post("/push/subscriptions", {
        body: {
          endpoint: json.endpoint,
          p256dh: json.keys?.p256dh,
          auth: json.keys?.auth,
        },
      });
      setState("subscribed");
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const unsubscribe = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const registration = await navigator.serviceWorker.getRegistration("/sw.js");
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription) {
        // Told the server *before* the browser drops it: once `unsubscribe()`
        // resolves the endpoint is gone from this page, and a failure after
        // that point would leave a row the server keeps pushing to until the
        // push service reports it dead.
        await api.post("/push/unsubscribe", { body: { endpoint: subscription.endpoint } });
        await subscription.unsubscribe();
      }
      setState("available");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  return { state, busy, subscribe, unsubscribe, error };
}
