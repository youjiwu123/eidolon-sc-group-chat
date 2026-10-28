import { describe, expect, it } from "vitest";

import { adminPage } from "@/lib/admin";

describe("adminPage", () => {
  it("picks the admin console page a path is on, the dashboard by default", () => {
    const cases: [string, ReturnType<typeof adminPage>][] = [
      ["/admin", "dashboard"],
      ["/admin/prompts", "prompts"],
      ["/admin/users", "users"],
      ["/admin/users/u-123", "users"],
      ["/admin/usersettings", "dashboard"],
    ];
    for (const [path, page] of cases) expect(adminPage(path), path).toBe(page);
  });
});
