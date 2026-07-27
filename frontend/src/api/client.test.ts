import { describe, expect, it } from "vitest";
import { getLoginUrl } from "../api/client";

describe("auth client helpers", () => {
  it("builds relative login url when API base is empty", () => {
    expect(getLoginUrl()).toBe("/api/auth/login");
  });
});
