import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // This repo is a Python service with the Readbase frontend alongside it.
    // Keep the linter on the Next.js app and out of everything else.
    "node_modules/**",
    "backend/**",
    "frontend/**",
    "infra/**",
    "design/**",
  ]),
]);

export default eslintConfig;
