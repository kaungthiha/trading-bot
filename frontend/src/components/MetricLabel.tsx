import type { ReactNode } from "react";

import type { TermId } from "../glossary/terms";
import { Term } from "./Term";

/** Glossary-aware label for table headers and metric cards (explain once per table). */
export function MetricLabel({ termId, children }: { termId: TermId; children: ReactNode }) {
  return <Term id={termId}>{children}</Term>;
}
