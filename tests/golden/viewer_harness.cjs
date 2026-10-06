// Runs a written report's own scripts (three.js and viewer.js) in Node, with a
// small stand-in for the DOM and no WebGL, and prints what the viewer drew.
//
//   node viewer_harness.cjs PAGE.html HASH      # one page load, HASH "" for none
//   node viewer_harness.cjs PAGE.html --walk    # load, then click through
//
// --walk loads with no hash and clicks every fastener in the list, then every
// attempt of the last one, then "back". Prints a JSON list of states, one per
// load or click: the viewer's #drawn record plus what the panel says. One load
// per process: a process is cheap, and nothing carries over from one to the
// next. Three's scene graph is real; only drawing it needs a browser
// (test_view_browser.py's Chrome test).
"use strict";
const fs = require("fs");
const vm = require("vm");

const page = fs.readFileSync(process.argv[2], "utf8");
if (process.argv.length !== 4) throw new Error("usage: viewer_harness.cjs PAGE (HASH | --walk)");
const walk = process.argv[3] === "--walk";
const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const data = page.match(/<script type="application\/json" id="wrenchroom-data">([\s\S]*?)<\/script>/)[1];
if (scripts.length !== 2) throw new Error("expected two scripts, found " + scripts.length);
// Every element the page gives an id, with its hidden attribute as written; the
// scripts' bodies are left out of the search, so nothing in them reads as a tag.
const markup = page.replace(/(<script[^>]*>)[\s\S]*?<\/script>/g, "$1</script>");
const elements = [...markup.matchAll(/<(\w+)\b([^>]*)>/g)]
  .map((m) => [m[1], (m[2].match(/\bid="([\w-]+)"/) || [])[1], /\bhidden\b/.test(m[2])])
  .filter(([, id]) => id);

class Element {
  constructor(tag, id) {
    this.tagName = tag;
    this.id = id;
    this.children = [];
    this.text = "";
    this.hidden = false;
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.clientWidth = 1000;
    this.clientHeight = 700;
  }
  set textContent(value) {
    this.text = String(value);
    this.children = [];
  }
  get textContent() {
    return this.text + this.children.map((child) => child.textContent).join("");
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren() {
    this.children = [];
    this.text = "";
  }
  addEventListener(type, listener) {
    (this.listeners[type] ||= []).push(listener);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  click() {
    for (const listener of this.listeners.click || []) listener({});
  }
  getContext() {
    return null; // no WebGL here: the viewer must cope, and say so
  }
  getBoundingClientRect() {
    return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight };
  }
}

function load(hash) {
  const byId = {};
  for (const [tag, id, hidden] of elements) {
    byId[id] = new Element(tag, id);
    byId[id].hidden = hidden;
  }
  byId["wrenchroom-data"].text = data;
  const document = {
    getElementById(id) {
      if (!(id in byId)) throw new Error("the page has no element #" + id);
      return byId[id];
    },
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag),
    addEventListener() {},
  };
  const context = {
    document,
    console,
    atob: (b64) => Buffer.from(b64, "base64").toString("latin1"),
    location: { hash, pathname: "/report.html", search: "" },
    history: { replaceState() {} },
    devicePixelRatio: 1,
    addEventListener() {},
    navigator: { userAgent: "node" },
    requestAnimationFrame: () => 0,
    cancelAnimationFrame() {},
  };
  context.window = context;
  context.self = context;
  vm.createContext(context);
  for (const script of scripts) vm.runInContext(script, context);
  return byId;
}

function state(byId) {
  return {
    drawn: JSON.parse(byId.drawn.textContent),
    panel: {
      detail_hidden: byId.detail.hidden,
      list_hidden: byId.list.hidden,
      headline: byId.headline.textContent,
      in_way: byId.inway.hidden ? null : byId.inway.textContent,
      attempts: byId.attempts.children.map((item) => item.textContent),
      fasteners: byId.fasteners.children.length,
      status: byId.status.textContent,
    },
  };
}

const byId = load(walk ? "" : process.argv[3]);
const out = [state(byId)];
if (walk) {
  for (const item of byId.fasteners.children) {
    item.children[0].click();
    out.push(state(byId));
  }
  for (const item of byId.attempts.children) {
    item.children[0].click();
    out.push(state(byId));
  }
  byId.back.click();
  out.push(state(byId));
}
process.stdout.write(JSON.stringify(out));
