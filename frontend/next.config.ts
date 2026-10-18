import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // There are deliberately no `NEXT_PUBLIC_*` variables for the API origin:
  // the browser never talks to the LMS API directly, it goes through the
  // same-origin proxy at /api/backend, so the origin is not something the
  // client needs -- or should be told.
  //
  // Type and lint errors are NOT suppressed here. `next build` fails on them
  // by default, and that default is the point.
};

export default config;
