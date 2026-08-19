export const PAGE_SIZE = 10;

export type MatchRange = [number, number];

/** Return [start, end) ranges of query matches inside text (case-insensitive). */
export function findMatchRanges(text: string, query: string): MatchRange[] {
  const q = query.trim();
  if (!q) return [];

  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  const ranges: MatchRange[] = [];
  let start = 0;
  let idx = lower.indexOf(needle);

  while (idx !== -1) {
    ranges.push([idx, idx + needle.length]);
    start = idx + needle.length;
    idx = lower.indexOf(needle, start);
  }

  return ranges;
}

export function paginate<T>(
  items: T[],
  page: number,
  pageSize: number = PAGE_SIZE,
): { pageItems: T[]; totalPages: number; currentPage: number; start: number } {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const start = (currentPage - 1) * pageSize;
  return {
    pageItems: items.slice(start, start + pageSize),
    totalPages,
    currentPage,
    start,
  };
}

/** e.g. [1, "ellipsis", 4, 5, 6, "ellipsis", 20] */
export function pageWindow(
  current: number,
  total: number,
  radius = 2,
): Array<number | "ellipsis"> {
  if (total <= 1) return total === 1 ? [1] : [];
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = new Set<number>([1, total]);
  for (let i = current - radius; i <= current + radius; i++) {
    if (i >= 1 && i <= total) pages.add(i);
  }
  const sorted = [...pages].sort((a, b) => a - b);
  const out: Array<number | "ellipsis"> = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
      out.push("ellipsis");
    }
    out.push(sorted[i]);
  }
  return out;
}
