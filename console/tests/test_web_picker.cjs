const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function browser() {
  class Event {
    constructor(type, options = {}) { Object.assign(this, { type, bubbles: false, defaultPrevented: false }, options); }
    preventDefault() { this.defaultPrevented = true; }
    stopPropagation() { this.cancelBubble = true; }
  }
  class Element {
    constructor(tag = "div") {
      this.tagName = tag.toUpperCase();
      this.nodeType = 1;
      this.value = "";
      this.children = [];
      this.listeners = new Map();
      this.attributes = {};
      this.dataset = {};
      this.className = "";
      this.open = false;
      this.hidden = false;
      this.disabled = false;
      this.checked = false;
      this.classList = {
        add: (...values) => this.classes((set) => values.forEach((value) => set.add(value))),
        remove: (...values) => this.classes((set) => values.forEach((value) => set.delete(value))),
        toggle: (value, enabled) => this.classes((set) => {
          if (enabled ?? !set.has(value)) set.add(value); else set.delete(value);
        }),
      };
    }
    classes(update) { const values = new Set(this.className.split(/\s+/).filter(Boolean)); update(values); this.className = [...values].join(" "); }
    get textContent() { return (this.text || "") + this.children.map((child) => child.textContent || "").join(""); }
    set textContent(value) { this.replaceChildren(); this.text = String(value); }
    get parentElement() { return this.parentNode; }
    get isConnected() { return this === document.body || !!this.parentNode?.isConnected; }
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (["disabled", "hidden", "checked", "open"].includes(name)) this[name] = true;
      else if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = String(value);
      else this[name] = String(value);
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    addEventListener(type, handler) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(handler);
    }
    append(...children) {
      for (const child of children) { child.parentNode = this; this.children.push(child); }
    }
    replaceChildren(...children) {
      for (const child of this.children) child.parentNode = null;
      this.children = [];
      this.text = "";
      this.append(...children);
    }
    dispatchEvent(event) {
      event.target ??= this;
      event.currentTarget = this;
      for (const handler of this.listeners.get(event.type) || []) handler(event);
      if (event.bubbles && !event.cancelBubble && this.parentNode?.dispatchEvent) this.parentNode.dispatchEvent(event);
      return !event.defaultPrevented;
    }
    click() {
      if (this.disabled) return;
      if (this.tagName === "INPUT" && ["radio", "checkbox"].includes(this.type)) {
        if (this.type === "radio") {
          for (const input of document.body.querySelectorAll("input"))
            if (input.type === "radio" && input.name === this.name) input.checked = false;
          this.checked = true;
        } else this.checked = !this.checked;
        this.dispatchEvent(new Event("click", { bubbles: true }));
        this.dispatchEvent(new Event("change", { bubbles: true }));
      } else this.dispatchEvent(new Event("click", { bubbles: true }));
    }
    matches(selector) {
      return selector.split(",").some((part) => {
        part = part.trim();
        if (part.startsWith("#")) return this.id === part.slice(1);
        const match = part.match(/^([a-z]+)?(?:\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\])?$/i);
        return !!match && (!match[1] || this.tagName === match[1].toUpperCase())
          && (!match[2] || match[2] in this.attributes && (match[3] === undefined || this.attributes[match[2]] === match[3]));
      });
    }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest?.(selector) || null; }
    querySelectorAll(selector) {
      const result = [];
      for (const child of this.children) if (child.nodeType === 1) {
        if (child.matches(selector)) result.push(child);
        result.push(...child.querySelectorAll(selector));
      }
      return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    showModal() { this.open = true; }
    close() { if (this.open) { this.open = false; this.dispatchEvent(new Event("close")); } }
    escape() { if (this.dispatchEvent(new Event("cancel"))) this.close(); }
    focus() {}
    select() {}
  }
  const nodes = new Map(), timers = new Map(), requests = [];
  let sequence = 0;
  const document = {
    body: new Element("body"),
    getElementById(id) {
      if (!nodes.has(id)) { const element = new Element(); element.id = id; nodes.set(id, element); }
      return nodes.get(id);
    },
    createElement: (tag) => new Element(tag),
    createElementNS: (_namespace, tag) => new Element(tag),
    createTextNode: (text) => ({ nodeType: 3, textContent: String(text) }),
    querySelectorAll: (selector) => document.body.querySelectorAll(selector),
    querySelector: (selector) => document.body.querySelector(selector),
    addEventListener() {},
  };
  function node(id, tag, parent = document.body) {
    const element = new Element(tag); element.id = id; nodes.set(id, element); parent.append(element); return element;
  }
  const dialog = node("picker-dialog", "dialog");
  const close = node("picker-close", "button", dialog); close.setAttribute("data-close-dialog", "");
  for (const id of ["picker-title", "picker-subtitle", "picker-count", "picker-results"]) node(id, "div", dialog);
  node("picker-query", "input", dialog);
  for (const id of ["picker-search", "picker-prev", "picker-next", "picker-confirm"]) node(id, "button", dialog);
  document.getElementById("error-banner").hidden = true;
  const context = {
    window: { ConsoleVocabulary: require("../web/vocabulary.js"), ConsoleFields: require("../web/fields.js"),
      ConsoleLauncher: require("../web/launcher.js") }, document, Event, MouseEvent: Event,
    URLSearchParams, AbortController, structuredClone, location: { search: "" },
    setTimeout(fn, delay) { timers.set(++sequence, { fn, delay }); return sequence; },
    clearTimeout(id) { timers.delete(id); }, setInterval() {},
    fetch(url, options) { return new Promise((resolve) => requests.push({ url, options, resolve })); },
  };
  const source = fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8");
  vm.runInNewContext(source.replace(/\sinitialize\(\);\s*\}\)\(\);\s*$/, "\n})();"), context);
  const core = context.window.ConsoleCore;
  async function tick() {
    for (const [id, timer] of [...timers]) if (timer.delay < 1000) { timers.delete(id); timer.fn(); }
    for (let index = 0; index < 20; index++) await Promise.resolve();
  }
  async function reply(index, rows, total = rows.length, identity_field = "id") {
    requests.filter((request) => request.url.startsWith("/admin/catalog"))[index]
      .resolve({ ok: true, json: async () => ({ rows, total, identity_field }) });
    await tick();
  }
  function form(specs, values) {
    const result = core.makeForm(specs, values);
    document.body.append(result.element); core.state.currentForm = result; return result;
  }
  function open(form, name = "id") {
    const wrap = form.controls.get(name).input.parentNode;
    const button = wrap.querySelectorAll("button").find((element) => element.textContent === "选择…");
    assert.ok(button, "form field exposes the real picker button"); button.click();
  }
  const choices = () => nodes.get("picker-results").querySelectorAll("input");
  return { core, form, open, reply, tick, requests, dialog, close, node: (id) => nodes.get(id), choices, Event };
}

const rows = [{ id: "170014", name: "原文", _display: { name: "SSR 必中轉蛋券" } }, { id: 170009, name: "紀念轉蛋券" }];

test("single selection immediately fills a numeric ID, remembers its name and closes", async () => {
  const page = browser(), form = page.form([{ name: "id", label: "内容主数据 ID", type: "integer", source: "m_items" }]);
  page.open(form); await page.reply(0, rows);
  assert.equal(page.dialog.open, true);
  assert.equal(page.node("picker-confirm").hidden, true);
  page.choices()[0].click(); await page.tick();
  assert.equal(form.read().id, 170014);
  assert.equal(page.dialog.open, false);
  assert.match(form.controls.get("id").reference.textContent, /SSR 必中轉蛋券.*170014/);
  assert.equal(page.requests.length, 1, "selection does not fetch the catalog again");
});

test("clicking a single-select row chooses its record without a second click", async () => {
  const page = browser(), form = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(form); await page.reply(0, rows);
  page.choices()[1].closest("tr").click(); await page.tick();
  assert.equal(form.read().id, 170009); assert.equal(page.dialog.open, false);
});

test("multiple selection stays open, survives pages and merges numeric IDs once", async () => {
  const page = browser(), form = page.form([{ name: "ids", type: "ids", source: "m_items" }], { ids: [170014] });
  page.open(form, "ids"); await page.reply(0, rows, 101);
  assert.equal(page.node("picker-confirm").hidden, false);
  assert.equal(page.node("picker-confirm").disabled, true);
  page.choices()[0].click();
  assert.equal(page.dialog.open, true); assert.equal(page.node("picker-confirm").disabled, false);
  page.node("picker-next").click(); await page.reply(1, [{ id: 170010, name: "第二页" }], 101);
  page.choices()[0].click();
  page.node("picker-prev").click(); await page.reply(2, rows, 101);
  assert.equal(page.choices()[0].checked, true);
  page.node("picker-confirm").click(); await page.tick();
  assert.equal(JSON.stringify(form.read().ids), "[170014,170010]"); assert.equal(page.dialog.open, false);
});

for (const closeWith of ["button", "escape", "close"]) test(`${closeWith} dismisses without filling and discards late results`, async () => {
  const page = browser(), form = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(form);
  if (closeWith === "button") page.close.click(); else if (closeWith === "escape") page.dialog.escape(); else page.dialog.close();
  assert.equal(page.dialog.open, false);
  await page.reply(0, rows);
  assert.equal(page.choices().length, 0); assert.equal(form.controls.get("id").input.value, "");
});

test("a closed picker's late failure does not raise an error in a new picker", async () => {
  const page = browser(), form = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(form); page.dialog.close(); page.open(form);
  await page.reply(1, [{ id: 8, name: "新记录" }]);
  page.requests[0].resolve({ ok: false, json: async () => ({ error: { message: "old failure" } }) }); await page.tick();
  assert.equal(page.node("error-banner")?.hidden ?? true, true);
  assert.equal(page.choices().length, 1); page.choices()[0].click();
  assert.equal(form.read().id, 8);
});

test("late catalog results cannot replace a reopened picker or a newer search", async () => {
  const page = browser(), form = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(form); page.dialog.close(); page.open(form);
  page.node("picker-query").value = "new"; page.node("picker-search").click();
  await page.reply(2, [{ id: 30, name: "新搜索" }]);
  await page.reply(1, [{ id: 20, name: "旧搜索" }]);
  await page.reply(0, [{ id: 10, name: "旧弹窗" }]);
  assert.equal(page.choices().length, 1);
  page.choices()[0].click(); assert.equal(form.read().id, 30);
});

test("interactive content inside a result row does not select the row", async () => {
  const page = browser(), form = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(form); await page.reply(0, rows);
  const row = page.choices()[0].closest("tr"), link = new row.constructor("a");
  row.children[1].append(link);
  link.click();
  assert.equal(form.controls.get("id").input.value, ""); assert.equal(page.dialog.open, true);
});

test("switching forms prevents a rendered stale row from filling either form", async () => {
  const page = browser(), first = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(first); await page.reply(0, rows);
  const stale = page.choices()[0], second = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  stale.click(); await page.tick();
  assert.equal(first.controls.get("id").input.value, ""); assert.equal(second.controls.get("id").input.value, "");
});

test("changing a dynamic source rejects stale choices and clears old results when reopened", async () => {
  const page = browser(), form = page.form([
    { name: "kind", type: "choice", default: 30, choices: [{ value: 30, label: "道具" }, { value: 40, label: "角色" }] },
    { name: "id", type: "integer", source_by: { field: "kind", values: { 30: "m_items", 40: "m_characters" } } },
  ]);
  page.open(form); await page.reply(0, rows);
  const stale = page.choices()[0]; form.set("kind", 40); stale.click();
  assert.equal(form.controls.get("id").input.value, "");
  page.dialog.close(); page.open(form);
  assert.equal(page.choices().length, 0);
  await page.reply(1, [{ id: 99, name: "角色" }]); page.choices()[0].click();
  assert.equal(form.read().id, 99);
});

test("rows without a valid unique safe integer cannot fill the field", async () => {
  const page = browser(), form = page.form([{ name: "id", type: "integer", source: "m_items" }]);
  page.open(form); await page.reply(0, [{ id: 1, name: "没有唯一键" }], 1, null);
  assert.equal(page.choices()[0].disabled, true); page.choices()[0].closest("tr").click();
  assert.equal(form.controls.get("id").input.value, ""); assert.equal(page.dialog.open, true);
  page.node("picker-search").click(); await page.reply(1, [{ id: "9007199254740993", name: "超出整数范围" }, { id: "x", name: "不是整数" }]);
  assert.ok(page.choices().every((input) => input.disabled));
  page.node("picker-confirm").click(); assert.equal(form.controls.get("id").input.value, "");
});
