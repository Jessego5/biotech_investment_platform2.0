import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server bundle, so the runtime image carries the traced
  // dependencies rather than the whole of node_modules. Every route is dynamic
  // the chrome reads /stats on each request, so this has to be a server
  // not an export.
  output: "standalone",
};

export default nextConfig;
