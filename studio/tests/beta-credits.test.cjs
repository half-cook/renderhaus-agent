const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const ts = require("typescript");
const { renderToStaticMarkup } = require("react-dom/server");

const root = path.resolve(__dirname, "..");
const openStatus = { enabled: true, wave: 1, wave_size: 3, spots_left: 3, programme_full: false, message: "3 spots left in this wave" };
const emptyAccount = { balance_cents: 0, recent_ledger: [], beta_credit: null };

function harness(respond, props = {}) {
  const cache = new Map();
  const values = [];
  const dependencies = [];
  const effects = [];
  const calls = [];
  let cursor = 0;
  let tree;
  let refreshed = 0;
  const componentProps = { account: emptyAccount, onClaimed: async () => { refreshed += 1; }, ...props };
  const hooks = {
    ...require("react"),
    useState(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = typeof initial === "function" ? initial() : initial;
      return [values[index], (next) => { values[index] = typeof next === "function" ? next(values[index]) : next; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = { current: initial };
      return values[index];
    },
    useEffect(effect, deps) {
      const index = cursor++;
      const old = dependencies[index];
      if (!old || !deps || deps.some((value, position) => value !== old[position])) {
        dependencies[index] = deps;
        effects.push(effect);
      }
    },
  };
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports;
    const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2021, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(filename, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, Headers, Response, Error, Number,
      fetch: async (url, init = {}) => {
        calls.push({ url, init, body: init.body ? JSON.parse(init.body) : null });
        return respond(url, init);
      },
      require: (name) => {
        if (name === "react") return hooks;
        if (name.endsWith(".module.css")) return new Proxy({}, { get: (_target, key) => key === "__esModule" ? false : String(key) });
        if (name.startsWith("@/")) return load(path.join(root, name.slice(2) + ".ts"));
        if (name.startsWith(".")) return load(path.resolve(path.dirname(filename), name + ".ts"));
        return require(name);
      },
    }, { filename });
    return module.exports;
  }
  function render() {
    cursor = 0;
    const { BetaCredits } = load(path.join(root, "components/BetaCredits.tsx"));
    tree = BetaCredits(componentProps);
    effects.splice(0).forEach((effect) => effect());
    return tree;
  }
  function elements(node) {
    if (Array.isArray(node)) return node.flatMap((child) => elements(child));
    if (!node || typeof node !== "object") return [];
    return [node, ...elements(node.props?.children)];
  }
  async function settle() {
    await new Promise((resolve) => setImmediate(resolve));
    render();
    await new Promise((resolve) => setImmediate(resolve));
    return render();
  }
  async function click(text) {
    const button = elements(tree).find((node) => node.type === "button" && renderToStaticMarkup(node).includes(text));
    assert.ok(button, `button ${text} is visible`);
    assert.equal(Boolean(button.props.disabled), false, `button ${text} is enabled`);
    await button.props.onClick();
    await settle();
  }
  function input(label, value) {
    const node = elements(tree).find((element) => element.type === "input" && element.props["aria-label"] === label);
    assert.ok(node, `input ${label} is visible`);
    node.props.onChange({ target: { value } });
    render();
  }
  return {
    render, settle, click, input, elements: () => elements(tree), calls,
    markup: () => renderToStaticMarkup(tree),
    setAccount: (account) => { componentProps.account = account; render(); },
    refreshed: () => refreshed,
    load: (relative) => load(path.join(root, relative)),
  };
}

const json = (value, status = 200) => new Response(JSON.stringify(value), { status });
function responses(status = openStatus, override) {
  return async (url, init) => {
    const special = override ? await override(url, init) : null;
    if (special) return special;
    if (url === "/api/beta/status") return json(status);
    if (url.endsWith("/start")) return json({ challenge_id: `${url.includes("email") ? "email" : "phone"}-challenge`, message: "Mock verification only. Use beta-email-ok for email or 424242 for phone.", dry_run: true });
    if (url.endsWith("/confirm")) return json({ verified: true, message: "Verified." });
    if (url === "/api/beta/claim") return json({ balance_cents: 1000, message: "Your free beta credit is ready.", grant: { amount_cents: 1000, wave: 1 } });
    if (url === "/api/beta/waitlist") return json({ message: "You joined the next-wave waitlist." });
    throw new Error(`unexpected URL ${url}`);
  };
}

async function mount(status = openStatus, props, override) {
  const ui = harness(responses(status, override), props);
  ui.render();
  await ui.settle();
  return ui;
}

async function verify(ui, kind, identifier, code) {
  ui.input(kind === "email" ? "Beta email" : "Beta phone", identifier);
  await ui.click(kind === "email" ? "Verify email" : "Verify phone");
  ui.input(kind === "email" ? "Email verification token" : "Phone verification code", code);
  await ui.click(kind === "email" ? "Confirm email" : "Confirm phone");
}

for (const [status, message, canVerify, canWaitlist] of [
  [openStatus, "3 spots left in this wave", true, false],
  [{ ...openStatus, spots_left: 0, message: "This wave is full. Join the waitlist for the next one." }, "This wave is full. Join the waitlist for the next one.", false, true],
  [{ ...openStatus, spots_left: 0, programme_full: true, message: "The free beta credit is fully allocated." }, "The free beta credit is fully allocated.", false, false],
  [{ ...openStatus, enabled: false, spots_left: 0, message: "Free beta credits are disabled." }, "Free beta credits are disabled.", false, false],
]) {
  test(`credits counter shows ${message} and only eligible actions`, async () => {
    const ui = await mount(status);
    assert.ok(ui.markup().includes(message));
    assert.equal(ui.markup().includes("Verify email"), canVerify);
    assert.equal(ui.markup().includes("Join waitlist"), canWaitlist);
  });
}

test("a compact credits popover links to the complete claim flow", async () => {
  const ui = await mount(openStatus, { compact: true });
  assert.match(ui.markup(), /3 spots left in this wave/);
  assert.match(ui.markup(), /href="\/home#beta-credits"/);
  assert.doesNotMatch(ui.markup(), /Verify email/);
});

test("claim requires both verifications and refreshes wallet and counter", async () => {
  let claimed = false;
  const ui = await mount(openStatus, undefined, (url) => {
    if (url === "/api/beta/claim") claimed = true;
    if (url === "/api/beta/status" && claimed) return json({ ...openStatus, spots_left: 2, message: "2 spots left in this wave" });
    return null;
  });
  ui.load("lib/authenticated-fetch.ts").configureStudioTokenGetter(async () => "fake-session");
  const claim = () => ui.elements().find((node) => node.type === "button" && renderToStaticMarkup(node).includes("Claim free credit"));
  assert.equal(claim().props.disabled, true);
  await verify(ui, "email", "person@example.test", "beta-email-ok");
  assert.equal(claim().props.disabled, true);
  await verify(ui, "phone", "+14165550123", "424242");
  assert.equal(claim().props.disabled, false);
  await ui.click("Claim free credit");
  assert.equal(ui.refreshed(), 1);
  assert.match(ui.markup(), /Your free beta credit is ready\./);
  assert.match(ui.markup(), /2 spots left in this wave/);
  assert.ok(ui.calls.filter((call) => call.url === "/api/beta/status").length >= 2);
  const emailConfirm = ui.calls.find((call) => call.url === "/api/beta/verify/email/confirm");
  assert.deepEqual(emailConfirm.body, { challenge_id: "email-challenge", token: "beta-email-ok" });
  assert.equal(emailConfirm.init.headers.get("Authorization"), "Bearer fake-session");
  const phoneConfirm = ui.calls.find((call) => call.url === "/api/beta/verify/phone/confirm");
  assert.deepEqual(phoneConfirm.body, { challenge_id: "phone-challenge", code: "424242" });
  assert.deepEqual(ui.calls.find((call) => call.url === "/api/beta/claim").body, {});
});

test("editing a verified identifier requires verifying it again before claim", async () => {
  const ui = await mount();
  await verify(ui, "email", "person@example.test", "beta-email-ok");
  await verify(ui, "phone", "+14165550123", "424242");
  ui.input("Beta email", "other@example.test");
  const claim = ui.elements().find((node) => node.type === "button" && renderToStaticMarkup(node).includes("Claim free credit"));
  assert.equal(claim.props.disabled, true);
  assert.match(ui.markup(), /Verify email/);
});

test("verification failures stay visible and do not enable claim", async () => {
  const ui = await mount(openStatus, undefined, (url) => url.endsWith("email/confirm") ? json({ detail: "Verification failed. Try again." }, 400) : null);
  ui.input("Beta email", "person@example.test");
  await ui.click("Verify email");
  assert.match(ui.markup(), /Mock verification only/);
  ui.input("Email verification token", "wrong");
  await ui.click("Confirm email");
  assert.match(ui.markup(), /role="alert"/);
  assert.match(ui.markup(), /Verification failed\. Try again\./);
  assert.ok(ui.elements().find((node) => node.type === "button" && renderToStaticMarkup(node).includes("Claim free credit")).props.disabled);
});

test("a claim denial displays the generic server message without losing verified inputs", async () => {
  const ui = await mount(openStatus, undefined, (url) => url === "/api/beta/claim" ? json({ detail: "Not eligible for free beta credit." }, 403) : null);
  await verify(ui, "email", "person@example.test", "beta-email-ok");
  await verify(ui, "phone", "+14165550123", "424242");
  await ui.click("Claim free credit");
  assert.match(ui.markup(), /Not eligible for free beta credit\./);
  assert.equal(ui.refreshed(), 0);
});

test("verification controls disable while a request is pending", async () => {
  let finish;
  const ui = await mount(openStatus, undefined, (url) => url.endsWith("email/start") ? new Promise((resolve) => { finish = resolve; }) : null);
  ui.input("Beta email", "person@example.test");
  const start = ui.elements().find((node) => node.type === "button" && renderToStaticMarkup(node).includes("Verify email"));
  const pending = start.props.onClick();
  await ui.settle();
  assert.ok(ui.elements().filter((node) => node.type === "button").every((node) => node.props.disabled));
  finish(json({ challenge_id: "email-challenge", message: "Mock verification only.", dry_run: true }));
  await pending;
  await ui.settle();
  assert.match(ui.markup(), /Confirm email/);
});

test("a full wave accepts a mocked waitlist entry and shows its result", async () => {
  const ui = await mount({ ...openStatus, spots_left: 0, message: "This wave is full. Join the waitlist for the next one." });
  ui.input("Waitlist email", "person@example.test");
  await ui.click("Join waitlist");
  assert.match(ui.markup(), /You joined the next-wave waitlist\./);
  assert.deepEqual(ui.calls.find((call) => call.url === "/api/beta/waitlist").body, { email: "person@example.test" });
});

test("an existing grant shows remaining credit and hides repeat verification", async () => {
  const ui = await mount(openStatus, { account: { ...emptyAccount, balance_cents: 700, beta_credit: { granted_cents: 1000, remaining_cents: 700, spent_cents: 300 } } });
  assert.match(ui.markup(), /\$7\.00 of your free beta credit remains\./);
  assert.doesNotMatch(ui.markup(), /Verify email|Claim free credit/);
});

test("empty-wallet guidance distinguishes spent beta credit from an ordinary empty wallet", () => {
  const ui = harness(responses());
  const { emptyWalletMessage } = ui.load("lib/beta-credits.ts");
  assert.equal(emptyWalletMessage(emptyAccount), "Your wallet is empty. Top up to keep creating.");
  assert.equal(emptyWalletMessage({ ...emptyAccount, beta_credit: { granted_cents: 1000, remaining_cents: 0, spent_cents: 1000 } }), "Your free beta credit is used up. Top up to keep creating.");
  assert.equal(emptyWalletMessage({ ...emptyAccount, balance_cents: 1 }), null);
});

test("an invalid public status cannot enable the claim flow", async () => {
  const ui = harness(async () => json({ enabled: true, spots_left: "unlimited" }));
  ui.render();
  await ui.settle();
  assert.match(ui.markup(), /Could not load free beta credit status\./);
  assert.doesNotMatch(ui.markup(), /Verify email|Claim free credit/);
});
