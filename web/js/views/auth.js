/* Sign in and sign up. No account is pre-filled: every workspace starts here. */
import { api, card, chip, clear, el, notice, toast } from "../core.js";
import { navigate, refresh, reloadShell } from "../router.js";

function shell(inner, side) {
  return el(
    "div",
    { class: "auth-page" },
    el(
      "div",
      { class: "auth-panel" },
      el(
        "div",
        { class: "auth-brand" },
        el("span", { class: "brandmark", style: { padding: 0 } }, "BrandSetGo"),
        el("p", { class: "tiny muted mt-1" }, "Brand governance for creators and teams"),
      ),
      inner,
    ),
    el("aside", { class: "auth-aside" }, side),
  );
}

function errorBox() {
  const node = el("div", { class: "hidden" });
  return {
    node,
    show(message) {
      node.className = "notice clay mt-3";
      node.textContent = message;
    },
    clear() {
      node.className = "hidden";
      node.textContent = "";
    },
  };
}

export async function login() {
  const email = el("input", { class: "field", type: "email", autocomplete: "email", placeholder: "you@company.com" });
  const password = el("input", { class: "field", type: "password", autocomplete: "current-password", placeholder: "Your password" });
  const errors = errorBox();
  const submit = el("button", { class: "btn btn-primary btn-block", type: "submit" }, "Sign in");

  const form = el(
    "form",
    { class: "stack mt-6" },
    el("label", { class: "form-field" }, el("span", { class: "label" }, "Email"), email),
    el("label", { class: "form-field" }, el("span", { class: "label" }, "Password"), password),
    errors.node,
    submit,
    el("p", { class: "small muted center" }, "No account yet? ", el("a", { href: "#/signup" }, "Create one")),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errors.clear();
    submit.disabled = true;
    submit.textContent = "Signing in…";
    try {
      const session = await api.post("/auth/login", { email: email.value.trim(), password: password.value });
      toast(`Signed in as ${session.user.name}`);
      await reloadShell();
      navigate(session.org.account_type === "creator" ? "/creator" : "/business");
    } catch (error) {
      errors.show(error.message);
      submit.disabled = false;
      submit.textContent = "Sign in";
    }
  });

  return shell(
    el("div", {},
      el("h1", { class: "h1", style: { fontSize: "30px" } }, "Welcome back"),
      el("p", { class: "sub" }, "Sign in to check content before it publishes."),
      form),
    el("div", { class: "stack" },
      el("h2", { class: "h2" }, "Every brand. Every medium. One standard."),
      el("p", { class: "small" }, "Independent reviewers, visible disagreement, minimal fixes, and a clearance record you can show."),
      el("ul", { class: "small", style: { paddingLeft: "18px", lineHeight: "1.9" } },
        el("li", {}, "AI classification of every submission"),
        el("li", {}, "Legal flags with the exact guideline cited"),
        el("li", {}, "Timecoded flags inside video and audio"),
        el("li", {}, "Version-locked Brand Passport")),
      el("p", { class: "tiny", style: { opacity: 0.8 } }, "Reviewer assistance, not legal advice.")),
  );
}

export async function signup() {
  const plans = await api.get("/auth/plans");
  let accountType = "creator";
  let planCode = "creator_free";

  const name = el("input", { class: "field", autocomplete: "name", placeholder: "Your name" });
  const email = el("input", { class: "field", type: "email", autocomplete: "email", placeholder: "you@company.com" });
  const company = el("input", { class: "field", placeholder: "Company or studio name" });
  const password = el("input", { class: "field", type: "password", autocomplete: "new-password", placeholder: "At least 8 characters" });
  const companyField = el("label", { class: "form-field hidden" }, el("span", { class: "label" }, "Company name"), company);
  const errors = errorBox();
  const planHost = el("div", { class: "plan-grid mt-2" });
  const submit = el("button", { class: "btn btn-primary btn-block", type: "submit" }, "Create account");

  const typeButton = (value, title, body) => {
    const active = accountType === value;
    const button = el(
      "button",
      {
        type: "button",
        class: "type-card" + (active ? " active" : ""),
      },
      el("div", { class: "strong" }, title),
      el("div", { class: "tiny muted mt-1" }, body),
    );
    button.addEventListener("click", () => {
      accountType = value;
      const first = plans.find((p) => p.account_type === value);
      planCode = first ? first.code : "";
      companyField.classList.toggle("hidden", value !== "business");
      renderTypes();
      renderPlans();
    });
    return button;
  };

  const typeHost = el("div", { class: "grid g2 mt-2" });
  function renderTypes() {
    clear(typeHost);
    typeHost.append(
      typeButton("creator", "I am a creator", "One personal brand, one seat"),
      typeButton("business", "I am a business", "Team, brands and approvals"),
    );
  }

  function renderPlans() {
    clear(planHost);
    for (const plan of plans.filter((p) => p.account_type === accountType)) {
      const active = plan.code === planCode;
      const button = el(
        "button",
        { type: "button", class: "plan-card" + (active ? " active" : "") },
        el("div", { class: "row-between" },
          el("span", { class: "strong" }, plan.name),
          el("span", { class: "strong" }, plan.price_inr === null ? "Custom" : `₹${plan.price_inr.toLocaleString("en-IN")}`)),
        el("div", { class: "tiny muted" }, `${plan.reviews_per_month} reviews / month · ${plan.brands} brand(s) · ${plan.seats} seat(s)`),
        el("div", { class: "tiny muted mt-1" }, plan.blurb),
      );
      button.addEventListener("click", () => {
        planCode = plan.code;
        renderPlans();
      });
      planHost.append(button);
    }
  }

  renderTypes();
  renderPlans();

  const form = el(
    "form",
    { class: "stack mt-5" },
    el("span", { class: "label" }, "Account type"),
    typeHost,
    companyField,
    el("label", { class: "form-field" }, el("span", { class: "label" }, "Your name"), name),
    el("label", { class: "form-field" }, el("span", { class: "label" }, "Work email"), email),
    el("label", { class: "form-field" }, el("span", { class: "label" }, "Password"), password),
    el("span", { class: "label mt-2" }, "Plan"),
    planHost,
    errors.node,
    submit,
    el("p", { class: "small muted center" }, "Already have an account? ", el("a", { href: "#/login" }, "Sign in")),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errors.clear();
    submit.disabled = true;
    submit.textContent = "Creating your workspace…";
    try {
      const session = await api.post("/auth/signup", {
        name: name.value.trim(),
        email: email.value.trim(),
        password: password.value,
        account_type: accountType,
        company: company.value.trim(),
        plan: planCode,
      });
      toast(session.platform_admin
        ? "Workspace created. You are the platform admin — open the Admin console to see every account."
        : "Workspace created.");
      await reloadShell();
      navigate(session.org.account_type === "creator" ? "/creator" : "/business");
    } catch (error) {
      errors.show(error.message);
      submit.disabled = false;
      submit.textContent = "Create account";
    }
  });

  return shell(
    el("div", {},
      el("h1", { class: "h1", style: { fontSize: "30px" } }, "Create your workspace"),
      el("p", { class: "sub" }, "Pick how you publish. A creator gets one personal brand; a business gets a team workspace."),
      form),
    el("div", { class: "stack" },
      el("h2", { class: "h2" }, "What you get on day one"),
      el("ul", { class: "small", style: { paddingLeft: "18px", lineHeight: "1.9" } },
        el("li", {}, "A brand policy drafted for you, enforced only after you approve it"),
        el("li", {}, "Six checkers, including a legal guideline registry with citations"),
        el("li", {}, "Timecoded flags for video and audio transcripts"),
        el("li", {}, "Clearance records locked to content and policy versions")),
      notice("No setup call needed", "Sign up, approve your policy, check your first post in a couple of minutes.")),
  );
}

export async function logout() {
  await api.post("/auth/logout");
  await reloadShell();
  navigate("/login");
  refresh();
}


export async function forgot() {
  const email = el("input", { class: "field", type: "email", placeholder: "you@company.com" });
  const out = el("div", { class: "hidden" });
  const submit = el("button", { class: "btn btn-primary btn-block", type: "submit" }, "Send reset link");

  const form = el("form", { class: "stack mt-6" },
    el("label", { class: "form-field" }, el("span", { class: "label" }, "Email"), email),
    out, submit,
    el("p", { class: "small muted center" }, el("a", { href: "#/login" }, "Back to sign in")));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "Sending…";
    try {
      const res = await api.post("/auth/forgot-password", { email: email.value.trim() });
      out.className = "notice sage mt-3";
      out.textContent = res.message;
    } catch (error) {
      out.className = "notice clay mt-3";
      out.textContent = error.message;
    } finally {
      submit.disabled = false;
      submit.textContent = "Send reset link";
    }
  });

  return shell(
    el("div", {},
      el("h1", { class: "h1", style: { fontSize: "30px" } }, "Reset your password"),
      el("p", { class: "sub" }, "We will email a single-use link that expires in 30 minutes."),
      form),
    el("div", { class: "stack" },
      el("h2", { class: "h2" }, "No mail server? Still works."),
      el("p", { class: "small" }, "Every message lands in the outbox. On a laptop with no SMTP, the platform admin can read the reset link from the admin console.")),
  );
}

export async function reset() {
  const token = new URLSearchParams(location.hash.split("?")[1] || "").get("token") || "";
  const password = el("input", { class: "field", type: "password", placeholder: "New password (8+ characters)" });
  const out = el("div", { class: "hidden" });
  const submit = el("button", { class: "btn btn-primary btn-block", type: "submit" }, "Set new password");

  const form = el("form", { class: "stack mt-6" },
    token ? null : notice("This link is missing its token", "Request a new reset link.", "clay"),
    el("label", { class: "form-field" }, el("span", { class: "label" }, "New password"), password),
    out, submit);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "Saving…";
    try {
      await api.post("/auth/reset-password", { token, password: password.value });
      toast("Password updated. Signing you in.");
      await reloadShell();
      const me = await api.get("/auth/me").catch(() => null);
      navigate(me ? (me.org.account_type === "creator" ? "/creator" : "/business") : "/login");
    } catch (error) {
      out.className = "notice clay mt-3";
      out.textContent = error.message;
      submit.disabled = false;
      submit.textContent = "Set new password";
    }
  });

  return shell(
    el("div", {},
      el("h1", { class: "h1", style: { fontSize: "30px" } }, "Choose a new password"),
      el("p", { class: "sub" }, "Signing in anywhere else will need the new password."),
      form),
    el("div", { class: "stack" },
      el("h2", { class: "h2" }, "Every other session is signed out"),
      el("p", { class: "small" }, "Changing the password revokes tokens issued before the change, so a stolen session stops working.")),
  );
}
