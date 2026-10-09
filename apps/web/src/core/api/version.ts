/**
 * Revision number of a context version such as `"store-001:v23871"` or `"v1"`.
 * Null when the string carries no `v<number>` suffix.
 */
export function contextRevision(version: string): number | null {
  const match = /v(\d+)$/.exec(version);
  return match ? Number(match[1]) : null;
}

/**
 * True when `next` should replace `current`: it is newer, or either revision cannot
 * be read (then order of arrival is the best evidence available).
 */
export function isNewerVersion(next: string, current: string | null): boolean {
  if (current === null) return true;
  const a = contextRevision(next);
  const b = contextRevision(current);
  return a === null || b === null ? next !== current : a > b;
}
