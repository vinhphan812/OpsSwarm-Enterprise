import { afterEach, describe, expect, it } from "vitest";
import { issueReason } from "@/core/api/validate";
import i18n, { setLanguage } from "@/i18n";
import { en } from "@/i18n/locales/en";
import { vi } from "@/i18n/locales/vi";

/** Every key path of a message tree, such as `twin.loading`. */
function keys(tree: object, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "string" ? [`${prefix}${key}`] : keys(value as object, `${prefix}${key}.`),
  );
}

/** Interpolation names in a message, such as `count` in `{{count}} more`. */
const placeholders = (text: string) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();

const lookup = (tree: object, path: string) =>
  path.split(".").reduce<unknown>((node, key) => (node as Record<string, unknown>)[key], tree) as string;

describe("locales", () => {
  afterEach(() => i18n.changeLanguage("en"));

  it("give English the same keys and placeholders as Vietnamese", () => {
    expect(keys(en)).toEqual(keys(vi));
    for (const path of keys(vi)) expect(placeholders(lookup(en, path)), path).toEqual(placeholders(lookup(vi, path)));
  });

  it("translate a product issue in the active language", () => {
    const issue = { sku: "P001", code: "slotNotOnShelf", values: { slotId: "A01-S99", shelfId: "A01" } } as const;
    expect(issueReason(issue)).toBe("slot A01-S99 is not on shelf A01");
    setLanguage("vi");
    expect(issueReason(issue)).toBe("slot A01-S99 không thuộc kệ A01");
  });
});
