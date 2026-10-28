/** The admin console's pages, in the order its navigation lists them. */
export const ADMIN_PAGES = ["dashboard", "config", "prompts", "users", "announcements"] as const;

export type AdminPage = (typeof ADMIN_PAGES)[number];

/** Where each page of the admin console is. */
export const ADMIN_HREFS: Record<AdminPage, string> = {
  dashboard: "/admin",
  config: "/admin/config",
  prompts: "/admin/prompts",
  users: "/admin/users",
  announcements: "/admin/announcements",
};

/** The page of the admin console `pathname` is on, or under (a user's details are under
 * users, an announcement under announcements); the dashboard, which `/admin` itself is, for any other. */
export function adminPage(pathname: string): AdminPage {
  for (const page of ADMIN_PAGES) {
    const href = ADMIN_HREFS[page];
    if (page !== "dashboard" && (pathname === href || pathname.startsWith(`${href}/`))) return page;
  }
  return "dashboard";
}
