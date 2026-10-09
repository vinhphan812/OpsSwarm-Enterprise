import { describe, expect, it } from "vitest";
import { issueReason, type IssueCode } from "@/core/api/validate";
import i18n from "@/i18n";
import { en } from "@/i18n/locales/en";

/** Every key path of a message tree, such as `twin.loading`. */
function keys(tree: object, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "string" ? [`${prefix}${key}`] : keys(value as object, `${prefix}${key}.`),
  );
}

describe("i18n", () => {
  it("runs in English", () => {
    expect(i18n.language).toBe("en");
    expect(i18n.t("twin.loading")).toBe(en.twin.loading);
  });

  it("has a non-empty message for every key", () => {
    for (const key of keys(en)) {
      expect(i18n.t(key as never), key).not.toBe("");
      expect(i18n.t(key as never), key).not.toBe(key);
    }
  });

  it("fills a product issue's values into its reason", () => {
    const issue = {
      sku: "P001",
      code: "slotNotOnShelf",
      values: { slotId: "A01-S99", shelfId: "A01" },
    } as const;
    expect(issueReason(issue)).toBe("slot A01-S99 is not on shelf A01");
  });

  it("leaves no placeholder unfilled in any issue reason", () => {
    for (const code of Object.keys(en.issue) as IssueCode[]) {
      const values = Object.fromEntries(
        [...en.issue[code].matchAll(/\{\{(\w+)\}\}/g)].map(([, name]) => [name, "x"]),
      );
      expect(issueReason({ sku: "P001", code, values }), code).not.toContain("{{");
    }
  });
});
