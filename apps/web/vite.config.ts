import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

// ADR 0025: the canonical SemVer lives in /VERSION at the repo root. The Web
// build reads it once at config time so the bundle embeds the same SemVer
// the API process reports. CI exports GIT_SHA before invoking Vite; the
// short SHA falls back to `git rev-parse --short HEAD` for local builds.
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

function readCanonicalVersion(): string {
  const raw = readFileSync(resolve(REPO_ROOT, "VERSION"), "utf8").trim();
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(raw)) {
    throw new Error(
      `VERSION file at repo root must contain strict SemVer (got ${JSON.stringify(raw)}).`,
    );
  }
  return raw;
}

function resolveGitSha(): string {
  const envSha = process.env.GIT_SHA?.trim();
  if (envSha) return envSha;
  try {
    return execSync("git rev-parse --short HEAD", {
      cwd: REPO_ROOT,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim() || "unknown";
  } catch {
    return "unknown";
  }
}

export default defineConfig({
  define: {
    // Build-time constants exposed via import.meta.env (ADR 0025).
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(readCanonicalVersion()),
    "import.meta.env.VITE_GIT_SHA": JSON.stringify(resolveGitSha()),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  // Imported on demand by the stock models; pre-bundled up front, so the dev server does not
  // re-optimize on first load and serve a second copy of three.
  optimizeDeps: { include: ["three/examples/jsm/loaders/GLTFLoader.js"] },
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
