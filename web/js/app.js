/* Shell + router. Boots the session once, then swaps the view on every hash change. */
import { api, chip, clear, el, toast } from "./core.js";
import { state, render, setRenderers } from "./router.js";
import * as auth from "./views/auth.js";
import * as home from "./views/home.js";
import * as admin from "./views/admin.js";
import * as legal from "./views/legal.js";
import * as billing from "./views/billing.js";
import * as workspace from "./views/workspace.js";
import * as review from "./views/review.js";
import * as governance from "./views/governance.js";

const AUTH_ROUTES = new Set(["/login", "/signup", "/forgot", "/reset"]);

const NAV = {
  creator: [
    ["Main", [
      ["/creator", "My Dashboard"],
      ["/studio", "Content Studio"],
      ["/reviews", "My Reviews"],
      ["/passport", "My Passports"],
    ]],
    ["Guidance", [
      ["/legal", "Legal Library"],
      ["/coaching", "Coaching"],
      ["/privacy", "Privacy Center"],
      ["/insights", "My Analytics"],
      ["/billing", "Plan & billing"],
    ]],
  ],
  business: [
    ["Main", [
      ["/business", "Business Dashboard"],
      ["/dashboard", "Brands"],
      ["/studio", "Content Studio"],
      ["/approvals", "Approvals"],
      ["/reviews", "Reviews"],
    ]],
    ["Governance", [
      ["/legal", "Legal Library"],
      ["/privacy", "Privacy Center"],
      ["/insights", "Analytics"],
      ["/multilingual", "Multilingual"],
      ["/passport", "Brand Passports"],
      ["/workflow", "Workflow"],
      ["/billing", "Plan & billing"],
    ]],
  ],
};

const ROUTES = [
  [/^\/login$/, () => auth.login()],
  [/^\/signup$/, () => auth.signup()],
  [/^\/forgot$/, () => auth.forgot()],
  [/^\/reset$/, () => auth.reset()],
  [/^\/billing$/, () => billing.billing()],
  [/^\/creator$/, () => home.creatorDashboard()],
  [/^\/business$/, () => home.businessDashboard()],
  [/^\/admin$/, () => admin.console()],
  [/^\/legal$/, () => legal.library()],
  [/^\/$/, () => home.landing()],
  [/^\/dashboard$/, () => workspace.dashboard()],
  [/^\/studio$/, () => workspace.studio()],
  [/^\/genesis$/, () => workspace.genesis()],
  [/^\/brands\/([^/]+)\/dna$/, (m) => workspace.brandDna(m[1])],
  [/^\/reviews$/, () => review.queue()],
  [/^\/reviews\/([^/]+)\/panel$/, (m) => review.panel(m[1])],
  [/^\/reviews\/([^/]+)\/rewrite$/, (m) => review.rewrite(m[1])],
  [/^\/reviews\/([^/]+)\/risk$/, (m) => review.risk(m[1])],
  [/^\/reviews\/([^/]+)$/, (m) => review.detail(m[1])],
  [/^\/approvals$/, () => governance.approvals()],
  [/^\/passport\/([^/]+)$/, (m) => governance.passportDetail(m[1])],
  [/^\/passport$/, () => governance.passportList()],
  [/^\/verify\/([^/]+)$/, (m) => governance.verify(m[1])],
  [/^\/coaching$/, () => governance.coaching()],
  [/^\/multilingual$/, () => governance.multilingual()],
  [/^\/privacy$/, () => governance.privacy()],
  [/^\/insights$/, () => governance.insights()],
  [/^\/workflow$/, () => governance.workflow()],
];

const viewNode = document.getElementById("view");
const appRoot = document.querySelector(".app");
const sidebar = document.getElementById("sidebar");
const topbar = document.querySelector(".topbar");
const pagefoot = document.querySelector(".pagefoot");

function homeRoute(session) {
  if (!session) return "/login";
  return session.org.account_type === "creator" ? "/creator" : "/business";
}

function railLink(item, current) {
  const [href, label] = item;
  const active = current === href || current.startsWith(`${href}/`);
  return el(
    "a",
    { class: `rail-link${active ? " active" : ""}`, href: `#${href}` },
    el("span", {}, label),
    active ? el("span", { class: "dot" }) : null,
  );
}

function renderShell() {
  const session = state.session;
  const signedIn = Boolean(session);

  sidebar.classList.toggle("hidden", !signedIn);
  topbar.classList.toggle("hidden", !signedIn);
  pagefoot.classList.toggle("hidden", !signedIn);
  appRoot.classList.toggle("auth-mode", !signedIn);

  if (!signedIn) return;

  const nav = document.getElementById("rail-nav");
  clear(nav);
  const groups = NAV[session.org.account_type] || NAV.business;
  for (const [title, items] of groups) {
    nav.append(el("div", { class: "rail-group" }, title));
    items.forEach((item) => nav.append(railLink(item, state.path)));
  }
  if (session.platform_admin) {
    nav.append(el("div", { class: "rail-group" }, "Platform"));
    nav.append(railLink(["/admin", "Admin Console"], state.path));
  }

  document.getElementById("rail-meta").textContent =
    `${session.org.plan_name} · ${session.role}`;

  const switcher = document.getElementById("brand-switcher");
  const previous = switcher.value;
  clear(switcher);
  switcher.append(el("option", { value: "" }, "All brands"));
  for (const brand of state.brands) switcher.append(el("option", { value: brand.id }, brand.name));
  switcher.value = previous || "";

  const ws = document.getElementById("workspace-switcher");
  if (ws) {
    clear(ws);
    const workspaces = session.workspaces || [];
    for (const item of workspaces) {
      ws.append(el("option", { value: item.id, selected: item.id === session.org.id }, item.name));
    }
    ws.append(el("option", { value: "__new__" }, "+ New workspace"));
  }

  const usage = session.usage || {};
  const right = document.getElementById("topbar-right");
  clear(right);
  right.append(
    chip(session.live_models ? "Sarvam live" : "Deterministic mode", session.live_models ? "sage" : "amber"),
    chip(`${usage.reviews_used ?? 0}/${usage.reviews_limit ?? "—"} reviews`, "neutral"),
    el(
      "span",
      { class: "chip", style: { paddingLeft: "4px", gap: "8px" } },
      el(
        "span",
        {
          style: {
            width: "22px", height: "22px", borderRadius: "50%", background: "var(--forest)",
            color: "var(--cream)", display: "inline-flex", alignItems: "center",
            justifyContent: "center", fontSize: "10px", fontWeight: "700",
          },
        },
        session.user.initials,
      ),
      session.user.name,
    ),
    el("button", { class: "btn btn-quiet btn-sm", type: "button", onclick: () => auth.logout() }, "Sign out"),
  );
}

async function loadShell() {
  try {
    const session = await api.get("/auth/me");
    state.session = session;
    state.brands = await api.get("/brands").catch(() => []);
  } catch (error) {
    state.session = null;
    state.brands = [];
  }
  renderShell();
}

async function renderRoute() {
  const raw = (location.hash || "#/").slice(1) || "/";
  // strip ?tab=…&brand=… before matching; views read the query themselves
  const path = raw.split("?")[0] || "/";
  state.path = path;
  renderShell();

  const match = ROUTES.map(([re, fn]) => [re.exec(path), fn]).find(([m]) => m);
  const isAuthRoute = AUTH_ROUTES.has(path);

  // not signed in: only the auth pages are reachable
  if (!state.session && !isAuthRoute) {
    location.hash = "/login";
    return;
  }
  // signed in: the auth pages bounce to the right dashboard
  if (state.session && isAuthRoute) {
    location.hash = homeRoute(state.session);
    return;
  }

  clear(viewNode);
  if (!isAuthRoute) viewNode.append(el("div", { class: "skeleton", style: { height: "120px" } }));

  try {
    const node = await (match
      ? match[1](match[0])
      : Promise.resolve(
          el("div", { class: "card card-pad" },
            el("h2", { class: "h2" }, "Page not found"),
            el("p", { class: "sub" }, "That route does not exist."),
            el("a", { class: "btn btn-ghost mt-3", href: `#${homeRoute(state.session)}` }, "Go to my dashboard")),
        ));
    clear(viewNode);
    viewNode.append(node);
  } catch (error) {
    clear(viewNode);
    if (error.status === 401) {
      state.session = null;
      location.hash = "/login";
      return;
    }
    viewNode.append(
      el("div", { class: "banner-down" },
        el("h2", { class: "h2" }, error.status === 403 ? "You do not have access to this" : "Something went wrong"),
        el("p", { class: "sub" }, error.message)),
    );
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

setRenderers(renderRoute, loadShell);

const workspaceSwitcher = document.getElementById("workspace-switcher");
if (workspaceSwitcher) {
  workspaceSwitcher.addEventListener("change", async (event) => {
    const value = event.target.value;
    try {
      if (value === "__new__") {
        const name = prompt("Name for the new workspace?");
        if (!name) return;
        const type = state.session.org.account_type;
        const created = await api.post("/auth/workspaces", {
          name,
          account_type: type,
          plan: type === "creator" ? "creator_pro" : "business_starter",
        });
        toast(`Workspace "${name}" created.`);
        await loadShell();
        navigate(created.org.account_type === "creator" ? "/creator" : "/business");
        return;
      }
      await api.post("/auth/switch-workspace", { org_id: value });
      await loadShell();
      navigate(state.session.org.account_type === "creator" ? "/creator" : "/business");
    } catch (error) {
      toast(error.message, true);
    }
  });
}

const navToggle = document.getElementById("nav-toggle");
if (navToggle) {
  navToggle.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(open));
  });
}

document.getElementById("brand-switcher").addEventListener("change", (event) => {
  const id = event.target.value;
  location.hash = id ? `/brands/${id}/dna` : state.session ? homeRoute(state.session) : "/login";
});

window.addEventListener("hashchange", renderRoute);

(async function boot() {
  await loadShell();
  await renderRoute();
})();
