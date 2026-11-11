/* Landing redirect, creator dashboard and business dashboard. */
import {
  actionButton, api, bar, card, chip, clear, dial, el, empty, fmt, kv, link,
  notice, pageHead, plural, riskBadge, stat, statusChip, table, toast,
} from "../core.js";
import { navigate, refresh, reloadShell, state } from "../router.js";

export async function landing() {
  const session = state.session;
  navigate(session ? (session.org.account_type === "creator" ? "/creator" : "/business") : "/login");
  return el("div", { class: "skeleton", style: { height: "120px" } });
}

function quotaCard(usage) {
  const pct = usage.reviews_limit ? Math.min(100, Math.round((usage.reviews_used / usage.reviews_limit) * 100)) : 0;
  return card(
    el("div", { class: "card-head" },
      el("h3", { class: "h3" }, "Plan & usage"),
      chip(usage.plan_name, "sage")),
    el("div", { class: "mt-3" },
      el("div", { class: "row-between small" },
        el("span", { class: "muted" }, "Reviews this month"),
        el("span", { class: "strong" }, `${usage.reviews_used} / ${usage.reviews_limit}`)),
      el("div", { class: "bar-track mt-2" },
        el("div", { class: "bar-fill", style: { width: `${Math.max(pct, 2)}%`, background: pct > 85 ? "var(--clay-ink)" : "" } }))),
    el("div", { class: "kv mt-4" },
      el("div", {}, el("dt", {}, "Brands"), el("dd", {}, `${usage.brands_used} / ${usage.brands_limit}`)),
      el("div", {}, el("dt", {}, "Seats"), el("dd", {}, `${usage.seats_used} / ${usage.seats_limit}`)),
      el("div", {}, el("dt", {}, "AI calls"), el("dd", {}, String(usage.ai_calls))),
      el("div", {}, el("dt", {}, "Tokens"), el("dd", {}, `${usage.tokens_in} / ${usage.tokens_out}`))),
    usage.over_review_limit
      ? el("div", { class: "mt-3" }, notice("Quota reached", "New reviews are blocked until the plan renews or you upgrade.", "clay"))
      : null,
  );
}

/* ------------------------------------------------------- creator dashboard */
export async function creatorDashboard() {
  const data = await api.get("/workspace/creator");
  const counts = data.counts;
  const brand = data.brand;

  const actions = data.next_actions.length
    ? card(
        el("h3", { class: "h3" }, "Do this next"),
        el("div", { class: "stack-sm mt-3" },
          ...data.next_actions.map((a) =>
            el("a", { class: "finding", href: a.href, style: { display: "block" } },
              el("div", { class: "row-between" },
                el("span", { class: "strong small" }, a.label),
                el("span", { class: "tiny muted" }, "open →")),
              el("div", { class: "tiny muted mt-1" }, a.detail)))),
      )
    : null;

  const reviewRows = data.recent_reviews.map((r) =>
    el("tr", {},
      el("td", {}, link(`/reviews/${r.id}`, r.content_title, "strong"),
        el("div", { class: "tiny muted" }, `v${r.content_version} · ${fmt.title(r.channel)}`)),
      el("td", {}, riskBadge(r.risk_score, r.risk_band)),
      el("td", {}, statusChip(r.status)),
      el("td", { class: "small muted" }, fmt.date(r.created_at))));

  const coaching = data.coaching;

  return el("div", {},
    pageHead(
      `Hi ${data.account.name.split(" ")[0]}`,
      `Your workspace, your brand, your clearances. Plan: ${data.account.plan}.`,
      [chip(plural(counts.reviews, "review"), "neutral"), el("a", { class: "btn btn-primary", href: "#/studio" }, "Check new content")],
    ),

    el("div", { class: "grid g4" },
      stat(counts.reviews, "Reviews run", `${plural(counts.content_items, "item")} submitted`),
      stat(counts.open_flags, "Open flags", "Findings waiting on you"),
      stat(counts.legal_flags, "Legal flags", "Guidelines engaged", ),
      stat(counts.cleared, "Cleared", "Valid passports")),

    el("div", { class: "split mt-5" },
      el("div", { class: "stack" },
        actions,
        brand
          ? card(
              el("div", { class: "card-head" },
                el("h2", { class: "h2" }, brand.name),
                chip(`Policy v${data.policy.version ?? "–"}`, data.policy.enforced ? "sage" : "amber")),
              el("p", { class: "sub" }, brand.audience || "Add an audience so checks can be sharper."),
              el("div", { class: "row mt-3" },
                chip(brand.languages.map(fmt.language).join(" · ") || "EN"),
                chip(`${brand.asset_count} assets`),
                !data.policy.enforced ? chip("policy not enforced yet", "amber") : null),
              el("div", { class: "row mt-4" },
                el("a", { class: "btn btn-ghost", href: `#/brands/${brand.id}/dna` }, "Open my brand"),
                el("a", { class: "btn btn-quiet", href: "#/studio" }, "Check content")),
              el("div", { class: "hairline" }),
              el("div", { class: "grid g3" },
                el("div", {}, el("div", { class: "tiny muted" }, "Rules enforced"), el("div", { class: "strong" }, String(data.policy.rules))),
                el("div", {}, el("div", { class: "tiny muted" }, "Approved by"), el("div", { class: "strong" }, data.policy.approved_by || "—")),
                el("div", {}, el("div", { class: "tiny muted" }, "Member since"), el("div", { class: "strong" }, fmt.date(data.account.member_since)))))
          : empty("No brand yet", "Create your personal brand to start checking content.", el("a", { class: "btn btn-primary", href: "#/genesis" }, "Create brand")),

        el("div", { class: "card card-flush" },
          el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
            el("h2", { class: "h2" }, "Recent checks"),
            link("/reviews", "All reviews", "small strong")),
          el("div", { class: "mt-3" },
            table(["Content", "Risk", "Status", "Date"], reviewRows, "Nothing checked yet. Paste a caption in Content Studio."))),
      ),

      el("div", { class: "stack" },
        quotaCard(data.usage),
        coaching && coaching.top_issues.length
          ? card(
              el("h3", { class: "h3" }, "What keeps coming up"),
              el("div", { class: "stack-sm mt-3" },
                ...coaching.top_issues.map((t, i) =>
                  el("div", { class: "finding" },
                    el("div", { class: "row-between" },
                      el("span", { class: "small strong" }, `${i + 1}. ${t.rule_code}`),
                      chip(`${t.count}×`, "amber")),
                    el("p", { class: "tiny mt-1" }, t.lesson)))),
              link("/coaching", "Open coaching", "small strong"))
          : null,
        card(
          el("h3", { class: "h3" }, "Creator tools"),
          el("div", { class: "stack-sm mt-2" },
            link("/legal", "Legal guideline library", "small"),
            link("/privacy", "Privacy & AI disclosure", "small"),
            link("/passport", "My clearances", "small"),
            link("/coaching", "Coaching", "small"))),
      ),
    ),
  );
}

/* ------------------------------------------------------ business dashboard */
export async function businessDashboard() {
  const data = await api.get("/workspace/business");
  const counts = data.counts;
  const isManager = ["owner", "admin"].includes(state.session.role);

  const brandCards = data.brands.length
    ? el("div", { class: "grid g3" },
        ...data.brands.map((b) =>
          card(
            el("div", { class: "row-between" },
              el("h3", { class: "h3" }, b.name),
              chip(b.policy_published ? `Policy v${b.policy_version}` : "draft policy", b.policy_published ? "sage" : "amber")),
            el("p", { class: "tiny muted mt-1" }, `${b.kind_label} · ${b.languages.map((l) => l.toUpperCase()).join(", ") || "EN"}`),
            el("div", { class: "row mt-3" },
              chip(`${b.reviews} reviews`),
              b.open ? chip(`${b.open} open`, "amber") : null,
              b.avg_risk !== null ? chip(`avg risk ${b.avg_risk}`, b.avg_risk > 55 ? "clay" : "sage") : null),
            el("div", { class: "row mt-3" },
              el("a", { class: "btn btn-ghost grow", href: `#/studio?brand=${b.id}` }, "Check content"),
              el("a", { class: "btn btn-quiet", href: `#/brands/${b.id}/dna` }, "DNA")))))
    : empty("No brands yet", "A business workspace holds many brands. Create the first one.",
        el("a", { class: "btn btn-primary", href: "#/genesis" }, "Create a brand"));

  const memberRows = data.members.map((m) =>
    el("tr", {},
      el("td", {}, el("div", { class: "strong small" }, m.name),
        el("div", { class: "tiny muted" }, m.email)),
      el("td", {}, chip(m.role, m.role === "owner" ? "sage" : "")),
      el("td", { class: "small muted" }, m.last_login_at ? fmt.date(m.last_login_at) : "never"),
      el("td", {},
        isManager && m.role !== "owner"
          ? el("div", { class: "row" },
              el("button", {
                class: "btn btn-quiet btn-sm", type: "button",
                onclick: async () => {
                  const next = prompt(`New role for ${m.name}? (admin, manager, legal, reviewer, creator, viewer)`, m.role);
                  if (!next) return;
                  try {
                    await api.patch(`/workspace/members/${m.membership_id}`, { role: next.trim() });
                    toast("Role updated.");
                    refresh();
                  } catch (error) { toast(error.message, true); }
                },
              }, "Change role"),
              el("button", {
                class: "btn btn-quiet btn-sm", type: "button",
                onclick: async () => {
                  if (!confirm(`Remove ${m.name} from this workspace?`)) return;
                  try {
                    await api.delete(`/workspace/members/${m.membership_id}`);
                    toast("Member removed.");
                    refresh();
                  } catch (error) { toast(error.message, true); }
                },
              }, "Remove"))
          : null)));

  const invite = isManager
    ? card(
        el("h3", { class: "h3" }, "Add a team member"),
        el("p", { class: "tiny muted mt-1" }, `Seats: ${data.usage.seats_used} / ${data.usage.seats_limit} used on ${data.usage.plan_name}.`),
        (() => {
          const name = el("input", { class: "field", placeholder: "Full name" });
          const email = el("input", { class: "field", type: "email", placeholder: "colleague@company.com" });
          const password = el("input", { class: "field", type: "password", placeholder: "Temporary password (8+ chars)" });
          const role = el("select", { class: "field" },
            ...["creator", "reviewer", "manager", "legal", "admin"].map((r) => el("option", { value: r }, r)));
          return el("div", { class: "stack-sm mt-3" }, name, email, password, role,
            actionButton("Create member account", async () => {
              await api.post("/workspace/members", {
                name: name.value.trim(), email: email.value.trim(), password: password.value, role: role.value,
              });
              toast("Member added. Share the password with them.");
              refresh();
            }, "btn-primary", { busyLabel: "Creating…" }));
        })(),
      )
    : null;

  const pending = data.pending_approvals.length
    ? card(
        el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Waiting on a decision"), link("/approvals", "Open queue", "small strong")),
        el("div", { class: "stack-sm mt-3" },
          ...data.pending_approvals.map((a) =>
            el("div", { class: "finding" },
              el("div", { class: "row-between" },
                el("span", { class: "small strong" }, a.review ? a.review.content_title : "—"),
                riskBadge(a.review ? a.review.risk_score : null, a.review ? a.review.risk_band : "pending")),
              el("div", { class: "tiny muted mt-1" },
                `${a.review ? a.review.brand_name : ""} · ${a.approver_role} · requested by ${a.requested_by}`)))))
    : null;

  const maxWeek = Math.max(1, ...data.reviews_by_week.map((w) => w.reviews));

  return el("div", {},
    pageHead(
      data.org.name,
      `Business workspace · ${data.org.plan} · ${plural(counts.brands, "brand")}, ${plural(counts.members, "member")}.`,
      [el("a", { class: "btn btn-ghost", href: "#/genesis" }, "+ New brand"),
       el("a", { class: "btn btn-primary", href: "#/studio" }, "Check new content")],
    ),

    el("div", { class: "grid g4" },
      stat(counts.brands, "Brands", `${data.usage.brands_limit} allowed`),
      stat(counts.members, "Team members", `${data.usage.seats_limit} seats`),
      stat(counts.reviews_30d, "Reviews (30 days)", `${counts.reviews} all time`),
      stat(counts.pending_approvals, "Pending approvals", `${counts.legal_flags} legal flags`)),

    el("div", { class: "split-wide mt-5" },
      el("div", { class: "stack" },
        el("div", { class: "card-head" },
          el("h2", { class: "h2" }, "Brands"),
          el("span", { class: "tiny muted" }, "Health is computed from real reviews")),
        brandCards,
        card(
          el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Team"), chip(plural(counts.members, "person", "people"), "lilac")),
          el("div", { class: "mt-3" }, table(["Member", "Role", "Last active", ""], memberRows, "No members."))),
        invite,
      ),
      el("div", { class: "stack" },
        quotaCard(data.usage),
        pending,
        card(
          el("h3", { class: "h3" }, "Reviews per week"),
          el("div", { class: "trend mt-3" },
            ...data.reviews_by_week.map((w) =>
              el("div", { class: "col" },
                el("div", { class: "v", style: { height: `${Math.max(4, (w.reviews / maxWeek) * 90)}px` } }),
                el("span", { class: "x" }, w.week_start.slice(5))))),
        ),
        data.issue_mix.length
          ? card(
              el("h3", { class: "h3" }, "What is being flagged"),
              el("div", { class: "stack-sm mt-3" },
                ...data.issue_mix.map((i) =>
                  bar(fmt.title(i.agent), i.count, Math.max(...data.issue_mix.map((x) => x.count))))))
          : null,
      ),
    ),
  );
}
