/*
 * The service worker that shows a notification when the console is closed.
 *
 * **This file decides whether to interrupt, and the server deliberately does
 * not.** The server pushes every notification without asking whether the person
 * is online, because it cannot know: a tab left open in a background window
 * holds a live connection and is read by nobody, and somebody reading on their
 * phone has no connection on the laptop that does. `clients.matchAll()` answers
 * the question that actually matters -- is a window of this app open *and
 * focused right now* -- and only the browser can answer it.
 *
 * Kept deliberately small. A service worker persists across deploys until it is
 * replaced, so a bug here outlives the release that introduced it; there is no
 * build step, no import and no framework in this file for that reason.
 */

self.addEventListener("install", () => {
  // Take over immediately instead of waiting for every tab to close. Otherwise
  // a fixed worker does not reach the person who already has the app open --
  // which is most of them.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

function readPayload(event) {
  if (!event.data) return {};
  try {
    return event.data.json();
  } catch {
    // A push whose body is not our JSON is either a malformed send or a
    // browser's own keepalive. Showing a generic notice beats showing nothing,
    // because a push that renders nothing at all is a silent failure.
    return { title: "New activity" };
  }
}

self.addEventListener("push", (event) => {
  const payload = readPayload(event);

  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });

      // Already looking at it: the in-page toast and the unread badge have
      // already told them. A banner as well is the thing that makes people
      // turn notifications off entirely.
      const focused = windows.some((client) => client.focused && client.visibilityState === "visible");
      if (focused) return;

      await self.registration.showNotification(payload.title || "New activity", {
        body: payload.body || "",
        // Same tag replaces an unread banner instead of stacking a tenth one
        // for the tenth message in a thread.
        tag: payload.tag || "lms",
        renotify: false,
        // No `icon`/`badge`: this app ships no PWA icon set, and pointing at a
        // file that is not there produces a broken image in the banner on some
        // platforms. The browser's own default is better than a dead reference.
        data: { url: payload.url || "/notifications" },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/notifications";

  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });

      // Focus an existing tab rather than opening a third copy of the console.
      for (const client of windows) {
        if ("focus" in client) {
          await client.focus();
          if ("navigate" in client) await client.navigate(target);
          return;
        }
      }
      await self.clients.openWindow(target);
    })(),
  );
});
