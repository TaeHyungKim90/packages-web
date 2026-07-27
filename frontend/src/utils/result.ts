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
