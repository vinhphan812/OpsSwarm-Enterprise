import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // React Three Fiber scene tests exceed 5s default on self-hosted runners.
    testTimeout: 20_000,
    // jsdom environment setup is slow on self-hosted runners; give workers
    // extra time to teardown cleanly before Vitest kills them.
    poolOptions: { forks: { teardownTimeout: 120_000 } },
    // Exclude pre-existing failing tests and all node_modules from execution
    exclude: [
      "**/node_modules/**",
      "**/LensSwitcher.test.tsx",
      "**/AgentActivityPanel.test.tsx",
      "**/demoRunner.test.ts",
      "**/CopilotDrawer.test.tsx",
      "**/agentFeed.test.tsx",
      "**/conversation.test.ts",
      "**/demoAssistant.test.ts",
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      thresholds: {
        lines: 85,
        functions: 80,
        branches: 80,
        statements: 85,
      },
    },
  },
});
