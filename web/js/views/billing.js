/* Plan management: self-serve upgrades, invoices, usage. */
import { actionButton, api, card, chip, el, fmt, notice, pageHead, toast } from "../core.js";
import { refresh, reloadShell, state } from "../router.js";

export async function billing() {
  const data = await api.get("/billing/summary");
  const usage = data.usage;

  const planCard = (plan) => {
    const isCurrent = plan.code === data.current.code;
    return el("div", { class: `card card-pad${isCurrent ? " current-plan" : ""}` },
      el("div", { class: "row-between" },
        el("h3", { class: "h3" }, plan.name),
        isCurrent ? chip("current plan", "sage") : chip(fmt.title(plan.account_type), "lilac")),
      el("div", { class: "serif mt-2", style: { fontSize: "26px" } },
        plan.price_inr === null ? "Custom" : `₹${plan.price_inr.toLocaleString("en-IN")}`,
        el("span", { class: "tiny muted", style: { marginLeft: "6px" } }, plan.interval === "custom" ? "" : "/ month")),
      el("div", { class: "stack-sm mt-3 tiny muted" },
        el("div", {}, `${plan.brands} brand(s)`),
        el("div", {}, `${plan.seats} seat(s)`),
        el("div", {}, `${plan.reviews_per_month.toLocaleString("en-IN")} reviews / month`)),
      el("ul", { class: "tiny muted mt-3", style: { paddingLeft: "16px", lineHeight: "1.7" } },
        ...plan.features.map((f) => el("li", {}, f))),
      isCurrent
        ? null
        : actionButton(`Switch to ${plan.name}`, async () => {
            const result = await api.post("/billing/checkout", { plan: plan.code });
            toast(result.message);
            await reloadShell();
            refresh();
          }, "btn-primary btn-block", { busyLabel: "Switching…" }),
    );
  };

  const invoiceRows = data.invoices.length
    ? data.invoices.map((inv) =>
        el("tr", {},
          el("td", { class: "mono tiny" }, inv.number),
          el("td", { class: "small" }, `${inv.plan_from} → ${inv.plan_to}`),
          el("td", { class: "small num" }, fmt.rupees(inv.amount_inr)),
          el("td", {}, chip(inv.status, inv.status === "paid" ? "sage" : "amber")),
          el("td", { class: "small muted" }, fmt.date(inv.created_at))))
    : null;

  return el("div", {},
    pageHead("Plan & billing",
      `You are on ${data.current.name}. ${data.note}`,
      chip(`test mode`, "amber")),
    el("div", { class: "grid g3 mt-4" },
      el("div", { class: "card card-pad" },
        el("h3", { class: "h3" }, "This month"),
        el("div", { class: "mt-3" },
          el("div", { class: "row-between small" },
            el("span", { class: "muted" }, "Reviews"),
            el("span", { class: "strong" }, `${usage.reviews_used} / ${usage.reviews_limit}`)),
          el("div", { class: "bar-track mt-2" },
            el("div", { class: "bar-fill", style: { width: `${Math.min(100, (usage.reviews_used / Math.max(1, usage.reviews_limit)) * 100)}%` } }))),
        el("div", { class: "kv mt-4" },
          el("div", {}, el("dt", {}, "Brands"), el("dd", {}, `${usage.brands_used} / ${usage.brands_limit}`)),
          el("div", {}, el("dt", {}, "Seats"), el("dd", {}, `${usage.seats_used} / ${usage.seats_limit}`)),
          el("div", {}, el("dt", {}, "AI calls"), el("dd", {}, String(usage.ai_calls))),
          el("div", {}, el("dt", {}, "Tokens"), el("dd", {}, `${usage.tokens_in} / ${usage.tokens_out}`)))),
      el("div", { class: "card card-pad" },
        el("h3", { class: "h3" }, "How limits behave"),
        el("ul", { class: "small muted mt-2", style: { paddingLeft: "16px", lineHeight: "1.8" } },
          el("li", {}, "A review past your monthly limit returns a clear upgrade message."),
          el("li", {}, "Brands and seats beyond the plan are refused, not silently allowed."),
          el("li", {}, "Downgrades are allowed; the invoice records any usage above the new limit."))),
      el("div", { class: "card card-pad" },
        el("h3", { class: "h3" }, "Why this is safe"),
        el("ul", { class: "small muted mt-2", style: { paddingLeft: "16px", lineHeight: "1.8" } },
          el("li", {}, "Your content stays yours; plan changes never touch it."),
          el("li", {}, "Every change is audited with who, when and how much."),
          el("li", {}, "Downgrades keep working — limits apply to new work, not old records.")))),
    el("div", { class: "card card-flush mt-5" },
      el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
        el("h3", { class: "h3" }, "Invoices"),
        el("span", { class: "tiny muted" }, "test mode · no money moves")),
      el("div", { class: "mt-3" },
        invoiceRows
          ? el("div", { class: "table-wrap" }, el("table", { class: "data" },
              el("thead", {}, el("tr", {},
                el("th", {}, "Number"), el("th", {}, "Change"), el("th", {}, "Amount"),
                el("th", {}, "Status"), el("th", {}, "Date"))),
              el("tbody", {}, ...invoiceRows)))
          : el("p", { class: "small muted", style: { padding: "0 24px 20px" } }, "No plan changes yet."))),
    el("h2", { class: "h2 mt-8" }, "Available plans"),
    el("div", { class: "grid g3 mt-3" }, ...data.available.map(planCard)),
    el("div", { class: "mt-5" },
      notice("Test-mode billing",
        "No card is charged. The plan change, the invoice number and the audit entry are real, so the pricing model works end to end. Wiring Razorpay or Stripe replaces one service.")),
  );
}
