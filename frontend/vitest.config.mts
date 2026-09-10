import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "url";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],

    // The default `forks` pool times out spawning workers on this Windows
    // host; threads start reliably and nothing here needs process isolation.
    pool: "threads",

    // Each test file pays ~30s for its own jsdom environment on this machine.
    // Run them two at a time rather than seven: with seven in flight the CPU
    // contention alone pushed component renders past the default 5s timeout,
    // which looks exactly like a slow component and is not one.
    maxWorkers: 2,
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
