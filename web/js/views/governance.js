/* Approvals, Brand Passport, verification, coaching, multilingual, privacy, analytics, workflow. */
import {
  actionButton, api, bar, card, chip, clear, crumbs, dial, el, empty, fmt, kv, link,
  notice, pageHead, riskBadge, stat, statusChip, table, toast,
} from "../core.js";
import { refresh, state } from "../router.js";

/* -------------------------------------------------------------- approvals */
export async function approvals() {
  const rows = await api.get("/approvals");
  const pending = rows.filter((a) => a.status === "pending");
  const decided = rows.filter((a) => a.status !== "pending");

  const approvalCard = (row) => {
    const comment = el("input", { class: "field mt-3", placeholder: "Comment for the creator (optional)" });
    const decide = (decision, label, cls) =>
      actionButton(label, async () => {
        const res = await api.post(`/approvals/${row.id}/decision`, { decision, comment: comment.value });
        toast(res.clearance_id ? `Clearance ${res.clearance_id} issued.` : "Decision recorded.");
        refresh();
      }, cls, { busyLabel: "Saving…" });

    return el("div", { class: "card card-pad" },
      el("div", { class: "row-between" },
        el("div", {},
          link(`/reviews/${row.review.id}`, row.review.content_title, "h3"),
          el("p", { class: "tiny muted mt-1" },
            `${row.review.brand_name} · v${row.review.content_version} · requested by ${row.requested_by} · ${row.approver_role} decision`)),
        el("div", { class: "row" }, riskBadge(row.review.risk_score, row.review.risk_band), statusChip(row.review.status))),
      el("div", { class: "finding mt-3" },
        "Route: ", el("span", { class: "strong" }, fmt.title(row.review.route)),
        ` · ${row.review.blocking_findings} open finding${row.review.blocking_findings === 1 ? "" : "s"} · policy-locked decision`),
      row.status === "pending"
        ? el("div", {},
            comment,
            el("div", { class: "row mt-3" },
              decide("approved", "Approve & issue passport", "btn-primary"),
              decide("changes_requested", "Request changes", "btn-quiet"),
              decide("rejected", "Reject", "btn-quiet"),
              link(`/reviews/${row.review.id}/panel`, "Inspect reviewer panel", "small strong")))
        : el("div", { class: "row mt-3" },
            chip(row.status.replace(/_/g, " "), row.status === "approved" ? "sage" : "clay"),
            el("span", { class: "small muted" }, `by ${row.decided_by || "—"}${row.comment ? ` · “${row.comment}”` : ""}`)),
    );
  };

  return el("div", {},
    pageHead("Approvals",
      "A decision here issues a clearance locked to this content version and policy version. It cannot be edited afterwards.",
      chip(`${pending.length} waiting`, "amber")),
    el("div", { class: "stack" },
      ...(pending.length ? pending.map(approvalCard) : [card(el("p", { class: "small muted" }, "Nothing is waiting on a human decision."))])),
    decided.length
      ? el("div", { class: "mt-8" },
          el("h2", { class: "h2" }, "Decided"),
          el("div", { class: "stack mt-3" }, ...decided.map(approvalCard)))
      : null,
    el("div", { class: "mt-6" },
      notice("Critical findings cannot be approved away",
        "A review with a critical finding cannot be approved, even by an owner. Only an authorised legal reviewer can record a justified override, and it appears in the audit trail and on the passport history.")),
  );
}

/* --------------------------------------------------------------- passport */
export async function passportList() {
  const rows = await api.get("/passports");
  const valid = rows.filter((p) => !p.invalidated).length;

  return el("div", {},
    pageHead("Brand Passport",
      "Your proof that this content was reviewed and approved. Each record is locked to a content version and a policy version.",
      chip(`${valid} valid`, "sage")),
    rows.length
      ? el("div", { class: "grid g2" },
          ...rows.map((p) =>
            el("div", { class: "card card-pad" },
              el("div", { class: "row-between" },
                el("div", {},
                  el("div", { class: "strong" }, p.content.title),
                  el("div", { class: "tiny muted" }, `${p.brand ? p.brand.name : ""} · v${p.content.version} · policy v${p.policy_version ?? "–"}`)),
                chip(p.invalidated ? "invalidated" : "cleared", p.invalidated ? "clay" : "sage")),
              el("div", { class: "row-between mt-3 tiny muted" },
                el("span", { class: "mono" }, p.clearance_id),
                el("span", {}, fmt.date(p.issued_at))),
              el("div", { class: "row mt-3" },
                el("a", { class: "btn btn-ghost grow", href: `#/passport/${p.clearance_id}` }, "Open record"),
                el("a", { class: "btn btn-quiet", href: `#/reviews/${p.review_id}` }, "Review")))))
      : empty("No clearances yet", "Approve a review to issue the first passport record.", el("a", { class: "btn btn-primary", href: "#/approvals" }, "Open approvals")),
  );
}

export async function passportDetail(clearanceId) {
  const p = await api.get(`/passports/${clearanceId}`);

  const cells = [
    ["Content version", `v${p.content.version}`],
    ["Policy version", `v${p.policy_version ?? "–"}`],
    ["Risk score", `${p.risk_score} / 100`],
  ].map(([label, value]) =>
    el("div", { class: "finding" }, el("span", { class: "label" }, label),
      el("div", { class: "serif", style: { fontSize: "19px", marginTop: "4px" } }, value)));

  return el("div", {},
    crumbs([{ label: "Brand Passport", href: "/passport" }, { label: p.clearance_id }]),
    pageHead("Brand Passport",
      "Your proof that this content was reviewed and approved. It cannot be changed afterwards.",
      chip(p.invalidated ? "Invalidated" : "Valid", p.invalidated ? "clay" : "sage")),
    el("div", { class: "split" },
      el("div", { class: "card card-pad", style: { borderColor: p.invalidated ? "rgba(155,44,30,.4)" : "rgba(30,58,43,.5)" } },
        el("div", { class: "row" },
          el("span", {
            style: {
              width: "44px", height: "44px", borderRadius: "50%", display: "inline-flex",
              alignItems: "center", justifyContent: "center", fontSize: "18px",
              background: p.invalidated ? "var(--clay)" : "var(--forest)",
              color: p.invalidated ? "var(--clay-ink)" : "var(--cream)",
            },
          }, p.invalidated ? "!" : "✓"),
          el("div", {},
            el("h2", { class: "h2" }, p.invalidated ? "Clearance no longer valid" : "Cleared for publishing"),
            el("p", { class: "small muted mt-1" },
              `${p.content.title} · ${p.brand ? p.brand.name : ""} · ${fmt.title(p.content.channel)} · ${fmt.language(p.content.language)}`))),
        el("div", { class: "grid g3 mt-5" }, ...cells),
        el("p", { class: "small muted mt-4" },
          "Approved by ", el("span", { class: "strong" }, p.approver), " on ", fmt.date(p.issued_at),
          " · Clearance ID ", el("span", { class: "mono" }, p.clearance_id)),
        el("div", { class: "mt-3" },
          p.invalidated
            ? notice("Why this record is void", p.invalidated_reason || "The content changed after clearance.", "clay")
            : notice("If you edit this content, this clearance becomes invalid",
                `A new review is required. The record is bound to content hash ${p.content_hash.slice(0, 12)} and policy v${p.policy_version ?? "–"}.`)),
        el("div", { class: "row mt-4" },
          el("a", { class: "btn btn-primary", href: `#/verify/${p.clearance_id}` }, "Verification link"),
          el("a", { class: "btn btn-ghost", href: `#/reviews/${p.review_id}` }, "Open the review")),
        el("div", { class: "finding mt-5" },
          el("span", { class: "label" }, "Approved copy"),
          el("p", { class: "small mt-1", style: { whiteSpace: "pre-wrap", lineHeight: "1.7" } }, p.content.body_text))),
      el("div", { class: "stack" },
        card(
          el("h2", { class: "h2" }, "Review history"),
          el("ul", { class: "timeline mt-3" },
            ...p.history.map((h) =>
              el("li", {},
                el("span", { class: "bullet" }),
                el("div", {},
                  el("div", { class: "small strong" }, h.action.replace(/[._]/g, " ")),
                  el("div", { class: "tiny muted" }, `${h.actor} · ${fmt.date(h.at)}`)))))),
        card(
          el("h3", { class: "h3" }, "Decision record"),
          el("p", { class: "small muted mt-1" },
            `${p.decision.status || "—"} by ${p.decision.by || "—"}${p.decision.comment ? ` · “${p.decision.comment}”` : ""}`),
          el("span", { class: "label mt-3" }, "Verification token"),
          el("p", { class: "mono mt-1", style: { wordBreak: "break-all" } }, p.verification_token))),
    ),
  );
}

export async function verify(clearanceId) {
  const v = await api.get(`/verify/${clearanceId}`);
  return el("div", { style: { maxWidth: "680px", margin: "0 auto" } },
    pageHead("Clearance verification",
      "Public check of a Brand Passport ID. It confirms validity and never exposes the content."),
    card(
      el("div", { class: "row-between" },
        el("span", { class: "mono" }, v.clearance_id),
        chip(v.valid ? "Valid clearance" : "Not valid", v.valid ? "sage" : "clay")),
      el("div", { class: "mt-4" }, kv([
        { label: "Issued", value: fmt.date(v.issued_at) },
        { label: "Approver", value: v.approver },
        { label: "Risk at approval", value: `${v.risk_score} / 100` },
        { label: "Content unchanged", value: v.content_hash_matches ? "yes" : "no" },
      ])),
      v.reason ? el("p", { class: "small mt-3", style: { color: "var(--clay-ink)" } }, v.reason) : null),
  );
}

/* --------------------------------------------------------------- coaching */
export async function coaching() {
  const data = await api.get("/coaching");
  const rows = data.brands || [];
  const maxTrend = Math.max(1, ...rows.flatMap((r) => (r.coaching.trend || []).map((t) => t.count)));

  return el("div", {},
    pageHead("Creator Coaching",
      "Your three most repeated mistakes, the example that triggered them, and a short lesson. Private to you by default.",
      chip("Private by default", "lilac")),
    el("div", { class: "stack" },
      ...rows.map(({ brand, coaching: c }) =>
        card(
          el("div", { class: "row-between" },
            el("div", {},
              el("h2", { class: "h2" }, brand.name),
              el("p", { class: "tiny muted" }, `${c.total_events} coaching signals from real review findings`)),
            el("a", { class: "btn btn-ghost", href: `#/studio?brand=${brand.id}` }, "Check content")),
          el("div", { class: "split mt-4" },
            el("div", {},
              el("span", { class: "label" }, "Top three repeated issues"),
              el("div", { class: "stack-sm mt-2" },
                ...(c.top_issues.length
                  ? c.top_issues.map((t, i) =>
                      el("div", { class: "finding" },
                        el("div", { class: "row-between" },
                          el("div", { class: "row" },
                            el("span", {
                              style: {
                                width: "20px", height: "20px", borderRadius: "50%", background: "var(--forest)",
                                color: "var(--cream)", fontSize: "10px", fontWeight: "700",
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                              },
                            }, String(i + 1)),
                            el("span", { class: "small strong" }, t.rule_code),
                            chip(t.category)),
                          el("span", { class: "tiny muted" }, `${t.count}×`)),
                        t.example.span ? el("p", { class: "tiny mt-2", style: { color: "var(--brass)" } }, `“${t.example.span}”`) : null,
                        el("p", { class: "small mt-1" }, t.lesson),
                        t.example.review_run_id
                          ? link(`/reviews/${t.example.review_run_id}`, "See the original review", "tiny strong")
                          : null)
                  )
                  : [el("p", { class: "small muted" }, "No repeated issues yet.")]))),
            el("div", {},
              el("span", { class: "label" }, "Last six weeks"),
              el("div", { class: "trend mt-2" },
                ...c.trend.map((t) =>
                  el("div", { class: "col" },
                    el("div", { class: "v", style: { height: `${Math.max(4, (t.count / maxTrend) * 90)}px` } }),
                    el("span", { class: "x" }, t.week_start.slice(5))))),
              el("div", { class: "stack-sm mt-4" },
                ...c.lessons.slice(0, 4).map((l) =>
                  el("div", { class: "tiny muted" }, el("span", { class: "strong" }, l.rule_code), ` · ${l.text}`)))))),
      )),
    el("div", { class: "mt-5" },
      notice("Coaching never rewrites policy",
        "These lessons come from confirmed findings. If a rule keeps confusing creators, the fix is a clearer policy — an owner still has to approve that change.")),
  );
}

/* ----------------------------------------------------------- multilingual */
export async function multilingual() {
  const brands = state.brands.length ? state.brands : await api.get("/brands");
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const target =
    brands.find((b) => b.id === params.get("brand")) ||
    brands.find((b) => b.languages.length > 1) ||
    brands[0];
  if (!target) return empty("No brands yet", "Create a brand to compare language variants.");

  const data = await api.get(`/brands/${target.id}/multilingual`);

  const variants = data.variants.map((v) =>
    card(
      el("div", { class: "row-between" }, chip(fmt.language(v.language), "lilac"), statusChip(v.status)),
      el("h3", { class: "h3 mt-2", style: { fontSize: "15px" } }, v.title),
      el("div", { class: "copy-block mt-2", style: { fontSize: "12.5px" } }, v.body_text),
      el("div", { class: "stack-sm mt-3 tiny" },
        el("div", { class: "row-between" },
          el("span", { class: "muted" }, "Glossary terms used"),
          el("span", { style: { color: v.approved_terms_used.length ? "var(--sage-ink)" : "var(--clay-ink)" } },
            v.approved_terms_used.length ? v.approved_terms_used.join(", ") : "none")),
        el("div", { class: "row-between" },
          el("span", { class: "muted" }, "Prohibited translations"),
          el("span", { style: { color: v.prohibited_hits.length ? "var(--clay-ink)" : "var(--sage-ink)" } },
            v.prohibited_hits.length ? v.prohibited_hits.join(", ") : "none")),
        el("div", { class: "row-between" },
          el("span", { class: "muted" }, "Disclaimer present"),
          el("span", { style: { color: v.disclaimer_present ? "var(--sage-ink)" : "var(--clay-ink)" } },
            v.disclaimer_present ? "yes" : "missing")),
        el("div", { class: "row-between" }, el("span", { class: "muted" }, "Risk"), el("span", {}, `${v.risk_score ?? "–"} / 100`))),
      v.review_id ? el("a", { class: "btn btn-quiet btn-block mt-3", href: `#/reviews/${v.review_id}` }, "Open review") : null,
    ),
  );

  return el("div", {},
    pageHead("Multilingual consistency",
      `${data.brand.name} · ${data.brand.languages.map(fmt.language).join(", ")}. Same claim, same glossary term, same disclaimer in every language.`,
      el("div", { class: "row" },
        ...brands.map((b) =>
          el("a", {
            class: `chip${b.id === data.brand.id ? " sage" : ""}`,
            href: `#/multilingual?brand=${b.id}`,
            style: { border: `1px solid ${b.id === data.brand.id ? "var(--forest)" : "var(--line)"}` },
          }, b.name)))),
    el("div", { class: "grid g3" }, ...variants),
    el("div", { class: "grid g2 mt-5" },
      card(el("h3", { class: "h3" }, "What is compared"),
        el("ul", { class: "small muted", style: { paddingLeft: "16px", lineHeight: "1.8" } },
          ...data.checks.map((c) => el("li", {}, c)))),
      notice("Language nuance needs humans",
        "Term parity is checked deterministically against the glossary. Cultural and festival sensitivity is flagged for a native-speaking reviewer — never decided by a similarity score.")),
  );
}

/* ---------------------------------------------------------------- privacy */
export async function privacy() {
  const [summary, disclosures, ai] = await Promise.all([
    api.get("/privacy/summary"),
    api.get("/privacy/disclosures"),
    api.get("/ai/status"),
  ]);

  const labels = summary.policy.map((p) =>
    card(
      el("div", { class: "row-between" },
        chip(p.label, p.label === "restricted" ? "clay" : p.label === "confidential" ? "amber" : "sage"),
        el("span", { class: "tiny muted" }, `${(summary.labels.find((l) => l.label === p.label) || {}).count || 0} runs`)),
      el("p", { class: "tiny muted mt-2" }, `${p.processors.join(", ")} · retention ${p.retention}`),
      el("p", { class: "tiny mt-1" }, p.external_ok ? "external allowed" : "no external transfer")));

  const text = el("textarea", { class: "field", rows: "3" },
    "Launch note for the Diwali campaign. Contact priya@example.com or 9876543210 before 20 October.");
  const sensitivity = el("select", { class: "field", style: { maxWidth: "190px" } },
    el("option", { value: "public" }, "Public"),
    el("option", { value: "internal", selected: true }, "Internal"),
    el("option", { value: "confidential" }, "Confidential"),
    el("option", { value: "restricted" }, "Restricted"));
  const previewOut = el("div", { class: "mt-4" });

  const layers = [
    ["Classification", ai.layers.classification],
    ["Semantic review", ai.layers.semantic_review],
    ["AI rewrites", ai.layers.rewrite],
    ["Rule extraction", ai.layers.rule_extraction],
  ];

  return el("div", {},
    pageHead("Privacy Center",
      "Sensitivity labels, redact-before-send and a full AI disclosure log. We never claim zero exposure when an external model is used.",
      chip(`${summary.local_only} local-only runs`, "sage")),
    el("div", { class: "grid g4" }, ...labels),
    el("div", { class: "split mt-5" },
      el("div", { class: "stack" },
        card(
          el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Inference provider"),
            chip(ai.enabled ? "Sarvam connected" : "deterministic mode", ai.enabled ? "sage" : "amber")),
          el("div", { class: "kv mt-2" },
            el("div", {}, el("dt", {}, "Model"), el("dd", { class: "mono" }, ai.model)),
            el("div", {}, el("dt", {}, "Region"), el("dd", {}, ai.region)),
            el("div", {}, el("dt", {}, "Calls this session"), el("dd", {}, String(ai.calls))),
            el("div", {}, el("dt", {}, "Tokens in / out"), el("dd", {}, `${ai.tokens_in} / ${ai.tokens_out}`)),
            el("div", {}, el("dt", {}, "Avg latency"), el("dd", {}, fmt.ms(ai.avg_latency_ms))),
            el("div", {}, el("dt", {}, "Circuit"), el("dd", { style: { color: ai.circuit_open ? "var(--clay-ink)" : "var(--sage-ink)" } },
              ai.circuit_open ? "open (degraded)" : "closed"))),
          el("div", { class: "row mt-3" },
            ...layers.map(([label, on]) => chip(`${label}: ${on ? "on" : "off"}`, on ? "sage" : ""))),
          el("div", { class: "row mt-3" },
            actionButton("Test connection", async () => {
              const probe = await api.get("/ai/status?probe=true");
              toast(probe.probe && probe.probe.ok ? `Sarvam reachable in ${probe.probe.latency_ms} ms.` : `Probe failed: ${probe.probe ? probe.probe.error : "unknown"}`, !(probe.probe && probe.probe.ok));
              refresh();
            }, "btn-quiet", { busyLabel: "Probing…" })),
        ),
        card(
          el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Redaction preview"), chip("before any external call", "lilac")),
          el("p", { class: "sub" }, "See exactly what would leave the workspace. Personal data raises the label automatically."),
          el("div", { class: "mt-3" }, text),
          el("div", { class: "row mt-2" }, sensitivity,
            actionButton("Preview redaction", async () => {
              const res = await api.post("/privacy/preview", { text: text.value, sensitivity: sensitivity.value });
              clear(previewOut);
              previewOut.append(
                el("div", { class: "row" },
                  chip(`declared ${res.declared}`, "amber"),
                  chip(`effective ${res.effective}`, "clay"),
                  chip(`${res.detections.length} detections`)),
                el("div", { class: "finding mt-2" },
                  el("span", { class: "label" }, "What would be sent"),
                  el("p", { class: "small mt-1", style: { whiteSpace: "pre-wrap" } }, res.redacted_text)),
                el("p", { class: "tiny muted mt-2" },
                  `Processors: ${res.policy.processors.join(", ")} · retention ${res.policy.retention} · ${res.policy.external_ok ? "external processing permitted" : "local processing only"}`),
                res.needs_local_processing
                  ? el("div", { class: "mt-2" }, notice("Redaction would destroy a required fact",
                      "A confidential product name is essential to the review. Process locally, or hand this to a human reviewer instead of sending it out.", "clay"))
                  : null,
              );
            }, "btn-primary", { busyLabel: "Checking…" })),
          previewOut,
        ),
        notice("Redaction is not allowed to erase the evidence",
          "If masking would remove the fact the review depends on, the platform offers local-only processing or a human-only review instead of sending the document out."),
      ),
      el("div", { class: "card card-flush" },
        el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
          el("h3", { class: "h3" }, "Retention by label"),
          el("span", { class: "tiny muted" }, "resolved per workspace")),
        el("div", { class: "stack-sm", style: { padding: "12px 24px 20px" } },
          ...summary.policy.map((p) =>
            el("div", { class: "row-between small" },
              el("span", {}, chip(p.label, p.label === "restricted" ? "clay" : p.label === "confidential" ? "amber" : "sage")),
              el("span", { class: "muted" }, `${p.retention} · ${p.external_ok ? "external allowed" : "local only"}`))))),
    ),
    el("div", { class: "card card-flush mt-5" },
        el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
          el("h3", { class: "h3" }, "AI disclosure log"),
          el("span", { class: "tiny muted" }, `${disclosures.length} entries`)),
        el("div", { class: "mt-3" },
          table(["Review", "Processor", "Label", "Retention", "Date"],
            disclosures.map((d) =>
              el("tr", {},
                el("td", {},
                  el("div", { class: "mono tiny" }, d.review_id.slice(0, 8)),
                  el("div", { class: "tiny muted" }, (d.data_categories || []).join(", ") || "brand copy")),
                el("td", {},
                  el("div", { class: "provider-name strong" }, d.processor),
                  el("div", { class: "provider-meta" }, `${d.model} · ${d.region}`)),
                el("td", {}, chip(fmt.title(d.sensitivity), d.sensitivity === "restricted" ? "clay" : d.sensitivity === "confidential" ? "amber" : "sage")),
                el("td", { class: "small muted" }, d.retention),
                el("td", { class: "small muted" }, fmt.date(d.created_at)))),
            "No disclosures yet."))),
    el("div", { class: "grid g3 mt-5" },
      notice("Stored metadata only", "Raw secrets are never logged. The log keeps the processor, model, region, label, redaction version and outcome."),
      notice("Per-tenant policy", "Permitted processors, retention and redaction rules resolve per workspace, not globally.", "sage"),
      notice("Honest boundaries", `${summary.note} Self-hosted models need a separate deployable adapter and capability evaluation.`, "clay")),
  );
}

/* --------------------------------------------------------------- insights */
export async function insights() {
  const data = await api.get("/insights");
  const rows = data.brands || [];
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const selected = rows.find((r) => r.brand.id === params.get("brand")) || rows[0];
  if (!selected) return empty("No history yet", "Run a review to populate analytics.");

  const i = selected.insights;
  const maxRule = Math.max(1, ...i.by_rule.map((r) => r.count));
  const maxAgent = Math.max(1, ...i.by_agent.map((r) => r.count));

  return el("div", {},
    pageHead("Analytics",
      "Violations by rule, reviewer agreement, turnaround and policy gaps — computed from this workspace's review history.",
      chip(selected.brand.name, "lilac")),
    el("div", { class: "grid g4" },
      stat(i.totals.reviews, "Reviews run", `${i.totals.findings} blocking findings`),
      stat(i.totals.clearances, "Valid clearances", "Version-locked passports"),
      stat(i.totals.avg_risk, "Average risk score", "Across all reviews"),
      stat(`${Math.round(i.totals.rework_rate * 100)}%`, "Rework rate", "Reviews returned for changes")),
    el("div", { class: "grid g2 mt-5" },
      card(el("h3", { class: "h3" }, "Violations by rule"),
        el("div", { class: "stack-sm mt-3" },
          ...(i.by_rule.length ? i.by_rule.map((r) => bar(r.rule_code, r.count, maxRule))
            : [el("p", { class: "small muted" }, "No findings recorded.")]))),
      card(el("h3", { class: "h3" }, "Findings by reviewer"),
        el("div", { class: "stack-sm mt-3" }, ...i.by_agent.map((r) => bar(fmt.title(r.agent), r.count, maxAgent)))),
      card(el("h3", { class: "h3" }, "Reviewer agreement"),
        el("div", { class: "grid g3 mt-3" },
          el("div", {}, el("div", { class: "serif", style: { fontSize: "26px" } }, String(i.reviewer_agreement.disagreements)),
            el("div", { class: "tiny muted" }, "disagreements")),
          el("div", {}, el("div", { class: "serif", style: { fontSize: "26px" } }, String(i.reviewer_agreement.resolved)),
            el("div", { class: "tiny muted" }, "resolved by a human")),
          el("div", {}, el("div", { class: "serif", style: { fontSize: "26px" } }, `${Math.round(i.reviewer_agreement.agreement_rate * 100)}%`),
            el("div", { class: "tiny muted" }, "agreement rate"))),
        el("p", { class: "tiny muted mt-3" },
          "Disagreements stay visible on purpose. An unresolved one routes the content to a specialist instead of being averaged away.")),
      card(el("h3", { class: "h3" }, "Coverage & routing"),
        el("div", { class: "grid g2 mt-3" },
          el("div", {}, el("span", { class: "label" }, "By language"),
            el("div", { class: "stack-sm mt-1" },
              ...i.by_language.map((l) => el("div", { class: "row-between small" },
                el("span", { class: "muted" }, fmt.language(l.language)), el("span", {}, String(l.count)))))),
          el("div", {}, el("span", { class: "label" }, "By route"),
            el("div", { class: "stack-sm mt-1" },
              ...i.routes.map((r) => el("div", { class: "row-between small" },
                el("span", { class: "muted" }, fmt.title(r.route)), el("span", {}, String(r.count))))))),
        el("div", { class: "mt-4" }, el("span", { class: "label" }, "Policy gaps"),
          el("div", { class: "row mt-1" },
            ...(i.policy_gaps.length ? i.policy_gaps.map((g) => chip(`no ${g} rule`, "amber")) : [chip("every category covered", "sage")])))),
    ),
    el("div", { class: "mt-5" },
      notice("Measured, not assumed",
        `Every number here is computed from reviews in this workspace. Average review time is ${i.totals.avg_review_seconds}s per run; these are demo-scale figures, not published benchmarks.`)),
  );
}

/* --------------------------------------------------------------- workflow */
export async function workflow() {
  const w = await api.get("/workflow");

  return el("div", {},
    pageHead("How content moves",
      "The state machine behind every review, plus what happens when a check fails. A missing check is never treated as a pass.",
      el("a", { class: "btn btn-primary", href: "#/studio" }, "Start a review")),
    card(
      el("h2", { class: "h2" }, "State machine"),
      el("div", { class: "row mt-4", style: { gap: "8px" } },
        ...w.states.map((s, idx) =>
          el("div", { class: "row", style: { gap: "8px" } },
            el("div", { class: "finding", style: { minWidth: "150px" } },
              el("div", { class: "row-between" },
                el("span", { class: "small strong" }, s.label),
                el("span", { class: "chip", style: { padding: "0 6px", fontSize: "10.5px" } }, String(s.count))),
              el("p", { class: "tiny muted mt-1" }, s.description)),
            idx < w.states.length - 1 ? el("span", { style: { color: "var(--line)" } }, "→") : null))),
      el("p", { class: "tiny muted mt-4" },
        "Revisions create a new immutable content version. When the content hash changes, the prior clearance is invalidated and the content must be reviewed again.")),
    el("div", { class: "grid g2 mt-5" },
      card(el("h3", { class: "h3" }, "The path, end to end"),
        el("ol", { class: "stack-sm mt-3", style: { paddingLeft: "18px" } },
          ...w.flow.map((f) => el("li", { class: "small" }, f)))),
      card(el("h3", { class: "h3" }, "When things go wrong"),
        el("div", { class: "stack-sm mt-3" },
          ...w.failure_paths.map((f) => el("div", { class: "finding small" }, f))))),
    el("div", { class: "grid g3 mt-5" },
      card(chip("Guarantee", "sage"), el("p", { class: "small muted mt-2" }, "A critical claim escalates regardless of creator trust.")),
      card(chip("Guarantee", "amber"), el("p", { class: "small muted mt-2" }, "An incomplete review cannot auto-clear; missing checks are named.")),
      card(chip("Boundary", "clay"), el("p", { class: "small muted mt-2" }, "Automated checks are decision support, never a legal certification."))),
  );
}
