/* Legal guideline library plus a stateless copy scanner. */
import { actionButton, api, card, chip, clear, el, fmt, notice, pageHead } from "../core.js";

const SEVERITY_TONE = { critical: "clay", high: "amber", medium: "", low: "sage" };

export async function library() {
  const data = await api.get("/legal/guidelines");
  const host = el("div", { class: "stack" });
  const search = el("input", { class: "field", placeholder: "Search title, authority or citation", style: { maxWidth: "340px" } });
  const tagHost = el("div", { class: "row mt-3" });
  let activeTag = "";

  const tags = [...new Set(data.guidelines.flatMap((g) => g.tags))].sort();

  function renderList() {
    const query = search.value.trim().toLowerCase();
    const items = data.guidelines.filter((g) => {
      const haystack = `${g.code} ${g.title} ${g.authority} ${g.citation} ${g.obligation}`.toLowerCase();
      return (!query || haystack.includes(query)) && (!activeTag || g.tags.includes(activeTag));
    });
    clear(host);
    if (!items.length) {
      host.append(el("p", { class: "sub" }, "No guideline matches that filter."));
      return;
    }
    host.append(
      ...items.map((g) =>
        card(
          el("div", { class: "row-between" },
            el("div", {},
              el("div", { class: "mono", style: { color: "var(--brass)" } }, g.code),
              el("h3", { class: "h3 mt-1" }, g.title)),
            chip(fmt.title(g.severity), SEVERITY_TONE[g.severity] || "")),
          el("p", { class: "small mt-2" }, el("span", { class: "strong" }, g.authority), " — ", g.citation),
          el("p", { class: "small muted mt-2" }, g.obligation),
          el("div", { class: "finding mt-3" },
            el("span", { class: "label" }, "What to change"),
            el("p", { class: "small mt-1" }, g.remediation)),
          el("div", { class: "row mt-3" },
            ...(g.sectors.length ? g.sectors.map((s) => chip(s, "lilac")) : [chip("all sectors")]),
            ...(g.channels.length ? g.channels.slice(0, 3).map((c) => chip(fmt.title(c))) : [chip("all channels")]))),
      ),
    );
  }

  function renderTags() {
    clear(tagHost);
    tagHost.append(
      el("button", {
        class: `chip${activeTag === "" ? " sage" : ""}`, type: "button",
        style: { border: "1px solid var(--line)", cursor: "pointer", fontFamily: "inherit" },
        onclick: () => { activeTag = ""; renderTags(); renderList(); },
      }, `All (${data.guidelines.length})`),
      ...tags.map((tag) =>
        el("button", {
          class: `chip${activeTag === tag ? " sage" : ""}`, type: "button",
          style: { border: "1px solid var(--line)", cursor: "pointer", fontFamily: "inherit" },
          onclick: () => { activeTag = tag; renderTags(); renderList(); },
        }, tag)),
    );
  }

  search.addEventListener("input", renderList);
  renderTags();
  renderList();

  // stateless scanner
  const text = el("textarea", { class: "field", rows: "4" },
    "Our night cream cures eczema in 7 days. Clinically proven, guaranteed results. Gifted by Glow Co.");
  const sector = el("select", { class: "field", style: { maxWidth: "170px" } },
    ...["", "skincare", "perfume", "food", "finance", "health", "fashion", "tech"].map((s) =>
      el("option", { value: s }, s || "Any sector")));
  const channel = el("select", { class: "field", style: { maxWidth: "190px" } },
    ...["instagram_caption", "product_page", "website_banner", "linkedin_post", "email", "print_poster"].map((c) =>
      el("option", { value: c }, fmt.title(c))));
  const out = el("div", { class: "mt-4" });

  const scanCard = card(
    el("div", { class: "card-head" },
      el("h3", { class: "h3" }, "Scan copy against the registry"),
      chip(`registry ${data.registry_version}`, "lilac")),
    el("p", { class: "sub" }, "No account changes, no review created: this is the same deterministic check the pipeline runs."),
    el("div", { class: "mt-3" }, text),
    el("div", { class: "row mt-2" }, sector, channel,
      actionButton("Scan", async () => {
        const result = await api.post("/legal/preview", {
          text: text.value, sector: sector.value, channel: channel.value,
        });
        clear(out);
        if (!result.findings.length) {
          out.append(notice("No registry trigger found", "That does not mean compliant: the semantic AI pass and a human reviewer still apply.", "sage"));
          return;
        }
        out.append(
          el("div", { class: "row" }, chip(`${result.findings.length} trigger(s)`, "clay"),
            chip(`${result.checked.length} guidelines in scope`, "neutral")),
          el("div", { class: "stack-sm mt-3" },
            ...result.findings.map((f) =>
              el("div", { class: "finding" },
                el("div", { class: "row-between" },
                  el("span", { class: "small strong" }, f.guideline_title || f.title),
                  chip(fmt.title(f.severity), SEVERITY_TONE[f.severity] || "")),
                el("div", { class: "tiny mono mt-1" }, f.guideline_code),
                el("div", { class: "tiny mt-1" }, el("span", { class: "strong" }, f.guideline_authority), " — ", f.guideline_citation),
                f.span_text ? el("div", { class: "tiny mt-2", style: { color: "var(--brass)" } }, `“${f.span_text}”`) : null,
                el("p", { class: "small mt-1" }, f.explanation),
                el("p", { class: "tiny muted mt-1" }, el("span", { class: "strong" }, "Fix: "), f.remediation)))),
        );
      }, "btn-primary", { busyLabel: "Scanning…" })),
    out,
  );

  return el("div", {},
    pageHead("Legal library",
      "Every guideline the reviewer can cite, with the obligation and the fix. Findings in a review always point back to one of these codes.",
      chip(`${data.guidelines.length} guidelines`, "sage")),
    notice("Reviewer assistance, not legal advice", data.disclaimer),
    el("div", { class: "split-wide mt-5" },
      el("div", {},
        el("div", { class: "row-between" }, search),
        tagHost,
        el("div", { class: "mt-4" }, host)),
      el("div", { class: "stack" }, scanCard),
    ),
  );
}
