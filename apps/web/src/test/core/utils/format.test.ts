import { describe, expect, it } from "vitest";
import { format, relativeChange } from "@/core/utils/format";

describe("format", () => {
  it("shows money in US dollars", () => {
    expect(format.money(0)).toBe("$0");
    expect(format.money(12_400)).toBe("$12.4K");
    expect(format.moneyExact(1234.5)).toBe("$1,234.50");
  });

  it("signs changes but not zero", () => {
    expect(format.change(0.08)).toBe("+8%");
    expect(format.change(-0.125)).toBe("-12.5%");
    expect(format.change(0)).toBe("0%");
  });
});

describe("relativeChange", () => {
  it("has nothing to compare with a zero baseline", () => {
    expect(relativeChange(0, 0)).toBeNull();
    expect(relativeChange(5, 0)).toBeNull();
    expect(relativeChange(110, 100)).toBeCloseTo(0.1);
  });
});
