/* BrandSetGo — core helpers: API client, DOM builder, formatting, shared pieces.
   No framework, no build step. Everything here is plain browser JavaScript. */

/* ------------------------------------------------------------------ api */
const BASE = "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  if (!res.ok) {
    let detail = body && typeof body.detail === "string" ? body.detail : `${res.status} ${res.statusText}`;
    if (body && body.detail && typeof body.detail === "object" && body.detail.message) {
      detail = body.detail.message;
    }
    const error = new Error(detail);
    error.status = res.status;
    error.body = body;
    throw error;
  }
  return body;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: (path, body) => request(path, { method: "PUT", body: JSON.stringify(body) }),
};

/* ------------------------------------------------------------------ dom */
export function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat(4)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export function svg(tag, attrs = {}, ...kids) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  for (const kid of kids.flat(3)) if (kid) node.append(kid);
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function link(href, label, cls = "") {
  return el("a", { href, class: cls }, label);
}

/* -------------------------------------------------------------- format */
export const fmt = {
  title(value) {
    if (!value) return "";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  },
  status(value) {
    const map = {
      passport_issued: "Cleared",
      ready_for_approval: "Awaiting decision",
      needs_changes: "Needs changes",
      needs_human: "Needs human review",
      partial: "Partial review",
      approved: "Approved",
      reviewing: "Reviewing",
      draft: "Draft",
      pending: "Pending",
      completed: "Completed",
      changes_requested: "Changes requested",
      rejected: "Rejected",
      confirmed: "Confirmed",
      needs_human_review: "Needs human",
      inconclusive: "Inconclusive",
      pass: "Passed",
    };
    return map[value] || fmt.title(value);
  },
  tone(value) {
    if (["passport_issued", "approved", "pass", "published", "sage"].includes(value)) return "sage";
    if (["needs_changes", "changes_requested", "rejected", "needs_human", "partial", "confirmed", "critical", "high"].includes(value)) return "clay";
    if (["ready_for_approval", "pending", "medium", "needs_human_review", "incomplete"].includes(value)) return "amber";
    if (["reviewing", "inconclusive", "draft"].includes(value)) return "lilac";
    return "";
  },
  language(code) {
    return { en: "English", hi: "Hindi", mr: "Marathi", other: "Other" }[code] || String(code || "").toUpperCase();
  },
  date(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  },
  dateTime(value) {
    if (!value) return "—";
    const d = new Date(value);
    return `${d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" })} · ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
  },
  band(band) {
    return { low: "Low", medium: "Medium", high: "High", critical: "Critical", incomplete: "Incomplete", pending: "Pending" }[band] || fmt.title(band);
  },
  ms(value) {
    return value ? `${value} ms` : "—";
  },
  timecode(seconds) {
    if (seconds === null || seconds === undefined) return "";
    const total = Math.round(Number(seconds));
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  },
  rupees(value) {
    if (value === null || value === undefined) return "Custom";
    return `₹${Number(value).toLocaleString("en-IN")}`;
  },
};

/* ------------------------------------------------------------- pieces */
/** "1 brand" / "3 brands" without hand-written strings everywhere. */
export function plural(count, singular, pluralForm) {
  return `${count} ${count === 1 ? singular : pluralForm || `${singular}s`}`;
}

export function chip(text, tone = "", extra = "") {
  return el("span", { class: `chip ${tone} ${extra}`.trim() }, text);
}

export function statusChip(status) {
  return chip(fmt.status(status), fmt.tone(status));
}

export function card(...kids) {
  return el("div", { class: "card card-pad" }, ...kids);
}

export function cardHead(title, right) {
  return el("div", { class: "card-head" }, el("h2", { class: "h2" }, title), right || null);
}

export function pageHead(title, subtitle, actions, sample = false) {
  return el(
    "header",
    { class: "page-head" },
    el(
      "div",
      { class: "lead" },
      el(
        "div",
        { class: "row" },
        el("h1", { class: "h1" }, title),
        sample ? chip("Sample data", "lilac") : null,
      ),
      subtitle ? el("p", { class: "sub" }, subtitle) : null,
    ),
    actions ? el("div", { class: "page-actions" }, ...(Array.isArray(actions) ? actions : [actions])) : null,
  );
}

export function crumbs(items) {
  const kids = [];
  items.forEach((item, i) => {
    if (i) kids.push(el("span", { class: "sep" }, "/"));
    kids.push(item.href ? link(`#${item.href}`, item.label) : el("span", {}, item.label));
  });
  return el("nav", { class: "crumbs" }, ...kids);
}

export function notice(title, body, tone = "") {
  return el(
    "div",
    { class: `notice ${tone}`.trim() },
    el("strong", {}, title),
    body ? el("div", {}, body) : null,
  );
}

export function kv(items) {
  const dl = el("dl", { class: "kv" });
  items.forEach(({ label, value }) => {
    dl.append(el("div", {}, el("dt", {}, label), el("dd", {}, value)));
  });
  return dl;
}

export function field(label, value, hint) {
  return el(
    "div",
    {},
    el("span", { class: "label" }, label),
    el("div", { class: "field field-readonly" }, value, hint ? el("div", { class: "tiny muted mt-1" }, hint) : null),
  );
}

export function dial(score, band, size = 96) {
  const stroke = 7;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  const dash = (value / 100) * c;
  const colour = {
    low: "#3E6B4A",
    medium: "#C08A22",
    high: "#B45B2B",
    critical: "#9B2C1E",
    incomplete: "#6C7169",
  }[band] || "#6C7169";

  const circle = (extra) => svg("circle", { cx: size / 2, cy: size / 2, r, fill: "none", "stroke-width": stroke, ...extra });
  const chart = svg(
    "svg",
    { width: size, height: size },
    circle({ stroke: "#EFE6D2" }),
    circle({ stroke: colour, "stroke-linecap": "round", "stroke-dasharray": `${dash} ${c}` }),
  );
  return el(
    "div",
    { class: "dial", style: { width: `${size}px`, height: `${size}px` } },
    chart,
    el(
      "div",
      { class: "val" },
      el("b", {}, score === null || score === undefined ? "–" : String(score)),
      el("span", {}, "/ 100"),
    ),
  );
}

export function riskBadge(score, band) {
  const tone = band === "low" ? "sage" : band === "medium" ? "amber" : band === "incomplete" ? "" : "clay";
  return chip(`${score ?? "–"} / 100 · ${fmt.band(band)}`, tone);
}

export function stepper(steps) {
  return el(
    "div",
    { class: "stepper" },
    ...steps.map((s) =>
      el(
        "div",
        { class: "step" },
        el("span", { class: "n" }, String(s.n)),
        el("div", {}, el("div", { class: "t" }, s.title), el("div", { class: "d" }, s.body)),
      ),
    ),
  );
}

export function stat(value, label, note) {
  return el(
    "div",
    { class: "card card-pad stat" },
    el("div", { class: "num" }, String(value)),
    el("div", { class: "lbl" }, label),
    note ? el("div", { class: "note" }, note) : null,
  );
}

export function bar(label, value, max, suffix = "") {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return el(
    "div",
    { class: "bar-row" },
    el("div", { class: "name" }, label),
    el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: { width: `${Math.max(pct, 3)}%` } })),
    el("div", { class: "n" }, `${value}${suffix}`),
  );
}

export function agentTag(agent) {
  const names = { tone: "Tone", facts: "Facts", claims: "Claims", visual: "Visual", accessibility: "Access", language: "Lang" };
  return el(
    "span",
    { class: "agent" },
    el("span", { class: "av" }, String(agent || "?").slice(0, 1)),
    el("span", { class: "nm" }, names[agent] || agent),
  );
}

export function empty(title, body, action) {
  return el(
    "div",
    { class: "card empty" },
    el("h3", { class: "h3" }, title),
    el("p", { class: "sub" }, body),
    action ? el("div", { class: "row mt-4", style: { justifyContent: "center" } }, action) : null,
  );
}

export function downBanner(error) {
  return el(
    "div",
    { class: "banner-down" },
    el("h2", { class: "h2" }, "The review service is not responding"),
    el("p", { class: "sub" }, error || "Unknown error"),
    el("p", { class: "small mt-3" }, "Start it with ", el("code", {}, "run.bat"), " (Windows) or ", el("code", {}, "./run.sh"), ", then reload."),
    el("p", { class: "small muted mt-2" }, "Every screen reads from the API, so nothing is faked when it is down."),
  );
}

export function toast(message, bad = false) {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = message;
  node.className = `toast${bad ? " bad" : ""}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => node.classList.add("hide"), 4200);
}

export function spinner(label) {
  return el("span", { class: "row" }, el("span", { class: "spinner" }), el("span", { class: "small" }, label || "Working…"));
}

/* A button that runs an async action, shows progress and reports errors. */
export function actionButton(label, action, cls = "btn-primary", options = {}) {
  const button = el("button", { class: `btn ${cls}`.trim(), type: "button" }, label);
  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    const original = label;
    button.textContent = options.busyLabel || "Working…";
    try {
      await action();
    } catch (error) {
      toast(error.message || "That did not work.", true);
      if (error.status === 402) {
        toast("Opening your plan options…");
        location.hash = "/billing";
      }
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  });
  return button;
}

export function tabs(items, active) {
  return el(
    "nav",
    { class: "tabs" },
    ...items.map((item) =>
      el("a", { class: `tab${item.key === active ? " active" : ""}`, href: `#${item.href}` }, item.label),
    ),
  );
}

export function table(headers, rows, emptyText = "Nothing here yet.") {
  if (!rows.length) return el("p", { class: "sub" }, emptyText);
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "data" },
      el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows),
    ),
  );
}
