import { describe, expect, it } from "vitest";
import { findMatchRanges, paginate, pageWindow, PAGE_SIZE } from "./result";

describe("findMatchRanges", () => {
  it("finds substring matches case-insensitively", () => {
    expect(findMatchRanges("17.13.9", "13")).toEqual([[3, 5]]);
    expect(findMatchRanges("AbC", "bc")).toEqual([[1, 3]]);
  });

  it("returns empty for blank query", () => {
    expect(findMatchRanges("17.13.9", "  ")).toEqual([]);
  });

  it("finds multiple occurrences", () => {
    expect(findMatchRanges("1.1.1", "1")).toEqual([
      [0, 1],
      [2, 3],
      [4, 5],
    ]);
  });
});

describe("paginate", () => {
  const items = Array.from({ length: 25 }, (_, i) => i + 1);

  it("slices by page size", () => {
    const { pageItems, totalPages, currentPage, start } = paginate(items, 2);
    expect(PAGE_SIZE).toBe(10);
    expect(totalPages).toBe(3);
    expect(currentPage).toBe(2);
    expect(start).toBe(10);
    expect(pageItems).toEqual([11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
  });

  it("clamps out-of-range page", () => {
    expect(paginate(items, 99).currentPage).toBe(3);
    expect(paginate(items, 0).currentPage).toBe(1);
  });
});

describe("pageWindow", () => {
  it("lists all pages when few", () => {
    expect(pageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("inserts ellipsis for a large range", () => {
    expect(pageWindow(10, 30)).toEqual([
      1,
      "ellipsis",
      8,
      9,
      10,
      11,
      12,
      "ellipsis",
      30,
    ]);
  });
});
