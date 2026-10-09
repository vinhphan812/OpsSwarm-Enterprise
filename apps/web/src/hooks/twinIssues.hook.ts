import { useMemo } from "react";
import type { ProductIssue } from "@/core/api/validate";
import { twinIssues } from "@/core/twin/twinIssues";
import { useTwinStore } from "@/state/twin.store";

/** Products of the live state that the scene leaves out, kept in step with the twin store. */
export function useTwinIssues(): ProductIssue[] {
  const live = useTwinStore((state) => state.live);
  const contractIssues = useTwinStore((state) => state.issues);
  return useMemo(() => twinIssues(live, contractIssues), [live, contractIssues]);
}
