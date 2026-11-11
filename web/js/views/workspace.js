/* Overview, dashboard, content studio, brand genesis and brand DNA studio. */
import {
  actionButton, agentTag, api, bar, card, cardHead, chip, clear, crumbs, dial, el,
  empty, field, fmt, kv, link, notice, pageHead, riskBadge, stat, statusChip, stepper,
  table, toast,
} from "../core.js";
import { navigate, refresh, reloadShell, state } from "../router.js";

const USPS = [
  ["01", "Brand Genesis", "A solo creator defines brand standards in minutes, versioned and approved, instead of waiting on a policy team."],
  ["02", "Independent reviewers, not one verdict", "Tone, Facts, Claims, Visual and Accessibility report separately. Contradictions stay visible and a human decides."],
  ["03", "Fix without changing the promise", "Every suggestion is a reversible patch with invariant checks for CTA, audience, facts and qualifiers."],
  ["04", "Risk-aware routing", "Explainable pre-publish risk with configurable paths. Trust changes the route, never the critical blockers."],
  ["05", "Coaching, not policing", "Repeated mistakes become short lessons, so creators improve instead of collecting rejections."],
  ["06", "Visible privacy and Indian-language fidelity", "Sensitivity labels, redact-before-send and an AI disclosure log, plus EN/HI/MR terminology consistency."],
];

/* ------------------------------------------------------------- overview */
export async function overview() {
  const brands = state.brands.length ? state.brands : await api.get("/brands");

  const paths = [
    ["Quick Check", "One item, default rules, no account setup.", "lilac", "#/"],
    ["Personal brand", "Your voice, vocabulary and saved examples.", "sage", "#/genesis"],
    ["Business brand", "Brand DNA, claims, assets and approval routing.", "amber", "#/genesis"],
    ["Agency workspace", "Isolated client brands with client approvers.", "", "#/genesis"],
  ].map(([title, body, tone, href]) =>
    el(
      "a",
      { class: "card card-pad", href, style: { transition: "transform .15s" } },
      chip(title, tone),
      el("p", { class: "sub", style: { marginTop: "12px" } }, body),
    ),
  );

  return el(
    "div",
    {},
    pageHead(
      "Every brand. Every medium. One standard.",
      "BrandSetGo turns each brand's approved identity into a versioned, evidence-backed review policy, so content is checked before it publishes.",
      el("a", { class: "btn btn-primary", href: "#/studio" }, "Check new content"),
    ),
    el("div", { class: "grid g4" }, ...paths),
    el(
      "div",
      { class: "split mt-6" },
      quickCheck(),
      card(
        cardHead("Your brands", link("#/genesis", "New brand")),
        el("p", { class: "sub" }, "Each brand carries its own policy version, verified claims and approval route."),
        el(
          "div",
          { class: "stack-sm mt-4" },
          ...(brands.length
            ? brands.map((b) =>
                el(
                  "a",
                  {
                    class: "row-between",
                    href: `#/brands/${b.id}/dna`,
                    style: { border: "1px solid var(--line)", background: "#FDF8EC", borderRadius: "12px", padding: "12px 16px" },
                  },
                  el(
                    "span",
                    {},
                    el("span", { class: "strong", style: { display: "block" } }, b.name),
                    el("span", { class: "tiny muted" }, `${b.kind_label} · ${b.languages.join(", ").toUpperCase() || "EN"}`),
                  ),
                  chip(`Policy v${b.policy_version ?? "–"}`, "sage"),
                ),
              )
            : [el("p", { class: "small muted" }, "No brands yet. Start with Brand Genesis.")]),
        ),
        el("a", { class: "btn btn-ghost btn-block mt-4", href: "#/genesis" }, "Create a brand"),
      ),
    ),
    el("h2", { class: "h2 mt-10" }, "Six things this product does that a grammar checker cannot"),
    el(
      "div",
      { class: "grid g3 mt-4" },
      ...USPS.map(([n, title, body]) =>
        el(
          "div",
          { class: "card card-pad" },
          el("span", { class: "serif", style: { color: "var(--brass)", fontSize: "13px" } }, n),
          el("h3", { class: "h3 mt-1" }, title),
          el("p", { class: "sub", style: { marginTop: "6px" } }, body),
        ),
      ),
    ),
    el(
      "div",
      { class: "card card-pad mt-6", style: { background: "#F1F4EA" } },
      el(
        "div",
        { class: "row-between" },
        el(
          "div",
          {},
          el("h3", { class: "h3" }, "From draft to a version-locked clearance"),
          el("p", { class: "sub" }, "Brand → policy version → submission → five checkers → reconciliation → intent-preserving fixes → risk routing → human decision → Brand Passport."),
        ),
        el("a", { class: "btn btn-ghost", href: "#/workflow" }, "See the state machine"),
      ),
    ),
  );
}

function quickCheck() {
  const textarea = el("textarea", { class: "field", rows: "4", "aria-label": "Content to check" },
    "Meet our new Winter Serum. Clinically proven to remove wrinkles in 7 days. Shop now!");
  const language = el("select", { class: "field", style: { maxWidth: "150px" } },
    el("option", { value: "en" }, "English"),
    el("option", { value: "hi" }, "Hindi"),
    el("option", { value: "mr" }, "Marathi"));
  const out = el("div", { class: "mt-4" });

  const run = actionButton("Run check", async () => {
    clear(out);
    out.append(el("p", { class: "small muted" }, "Checking…"));
    const result = await api.post("/quick-check", {
      body_text: textarea.value,
      language: language.value,
      channel: "instagram_caption",
    });
    clear(out);
    out.append(riskBadge(result.risk.score, result.risk.band));
    const blocking = result.findings.filter((f) => f.status !== "pass");
    if (!blocking.length) {
      out.append(el("p", { class: "small mt-2", style: { color: "var(--sage-ink)" } }, "No blocking issues with the default rules."));
    }
    for (const f of blocking) {
      out.append(
        el(
          "div",
          { class: "finding mt-2" },
          el("div", { class: "top" },
            el("span", { class: "strong" }, `${f.agent} · ${f.span_text || "whole item"}`),
            chip(fmt.title(f.severity), f.severity === "high" || f.severity === "critical" ? "clay" : "amber")),
          el("p", { class: "small mt-1" }, f.explanation),
          f.suggested_patch && f.suggested_patch.replacement
            ? el("p", { class: "small mt-1", style: { color: "var(--sage-ink)" } }, `Suggested: ${f.suggested_patch.replacement}`)
            : null,
        ),
      );
    }
    out.append(el("p", { class: "tiny muted mt-2" }, result.note));
  });

  return el(
    "div",
    { class: "card card-pad" },
    el("div", { class: "card-head" }, el("h2", { class: "h2" }, "Quick Check"), chip("No brand needed", "lilac")),
    el("p", { class: "sub" }, "Paste one item for default clarity, claim and accessibility checks. Create a brand page to enforce your own policy."),
    el("div", { class: "mt-3" }, textarea),
    el("div", { class: "row mt-3" }, language, run),
    out,
  );
}

/* ------------------------------------------------------------ dashboard */
export async function dashboard() {
  const d = await api.get("/dashboard");

  const brandCards = d.brands.map((b) =>
    el(
      "div",
      { class: "card card-pad stack" },
      el("h3", { class: "h3" }, b.name),
      el("p", { class: "small muted" }, `${b.kind_label} · ${b.languages.map((l) => l.toUpperCase()).join(", ") || "EN"}`),
      el("div", { class: "row" },
        chip(`Policy v${b.policy_version ?? "–"}`, "sage"),
        chip(`${b.asset_count} assets`, "lilac"),
        b.open_reviews ? chip(`${b.open_reviews} open`, "amber") : null),
      el("div", { class: "row" },
        el("a", { class: "btn btn-ghost grow", href: `#/studio?brand=${b.id}` }, "Check content"),
        el("a", { class: "btn btn-quiet", href: `#/brands/${b.id}/dna` }, "DNA")),
    ),
  );

  const reviewRows = d.recent_reviews.map((r) =>
    el(
      "tr",
      {},
      el("td", {},
        el("a", { href: `#/reviews/${r.id}`, class: "strong" }, r.content_title),
        el("span", { class: "tiny muted" }, ` v${r.content_version}`)),
      el("td", { class: "small muted" }, r.brand_name),
      el("td", { class: "num small" }, `${r.risk_score ?? "–"} / 100`),
      el("td", {}, statusChip(r.status)),
      el("td", { class: "small muted" }, fmt.date(r.created_at)),
    ),
  );

  const pending = d.pending_approvals.map((a) =>
    el(
      "div",
      { class: "row-between", style: { border: "1px solid var(--line)", background: "#FDF8EC", borderRadius: "12px", padding: "12px 16px" } },
      el("div", {},
        el("div", { class: "strong" }, a.review ? a.review.content_title : "—"),
        el("div", { class: "tiny muted" }, `${a.review ? a.review.brand_name : ""} · requested by ${a.requested_by} · ${a.approver_role} approval`)),
      el("div", { class: "row" }, chip(`${a.review ? a.review.risk_score ?? "–" : "–"} / 100`, "amber"),
        el("a", { class: "btn btn-quiet btn-sm", href: "#/approvals" }, "Decide")),
    ),
  );

  return el(
    "div",
    {},
    pageHead("Dashboard", "Check content before you publish. Start with “Check new content”.",
      el("a", { class: "btn btn-primary", href: "#/studio" }, "+ Check new content")),
    stepper([
      { n: 1, title: "Pick a brand", body: "Choose whose rules apply." },
      { n: 2, title: "Add content", body: "Paste text or upload a file." },
      { n: 3, title: "Review findings", body: "Fix issues with suggested edits." },
      { n: 4, title: "Get cleared", body: "Receive your Brand Passport." },
    ]),
    el("div", { class: "grid g3 mt-4" },
      stat(d.counts.waiting, "Waiting for your decision", "Approvals routed to a human"),
      stat(d.counts.cleared_this_month, "Cleared this month", "Version-locked clearances"),
      stat(d.counts.need_changes, "Need changes", `${d.counts.needs_human} escalated to a specialist`)),
    el("div", { class: "row-between mt-8" },
      el("h2", { class: "h2" }, "Your brands"),
      el("div", { class: "row" }, chip("Sample data", "lilac"), link("#/genesis", "+ New brand", "small strong"))),
    el("div", { class: "grid g3 mt-3" }, ...brandCards),
    el("div", { class: "card card-flush mt-6" },
      el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
        el("h2", { class: "h2" }, "Recent reviews"),
        link("#/reviews", "Open review queue", "small strong")),
      el("div", { class: "mt-3" }, table(["Content", "Brand", "Risk score", "Status", "Date"], reviewRows, "No reviews yet."))),
    pending.length
      ? card(cardHead("Waiting for your decision", link("#/approvals", "All approvals", "small strong")),
          el("div", { class: "stack-sm mt-3" }, ...pending))
      : null,
  );
}

/* ---------------------------------------------------------- content studio */
export async function studio() {
  const brands = await api.get("/brands");
  if (!brands.length) {
    return el("div", {}, pageHead("Content Studio"), empty("No brands yet", "Create a brand first so there are rules to check against.", el("a", { class: "btn btn-primary", href: "#/genesis" }, "Create a brand")));
  }

  const params = new URLSearchParams((location.hash.split("?")[1] || ""));
  const initial = params.get("brand") || brands[0].id;

  const brandSelect = el("select", { class: "field" }, ...brands.map((b) => el("option", { value: b.id }, `${b.name} · Policy v${b.policy_version ?? "–"}`)));
  brandSelect.value = initial;

  const modality = el("select", { class: "field" },
    ...["text", "image", "video", "audio"].map((m) => el("option", { value: m }, fmt.title(m))));

  let segments = [];
  let duration = 0;
  const transcriptArea = el("textarea", {
    class: "field", rows: "5",
    placeholder: "Paste an SRT or VTT transcript, or lines like 00:12 the spoken words…",
  });
  const transcriptInfo = el("p", { class: "tiny muted mt-1" });
  const mediaPanel = el("div", { class: "hidden" });

  async function parseTranscript() {
    if (!transcriptArea.value.trim()) {
      transcriptInfo.textContent = "Paste a transcript first.";
      return;
    }
    try {
      const result = await api.post("/content/transcript", { content: transcriptArea.value, format: "auto" });
      segments = result.segments;
      duration = result.duration_s;
      transcriptInfo.textContent = `${segments.length} segments · ${fmt.timecode(duration)} · ${result.word_count} words`;
      toast("Transcript parsed.");
    } catch (error) {
      transcriptInfo.textContent = error.message;
    }
  }

  const audioInput = el("input", { type: "file", accept: "audio/*", class: "hidden" });
  audioInput.addEventListener("change", async () => {
    const file = audioInput.files && audioInput.files[0];
    if (!file) return;
    transcriptInfo.textContent = "Transcribing with Sarvam…";
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/content/transcribe", { method: "POST", body: form });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail && json.detail.message ? json.detail.message : "Could not transcribe that file.");
      segments = json.segments;
      duration = json.duration_s;
      transcriptArea.value = segments.map((seg) => `${fmt.timecode(seg.start)} ${seg.text}`).join("\n");
      transcriptInfo.textContent = `${segments.length} segments · ${fmt.timecode(duration)} · ${json.engine}` +
        (json.timing === "estimated" ? " · timings estimated from runtime" : " · word-level timings");
    } catch (error) {
      transcriptInfo.textContent = error.message;
    }
  });

  let imageAsset = null;
  let imageAnalysis = null;
  const imageInput = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif", class: "hidden" });
  const imageInfo = el("div", { class: "mt-2" });
  const imageCard = el("div", { class: "card card-pad mt-4" },
    el("div", { class: "card-head" },
      el("h3", { class: "h3" }, "Image"),
      chip("measured from pixels", "brass")),
    el("p", { class: "tiny muted mt-1" },
      "Palette and text contrast are measured from the file itself. Text baked into the image is not read automatically — paste the on-screen copy above to have it reviewed."),
    actionButton("Upload image", async () => imageInput.click(), "btn-quiet"),
    imageInput,
    imageInfo);

  imageInput.addEventListener("change", async () => {
    const file = imageInput.files && imageInput.files[0];
    if (!file) return;
    imageInfo.textContent = "Measuring…";
    const form = new FormData();
    form.append("brand_id", brandSelect.value);
    form.append("alt_text", title.value || file.name);
    form.append("file", file);
    try {
      const res = await fetch("/api/content/upload-image", { method: "POST", body: form });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "Upload failed.");
      imageAsset = json.asset_id;
      imageAnalysis = json.analysis;
      clear(imageInfo);
      imageInfo.append(
        el("div", { class: "row" },
          chip(`${json.analysis.width}×${json.analysis.height}`, "neutral"),
          json.analysis.contrast_ratio ? chip(`contrast ${json.analysis.contrast_ratio}:1`, json.analysis.contrast_ratio >= 4.5 ? "sage" : "clay") : chip("contrast unmeasured", "amber"),
          json.off_palette.length ? chip(`${json.off_palette.length} off-palette`, "clay") : chip("on palette", "sage")),
        el("div", { class: "row mt-2" },
          ...json.analysis.palette.map((c) => el("span", { style: { width: "22px", height: "22px", borderRadius: "6px", border: "1px solid var(--line)", background: c } }))),
        el("p", { class: "tiny muted mt-2" }, json.analysis.note),
      );
    } catch (error) {
      imageInfo.textContent = error.message;
    }
  });

  const mediaCard = el("div", { class: "card card-pad mt-4" },
    el("div", { class: "card-head" },
      el("h3", { class: "h3" }, "Spoken copy"),
      chip("timecoded flags", "brass")),
    el("p", { class: "tiny muted mt-1" },
      "Video and audio are reviewed through their words. Sarvam transcribes audio with word timings; a transcript gives the same result without a model call."),
    transcriptArea,
    el("div", { class: "row mt-2" },
      actionButton("Parse transcript", parseTranscript, "btn-quiet", { busyLabel: "Parsing…" }),
      actionButton("Upload audio", async () => audioInput.click(), "btn-quiet"),
      audioInput),
    transcriptInfo);

  function syncMediaPanel() {
    const media = modality.value === "video" || modality.value === "audio";
    mediaPanel.classList.toggle("hidden", !media && modality.value !== "image");
    if (media && !mediaPanel.contains(mediaCard)) mediaPanel.append(mediaCard);
    if (modality.value === "image" && !mediaPanel.contains(imageCard)) mediaPanel.append(imageCard);
    if (modality.value !== "image" && mediaPanel.contains(imageCard)) imageCard.remove();
  }
  modality.addEventListener("change", syncMediaPanel);

  const channel = el("select", { class: "field" },
    ...["instagram_caption", "website_banner", "product_page", "linkedin_post", "email", "print_poster"]
      .map((c) => el("option", { value: c }, fmt.title(c))));
  const language = el("select", { class: "field" },
    el("option", { value: "en" }, "English"),
    el("option", { value: "hi" }, "Hindi"),
    el("option", { value: "mr" }, "Marathi"));
  const sensitivity = el("select", { class: "field" },
    el("option", { value: "public" }, "Public"),
    el("option", { value: "internal", selected: true }, "Internal – no private data"),
    el("option", { value: "confidential" }, "Confidential"),
    el("option", { value: "restricted" }, "Restricted – local only"));
  const title = el("input", { class: "field", value: "Instagram caption – Noir Oud" });
  const cta = el("input", { class: "field", value: "Shop the collection" });
  const body = el("textarea", { class: "field", rows: "6" },
    "Noir Oud Eau de Parfum 50 ml lasts 24 hours. A deep oud trail. Shop the collection.");
  const audience = el("input", { class: "field field-readonly", readonly: true });
  const note = el("p", { class: "small mt-2" });

  const brandOf = () => brands.find((b) => b.id === brandSelect.value) || brands[0];
  const syncBrand = () => {
    audience.value = brandOf().audience || "";
    const b = brandOf();
    const channels = el("div", { class: "row mt-2" }, ...(b.channels || []).map((c) => chip(fmt.title(c))));
    const holder = document.getElementById("brand-chips");
    if (holder) { clear(holder); holder.append(channels); }
  };
  brandSelect.addEventListener("change", syncBrand);

  const fileInput = el("input", { type: "file", accept: ".pdf,.docx,.txt,.md,.csv", class: "hidden" });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    note.textContent = "Extracting…";
    try {
      const res = await fetch("/api/content/extract", { method: "POST", body: form });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Could not read that file.");
      body.value = json.text;
      note.textContent = `Extracted ${json.characters} characters from ${json.filename}.`;
    } catch (error) {
      note.textContent = error.message;
    }
  });

  const run = actionButton("Run review", async () => {
    const created = await api.post("/content", {
      brand_id: brandSelect.value,
      title: title.value || "Untitled content",
      body_text: body.value,
      channel: channel.value,
      language: language.value,
      desired_cta: cta.value,
      audience: brandOf().audience,
      sensitivity: sensitivity.value,
      modality: modality.value,
      meta: imageAnalysis
        ? { contrast_ratio: imageAnalysis.contrast_ratio, image: imageAnalysis, media_ref: imageAsset, asset_hash: imageAsset }
        : { contrast_ratio: 4.8 },
      transcript: modality.value === "text" ? [] : segments,
      duration_s: modality.value === "text" ? 0 : duration,
    });
    const review = await api.post("/reviews", { content_version_id: created.version_id });
    navigate(`/reviews/${review.id}`);
  }, "btn-primary", { busyLabel: "Running five checks…" });

  const left = card(
    el("h2", { class: "h2" }, "1. About this content"),
    el("div", { class: "form-row mt-4" },
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Brand"), brandSelect),
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Channel"), channel),
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Audience"), audience),
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Sensitivity"), sensitivity),
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Content type"), modality),
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Language"), language),
      el("label", { class: "form-field" }, el("span", { class: "label" }, "Desired call to action"), cta)),
    el("h2", { class: "h2 mt-6" }, "2. Your content"),
    el("label", { class: "form-field mt-3" }, el("span", { class: "label" }, "Title"), title),
    el("label", { class: "form-field mt-3" }, el("span", { class: "label" }, "Copy"), body),
    mediaPanel,
    fileInput,
    el("div", { class: "row mt-4" }, run,
      actionButton("Upload document or image", async () => fileInput.click(), "btn-ghost")),
    note,
  );

  const right = el("div", { class: "stack" },
    card(
      el("h3", { class: "h3" }, "What will be checked"),
      el("div", { class: "stack-sm mt-3" },
        ...[["Tone", "Voice, restricted words, approved examples"],
            ["Facts", "Sizes, prices and product details against the sheet"],
            ["Claims", "Promises and substantiation against approved sources"],
            ["Visual", "Approved assets, palette, logo lockup"],
            ["Accessibility", "Contrast, alt text, structure"]]
          .map(([k, v]) => el("div", { class: "row" },
            el("span", { class: "strong", style: { width: "100px", flex: "0 0 100px", fontSize: "12.5px" } }, k),
            el("span", { class: "small muted grow" }, v)))),
      el("p", { class: "tiny muted mt-2" }, "A semantic AI pass adds implied promises the patterns cannot see."),
      el("p", { class: "tiny muted mt-1" }, "Legal guidelines are checked even before your policy is approved; brand rules are marked provisional until then."),
    ),
    card(
      el("h3", { class: "h3" }, "This brand"),
      el("div", { class: "mt-3" }, field("Policy version", `v${brandOf().policy_version ?? "–"} · ${brandOf().policy_status ?? "—"}`)),
      el("div", { id: "brand-chips" }),
    ),
  );

  queueMicrotask(syncMediaPanel);

  const node = el("div", {},
    pageHead("Content Studio", "Add your content on the left. Findings appear on the right, explained in plain words."),
    el("div", { class: "split" }, left, right));
  queueMicrotask(syncBrand);
  return node;
}

/* ------------------------------------------------------------ brand genesis */
export async function genesis() {
  const draft = {
    kind: "business",
    name: "Élan Fragrances",
    sector: "perfume",
    description: "Small-batch Indian fragrance house launching its first oud line.",
    audience: "Fragrance lovers 24–40, India",
    tone: "Confident, sensory, restrained",
    banned: "cheap, knockoff",
    examples: "An oud that stays close. Worn for evenings that matter.",
    product: "Noir Oud Eau de Parfum",
    volume: "50",
    price: "4200",
    claim: "Concentrated oud accord",
    languages: ["en", "hi", "mr"],
    channels: ["instagram_caption", "website_banner"],
    colors: "#2C3A2E, #F3E9D2, #A9812F",
  };
  let step = 0;
  let created = null;

  const host = el("div");
  const previewHost = el("div", { class: "stack" });

  const steps = ["Identity", "Audience & tone", "Claims & products", "Assets & languages", "Review & approve"];

  function stepIndicator() {
    return el("ol", { class: "row", style: { listStyle: "none", padding: 0, gap: "16px", marginBottom: "24px" } },
      ...steps.map((label, i) =>
        el("li", { class: "row", style: { gap: "8px" } },
          el("span", {
            style: {
              width: "24px", height: "24px", borderRadius: "50%", display: "inline-flex",
              alignItems: "center", justifyContent: "center", fontSize: "11px", fontWeight: "600",
              background: i === step ? "var(--forest)" : i < step ? "var(--sage)" : "#EFE6D2",
              color: i === step ? "var(--cream)" : i < step ? "var(--sage-ink)" : "var(--muted)",
            },
          }, String(i + 1)),
          el("span", { class: i === step ? "small strong" : "small muted" }, label))),
    );
  }

  function textField(label, key, opts = {}) {
    const input = el(opts.textarea ? "textarea" : "input", {
      class: "field", value: draft[key], rows: opts.textarea ? "3" : null, type: opts.type || "text",
    });
    input.addEventListener("input", () => { draft[key] = input.value; renderPreview(); });
    return el("label", { class: "form-field" }, el("span", { class: "label" }, label), input);
  }

  function toggleRow(values, key) {
    return el("div", { class: "row" },
      ...values.map(([value, label]) => {
        const on = draft[key].includes(value);
        const button = el("button", {
          type: "button",
          class: `chip${on ? " sage" : ""}`,
          style: { border: "1px solid " + (on ? "var(--forest)" : "var(--line)"), cursor: "pointer", fontFamily: "inherit" },
        }, label);
        button.addEventListener("click", () => {
          draft[key] = on ? draft[key].filter((v) => v !== value) : [...draft[key], value];
          render();
        });
        return button;
      }),
    );
  }

  function renderPreview() {
    clear(previewHost);
    previewHost.append(
      card(
        el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Live Brand DNA preview"), chip("Draft", "lilac")),
        el("div", { class: "stack-sm mt-4" },
          field("Brand", draft.name || "—"),
          field("Audience", draft.audience || "—"),
          field("Voice", draft.tone || "—"),
          field("Languages", draft.languages.map((l) => l.toUpperCase()).join(" · ") || "—"),
          field("Channels", draft.channels.map((c) => fmt.title(c)).join(", ") || "—"),
          field("Restricted words", draft.banned.split(",").map((t) => t.trim()).filter(Boolean).join(" · ") || "none")),
      ),
      card(
        el("h3", { class: "h3" }, "What happens next"),
        el("ol", { class: "small muted", style: { paddingLeft: "18px", lineHeight: "1.8" } },
          el("li", {}, "Rules are drafted with a source and severity."),
          el("li", {}, "You approve, which publishes policy version 1."),
          el("li", {}, "Submissions are checked against that exact version."),
          el("li", {}, "A new policy version forces re-review.")),
      ),
    );
  }

  function stepBody() {
    if (step === 0) {
      return el("div", { class: "stack" },
        el("h2", { class: "h2" }, "1. What kind of brand is this?"),
        el("div", { class: "grid g3" },
          ...[["personal", "Personal brand", "Creators, freelancers, professionals"],
              ["business", "Business brand", "Startups, SMEs, in-house teams"],
              ["agency_client", "Agency client", "Isolated client brand with its own approver"]]
            .map(([value, title, body]) => {
              const on = draft.kind === value;
              const button = el("button", {
                type: "button",
                style: {
                  textAlign: "left", cursor: "pointer", fontFamily: "inherit", borderRadius: "12px",
                  padding: "12px 14px", background: on ? "#F1F4EA" : "#FDF8EC",
                  border: `1px solid ${on ? "var(--forest)" : "var(--line)"}`,
                },
              }, el("div", { class: "strong" }, title), el("div", { class: "tiny muted mt-1" }, body));
              button.addEventListener("click", () => { draft.kind = value; render(); });
              return button;
            })),
        el("div", { class: "form-row" }, textField("Brand name", "name"), textField("Sector", "sector")),
        textField("One-line description", "description", { textarea: true }),
        notice("Every proposed rule needs your approval",
          "Brand Genesis drafts a starter policy from this questionnaire. Nothing becomes enforceable until an owner approves a policy version."),
      );
    }
    if (step === 1) {
      return el("div", { class: "stack" },
        el("h2", { class: "h2" }, "2. Who is it for, and how does it sound?"),
        textField("Audience", "audience"),
        textField("Brand voice", "tone"),
        el("div", { class: "form-row" }, textField("Restricted words (comma separated)", "banned"),
          textField("Approved example lines", "examples")),
      );
    }
    if (step === 2) {
      return el("div", { class: "stack" },
        el("h2", { class: "h2" }, "3. What can you prove?"),
        el("p", { class: "sub" }, "Only claims with a source can be enforced. A claim you cannot substantiate is flagged every time it repeats."),
        el("div", { class: "form-row" }, textField("Product name", "product"), textField("Approved claim", "claim")),
        el("div", { class: "form-row" }, textField("Volume (ml)", "volume"), textField("Price (₹)", "price")),
        notice("Facts come from the product sheet",
          "The Facts reviewer compares sizes and prices in copy against this record. A mismatch is a fact finding, not a style note.", "sage"),
      );
    }
    if (step === 3) {
      return el("div", { class: "stack" },
        el("h2", { class: "h2" }, "4. Languages, channels and visuals"),
        el("div", {}, el("span", { class: "label" }, "Languages"),
          toggleRow([["en", "English"], ["hi", "Hindi"], ["mr", "Marathi"]], "languages")),
        el("div", {}, el("span", { class: "label" }, "Channels in scope"),
          toggleRow(["instagram_caption", "website_banner", "product_page", "linkedin_post", "email", "print_poster"]
            .map((c) => [c, fmt.title(c)]), "channels")),
        textField("Palette (comma separated hex)", "colors"),
        el("div", { class: "row" },
          ...draft.colors.split(",").map((c) => c.trim()).filter(Boolean)
            .map((c) => el("span", { style: { width: "36px", height: "36px", borderRadius: "10px", border: "1px solid var(--line)", background: c } }))),
      );
    }

    if (!created) {
      return el("div", { class: "stack" },
        el("h2", { class: "h2" }, "5. Approve your Brand DNA"),
        el("p", { class: "sub" }, "Brand Genesis will create the brand page, draft the policy and register the product and claim you supplied."),
        el("div", { class: "finding" },
          el("strong", {}, draft.name), ` · ${fmt.title(draft.kind)} · ${draft.sector} · ${draft.languages.join("/").toUpperCase()} · ${draft.channels.length} channels`),
        actionButton("Create brand & draft policy", async () => {
          const payload = {
            name: draft.name, kind: draft.kind, sector: draft.sector, description: draft.description,
            audience: draft.audience, tone: draft.tone, languages: draft.languages, channels: draft.channels,
            personality: {
              banned_terms: draft.banned.split(",").map((t) => t.trim()).filter(Boolean),
              approved_examples: draft.examples.split(".").map((t) => t.trim()).filter(Boolean),
            },
            palette: {
              colors: draft.colors.split(",").map((c) => c.trim()).filter(Boolean),
              text: draft.colors.split(",")[0] || "#1B2A21",
              background: draft.colors.split(",")[1] || "#FFFDF7",
            },
            logo_url: `/brands/${draft.name.toLowerCase().replace(/\s+/g, "-")}-logo.svg`,
            starter_questionnaire: { sector: draft.sector },
          };
          const res = await api.post("/brands", payload);
          const id = res.brand.id;
          if (draft.product.trim()) {
            await api.post(`/brands/${id}/products`, {
              name: draft.product,
              attributes: {
                ...(draft.volume ? { volume_ml: Number(draft.volume) } : {}),
                ...(draft.price ? { price_inr: Number(draft.price) } : {}),
              },
              sheet_ref: "Product sheet v4", sheet_page: 2,
            });
          }
          if (draft.claim.trim()) {
            await api.post(`/brands/${id}/claims`, {
              text: draft.claim, evidence_ref: "Founder-supplied substantiation", status: "verified",
            });
          }
          created = { id, rules: res.draft_policy.rules, version: res.brand.policy_version ?? 1 };
          await reloadShell();
          render();
        }, "btn-primary", { busyLabel: "Drafting Brand DNA…" }),
      );
    }

    return el("div", { class: "stack" },
      el("h2", { class: "h2" }, "5. Approve your Brand DNA"),
      el("p", { class: "sub" }, `Draft policy v${created.version} is ready with ${created.rules.length} rules. Approving makes them authoritative.`),
      el("div", { class: "card card-flush" },
        ...created.rules.map((r) =>
          el("div", { class: "row-between", style: { padding: "10px 16px", borderBottom: "1px solid var(--line-soft)" } },
            el("div", {},
              el("div", { class: "mono", style: { color: "var(--brass)" } }, r.code),
              el("div", { class: "strong small" }, r.title),
              el("div", { class: "tiny muted" }, `${r.category} · source: ${r.source_ref}`)),
            chip(fmt.title(r.severity), r.severity === "critical" ? "clay" : r.severity === "high" ? "amber" : "sage")))),
      notice("Model-proposed, human-approved",
        "These rules were drafted automatically. They stay proposed until you approve them, and every finding cites the rule it came from.", "sage"),
      actionButton("Approve & publish policy", async () => {
        await api.post(`/brands/${created.id}/policies/approve`, { approver: "Workspace owner" });
        toast("Policy published.");
        await reloadShell();
        navigate(`/brands/${created.id}/dna`);
      }, "btn-primary", { busyLabel: "Publishing…" }),
    );
  }

  function render() {
    clear(host);
    host.append(
      el("div", { class: "split-wide" },
        card(stepIndicator(), stepBody(),
          el("div", { class: "row-between mt-6" },
            el("button", {
              class: "btn btn-quiet", type: "button", disabled: step === 0,
              onclick: () => { step = Math.max(0, step - 1); render(); },
            }, "Back"),
            step < 4
              ? el("button", { class: "btn btn-primary", type: "button", onclick: () => { step += 1; render(); } }, "Continue")
              : null)),
        previewHost),
    );
  }

  renderPreview();
  render();
  return el("div", {},
    pageHead("Brand Genesis", "Five steps from a name to an approved, versioned policy. You approve every rule before it can block a submission."),
    host);
}

/* ------------------------------------------------------------- brand DNA */
export async function brandDna(id) {
  const b = await api.get(`/brands/${id}`);
  const policy = b.policy;
  const draftVersion = (b.drafts.find((d) => d.status === "draft") || {}).version;
  const hasDraft = Boolean(draftVersion);

  const ruleRows = (policy ? policy.rules : []).map((r) =>
    el("tr", {},
      el("td", {},
        el("div", { class: "mono", style: { color: "var(--brass)" } }, r.code),
        el("div", { class: "strong small" }, r.title),
        el("div", { class: "tiny muted" }, r.statement)),
      el("td", { class: "small" }, fmt.title(r.category)),
      el("td", {}, chip(fmt.title(r.severity), r.severity === "critical" ? "clay" : r.severity === "high" ? "amber" : "sage")),
      el("td", { class: "tiny muted" }, r.evidence_ref || r.source_ref,
        el("div", { class: "tiny muted" }, r.scope.length ? r.scope.map((s) => fmt.title(s)).join(", ") : "all channels")),
      el("td", {}, chip(r.is_authoritative ? "enforced" : "proposed", r.is_authoritative ? "sage" : "amber"))));

  const guidelineBox = el("textarea", { class: "field", rows: "6",
    style: { fontFamily: "var(--mono)", fontSize: "12px" } },
    "Tone: confident but never boastful. Never promise a medical outcome.\nEvery performance or duration claim must be backed by our approved claim register.\nAlways show the price including GST. Never use the words 'cheap' or 'knockoff'.\nMarathi and Hindi copy must use the approved glossary terms for product names.");

  const importCard = card(
    el("div", { class: "card-head" }, el("h3", { class: "h3" }, "Import brand guidelines"), chip("Sarvam extraction", "lilac")),
    el("p", { class: "sub" }, "Paste existing guidelines. Sarvam turns them into enforceable draft rules with a source for each one."),
    guidelineBox,
    el("div", { class: "row mt-2" },
      actionButton("Extract rules", async () => {
        const res = await api.post(`/brands/${id}/policies/import`, {
          guideline_text: guidelineBox.value, source_summary: "Imported brand guidelines",
        });
        toast(`Draft v${res.version} created with ${res.rules.length} rules (${res.extraction.source}).`);
        refresh();
      }, "btn-primary", { busyLabel: "Extracting…" })),
  );

  const approveCard = hasDraft
    ? el("div", { class: "card card-pad", style: { background: "#FBF2DE", borderColor: "rgba(169,129,47,.4)" } },
        el("div", { class: "row-between" },
          el("div", {},
            el("div", { class: "strong" }, `Policy v${draftVersion} is drafted but not enforced`),
            el("div", { class: "small muted" }, "Rules proposed by Brand Genesis stay advisory until an owner approves them.")),
          actionButton(`Approve policy v${draftVersion}`, async () => {
            await api.post(`/brands/${id}/policies/approve`, { approver: "Workspace owner" });
            toast("Policy published.");
            refresh();
          }, "btn-primary", { busyLabel: "Publishing…" })))
    : null;

  return el("div", {},
    crumbs([{ label: "Dashboard", href: "/dashboard" }, { label: b.name }]),
    pageHead("Brand DNA Studio",
      "Versioned voice, verified claims, terminology and visuals. A published policy is what every review is measured against.",
      [el("a", { class: "btn btn-ghost", href: `#/studio?brand=${b.id}` }, "Check content"), chip(`Policy v${policy ? policy.version : "–"}`, "sage")],
      b.is_sample),
    approveCard,
    el("div", { class: "split-wide" },
      el("div", { class: "stack" },
        el("div", { class: "card card-flush" },
          el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
            el("h2", { class: "h2" }, "Rules in force"),
            el("span", { class: "tiny muted" }, `${policy && policy.approved_by ? `Approved by ${policy.approved_by}` : "Awaiting approval"} · ${policy ? policy.source_summary : ""}`)),
          el("div", { class: "mt-3" },
            table(["Rule", "Category", "Severity", "Source", "Status"], ruleRows, "No published policy yet."))),
        el("div", { class: "grid g2" },
          card(
            el("h3", { class: "h3" }, "Products & verified claims"),
            el("div", { class: "stack-sm mt-3" },
              ...(b.products.length
                ? b.products.map((p) => el("div", { class: "finding" },
                    el("div", { class: "strong small" }, p.name),
                    el("div", { class: "tiny muted" },
                      `${p.sku}${p.attributes.volume_ml ? ` · ${p.attributes.volume_ml} ml` : ""}${p.attributes.price_inr ? ` · ₹${p.attributes.price_inr}` : ""} · ${p.sheet_ref} p.${p.sheet_page}`)))
                : [el("p", { class: "small muted" }, "No products recorded.")]),
              el("div", { class: "hairline" }),
              ...(b.claims.length
                ? b.claims.map((c) => el("div", {},
                    el("div", { class: "small" }, `“${c.text}”`),
                    el("div", { class: "tiny muted" }, `${c.status} · ${c.evidence_ref}`)))
                : [el("p", { class: "small muted" }, "No approved claims yet.")])),
          ),
          card(
            el("h3", { class: "h3" }, "Voice & restricted language"),
            el("div", { class: "stack-sm mt-3" },
              el("div", {}, el("span", { class: "label" }, "Voice"), el("p", { class: "small" }, b.tone || "—")),
              el("div", {}, el("span", { class: "label" }, "Restricted words"),
                el("div", { class: "row mt-1" },
                  ...((b.personality.banned_terms || []).length
                    ? b.personality.banned_terms.map((t) => chip(t, "clay"))
                    : [el("span", { class: "small muted" }, "none")]))),
              el("div", {}, el("span", { class: "label" }, "Approved examples"),
                el("ul", { class: "small muted", style: { margin: "4px 0 0", paddingLeft: "16px" } },
                  ...(b.personality.approved_examples || []).map((e) => el("li", {}, `“${e}”`)))))),
        ),
        el("div", { class: "card card-flush" },
          el("div", { class: "card-head", style: { padding: "20px 24px 0" } },
            el("h3", { class: "h3" }, "Glossary"),
            el("span", { class: "tiny muted" }, "Approved terms and prohibited translations")),
          el("div", { class: "mt-3" },
            table(["English", "Hindi", "Marathi", "Never use"],
              b.glossary.map((g) => el("tr", {},
                el("td", { class: "strong small" }, g.term_en),
                el("td", { class: "small" }, g.term_hi || "—"),
                el("td", { class: "small" }, g.term_mr || "—"),
                el("td", { class: "small", style: { color: "var(--clay-ink)" } }, (g.prohibited || []).join(", ") || "—"))),
              "No glossary terms recorded."))),
      ),
      el("div", { class: "stack" },
        card(
          el("h3", { class: "h3" }, "Brand profile"),
          el("div", { class: "mt-3" }, kv([
            { label: "Type", value: b.kind_label },
            { label: "Sector", value: b.sector || "—" },
            { label: "Audience", value: b.audience || "—" },
            { label: "Languages", value: b.languages.map(fmt.language).join(", ") || "—" },
            { label: "Creator trust", value: Number(b.trust_score).toFixed(2) },
            { label: "Assets", value: String(b.asset_count) },
          ])),
          el("div", { class: "row mt-4" },
            ...((b.palette.colors || []).map((c) =>
              el("span", { style: { width: "32px", height: "32px", borderRadius: "8px", border: "1px solid var(--line)", background: c } })))),
        ),
        card(
          el("h3", { class: "h3" }, "Policy history"),
          el("div", { class: "stack-sm mt-3" },
            ...b.drafts.map((d) => el("div", { class: "row-between" },
              el("span", { class: "small" }, `v${d.version} · ${d.rules} rules`),
              chip(d.status, d.status === "published" ? "sage" : d.status === "draft" ? "amber" : "")))),
        ),
        importCard,
        notice("Why versions matter",
          "A clearance is locked to the policy version it was reviewed under. Publishing a new version forces re-review of content whose rules changed."),
      ),
    ),
  );
}
