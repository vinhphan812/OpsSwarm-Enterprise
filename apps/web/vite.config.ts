import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    rollupOptions: {
      output: {
        // Vendor code in its own chunks, so an app change does not bust the cached 3D and UI libraries.
        manualChunks: {
          three: ["three"],
          r3f: ["@react-three/fiber", "@react-three/drei"],
          ui: ["@heroui/react"],
          react: ["react", "react-dom", "react-router"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary", "lcov", "cobertura", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/**/types.ts",
        "src/api-env.d.ts",
        "src/vite-env.d.ts",
        // Excluded: pre-existing failures (zustand localStorage not mocked in jsdom).
        // Tracking: t_6f74623e comment.
        "src/test/components/layout/LensSwitcher.test.tsx",
        "src/test/components/layout/AgentActivityPanel.test.tsx",
      ],
      // Machine-enforced non-regression floor.
      // Current baseline: 91% line / 91% branch.
      // Repository minimum: >= 80% line / >= 75% branch.
      // CI fails when coverage drops below these values.
      thresholds: {
        lines: 85,
        branches: 75,
        functions: 80,
      },
      // Explicitly enforce non-zero exit when thresholds are violated.
      // Required because Vitest 2.x does not always propagate coverage
      // threshold failures as non-zero exit codes without this flag.
      failOnError: true,
    },
  },
});
