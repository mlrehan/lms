"use client";

/**
 * The chime when a notification arrives.
 *
 * **Synthesised, not a file.** A short tone from the Web Audio API costs no
 * asset, no request and no 404 when somebody forgets to deploy `public/`. It
 * also cannot be the wrong length or the wrong loudness for the device,
 * because there is nothing recorded to be wrong.
 *
 * **What this cannot do, and does not pretend to.** A browser will not let a
 * page make a sound before the person has interacted with it, and the volume
 * belongs to the device and the operating system. So `prominent` is a longer,
 * more insistent pattern -- three rising notes rather than one -- and not a
 * louder one: raising the volume past what somebody chose is not ours to do,
 * and attempting it is how an application ends up muted permanently.
 *
 * **Only when the tab is visible.** If it is not, the push notification is
 * what announces this, with the operating system's own sound. Doing both is
 * the thing that makes people switch notifications off altogether -- the same
 * reasoning as the service worker's focused-window check, applied from the
 * other side.
 */

export type SoundMode = "off" | "subtle" | "prominent";

/** One AudioContext for the page: browsers cap how many may exist. */
let context: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    context ??= new Ctor();
    return context;
  } catch {
    // Audio unavailable (a locked-down browser, a device with no output).
    // A missing chime is not worth an error anybody sees.
    return null;
  }
}

/** One note. `when` is seconds from now. */
function note(ctx: AudioContext, frequency: number, when: number, seconds: number, peak: number): void {
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = frequency;

  const start = ctx.currentTime + when;
  // Ramped rather than switched on: an abrupt start produces an audible click,
  // which reads as a glitch rather than as a notification.
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peak, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + seconds);

  oscillator.connect(gain).connect(ctx.destination);
  oscillator.start(start);
  oscillator.stop(start + seconds + 0.02);
}

export function playNotificationTone(mode: SoundMode): void {
  if (mode === "off") return;
  if (typeof document !== "undefined" && document.visibilityState !== "visible") return;

  const ctx = audio();
  if (!ctx) return;

  // Suspended until the person has interacted with the page. Resuming is a
  // request, not a guarantee; if it is refused the notification still arrives
  // in the tray and on the badge, which is the part that matters.
  void ctx.resume?.().catch(() => undefined);

  try {
    if (mode === "subtle") {
      note(ctx, 880, 0, 0.12, 0.05);
      return;
    }
    // `prominent`: three rising notes, longer and harder to miss -- the same
    // peak as `subtle`, because loudness is the device's business.
    note(ctx, 660, 0, 0.14, 0.07);
    note(ctx, 880, 0.16, 0.14, 0.07);
    note(ctx, 1175, 0.32, 0.26, 0.07);
  } catch {
    // Nothing here is worth failing a notification over.
  }
}
