/* Platform admin console: accounts, workspaces, plans and revenue. */
import {
  actionButton, api, bar, card, chip, clear, el, fmt, link, notice, pageHead,
  stat, table, tabs, toast,
} from "../core.js";
import { refresh, state } from "../router.js";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "users", label: "Users" },
  { key: "orgs", label: "Workspaces" },
  { key: "plans", label: "Plans & pricing" },
  { key: "billing", label: "Invoices" },
  { key: "mail", label: "Mail outbox" },
];

export async function console() {
  return consoleView();
}

export async function consoleView() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const active = params.get("tab") || "overview";
  const host = el("div");

  const data = await api.get("/admin/overview");
  const totals = data.totals;

  const body = el("div");
  clear(body);

  if (active === "overview") {
    const maxSignups = Math.max(1, ...data.signups_by_week.map((w) => w.signups));
    body.append(
      el("div", { class: "grid g4" },
        stat(totals.users, "Total accounts", `${totals.active_users_30d} active in 30 days`),
        stat(totals.orgs, "Workspaces", `${totals.creator_orgs} creator · ${totals.business_orgs} business`),
        stat(fmt.rupees(data.revenue.mrr_inr), "MRR", `${fmt.rupees(data.revenue.arr_inr)} ARR`),
        stat(totals.reviews_30d, "Reviews (30 days)", `${totals.ai_calls_30d} AI calls`)),
      el("div", { class: "split mt-5" },
        card(
          el("h3", { class: "h3" }, "Sign-ups per week"),
          el("div", { class: "trend mt-3" },
            ...data.signups_by_week.map((w) =>
              el("div", { class: "col" },
                el("div", { class: "v", style: { height: `${Math.max(4, (w.signups / maxSignups) * 90)}px` } }),
                el("span", { class: "x" }, w.week_start.slice(5))))),
          el("p", { class: "tiny muted mt-2" }, "Last eight weeks, from account creation timestamps.")),
        card(
          el("h3", { class: "h3" }, "Revenue mix"),
          el("div", { class: "stack-sm mt-3" },
            ...data.revenue.by_plan.map((p) =>
              bar(p.plan, p.count, Math.max(...data.revenue.by_plan.map((x) => x.count)), p.count === 1 ? " org" : " orgs"))),
          el("div", { class: "kv mt-4" },
            el("div", {}, el("dt", {}, "Paying workspaces"), el("dd", {}, String(data.revenue.paying_orgs))),
            el("div", {}, el("dt", {}, "Tokens (30d)"), el("dd", {}, `${totals.tokens_in_30d} in / ${totals.tokens_out_30d} out`)))),
      ),
      el("div", { class: "split mt-5" },
        card(
          el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Busiest workspaces"), link("/admin?tab=orgs", "All workspaces", "small strong")),
          el("div", { class: "mt-3" },
            table(["Workspace", "Type", "Plan", "Reviews", "MRR"],
              data.top_orgs.map((o) =>
                el("tr", {},
                  el("td", {}, el("div", { class: "strong small" }, o.name), el("div", { class: "tiny muted" }, o.status)),
                  el("td", { class: "small" }, fmt.title(o.account_type)),
                  el("td", {}, chip(o.plan_name, "sage")),
                  el("td", { class: "small num" }, String(o.reviews)),
                  el("td", { class: "small num" }, fmt.rupees(o.mrr_inr)))))),
        ),
        card(
          el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Newest accounts"), link("/admin?tab=users", "All users", "small strong")),
          el("div", { class: "stack-sm mt-3" },
            ...data.recent_users.map((u) =>
              el("div", { class: "row-between finding" },
                el("div", {},
                  el("div", { class: "small strong" }, u.name),
                  el("div", { class: "tiny muted" }, `${u.email} · ${u.org || "no workspace"}`)),
                el("div", { class: "row" },
                  chip(fmt.title(u.account_type), u.account_type === "creator" ? "lilac" : "sage"),
                  u.platform_role ? chip("admin", "brass") : null))))),
      ),
    );
  }

  if (active === "users") {
    const query = el("input", { class: "field", placeholder: "Search name or email", style: { maxWidth: "280px" } });
    const listHost = el("div", { class: "mt-4" });

    async function load() {
      const rows = await api.get(`/admin/users?query=${encodeURIComponent(query.value)}`);
      clear(listHost);
      listHost.append(
        table(["Person", "Type", "Workspace", "Plan", "Role", "Status", "Last active", "MRR", ""],
          rows.map((u) =>
            el("tr", {},
              el("td", {}, el("div", { class: "strong small" }, u.name), el("div", { class: "tiny muted" }, u.email)),
              el("td", {}, chip(fmt.title(u.account_type), u.account_type === "creator" ? "lilac" : "sage")),
              el("td", { class: "small" }, u.org_name || "—"),
              el("td", { class: "small" }, u.plan_name || "—"),
              el("td", { class: "small" }, u.role || "—"),
              el("td", {}, chip(u.status, u.status === "active" ? "sage" : "clay")),
              el("td", { class: "small muted" }, u.last_login_at ? fmt.date(u.last_login_at) : "never"),
              el("td", { class: "small num" }, fmt.rupees(u.mrr_inr)),
              el("td", {},
                el("button", {
                  class: "btn btn-quiet btn-sm", type: "button",
                  onclick: async () => {
                    const next = u.status === "active" ? "suspended" : "active";
                    try {
                      await api.patch(`/admin/users/${u.id}`, { status: next });
                      toast(`${u.name} is now ${next}.`);
                      load();
                    } catch (error) { toast(error.message, true); }
                  },
                }, u.status === "active" ? "Suspend" : "Reactivate")))),
          "No users match that search."),
      );
    }

    let timer;
    query.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(load, 250);
    });
    await load();
    body.append(el("div", { class: "row-between" }, query), listHost);
  }

  if (active === "orgs") {
    const rows = await api.get("/admin/orgs");
    const planOptions = (org) =>
      el("select", {
        class: "field", style: { maxWidth: "190px" },
        onchange: async (event) => {
          try {
            await api.patch(`/admin/orgs/${org.id}/plan`, { plan: event.target.value });
            toast(`${org.name} moved to ${event.target.value}.`);
            refresh();
          } catch (error) { toast(error.message, true); }
        },
      }, ...["creator_free", "creator_pro", "business_starter", "business_growth", "enterprise"]
        .filter((code) => code.startsWith(org.account_type))
        .map((code) => el("option", { value: code, selected: code === org.plan }, code)));

    body.append(
      table(["Workspace", "Type", "Plan", "Seats", "Brands", "Reviews / month", "MRR", "Created"],
        rows.map((o) =>
          el("tr", {},
            el("td", {}, el("div", { class: "strong small" }, o.name),
              el("div", { class: "tiny muted" }, `${o.slug} · ${o.status}`)),
            el("td", {}, chip(fmt.title(o.account_type), o.account_type === "creator" ? "lilac" : "sage")),
            el("td", {}, planOptions(o)),
            el("td", { class: "small" }, `${o.seats_used} / ${o.seats_limit}`),
            el("td", { class: "small" }, String(o.brands)),
            el("td", { class: "small" }, `${o.reviews_this_month} / ${o.reviews_limit}`),
            el("td", { class: "small num" }, fmt.rupees(o.mrr_inr)),
            el("td", { class: "small muted" }, fmt.date(o.created_at))))),
    );
  }

  if (active === "plans") {
    body.append(
      notice("Pricing model", "Plans are product configuration in one place. Changing a price here does not migrate existing subscriptions; the admin console moves a workspace between plans explicitly."),
      el("div", { class: "grid g3 mt-4" },
        ...data.plans.map((p) =>
          card(
            el("div", { class: "row-between" },
              el("h3", { class: "h3" }, p.name),
              chip(fmt.title(p.account_type), p.account_type === "creator" ? "lilac" : "sage")),
            el("div", { class: "serif mt-2", style: { fontSize: "26px" } },
              p.price_inr === null ? "Custom" : `₹${p.price_inr.toLocaleString("en-IN")}`,
              el("span", { class: "tiny muted", style: { marginLeft: "6px" } }, p.interval === "custom" ? "" : "/ month")),
            el("div", { class: "stack-sm mt-3 tiny muted" },
              el("div", {}, `${p.brands} brands`),
              el("div", {}, `${p.seats} seats`),
              el("div", {}, `${p.reviews_per_month.toLocaleString("en-IN")} reviews / month`)),
            el("div", { class: "hairline" }),
            el("div", { class: "row-between small" },
              el("span", { class: "muted" }, "Workspaces"),
              el("span", { class: "strong" }, String(p.orgs))),
            el("div", { class: "row-between small mt-1" },
              el("span", { class: "muted" }, "MRR from plan"),
              el("span", { class: "strong" }, fmt.rupees((p.price_inr || 0) * p.orgs))))),
      ),
    );
  }

  if (active === "billing") {
    const rows = await api.get("/admin/invoices");
    body.append(
      rows.length
        ? table(["Invoice", "Workspace", "Change", "Amount", "Status", "Date"],
            rows.map((r) =>
              el("tr", {},
                el("td", { class: "mono tiny" }, r.number),
                el("td", { class: "small" }, r.org),
                el("td", { class: "small" }, `${r.plan_from} → ${r.plan_to}`),
                el("td", { class: "small num" }, fmt.rupees(r.amount_inr)),
                el("td", {}, chip(r.status, r.status === "paid" ? "sage" : "amber")),
                el("td", { class: "small muted" }, fmt.date(r.created_at)))))
        : el("p", { class: "sub" }, "No invoices yet. A workspace can upgrade from its Plan & billing page."),
    );
  }

  if (active === "mail") {
    const rows = await api.get("/admin/mail");
    body.append(
      notice("Outbox", "Every message is stored here. With SMTP configured it is also sent; without it, this is where reset links and invites can be read."),
      el("div", { class: "stack mt-4" },
        ...(rows.length
          ? rows.map((m) =>
              el("div", { class: "card card-pad" },
                el("div", { class: "row-between" },
                  el("div", {}, el("div", { class: "small strong" }, m.subject),
                    el("div", { class: "tiny muted" }, `${m.to} · ${m.kind} · ${fmt.date(m.created_at)}`)),
                  chip(m.status, m.status === "sent" ? "sage" : m.status === "failed" ? "clay" : "amber")),
                el("pre", { class: "tiny mt-2", style: { whiteSpace: "pre-wrap", fontFamily: "var(--mono)", color: "var(--muted)" } }, m.body)))
          : [el("p", { class: "sub" }, "No messages yet.")])),
    );
  }

  return el("div", {},
    pageHead("Admin console",
      `Platform operator view · ${totals.users} accounts, ${totals.orgs} workspaces, ${fmt.rupees(data.revenue.mrr_inr)} MRR.`,
      chip("Platform admin", "brass")),
    el("nav", { class: "tabs" },
      ...TABS.map((t) => el("a", { class: `tab${t.key === active ? " active" : ""}`, href: `#/admin?tab=${t.key}` }, t.label))),
    body,
  );
}
