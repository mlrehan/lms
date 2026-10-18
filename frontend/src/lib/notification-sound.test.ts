import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The chime.
 *
 * Two rules are worth protecting, and both are about *not* making a sound:
 * silent means silent, and a hidden tab says nothing because the push
 * notification is already announcing it with the operating system's own sound.
 * Doing both is what makes people switch notifications off altogether.
 *
 * The module keeps one AudioContext for the page, because browsers cap how
 * many may exist -- so each test imports the module afresh rather than
 * inheriting a context built against a previous test's stub.
 *
 * The third rule is that nothing here may throw. A browser that refuses audio --
 * locked down, no output device, autoplay not yet unlocked -- must cost a
 * missing chime and not a broken notification handler.
 */

class FakeOscillator {
  type = "";
  frequency = { value: 0 };
  connect = vi.fn(() => ({ connect: vi.fn() }));
  start = vi.fn();
  stop = vi.fn();
}

function fakeAudio() {
  const oscillators: FakeOscillator[] = [];
  class FakeContext {
    currentTime = 0;
    destination = {};
    resume = vi.fn(() => Promise.resolve());
    createOscillator() {
      const o = new FakeOscillator();
      oscillators.push(o);
      return o;
    }
    createGain() {
      return {
        gain: {
          setValueAtTime: vi.fn(),
          exponentialRampToValueAtTime: vi.fn(),
        },
        connect: vi.fn(() => ({ connect: vi.fn() })),
      };
    }
  }
  vi.stubGlobal("AudioContext", FakeContext);
  return oscillators;
}

function visible(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

async function load() {
  // Fresh module per test: the AudioContext singleton is deliberate in
  // production and would otherwise carry one test's stub into the next.
  vi.resetModules();
  return (await import("./notification-sound")).playNotificationTone;
}

beforeEach(() => {
  visible("visible");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  visible("visible");
});

describe("playNotificationTone", () => {
  it("says nothing when the person chose silent", async () => {
    const oscillators = fakeAudio();
    (await load())("off");
    expect(oscillators).toHaveLength(0);
  });

  it("plays one note for subtle", async () => {
    const oscillators = fakeAudio();
    (await load())("subtle");
    expect(oscillators).toHaveLength(1);
  });

  it("plays a longer pattern for prominent, not a louder one", async () => {
    const oscillators = fakeAudio();
    (await load())("prominent");
    expect(oscillators.length).toBeGreaterThan(1);
    // Rising, so it reads as insistent rather than as a repeated error beep.
    const pitches = oscillators.map((o) => o.frequency.value);
    expect([...pitches].sort((a, b) => a - b)).toEqual(pitches);
  });

  it("says nothing when the tab is hidden, because the push already did", async () => {
    const oscillators = fakeAudio();
    visible("hidden");
    (await load())("prominent");
    expect(oscillators).toHaveLength(0);
  });

  it("is silent rather than broken when the browser refuses audio", async () => {
    vi.stubGlobal("AudioContext", undefined);
    const play = await load();
    expect(() => play("prominent")).not.toThrow();
  });

  it("is silent rather than broken when constructing a context throws", async () => {
    vi.stubGlobal(
      "AudioContext",
      class {
        constructor() {
          throw new Error("not allowed");
        }
      },
    );
    const play = await load();
    expect(() => play("subtle")).not.toThrow();
  });
});
