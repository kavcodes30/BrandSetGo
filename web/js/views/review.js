/* Review queue, explainable review, reviewer panel, rewrite/drift, risk & routing. */
import {
  actionButton, agentTag, api, card, chip, clear, crumbs, dial, el, fmt, kv, link,
  notice, pageHead, plural, riskBadge, statusChip, table, tabs, toast,
} from "../core.js";
import { navigate, refresh } from "../router.js";

function reviewTabs(id, active) {
  return tabs(
    [
      { key: "", label: "Findings", href: `/reviews/${id}` },
      { key: "panel", label: "Reviewer panel", href: `/reviews/${id}/panel` },
      { key: "rewrite", label: "Rewrite & drift", href: `/reviews/${id}/rewrite` },
      { key: "risk", label: "Risk & routing", href: `/reviews/${id}/risk` },
    ],
    active,
  );
}

/** Anchors every finding to the exact span of copy it refers to. */
function highlight(text, findings) {
  const spans = findings
    .filter((f) => f.status !== "pass" && f.span_end > f.span_start)
    .sort((a, b) => a.span_start - b.span_start);

  const merged = [];
  for (const f of spans) {
    const last = merged[merged.length - 1];
    if (last && f.span_start < last.end) continue;
    merged.push({ start: f.span_start, end: f.span_end, finding: f });
  }

  const node = el("div", { class: "copy-block" });
  let cursor = 0;
  merged.forEach((m) => {
    if (m.start > cursor) node.append(document.createTextNode(text.slice(cursor, m.start)));
    node.append(
      el("mark", { class: `hl ${m.finding.severity}`, title: `${m.finding.agent}: ${m.finding.title}` },
        text.slice(m.start, m.end)),
    );
    cursor = m.end;
  });
  if (cursor < text.length) node.append(document.createTextNode(text.slice(cursor)));
  return node;
}

function classificationCard(review) {
  const c = review.classification || {};
  if (!c.language) {
    return card(
      el("h3", { class: "h3" }, "AI classification"),
      el("p", { class: "sub" }, "This review ran without a model: language, script and personal-data patterns only."),
    );
  }
  const meta = review.ai_meta || {};
  const semantic = meta.semantic || {};
  const live = c.source === "sarvam";

  return card(
    el("div", { class: "card-head" },
      el("h3", { class: "h3" }, "AI classification"),
      chip(live ? "Sarvam" : "deterministic fallback", live ? "sage" : "amber")),
    el("p", { class: "tiny muted mt-1" },
      `${c.model} · ${c.latency_ms} ms · confidence ${Math.round((c.confidence || 0) * 100)}%` +
      (meta.calls ? ` · ${meta.calls} call(s)` : "") +
      (meta.tokens_in ? ` · ${meta.tokens_in}/${meta.tokens_out} tokens` : "")),
    el("div", { class: "kv mt-3" },
      el("div", {}, el("dt", {}, "Language"), el("dd", {}, fmt.language(c.language))),
      el("div", {}, el("dt", {}, "Content type"), el("dd", {}, fmt.title(c.content_type))),
      el("div", {}, el("dt", {}, "Category"), el("dd", {}, fmt.title(c.category))),
      el("div", {}, el("dt", {}, "Sensitivity"), el("dd", {}, fmt.title(c.sensitivity))),
      el("div", {}, el("dt", {}, "Detected audience"), el("dd", {}, c.audience || "—")),
      el("div", {}, el("dt", {}, "Personal data"),
        el("dd", {}, (c.pii || []).filter((p) => p !== "none").join(", ") || "none detected"))),
    (c.claims || []).length
      ? el("div", { class: "mt-3" },
          el("span", { class: "label" }, `Claims extracted (${c.claims.length})`),
          el("div", { class: "stack-sm mt-1" },
            ...c.claims.map((claim) =>
              el("div", { class: "row-between", style: { border: "1px solid var(--line)", background: "#FDF8EC", borderRadius: "8px", padding: "6px 12px" } },
                el("span", { class: "small" }, `“${claim.text}”`),
                el("span", { class: "tiny muted", style: { textTransform: "uppercase", letterSpacing: ".08em" } }, claim.type)))))
      : null,
    (c.risk_hints || []).length
      ? el("div", { class: "mt-3" },
          el("span", { class: "label" }, "Model risk hints"),
          el("div", { class: "row mt-1" }, ...c.risk_hints.map((h) => chip(h, "amber"))))
      : null,
    semantic.called
      ? el("div", { class: "finding mt-3", style: { background: "#F1F4EA" } },
          el("div", { class: "small" },
            `Semantic pass: ${semantic.added || 0} finding(s) added, ${semantic.rejected || 0} rejected by the verifier.`),
          (semantic.reasons || []).length
            ? el("ul", { class: "tiny muted", style: { margin: "4px 0 0", paddingLeft: "16px" } },
                ...semantic.reasons.slice(0, 3).map((r) => el("li", {}, r)))
            : null)
      : null,
    (c.notes || []).length
      ? el("ul", { class: "tiny muted", style: { margin: "8px 0 0", paddingLeft: "16px" } },
          ...c.notes.map((n) => el("li", {}, n)))
      : null,
  );
}

function legalBlock(f) {
  if (!f.guideline_code) return null;
  return el("div", { class: "legal-block" },
    el("div", { class: "row-between" },
      el("span", { class: "label" }, "Guideline engaged"),
      el("span", { class: "mono tiny", style: { color: "var(--brass)" } }, f.guideline_code)),
    el("div", { class: "small strong mt-1" }, f.guideline_title || f.title),
    el("div", { class: "tiny mt-1" }, f.guideline_authority),
    el("div", { class: "tiny muted" }, f.guideline_citation),
    f.legal_basis ? el("p", { class: "small muted mt-2" }, f.legal_basis) : null,
    f.remediation
      ? el("div", { class: "finding mt-2", style: { background: "var(--card)" } },
          el("span", { class: "label" }, "What to change"),
          el("p", { class: "small mt-1" }, f.remediation))
      : null);
}

function findingCard(review, f) {
  const tone = f.severity === "critical" || f.severity === "high" ? "clay" : f.severity === "medium" ? "amber" : "sage";
  const patch = f.suggested_patch || {};
  const timed = f.timecode_start !== null && f.timecode_start !== undefined;
  return el("div", { class: "card card-pad", id: `finding-${f.id}` },
    el("div", { class: "row-between" },
      el("div", {}, agentTag(f.agent), el("h3", { class: "h3 mt-1", style: { fontSize: "14px", fontWeight: "600", fontFamily: "var(--sans)" } }, f.title || fmt.title(f.agent))),
      el("div", { class: "row" },
        timed ? chip(`${fmt.timecode(f.timecode_start)}–${fmt.timecode(f.timecode_end)}`, "brass") : null,
        f.source === "sarvam" ? chip("AI", "lilac") : null,
        chip(fmt.title(f.severity), tone))),
    el("p", { class: "small mt-2" }, f.explanation),
    el("p", { class: "tiny muted mt-1" }, (f.evidence_refs || []).filter(Boolean).join(" · ") || "Evidence: none found"),
    f.rule_code && !f.guideline_code
      ? el("p", { class: "tiny mt-1", style: { color: "var(--brass)" } },
          `Rule ${f.rule_code} · confidence ${Math.round((f.confidence || 0) * 100)}% · ${fmt.status(f.status)}`)
      : null,
    legalBlock(f),
    patch.replacement !== undefined
      ? el("div", { class: "edit-box" },
          el("span", { class: "label" }, "Suggested edit"),
          el("p", { class: "old mt-1" }, f.span_text),
          el("p", { class: "new" }, patch.replacement || "(removed)"),
          el("p", { class: "tiny muted mt-1" }, patch.reason || ""),
          el("a", { class: "btn btn-primary btn-sm mt-2", href: `#/reviews/${review.id}/rewrite` }, "Review this edit"))
      : null,
  );
}

/** A video/audio timeline with every flagged moment pinned to its second. */
function mediaTimeline(review) {
  const segments = (review.content.transcript || []).filter((s) => s.text);
  if (!segments.length) return null;
  const duration = review.content.duration_s || Math.max(...segments.map((s) => s.end), 1);
  const flagged = review.findings.filter(
    (f) => f.timecode_start !== null && f.timecode_start !== undefined && f.status !== "pass",
  );

  const track = el("div", { class: "timeline-track" });
  for (const seg of segments) {
    const width = ((seg.end - seg.start) / duration) * 100;
    track.append(
      el("div", { class: "timeline-seg", style: { width: `${Math.max(width, 0.5)}%` }, title: seg.text }, ""),
    );
  }
  for (const f of flagged) {
    const left = (f.timecode_start / duration) * 100;
    const width = Math.max((((f.timecode_end || f.timecode_start + 1) - f.timecode_start) / duration) * 100, 1.2);
    track.append(
      el("button", {
        class: `timeline-flag ${f.severity}`,
        style: { left: `${left}%`, width: `${width}%` },
        type: "button",
        title: `${fmt.timecode(f.timecode_start)} — ${f.span_text || f.title}`,
        onclick: () => document.getElementById(`finding-${f.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }),
      }),
    );
  }

  const rows = segments.map((seg) => {
    const hits = flagged.filter((f) => f.timecode_start >= seg.start && f.timecode_start < seg.end);
    return el("div", { class: `timeline-line${hits.length ? " flagged" : ""}` },
      el("div", { class: "timeline-time" }, `${fmt.timecode(seg.start)}–${fmt.timecode(seg.end)}`),
      el("div", { class: "grow" },
        el("div", { class: "small" }, seg.text),
        hits.length
          ? el("div", { class: "row mt-1" },
              ...hits.map((f) => chip(f.guideline_code || fmt.title(f.agent), f.severity === "critical" || f.severity === "high" ? "clay" : "amber")))
          : null));
  });

  return card(
    el("div", { class: "card-head" },
      el("h3", { class: "h3" }, "Timeline"),
      el("span", { class: "tiny muted" }, `${segments.length} segments · ${fmt.timecode(duration)} · ${flagged.length} flagged moment(s)`)),
    el("p", { class: "tiny muted mt-1" }, "Every flag points at the seconds it is spoken. Click a marker to jump to the finding."),
    track,
    el("div", { class: "mt-3" }, ...rows),
  );
}

/* ----------------------------------------------------------------- queue */
export async function queue() {
  const rows = await api.get("/reviews?limit=40");
  const open = rows.filter((r) => ["needs_changes", "needs_human", "partial"].includes(r.status));

  return el("div", {},
    pageHead("Reviewer Panel",
      "Open reviews first. Each row links to the independent checkers, their disagreements and the routing decision.",
      [chip(`${open.length} open`, "clay"), el("a", { class: "btn btn-primary", href: "#/studio" }, "Check new content")]),
    el("div", { class: "card card-flush" },
      table(["Content", "Brand", "Risk", "Route", "Status", "Opened"],
        rows.map((r) =>
          el("tr", {},
            el("td", {},
              link(`/reviews/${r.id}`, r.content_title, "strong"),
              el("div", { class: "tiny muted" }, `v${r.content_version} · ${fmt.title(r.channel)} · ${r.blocking_findings} open finding${r.blocking_findings === 1 ? "" : "s"}`)),
            el("td", { class: "small muted" }, r.brand_name),
            el("td", {}, riskBadge(r.risk_score, r.risk_band)),
            el("td", { class: "small" }, fmt.title(r.route || "—")),
            el("td", {}, statusChip(r.status)),
            el("td", { class: "small muted" }, fmt.date(r.created_at)))),
        "No reviews yet.")),
    el("div", { class: "row mt-4" },
      el("a", { class: "btn btn-ghost", href: "#/approvals" }, "Approvals queue"),
      el("a", { class: "btn btn-quiet", href: "#/workflow" }, "State machine & failure handling")),
  );
}

/* ---------------------------------------------------------------- detail */
export async function detail(id) {
  const r = await api.get(`/reviews/${id}`);
  const blocking = r.findings.filter((f) => f.status === "confirmed" || f.status === "needs_human_review");
  const inconclusive = r.findings.filter((f) => f.status === "inconclusive");
  const passing = r.findings.filter((f) => f.status === "pass");
  const otherChecks = ["tone", "visual", "accessibility", "language"]
    .map((a) => passing.find((f) => f.agent === a))
    .filter(Boolean);

  const download = actionButton("Download report", async () => {
    const data = await api.get(`/reviews/${id}`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: `brandsetgo-review-${id.slice(0, 8)}.json` });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, "btn-quiet", { busyLabel: "Preparing…" });

  const pendingApproval = r.approval && r.approval.status === "pending";
  const send = actionButton(pendingApproval ? "Awaiting decision" : "Send to manager", async () => {
    await api.post(`/approvals?review_run_id=${id}`, { approver_role: "manager" });
    toast("Sent for approval.");
    refresh();
  }, "btn-primary", { busyLabel: "Sending…" });
  send.disabled = pendingApproval;

  const policyState = r.policy_state || {};
  const provisional = policyState.status && policyState.status !== "published";

  const left = el("div", { class: "stack" },
    provisional
      ? notice(
          `Checked against draft policy v${policyState.version ?? "?"}`,
          el("span", {},
            `${policyState.proposed_rules || 0} brand rule(s) are still proposed, so their findings are provisional. `,
            "Legal guidelines are statutory and are enforced regardless of your policy state. ",
            el("a", { href: `#/brands/${r.brand_id}/dna`, class: "strong" }, "Approve the policy"),
            " when you are ready to make the brand rules enforceable."),
          "warn")
      : null,
    card(
      el("h2", { class: "h2" }, "1. About this content"),
      el("div", { class: "form-row mt-4" },
        el("div", {}, el("span", { class: "label" }, "Brand"),
          el("div", { class: "field field-readonly" }, `${r.brand_name} · Policy v${r.policy_version ?? "–"}`)),
        el("div", {}, el("span", { class: "label" }, "Channel"),
          el("div", { class: "field field-readonly" }, fmt.title(r.content.channel))),
        el("div", {}, el("span", { class: "label" }, "Audience"),
          el("div", { class: "field field-readonly" }, r.content.audience || (r.brand ? r.brand.audience : "") || "—")),
        el("div", {}, el("span", { class: "label" }, "Sensitivity"),
          el("div", { class: "field field-readonly" }, fmt.title(r.content.sensitivity)))),
      el("h2", { class: "h2 mt-6" }, "2. Your content"),
      el("div", { class: "mt-3" }, highlight(r.content.body_text, r.findings)),
      el("p", { class: "tiny muted mt-2" },
        "Highlighted spans are the exact text each finding refers to. Content hash ",
        el("span", { class: "mono" }, r.content.hash.slice(0, 12)), "."),
    ),
    mediaTimeline(r),
    classificationCard(r),
    r.disagreements.length
      ? el("div", { class: "card card-pad", style: { background: "#FBF2DE", borderColor: "rgba(169,129,47,.4)" } },
          el("div", { class: "card-head" },
            el("h3", { class: "h3" }, "Reviewers disagree"),
            link(`/reviews/${r.id}/panel`, "Open panel", "small strong")),
          ...r.disagreements.map((d) => el("p", { class: "small mt-2" }, d.summary)))
      : null,
  );

  const right = el("div", { class: "stack" },
    card(
      el("div", { class: "row" },
        dial(r.risk_score, r.risk_band),
        el("div", {},
          el("h2", { class: "h3" }, `Brand Risk Score: ${fmt.band(r.risk_band)}`),
          el("p", { class: "small muted mt-1" }, r.routing.reason),
          r.hard_blocker ? el("div", { class: "mt-2" }, chip("Critical finding blocks approval", "clay")) : null))),
    blocking.some((f) => f.guideline_code)
      ? card(
          el("div", { class: "card-head" },
            el("h3", { class: "h3" }, "Legal review"),
            chip(`${plural(blocking.filter((f) => f.guideline_code).length, "guideline")} engaged`, "clay")),
          el("div", { class: "stack-sm mt-2" },
            ...blocking.filter((f) => f.guideline_code).map((f) =>
              el("div", { class: "row-between small legal-summary-row" },
                el("span", {}, el("span", { class: "strong" }, f.guideline_code), ` · ${f.guideline_title || f.title}`),
                chip(fmt.title(f.severity), f.severity === "critical" ? "clay" : "amber")))),
          el("p", { class: "tiny muted mt-2" }, "Reviewer assistance, not legal advice. Confirm with counsel before publishing."))
      : null,
    blocking.length === 0
      ? card(el("h3", { class: "h3", style: { color: "var(--sage-ink)" } }, "No blocking findings"),
          el("p", { class: "sub" }, "Every check passed or returned a non-blocking note."))
      : null,
    ...blocking.map((f) => findingCard(r, f)),
    inconclusive.length
      ? card(
          el("h3", { class: "h3" }, "Could not be checked"),
          el("p", { class: "tiny muted mt-1" }, "Non-blocking: these returned no verdict, so they are not counted as a pass."),
          el("div", { class: "stack-sm mt-2" },
            ...inconclusive.map((f) =>
              el("div", { class: "row-between" },
                el("span", { class: "small" }, el("span", { class: "strong" }, fmt.title(f.agent)), ` · ${f.title}`),
                el("span", { class: "tiny muted", style: { textTransform: "uppercase", letterSpacing: ".08em" } }, fmt.status(f.status))))))
      : null,
    otherChecks.length
      ? card(
          el("h3", { class: "h3" }, "Other checks"),
          el("div", { class: "row mt-3" },
            ...otherChecks.map((f) =>
              chip(`${fmt.title(f.agent)}: ${String(f.title).toLowerCase()}`, f.agent === "accessibility" ? "amber" : "sage"))))
      : null,
    card(
      el("div", { class: "row-between" },
        el("div", { class: "small muted" }, "Route: ", el("span", { class: "strong" }, fmt.title(r.routing.route)), ` · ${r.routing.approver_role} decides`),
        send),
      r.status === "needs_changes"
        ? el("div", { class: "mt-3" }, notice("Open findings block approval",
            "Fix the findings in Rewrite & drift, or create a revised version. An approver can only decide on a review with no open blocking findings."))
        : null,
    ),
    r.disclosure
      ? card(
          el("h3", { class: "h3" }, "AI disclosure for this review"),
          el("p", { class: "small muted mt-1" },
            `${r.disclosure.processor} · ${r.disclosure.model} · region ${r.disclosure.region} · label ${r.disclosure.sensitivity} · retention ${r.disclosure.retention}`),
          link("/privacy", "Privacy Center", "small strong"))
      : null,
  );

  return el("div", {},
    crumbs([{ label: "Dashboard", href: "/dashboard" }, { label: r.brand_name, href: `/brands/${r.brand_id}/dna` }, { label: r.content_title }]),
    pageHead(r.content.title,
      `${r.brand_name} · ${fmt.title(r.content.channel)} · ${fmt.language(r.content.language)}` +
        `${r.modality && r.modality !== "text" ? ` · ${fmt.title(r.modality)}` : ""} · content v${r.content.version} · policy v${r.policy_version ?? "–"}`,
      [provisional ? chip("draft policy", "amber") : null, statusChip(r.status), download]),
    reviewTabs(r.id, ""),
    el("div", { class: "split" }, left, right),
  );
}

/* ----------------------------------------------------------------- panel */
export async function panel(id) {
  const [p, r] = await Promise.all([api.get(`/reviews/${id}/panel`), api.get(`/reviews/${id}`)]);
  const verdictTone = { approved: "sage", blocked: "clay", uncertain: "amber", unavailable: "" };

  const agents = p.agents.map((a) =>
    el("div", { class: "card card-pad" },
      el("div", { class: "row-between" },
        el("div", { class: "row" }, agentTag(a.agent),
          el("span", { class: "tiny muted" }, a.checked ? `confidence ${Math.round(a.confidence * 100)}%` : "check unavailable")),
        el("div", { class: "row" },
          a.worst_severity !== "none" && a.worst_severity !== "unknown"
            ? chip(fmt.title(a.worst_severity), a.worst_severity === "high" || a.worst_severity === "critical" ? "clay" : "amber")
            : null,
          chip(a.verdict, verdictTone[a.verdict] || ""))),
      el("div", { class: "stack-sm mt-3" },
        ...(a.findings.length
          ? a.findings.map((f) =>
              el("div", { class: "finding" },
                el("div", { class: "row-between" },
                  el("span", { class: "small strong" }, f.title || fmt.title(f.agent)),
                  el("span", { class: "tiny muted", style: { textTransform: "uppercase", letterSpacing: ".08em" } }, fmt.status(f.status))),
                f.span_text ? el("div", { class: "tiny mt-1", style: { color: "var(--brass)" } }, `“${f.span_text}”`) : null,
                el("p", { class: "small mt-1" }, f.explanation),
                el("p", { class: "tiny muted mt-1" },
                  `${f.rule_code ? `${f.rule_code} · ` : ""}${(f.evidence_refs || []).filter(Boolean).join(" · ") || "no source cited"}`)))
          : [el("p", { class: "small muted" }, "This checker returned no findings.")])),
    ),
  );

  const disagreements = p.disagreements.map((d) => {
    const input = el("input", { class: "field", placeholder: "Record how this was resolved…", style: { maxWidth: "340px" } });
    return el("div", { class: "finding mt-3", style: { background: "#FBF2DE", borderColor: "rgba(169,129,47,.4)" } },
      el("div", { class: "strong small" }, d.topic),
      el("p", { class: "small mt-1" }, d.summary),
      el("div", { class: "row mt-2" }, chip(`${d.agent_a} approved`, "sage"), chip(`${d.agent_b} blocked`, "clay")),
      d.resolution
        ? el("p", { class: "small mt-2", style: { color: "var(--sage-ink)" } }, `Resolved by ${d.resolved_by}: ${d.resolution}`)
        : el("div", { class: "row mt-2" }, input,
            actionButton("Record resolution", async () => {
              await api.post(`/reviews/${id}/disagreements/${d.id}/resolve`, { resolution: input.value });
              toast("Resolution recorded.");
              refresh();
            }, "btn-quiet", { busyLabel: "Saving…" })),
    );
  });

  return el("div", {},
    crumbs([{ label: "Dashboard", href: "/dashboard" }, { label: r.content_title, href: `/reviews/${id}` }, { label: "Reviewer panel" }]),
    pageHead("Reviewer Panel", "Five checkers run independently and report separately. Contradictions are kept, never averaged away.", statusChip(r.status)),
    reviewTabs(id, "panel"),
    el("div", { class: "split-wide" },
      el("div", { class: "stack" }, ...agents),
      el("div", { class: "stack" },
        card(
          el("h3", { class: "h3" }, "Reconciliation"),
          el("p", { class: "small muted mt-1" }, p.reconciliation_note),
          el("div", { class: "stack-sm mt-3" },
            el("div", { class: "row-between small" }, el("span", { class: "muted" }, "Expected checks"), el("span", {}, String((p.completeness.expected || []).length))),
            el("div", { class: "row-between small" }, el("span", { class: "muted" }, "Returned"), el("span", {}, String((p.completeness.returned || []).length))),
            el("div", { class: "row-between small" }, el("span", { class: "muted" }, "Missing"), el("span", {}, (p.completeness.missing || []).join(", ") || "none"))),
          p.completeness.complete === false
            ? el("div", { class: "mt-3" }, notice("Incomplete review", "A missing check means the review cannot be treated as safe. Retry before routing for approval.", "clay"))
            : null),
        card(el("h3", { class: "h3" }, "Disagreement"),
          p.disagreements.length ? null : el("p", { class: "small muted mt-1" }, "No conflicting conclusions on this review."),
          ...disagreements),
      ),
    ),
  );
}

/* --------------------------------------------------------------- rewrite */
export async function rewrite(id) {
  const r = await api.get(`/reviews/${id}`);
  const accepted = r.patches.filter((p) => p.decision === "accepted" || p.decision === "edited");
  const drift = r.drift;

  const patchCards = r.patches.map((p) => {
    const editor = el("input", { class: "field hidden", value: p.edited_text || p.replacement });

    const decide = (decision, editedText) =>
      actionButton(decision === "accepted" ? "Accept edit" : decision === "rejected" ? "Keep mine" : "Save edit", async () => {
        const res = await api.post(`/rewrite-patches/${p.id}/decision`, { decision, edited_text: editedText || null });
        if (res.blocked) toast(res.message || "Meaning drift detected.", true);
        else toast(decision === "rejected" ? "Kept your wording." : "Edit accepted.");
        refresh();
      }, decision === "accepted" ? "btn-primary" : "btn-quiet", { busyLabel: "Saving…" });

    const editButton = el("button", { class: "btn btn-quiet", type: "button" }, "Edit then accept");
    editButton.addEventListener("click", async () => {
      if (editor.classList.contains("hidden")) {
        editor.classList.remove("hidden");
        editButton.textContent = "Accept edited text";
        return;
      }
      const res = await api.post(`/rewrite-patches/${p.id}/decision`, { decision: "edited", edited_text: editor.value });
      if (res.blocked) toast(res.message || "Meaning drift detected.", true);
      else toast("Edit accepted.");
      refresh();
    });

    return el("div", { class: `patch ${p.decision === "accepted" ? "accepted" : p.decision === "rejected" ? "rejected" : ""}` },
      el("div", { class: "row-between" },
        el("span", { class: "tiny muted" }, `${p.rule_code || "policy"} · characters ${p.start}–${p.end}`),
        el("span", { class: "tiny muted", style: { textTransform: "uppercase", letterSpacing: ".08em" } }, p.decision)),
      el("div", { class: "sides" },
        el("div", { class: "side old" }, el("span", { class: "label" }, "Original"), el("p", { class: "small", style: { textDecoration: "line-through", color: "var(--clay-ink)" } }, p.original)),
        el("div", { class: "side new" }, el("span", { class: "label" }, "Proposed"), el("p", { class: "small strong", style: { color: "var(--sage-ink)" } }, p.replacement || "(removed)"))),
      el("p", { class: "tiny muted mt-2" }, p.reason),
      editor,
      el("div", { class: "row mt-3" }, decide("accepted"), editButton, decide("rejected")),
      el("p", { class: "tiny muted mt-2" }, "There is deliberately no “accept all”: each change is a separate, reversible decision."),
    );
  });

  const driftCard = card(
    el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Meaning drift"),
      chip(drift && drift.passed ? "invariants hold" : "blocked", drift && drift.passed ? "sage" : "clay")),
    el("p", { class: "tiny muted mt-1" },
      `Similarity ${drift ? Math.round(drift.similarity * 100) : 0}% — a warning signal, never proof of equal meaning.`),
    el("ul", { class: "check-list mt-3" },
      ...((drift ? drift.invariants : []) || []).map((c) =>
        el("li", {},
          el("span", { class: `mark ${c.passed ? "ok" : "bad"}` }, c.passed ? "✓" : "!"),
          el("div", {}, el("div", { class: "small strong" }, c.label), el("div", { class: "tiny muted" }, c.detail))))),
    drift && !drift.passed
      ? el("div", { class: "mt-3" }, notice("Automatic acceptance blocked", drift.blocking_reason, "clay"))
      : null,
  );

  const revision = card(
    el("h3", { class: "h3" }, "Re-review the revised version"),
    el("p", { class: "sub" }, "Accepted edits create an immutable new content version and a fresh review. Any old clearance is invalidated."),
    actionButton("Create revised version & re-review", async () => {
      const res = await api.post(`/reviews/${id}/revise`);
      navigate(`/reviews/${res.review.id}`);
    }, "btn-primary", { busyLabel: "Re-reviewing…" }),
  );
  revision.querySelector("button").disabled = accepted.length === 0;

  return el("div", {},
    crumbs([{ label: "Dashboard", href: "/dashboard" }, { label: r.content_title, href: `/reviews/${id}` }, { label: "Rewrite & drift" }]),
    pageHead("Rewrite & meaning drift",
      "A correction is a minimal patch, not a rewrite. Check the invariants before you accept anything.",
      chip(`${accepted.length} of ${r.patches.length} accepted`, accepted.length ? "sage" : "")),
    reviewTabs(id, "rewrite"),
    el("div", { class: "split" },
      el("div", { class: "stack" },
        card(el("h2", { class: "h2" }, "Original"),
          el("div", { class: "copy-block mt-2" }, r.content.body_text)),
        ...(patchCards.length ? patchCards : [card(el("p", { class: "small muted" }, "This review produced no suggested edits."))]),
        revision),
      el("div", { class: "stack" },
        driftCard,
        card(
          el("h3", { class: "h3" }, "Intent captured before generation"),
          el("div", { class: "stack-sm mt-2" },
            el("div", { class: "small" }, el("span", { class: "muted" }, "Audience: "), r.content.audience || (r.brand ? r.brand.audience : "") || "—"),
            el("div", { class: "small" }, el("span", { class: "muted" }, "Call to action: "), r.content.desired_cta || "—"),
            el("div", { class: "small" }, el("span", { class: "muted" }, "Channel: "), fmt.title(r.content.channel))),
          el("p", { class: "tiny muted mt-2" },
            "These are the invariants the validator enforces. Removing a qualifier or changing a quantity fails the check even if the wording reads well."))),
    ),
  );
}

/* ------------------------------------------------------------------ risk */
export async function risk(id) {
  const [riskData, r] = await Promise.all([api.get(`/reviews/${id}/risk`), api.get(`/reviews/${id}`)]);
  const total = (riskData.factors || []).reduce((sum, f) => sum + f.points, 0);

  const factors = (riskData.factors || []).map((f) =>
    el("div", { class: "row-between", style: { padding: "12px 24px", borderBottom: "1px solid var(--line-soft)" } },
      el("div", {},
        el("div", { class: "small strong" }, f.label),
        el("div", { class: "tiny muted" }, f.note)),
      el("div", { class: "row" },
        el("div", { class: "bar-track", style: { width: "96px" } },
          el("div", { class: "bar-fill", style: { width: `${Math.min(100, (f.points / Math.max(total, 1)) * 100)}%` } })),
        el("span", { class: "small num", style: { width: "34px", textAlign: "right" } }, `+${f.points}`))));

  const overrideInput = el("textarea", { class: "field", rows: "3", placeholder: "Why is this critical finding acceptable for this release?" });
  const overrideCard = riskData.hard_blocker
    ? el("div", { class: "card card-pad", style: { background: "#FBEDE9", borderColor: "rgba(155,44,30,.3)" } },
        el("h3", { class: "h3", style: { color: "var(--clay-ink)" } }, "Critical finding"),
        el("p", { class: "small mt-1" },
          "Approval is blocked. Resolve the finding, or have an authorised legal reviewer record a justified override. The override is written to the audit log."),
        el("span", { class: "label mt-3" }, "Justification (legal/compliance role only)"),
        overrideInput,
        actionButton("Record override", async () => {
          await api.post(`/reviews/${id}/override?justification=${encodeURIComponent(overrideInput.value)}`);
          toast("Override recorded with an audit entry.");
          refresh();
        }, "btn-quiet", { busyLabel: "Recording…" }))
    : null;

  return el("div", {},
    crumbs([{ label: "Dashboard", href: "/dashboard" }, { label: r.content_title, href: `/reviews/${id}` }, { label: "Risk & routing" }]),
    pageHead("Brand Risk Score & routing", "A transparent weighted score, with hard blockers that no number can override."),
    reviewTabs(id, "risk"),
    el("div", { class: "split" },
      el("div", { class: "stack" },
        card(
          el("div", { class: "row" },
            dial(riskData.score, riskData.band, 110),
            el("div", {},
              el("h2", { class: "h2" }, `${fmt.band(riskData.band)} risk`),
              el("p", { class: "small muted mt-1" }, riskData.routing.reason),
              el("div", { class: "row mt-2" },
                chip(`Route: ${fmt.title(riskData.routing.route)}`, "sage"),
                chip(`${riskData.routing.approver_role} decides`, "lilac"),
                riskData.hard_blocker ? chip("Hard blocker", "clay") : null)))),
        el("div", { class: "card card-flush" },
          el("div", { style: { padding: "20px 24px 0" } },
            el("h3", { class: "h3" }, "Score composition"),
            el("p", { class: "sub" }, "Each factor is additive and shown with the reason it scored.")),
          el("div", { class: "mt-3" }, ...factors,
            el("div", { class: "row-between", style: { padding: "12px 24px" } },
              el("span", { class: "small strong" }, "Total (capped at 100)"),
              el("span", { class: "small strong num" }, String(riskData.score))))),
        card(el("h3", { class: "h3" }, "Blocking findings"),
          el("div", { class: "stack-sm mt-2" },
            ...(riskData.blocking_findings.length
              ? riskData.blocking_findings.map((f) =>
                  el("div", { class: "finding" },
                    el("div", { class: "row-between" }, agentTag(f.agent), chip(fmt.title(f.severity), f.severity === "critical" || f.severity === "high" ? "clay" : "amber")),
                    el("p", { class: "small mt-1" }, f.explanation)))
              : [el("p", { class: "small muted" }, "No blocking findings.")]))),
      ),
      el("div", { class: "stack" },
        card(
          el("h3", { class: "h3" }, "Check completeness"),
          el("div", { class: "stack-sm mt-2" },
            el("div", { class: "row-between small" }, el("span", { class: "muted" }, "Expected"), el("span", {}, (riskData.completeness.expected || []).join(", "))),
            el("div", { class: "row-between small" }, el("span", { class: "muted" }, "Returned"), el("span", {}, (riskData.completeness.returned || []).join(", "))),
            el("div", { class: "row-between small" }, el("span", { class: "muted" }, "Missing"), el("span", {}, (riskData.completeness.missing || []).join(", ") || "none"))),
          riskData.completeness.complete === false
            ? el("div", { class: "mt-3" }, notice("Incomplete is not safe", "Missing checks can never auto-clear. Retry the review or route it to a specialist.", "clay"))
            : null),
        card(
          el("h3", { class: "h3" }, "Routing rules in force"),
          el("ul", { class: "small muted", style: { paddingLeft: "16px", lineHeight: "1.8" } },
            el("li", {}, "Low risk + trusted creator + complete checks → fast track"),
            el("li", {}, "Medium risk or low confidence → brand manager"),
            el("li", {}, "High-risk claim or regulated sector → legal/compliance"),
            el("li", {}, "Disagreement or missing evidence → specialist"),
            el("li", {}, "Changed content or policy → re-review"))),
        overrideCard,
        notice("What this score is not", riskData.disclaimer),
      ),
    ),
  );
}
