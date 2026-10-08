import { describe, expect, it } from "vitest";
import { formatters, relativeChange } from "@/core/utils/format";

describe("formatters", () => {
  it("show money in each language's currency", () => {
    expect(formatters("en").money(0)).toBe("$0");
    expect(formatters("en").money(12_400)).toBe("$12.4K");
    expect(formatters("vi").moneyExact(0)).toMatch(/^0\s₫$/);
  });

  it("sign changes but not zero", () => {
    const f = formatters("en");
    expect(f.change(0.08)).toBe("+8%");
    expect(f.change(-0.125)).toBe("-12.5%");
    expect(f.change(0)).toBe("0%");
  });
});

describe("relativeChange", () => {
  it("has nothing to compare with a zero baseline", () => {
    expect(relativeChange(0, 0)).toBeNull();
    expect(relativeChange(5, 0)).toBeNull();
    expect(relativeChange(110, 100)).toBeCloseTo(0.1);
  });
});
