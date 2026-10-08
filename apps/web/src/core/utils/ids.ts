/** Zero-padded id with a prefix, for example `padId("S", 3) === "S03"`. */
export function padId(prefix: string, index: number, digits = 2): string {
  return `${prefix}${String(index).padStart(digits, "0")}`;
}
