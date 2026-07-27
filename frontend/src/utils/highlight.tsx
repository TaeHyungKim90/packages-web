import type { ReactNode } from "react";
import { findMatchRanges } from "./result";

export function highlightMatch(text: string, query: string): ReactNode {
  const ranges = findMatchRanges(text, query);
  if (ranges.length === 0) return text;

  const parts: ReactNode[] = [];
  let cursor = 0;

  for (const [start, end] of ranges) {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={`${start}-${end}`} className="version-highlight">
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  }

  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}
