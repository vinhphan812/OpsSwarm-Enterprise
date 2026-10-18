import { describe, expect, it } from "vitest";
import { buildLabel } from "@/core/app/buildInfo";

describe("buildLabel", () => {
  it("shows the version CD passes with the build SHA", () => {
    expect(buildLabel({ VITE_APP_VERSION: "0.8.0", VITE_GIT_SHA: "abc1234" })).toBe("v0.8.0+abc1234");
    expect(buildLabel({ VITE_APP_VERSION: "v0.8.0", VITE_GIT_SHA: "" })).toBe("v0.8.0");
  });

  it("shows the SHA alone without a version, and nothing without either", () => {
    expect(buildLabel({ VITE_GIT_SHA: "abc1234" })).toBe("abc1234");
    expect(buildLabel({ VITE_APP_VERSION: " ", VITE_GIT_SHA: undefined })).toBeNull();
  });
});
