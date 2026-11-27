import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "happy-dom", include: ["test/**/*.test.ts"] },
  esbuild: { tsconfigRaw: { compilerOptions: { useDefineForClassFields: false } } },
});
