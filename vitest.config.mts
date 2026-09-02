import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // the same "@/" the app uses, so a test imports a module by the path the
  // component does and cannot drift from it
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: { include: ["lib/**/*.test.ts", "components/**/*.test.ts"] },
});
