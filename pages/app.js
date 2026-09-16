"use strict";

/* ---------------------------------------------------------------------
 * Config: figure out which repo/branch this content came from, purely to
 * build the "View on GitHub" link - the only thing that still points back
 * at the source repo. Everything else is served locally (see
 * localContentUrl below). Auto-detects owner/repo when this page is served
 * as a normal GitHub Pages project site (https://<owner>.github.io/<repo>/...),
 * so a fork of this repo links back to itself instead of the upstream repo.
 * The defaults used otherwise (e.g. enterprise/local hosting) come from
 * pages/config.json, so they can be changed per-deployment without touching
 * this file. If that fetch fails, FALLBACK_CONFIG keeps the app usable.
 * ------------------------------------------------------------------- */
const CONFIG_URL = "pages/config.json";
const FALLBACK_CONFIG = {
  defaultOwner: "bigfix-content",
  defaultRepo: "github-pages-browser",
  defaultBranch: "refs/heads/main", // default 'main' for public github.com
  githubSite: "github01.hclpnp.com",
};

async function loadConfig() {
  try {
    const res = await fetch(CONFIG_URL);
    if (!res.ok) throw new Error(`Could not load config.json (${res.status})`);
    return await res.json();
  } catch (err) {
    console.warn(`${CONFIG_URL} unavailable, using built-in defaults:`, err);
    return FALLBACK_CONFIG;
  }
}

function detectRepoConfig(config) {
  const host = location.hostname; // e.g. bigfix.github.io
  const parts = location.pathname.split("/").filter(Boolean); // e.g. ["content", "pages", ...]
  const ghPagesMatch = host.match(/^([^.]+)\.github\.io$/);
  if (ghPagesMatch && parts.length > 0) {
    return { owner: ghPagesMatch[1], repo: parts[0], branch: config.defaultBranch };
  }
  return { owner: config.defaultOwner, repo: config.defaultRepo, branch: config.defaultBranch };
}

let GITHUB_SITE;
let REPO;
let BLOB_BASE;

const repoLinkEl = document.getElementById("repo-link");

async function initConfig() {
  const config = await loadConfig();
  GITHUB_SITE = config.githubSite;
  REPO = detectRepoConfig(config);
  BLOB_BASE = `https://${GITHUB_SITE}/${REPO.owner}/${REPO.repo}/blob/${REPO.branch}/`;
  repoLinkEl.href = `https://${GITHUB_SITE}/${REPO.owner}/${REPO.repo}`;
  repoLinkEl.textContent = `${GITHUB_SITE}/${REPO.owner}/${REPO.repo}`;
}

// pages/index.json is generated (scripts/generate_index.py) but never moved or duplicated -
// this page now lives at the repo root (alongside content/), and index.json is fetched
// from where it actually sits, in pages/. Also sidesteps the GitHub REST API's
// unauthenticated rate limit the way the old git/trees call would have hit.
const INDEX_URL = "pages/index.json";

/* ---------------------------------------------------------------------
 * Local content fetch
 * Every entry's `path` in index.json (e.g. "content/Analyses/Foo.bes") is
 * both its location in the source repo (for the "View on GitHub" link
 * above) and a path relative to this page - which, since GitHub Pages
 * publishes the whole repo root, resolves directly to the real content/
 * file. No copy of the .bes files is kept anywhere; the viewer just never
 * calls back to GitHub to show or download one.
 * ------------------------------------------------------------------- */
function localContentUrl(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

const treeRootEl = document.getElementById("tree-root");
const statusTextEl = document.getElementById("status-text");
const refreshBtn = document.getElementById("refresh-btn");
const collapseAllBtn = document.getElementById("collapse-all-btn");
const searchBoxEl = document.getElementById("search-box");
const mainEl = document.getElementById("main");
const layoutEl = document.getElementById("layout");
const sidebarHideBtn = document.getElementById("sidebar-hide-btn");
const sidebarShowBtn = document.getElementById("sidebar-show-btn");

let allFiles = []; // [{path, name, dir}]
let activePath = null;

collapseAllBtn.addEventListener("click", () => {
  treeRootEl.querySelectorAll(".tree-group").forEach((group) => group.classList.add("collapsed"));
});

sidebarHideBtn.addEventListener("click", () => layoutEl.classList.add("sidebar-hidden"));
sidebarShowBtn.addEventListener("click", () => layoutEl.classList.remove("sidebar-hidden"));

/* ---------------------------------------------------------------------
 * Theme (light/dark)
 * The initial theme (saved choice, else OS preference) is already applied
 * before this script runs - see the inline snippet in index.html's <head>,
 * which sets data-theme early enough to avoid a flash of the wrong theme.
 * This just wires up the toggle button to flip and persist it.
 * ------------------------------------------------------------------- */
const THEME_STORAGE_KEY = "bigfix-theme";
const themeToggleBtn = document.getElementById("theme-toggle-btn");

function currentTheme() {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

themeToggleBtn.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch (e) {
    // Private-browsing/blocked storage: theme still applies for this load, just isn't remembered.
  }
});

/* ---------------------------------------------------------------------
 * File list loading
 * ------------------------------------------------------------------- */

async function loadFileList(forceRefresh) {
  statusTextEl.textContent = "Loading file list…";
  try {
    // no-store on manual refresh so a stale CDN/browser cache doesn't hide a just-published index.
    const res = await fetch(INDEX_URL, forceRefresh ? { cache: "no-store" } : {});
    if (!res.ok) throw new Error(`Could not load index.json (${res.status})`);
    const data = await res.json();
    allFiles = (data.files || []).slice().sort((a, b) => a.path.localeCompare(b.path));
    renderTree(allFiles);
    statusTextEl.textContent = `${allFiles.length} files`;
  } catch (err) {
    statusTextEl.textContent = "Failed to load file list";
    treeRootEl.innerHTML = "";
    const box = document.createElement("div");
    box.className = "error-box";
    box.style.margin = "8px 0";
    box.textContent = err.message || String(err);
    const retry = document.createElement("button");
    retry.textContent = "Retry";
    retry.onclick = () => loadFileList(true);
    box.appendChild(document.createElement("br"));
    box.appendChild(retry);
    treeRootEl.appendChild(box);
  }
}

/* ---------------------------------------------------------------------
 * Sidebar tree rendering + filtering
 * ------------------------------------------------------------------- */

// Builds a nested directory tree from each file's `dir` (e.g. "content/Analysis/BES"),
// dropping the leading "content" segment - every entry lives under it, so showing it
// on every group would just be noise. A file directly in "content/" itself (dir
// "(root)") lands on the tree root with no group wrapper.
function buildTree(files) {
  const root = { name: "", path: "", children: new Map(), files: [] };
  for (const f of files) {
    let segments = f.dir === "(root)" ? [] : f.dir.split("/").filter(Boolean);
    if (segments[0] && segments[0].toLowerCase() === "content") segments = segments.slice(1);

    let node = root;
    let pathAcc = "";
    for (const seg of segments) {
      pathAcc = pathAcc ? `${pathAcc}/${seg}` : seg;
      if (!node.children.has(seg)) {
        node.children.set(seg, { name: seg, path: pathAcc, children: new Map(), files: [] });
      }
      node = node.children.get(seg);
    }
    node.files.push(f);
  }
  return root;
}

function countFilesRecursive(node) {
  let count = node.files.length;
  for (const child of node.children.values()) count += countFilesRecursive(child);
  return count;
}

function renderTree(files) {
  const query = searchBoxEl.value.trim().toLowerCase();
  const filtered = query ? files.filter((f) => f.path.toLowerCase().includes(query)) : files;

  treeRootEl.innerHTML = "";
  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "No files match.";
    treeRootEl.appendChild(empty);
    return;
  }

  // Collapsed is the default resting state at every level; while actively filtering,
  // every level starts expanded instead so the matches a search turns up aren't
  // hidden behind a chevron several directory levels deep.
  const startExpanded = !!query;
  renderTreeLevel(buildTree(filtered), treeRootEl, startExpanded);
}

// Renders one directory's immediate contents (its subdirectory groups, then its own
// files) into `container`. Each subdirectory is its own independently collapsible
// group (see renderDirGroup) - only its own children are built one level at a time
// conceptually, though the whole subtree is pre-built and collapse is CSS-only, so
// expanding a deep group never needs a re-render.
function renderTreeLevel(node, container, startExpanded) {
  const dirNames = [...node.children.keys()].sort((a, b) => a.localeCompare(b));
  for (const name of dirNames) {
    container.appendChild(renderDirGroup(node.children.get(name), startExpanded));
  }
  for (const f of node.files.slice().sort((a, b) => a.name.localeCompare(b.name))) {
    container.appendChild(renderFileRow(f));
  }
}

function renderDirGroup(node, startExpanded) {
  const group = document.createElement("div");
  group.className = startExpanded ? "tree-group" : "tree-group collapsed";

  const label = document.createElement("div");
  label.className = "tree-group-label";
  label.innerHTML = `<span class="chevron">▼</span><span></span>`;
  label.querySelector("span:last-child").textContent = `${node.name} (${countFilesRecursive(node)})`;
  // Toggles this group only - a plain CSS class flip, since the children (including
  // nested subdirectory groups, each with their own independent collapsed state) are
  // already built. Any number of groups, at any depth, can be expanded at once.
  label.onclick = () => group.classList.toggle("collapsed");
  group.appendChild(label);

  const childrenEl = document.createElement("div");
  childrenEl.className = "tree-files";
  renderTreeLevel(node, childrenEl, startExpanded);
  group.appendChild(childrenEl);

  return group;
}

function renderFileRow(f) {
  const item = document.createElement("div");
  item.className = "tree-file";
  item.dataset.path = f.path;
  if (f.path === activePath) item.classList.add("active");
  const dot = document.createElement("span");
  dot.className = `type-dot ${typeDotClass(f.type)}`;
  const label = document.createElement("span");
  label.textContent = f.name.replace(/\.bes$/i, "");
  item.title = f.title && f.title !== f.name ? `${f.title} (${f.type || "Other"})` : f.type || "";
  item.appendChild(dot);
  item.appendChild(label);
  item.onclick = () => selectFile(f.path);
  return item;
}

function typeDotClass(type) {
  switch (type) {
    case "Fixlet": return "fixlet";
    case "Task": return "task";
    case "Analysis": return "analysis";
    case "Baseline": return "baseline";
    case "Signature": return "signature";
    default: return "other";
  }
}

searchBoxEl.addEventListener("input", () => renderTree(allFiles));
refreshBtn.addEventListener("click", () => loadFileList(true));

/* ---------------------------------------------------------------------
 * File selection + fetch + parse
 * ------------------------------------------------------------------- */

function selectFile(path) {
  activePath = path;
  const url = new URL(location.href);
  url.searchParams.set("file", path);
  history.pushState({ path }, "", url);
  document.querySelectorAll(".tree-file").forEach((el) => {
    el.classList.toggle("active", el.dataset.path === path);
  });
  loadAndRenderFile(path);
}

window.addEventListener("popstate", () => {
  const path = new URL(location.href).searchParams.get("file");
  if (path) {
    activePath = path;
    loadAndRenderFile(path);
  }
});

async function loadAndRenderFile(path) {
  mainEl.innerHTML = `<div class="spinner-line">Loading ${escapeText(path)}…</div>`;
  try {
    const res = await fetch(localContentUrl(path));
    if (!res.ok) throw new Error(`Could not fetch file (${res.status})`);
    const xmlText = await res.text();
    const doc = new DOMParser().parseFromString(xmlText, "application/xml");
    const parserError = doc.querySelector("parsererror");
    if (parserError) throw new Error("This file could not be parsed as XML.");
    renderDocument(doc, path);
  } catch (err) {
    mainEl.innerHTML = "";
    const box = document.createElement("div");
    box.className = "error-box";
    box.textContent = err.message || String(err);
    const retry = document.createElement("button");
    retry.textContent = "Retry";
    retry.onclick = () => loadAndRenderFile(path);
    box.appendChild(document.createElement("br"));
    box.appendChild(retry);
    mainEl.appendChild(box);
  }
}

/* ---------------------------------------------------------------------
 * Rendering a parsed .bes document
 * ------------------------------------------------------------------- */

function renderDocument(doc, path) {
  const bes = doc.documentElement;
  mainEl.innerHTML = "";

  if (bes.tagName === "SoftwareIdentityCatalog") {
    renderSignatureDocument(doc, path);
    return;
  }

  const root = bes.querySelector(":scope > Task, :scope > Fixlet, :scope > Analysis, :scope > Baseline, :scope > TaskCondition, :scope > ComputerGroup");

  if (!root) {
    renderUnknown(doc, path);
    return;
  }

  const docType = root.tagName;
  const title = textOf(root, "Title") || path.split("/").pop();
  const description = textOf(root, "Description");
  const relevances = [...root.querySelectorAll(":scope > Relevance")].map((el) => el.textContent.trim());
  const source = textOf(root, "Source");
  const sourceDate = textOf(root, "SourceReleaseDate");
  const severity = textOf(root, "SourceSeverity");
  const domain = textOf(root, "Domain");
  const downloadSize = textOf(root, "DownloadSize");

  // Header -----------------------------------------------------------
  const titleRow = document.createElement("div");
  titleRow.className = "title-row";
  const h1 = document.createElement("h1");
  h1.className = "doc-title";
  h1.textContent = title;
  titleRow.appendChild(h1);

  const badges = document.createElement("div");
  badges.className = "badges";
  badges.appendChild(makeBadge(docType, "doctype"));
  if (severity) badges.appendChild(makeBadge(severity, `severity-${severity.toLowerCase()}`));
  if (domain) badges.appendChild(makeBadge(domain, "domain"));
  titleRow.appendChild(badges);
  mainEl.appendChild(titleRow);

  const metaLine = document.createElement("div");
  metaLine.className = "meta-line";
  if (source) metaLine.appendChild(metaSpan("Source", source));
  if (sourceDate) metaLine.appendChild(metaSpan("Released", sourceDate));
  if (downloadSize) metaLine.appendChild(metaSpan("Download size", formatBytes(downloadSize)));
  metaLine.appendChild(metaLineFooter(path));
  mainEl.appendChild(metaLine);

  // Attribution (frontmatter comment) -----------------------------------
  const attribution = extractAttribution(doc);
  if (attribution) renderAttributionSection(mainEl, attribution);

  // Description --------------------------------------------------------
  if (description) {
    mainEl.appendChild(sectionLabel("Description"));
    const card = document.createElement("div");
    card.className = "card description-box";
    renderSanitizedHtml(card, description);
    mainEl.appendChild(card);
  }

  // Relevance -----------------------------------------------------------
  if (relevances.length) {
    mainEl.appendChild(sectionLabel("Relevance", relevances.length));
    mainEl.appendChild(renderRelevanceList(relevances));
  }

  // Type-specific body ---------------------------------------------------
  if (docType === "Task" || docType === "Fixlet") {
    renderActions(root);
  } else if (docType === "Analysis") {
    renderProperties(root);
  } else if (docType === "Baseline") {
    renderBaselineComponents(root);
  }

  // Raw XML fallback ------------------------------------------------------
  mainEl.appendChild(renderRawXmlDetails(doc));
}

function renderActions(root) {
  const actions = [...root.querySelectorAll(":scope > DefaultAction, :scope > Action")];
  if (!actions.length) return;

  mainEl.appendChild(sectionLabel("Action Script", actions.length > 1 ? actions.length : null));

  const tabsWrap = document.createElement("div");
  const tabs = document.createElement("div");
  tabs.className = "tabs";
  const panels = [];

  actions.forEach((action, i) => {
    const id = action.getAttribute("ID") || `Action${i + 1}`;
    const scriptEl = action.querySelector(":scope > ActionScript");
    const mime = scriptEl ? scriptEl.getAttribute("MIMEType") || "" : "";
    const script = scriptEl ? scriptEl.textContent.trim() : "(no ActionScript)";
    const label = actionLabel(action) || id;

    const tabBtn = document.createElement("button");
    tabBtn.className = "tab-btn" + (i === 0 ? " active" : "");
    tabBtn.textContent = label;
    tabBtn.onclick = () => {
      tabs.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      tabBtn.classList.add("active");
      panels.forEach((p, pi) => p.style.display = pi === i ? "" : "none");
    };
    tabs.appendChild(tabBtn);

    const panel = document.createElement("div");
    panel.className = "actionscript-box";
    panel.style.display = i === 0 ? "" : "none";
    panel.innerHTML = `
      <div class="actionscript-titlebar">
        <div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div>
        <span class="fname"></span>
      </div>`;
    panel.querySelector(".fname").textContent = `${id}${mime ? " · " + mime : ""}`;
    const textarea = document.createElement("textarea");
    textarea.className = "actionscript";
    textarea.readOnly = true;
    textarea.value = script;
    panel.appendChild(textarea);
    panels.push(panel);
  });

  tabsWrap.appendChild(tabs);
  panels.forEach((p) => tabsWrap.appendChild(p));
  mainEl.appendChild(tabsWrap);
}

function actionLabel(action) {
  const desc = action.querySelector(":scope > Description");
  if (!desc) return null;
  const pre = desc.querySelector("PreLink")?.textContent || "";
  const link = desc.querySelector("Link")?.textContent || "";
  const post = desc.querySelector("PostLink")?.textContent || "";
  const combined = (pre + link + post).trim();
  return combined.length > 40 ? combined.slice(0, 37) + "…" : combined || null;
}

function renderProperties(root) {
  const props = [...root.querySelectorAll(":scope > Property")];
  if (!props.length) return;
  mainEl.appendChild(sectionLabel("Properties", props.length));
  const list = document.createElement("div");
  list.className = "property-list";
  props.forEach((prop, i) => {
    const name = prop.getAttribute("Name") || `Property ${i + 1}`;
    list.appendChild(relevanceItem(i + 1, prop.textContent.trim(), name));
  });
  mainEl.appendChild(list);
}

function renderBaselineComponents(root) {
  const components = [...root.querySelectorAll(":scope > BaselineComponent")];
  if (!components.length) return;
  mainEl.appendChild(sectionLabel("Components", components.length));
  const list = document.createElement("div");
  list.className = "property-list";
  components.forEach((c, i) => {
    const name = textOf(c, "Name") || `Component ${i + 1}`;
    const relevance = textOf(c, "Relevance") || "(no relevance)";
    list.appendChild(relevanceItem(i + 1, relevance, name));
  });
  mainEl.appendChild(list);
}

function renderUnknown(doc, path) {
  const attribution = extractAttribution(doc);
  if (attribution) renderAttributionSection(mainEl, attribution);

  const box = document.createElement("div");
  box.className = "error-box";
  box.textContent = "This file's structure wasn't recognized (expected a Task, Fixlet, Analysis, Baseline, or Signature). Showing raw XML instead.";
  mainEl.appendChild(box);
  mainEl.appendChild(renderRawXmlDetails(doc, true));
}

/* ---------------------------------------------------------------------
 * Rendering a parsed BigFix Inventory Signature (SoftwareIdentityCatalog) doc
 * See dev/scripts/signature-schema.md. Unlike Task/Fixlet/Analysis/Baseline,
 * a Signature file's only structured metadata lives in its frontmatter
 * comment (Description/Author/Publisher/ProductName/Release/Keywords) -
 * the XML body itself is one or more <Software> detection trees.
 * ------------------------------------------------------------------- */

function renderSignatureDocument(doc, path) {
  const root = doc.documentElement;
  const attribution = extractAttribution(doc);
  const fields = parseFrontmatterFields(attribution);

  const firstSoftware = root.querySelector(":scope > Software");
  const title = fields.ProductName || (firstSoftware && firstSoftware.getAttribute("name")) || path.split("/").pop();

  // Header -----------------------------------------------------------
  const titleRow = document.createElement("div");
  titleRow.className = "title-row";
  const h1 = document.createElement("h1");
  h1.className = "doc-title";
  h1.textContent = title;
  titleRow.appendChild(h1);

  const badges = document.createElement("div");
  badges.className = "badges";
  badges.appendChild(makeBadge("Signature", "doctype"));
  titleRow.appendChild(badges);
  mainEl.appendChild(titleRow);

  const metaLine = document.createElement("div");
  metaLine.className = "meta-line";
  if (fields.Publisher) metaLine.appendChild(metaSpan("Publisher", fields.Publisher));
  if (fields.Release) metaLine.appendChild(metaSpan("Release", fields.Release));
  if (fields.Author) metaLine.appendChild(metaSpan("Author", fields.Author));
  if (fields.uploadedOn) metaLine.appendChild(metaSpan("Uploaded", fields.uploadedOn));
  if (fields.Keywords) metaLine.appendChild(metaSpan("Keywords", fields.Keywords));
  metaLine.appendChild(metaLineFooter(path));
  mainEl.appendChild(metaLine);

  // Attribution (frontmatter comment) -----------------------------------
  if (attribution) renderAttributionSection(mainEl, attribution);

  // Description --------------------------------------------------------
  if (fields.Description) {
    mainEl.appendChild(sectionLabel("Description"));
    const card = document.createElement("div");
    card.className = "card description-box";
    const text = document.createElement("div");
    text.className = "plain-text";
    text.textContent = fields.Description;
    card.appendChild(text);
    mainEl.appendChild(card);
  }

  // Detection logic -------------------------------------------------------
  renderSoftwareList(root);

  // Raw XML fallback ------------------------------------------------------
  mainEl.appendChild(renderRawXmlDetails(doc));
}

function renderSoftwareList(root) {
  const softwareList = [...root.querySelectorAll(":scope > Software")];
  if (!softwareList.length) return;

  mainEl.appendChild(sectionLabel("Detection Logic", softwareList.length > 1 ? softwareList.length : null));

  for (const sw of softwareList) {
    const card = document.createElement("div");
    card.className = "software-card";

    const header = document.createElement("div");
    header.className = "software-card-header";
    const name = document.createElement("span");
    name.className = "sw-name";
    name.textContent = sw.getAttribute("name") || "(unnamed)";
    header.appendChild(name);
    const vendor = sw.getAttribute("vendor");
    const version = sw.getAttribute("version");
    if (vendor) header.appendChild(metaSpan("Vendor", vendor));
    if (version) header.appendChild(metaSpan("Version", version));
    card.appendChild(header);

    const signatures = [...sw.querySelectorAll(":scope > Signature")];
    signatures.forEach((sig, i) => {
      const block = document.createElement("div");
      block.className = "signature-block";
      if (signatures.length > 1) {
        const meta = document.createElement("div");
        meta.className = "signature-block-meta";
        const modified = sig.getAttribute("modified");
        meta.textContent = `Signature ${i + 1}${modified ? " · modified " + modified : ""}`;
        block.appendChild(meta);
      }
      for (const child of [...sig.children]) {
        block.appendChild(renderSignatureFilterNode(child));
      }
      card.appendChild(block);
    });

    mainEl.appendChild(card);
  }
}

// Recursively renders a Signature detection node: AND/OR groups nest their
// children; ExtendedSignature holds a CDATA blob in BigFix's own mini
// relevance-like detection language (shown as collapsed XML, like embedded
// <script>/<style> elsewhere); anything else (PackageFilter, File, ...) is a
// leaf filter shown as its tag name plus non-empty attributes.
function renderSignatureFilterNode(el) {
  const tag = el.tagName;

  if (tag === "AND" || tag === "OR") {
    const wrap = document.createElement("div");
    wrap.className = `sig-group sig-group-${tag.toLowerCase()}`;
    const label = document.createElement("div");
    label.className = "sig-group-label";
    label.textContent = tag;
    wrap.appendChild(label);
    const children = document.createElement("div");
    children.className = "sig-group-children";
    for (const child of [...el.children]) {
      children.appendChild(renderSignatureFilterNode(child));
    }
    wrap.appendChild(children);
    return wrap;
  }

  if (tag === "ExtendedSignature") {
    const code = el.textContent.trim();
    const block = makeEmbeddedCodeBlock("ExtendedSignature", code, "xml");
    block.style.display = "block";
    return block;
  }

  const item = document.createElement("div");
  item.className = "sig-filter";
  const tagEl = document.createElement("span");
  tagEl.className = "sig-filter-tag";
  tagEl.textContent = tag;
  item.appendChild(tagEl);
  for (const attr of [...el.attributes]) {
    if (!attr.value) continue;
    const attrEl = document.createElement("span");
    attrEl.className = "sig-filter-attr";
    const b = document.createElement("b");
    b.textContent = attr.name + "=";
    attrEl.appendChild(b);
    attrEl.appendChild(document.createTextNode(JSON.stringify(attr.value)));
    item.appendChild(attrEl);
  }
  return item;
}

function renderRawXmlDetails(doc, open) {
  const details = document.createElement("details");
  details.className = "raw-xml";
  if (open) details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = "View raw XML";
  const pre = document.createElement("pre");
  pre.textContent = new XMLSerializer().serializeToString(doc);
  details.appendChild(summary);
  details.appendChild(pre);
  return details;
}

/* ---------------------------------------------------------------------
 * Small render helpers
 * ------------------------------------------------------------------- */

function renderRelevanceList(items) {
  const list = document.createElement("div");
  list.className = "relevance-list";
  items.forEach((text, i) => list.appendChild(relevanceItem(i + 1, text)));
  return list;
}

function relevanceItem(index, text, name) {
  const item = document.createElement("div");
  item.className = "relevance-item";
  const idx = document.createElement("div");
  idx.className = "idx";
  idx.textContent = String(index);
  const body = document.createElement("div");
  body.className = "item-body";
  if (name) {
    const nameEl = document.createElement("div");
    nameEl.className = "item-name";
    nameEl.textContent = name;
    body.appendChild(nameEl);
  }
  body.appendChild(highlightedRelevance(text));
  item.appendChild(idx);
  item.appendChild(body);
  return item;
}

// Every caller of relevanceItem() passes actual BigFix Relevance-language text
// (the main Relevance list, Analysis properties, Baseline component relevance),
// so highlighting lives here rather than duplicated at each call site.
function highlightedRelevance(text) {
  const pre = document.createElement("pre");
  pre.className = "relevance-code";
  const code = document.createElement("code");
  if (window.hljs && hljs.getLanguage("bigfix-relevance")) {
    code.innerHTML = hljs.highlight(text, { language: "bigfix-relevance" }).value;
  } else {
    code.textContent = text;
  }
  pre.appendChild(code);
  return pre;
}

function sectionLabel(text, count) {
  const label = document.createElement("div");
  label.className = "section-label";
  label.appendChild(document.createTextNode(text));
  if (count) {
    const span = document.createElement("span");
    span.className = "count";
    span.textContent = String(count);
    label.appendChild(span);
  }
  return label;
}

function makeBadge(text, cls) {
  const span = document.createElement("span");
  span.className = `badge ${cls}`;
  span.textContent = text;
  return span;
}

function metaSpan(label, value) {
  const span = document.createElement("span");
  const b = document.createElement("b");
  b.textContent = label + ": ";
  span.appendChild(b);
  span.appendChild(document.createTextNode(value));
  return span;
}

// "View on GitHub" + "Download" - identical for every doc type, so both
// renderDocument (Task/Fixlet/Analysis/Baseline) and renderSignatureDocument
// share this instead of duplicating the link-building logic.
function metaLineFooter(path) {
  const frag = document.createDocumentFragment();
  const ghLink = document.createElement("span");
  ghLink.innerHTML = `<a href="${BLOB_BASE + path.split("/").map(encodeURIComponent).join("/")}" target="_blank" rel="noopener">View on GitHub</a>`;
  frag.appendChild(ghLink);

  const indexEntry = allFiles.find((f) => f.path === path);
  if (indexEntry) {
    const dlSpan = document.createElement("span");
    const dlLink = document.createElement("a");
    // Same origin as this page (content/ is served as-is from the repo root), so the
    // browser honors `download` natively - no fetch-to-blob workaround needed.
    dlLink.href = localContentUrl(path);
    dlLink.textContent = "Download";
    dlLink.setAttribute("download", indexEntry.name);
    dlSpan.appendChild(dlLink);
    frag.appendChild(dlSpan);
  }
  return frag;
}

/* ---------------------------------------------------------------------
 * XML frontmatter comment ("attribution") shared by every content type.
 * Every .bes export and content/Signature/*.xml file embeds a leading XML
 * comment with fields like Description/Author/ID/Publisher/... before the
 * real root element (see dev/scripts/signature-schema.md). We surface its
 * raw text (comment delimiters stripped) as the first field of every doc,
 * and also parse it into key/value pairs for Signature's own header.
 * ------------------------------------------------------------------- */

const FRONTMATTER_HINT_RE = /(^|\n)\s*(Description|Author)\s*:/i;

function extractAttribution(doc) {
  for (const node of doc.childNodes) {
    if (node.nodeType !== Node.COMMENT_NODE) continue;
    const text = (node.textContent || "").trim();
    if (text && FRONTMATTER_HINT_RE.test(text)) return text;
  }
  return "";
}

function parseFrontmatterFields(text) {
  const fields = {};
  if (!text) return fields;
  for (const line of text.split(/\r?\n/)) {
    const match = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if (value.length >= 2 && value[0] === '"' && value[value.length - 1] === '"') {
      value = value.slice(1, -1);
    }
    if (!(match[1] in fields)) fields[match[1]] = value;
  }
  return fields;
}

function renderAttributionSection(parent, text) {
  parent.appendChild(sectionLabel("Attribution"));
  const box = document.createElement("div");
  box.className = "attribution-box";
  const textarea = document.createElement("textarea");
  textarea.className = "attribution";
  textarea.readOnly = true;
  textarea.value = text;
  textarea.rows = Math.min(Math.max(text.split("\n").length, 3), 12);
  box.appendChild(textarea);
  parent.appendChild(box);
}

function textOf(root, tag) {
  const el = root.querySelector(`:scope > ${tag}`);
  return el ? el.textContent.trim() : "";
}

function formatBytes(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeText(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

/* ---------------------------------------------------------------------
 * Minimal allowlist HTML sanitizer for <Description> content.
 * Descriptions come from files in the repo (or any fork/PR of it), so
 * they are treated as untrusted input and never injected as raw innerHTML.
 * <SCRIPT>/<STYLE> are never executed/applied - their source is pulled out
 * and shown, on demand, in a collapsed, syntax-highlighted code block
 * instead (see makeEmbeddedCodeBlock). <INPUT> types with no safe, inert
 * rendering (file, image, submit/button/reset, hidden, ...) are replaced
 * with a highlighted snippet of the original tag instead of being dropped
 * silently (see describeUnsupportedElement).
 * ------------------------------------------------------------------- */

const ALLOWED_TAGS = new Set([
  "P", "A", "STRONG", "B", "EM", "I", "U", "BR", "UL", "OL", "LI", "SPAN",
  "H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "CODE", "PRE",
  "TABLE", "THEAD", "TBODY", "TR", "TD", "TH", "IMG", "INPUT", "TEXTAREA",
]);

// input types that are purely local/presentational - no navigation, no file
// access, no implicit form action - so are safe to render as real controls.
const SAFE_INPUT_TYPES = new Set([
  "text", "password", "checkbox", "radio", "number", "date", "datetime-local",
  "time", "email", "tel", "url", "range", "color", "search", "month", "week",
]);

// Attributes kept as-is for each allowed tag; everything else is stripped
// below (this is what keeps event-handler attributes like onclick/onfocus -
// a classic no-<script>-needed XSS vector - from ever surviving sanitizing).
const TAG_ATTR_ALLOWLIST = {
  A: new Set(["href"]),
  IMG: new Set(["src", "alt", "width", "height"]),
  INPUT: new Set(["type", "value", "placeholder", "checked", "disabled", "readonly", "maxlength", "min", "max", "step", "size"]),
  TEXTAREA: new Set(["rows", "cols", "placeholder", "disabled", "readonly", "maxlength"]),
};

// Renders an unsupported element (e.g. <input type="file">) as an inert,
// syntax-highlighted snippet of its original markup instead of the live
// element, so the file's content is still visible without being rendered.
function describeUnsupportedElement(node) {
  const span = document.createElement("span");
  span.className = "unsupported-element-note";
  const code = document.createElement("code");
  const snippet = node.outerHTML;
  if (window.hljs && hljs.getLanguage("xml")) {
    code.innerHTML = hljs.highlight(snippet, { language: "xml" }).value;
  } else {
    code.textContent = snippet;
  }
  span.appendChild(code);
  return span;
}

// Builds a collapsed "SCRIPT"/"STYLE" toggle button that expands into a
// read-only, syntax-highlighted code panel - used in place of rendering
// embedded <script>/<style> content directly.
function makeEmbeddedCodeBlock(tagName, code, lang) {
  const wrap = document.createElement("div");
  wrap.className = "embedded-code-block";

  const toggleBtn = document.createElement("button");
  toggleBtn.type = "button";
  toggleBtn.className = "embedded-code-toggle";
  toggleBtn.textContent = tagName;

  const panel = document.createElement("div");
  panel.className = "embedded-code-panel";
  panel.hidden = true;

  const pre = document.createElement("pre");
  pre.className = "embedded-code";
  const codeEl = document.createElement("code");
  if (window.hljs && hljs.getLanguage(lang)) {
    codeEl.innerHTML = hljs.highlight(code, { language: lang }).value;
  } else {
    codeEl.textContent = code;
  }
  pre.appendChild(codeEl);
  panel.appendChild(pre);

  toggleBtn.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    toggleBtn.classList.toggle("expanded", !panel.hidden);
  });

  wrap.appendChild(toggleBtn);
  wrap.appendChild(panel);
  return wrap;
}

// Sanitizes `html` and appends the result into `container` as real DOM nodes
// (rather than returning a string) so the SCRIPT/STYLE toggle buttons keep
// their event listeners - re-parsing a serialized string would lose them.
function renderSanitizedHtml(container, html) {
  const template = document.createElement("template");
  template.innerHTML = html;
  sanitizeNode(template.content);
  container.appendChild(template.content);
}

function sanitizeNode(parent) {
  const walker = [...parent.childNodes];
  for (const node of walker) {
    if (node.nodeType === Node.COMMENT_NODE) {
      node.remove();
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;

    if (node.tagName === "SCRIPT" || node.tagName === "STYLE") {
      const lang = node.tagName === "SCRIPT" ? "javascript" : "css";
      node.parentNode.replaceChild(makeEmbeddedCodeBlock(node.tagName, node.textContent.trim(), lang), node);
      continue;
    }

    if (node.tagName === "INPUT" && !SAFE_INPUT_TYPES.has((node.getAttribute("type") || "text").toLowerCase())) {
      node.parentNode.replaceChild(describeUnsupportedElement(node), node);
      continue;
    }

    if (!ALLOWED_TAGS.has(node.tagName)) {
      // Unwrap: keep children (usually just text) but drop the disallowed tag itself.
      const parentNode = node.parentNode;
      while (node.firstChild) parentNode.insertBefore(node.firstChild, node);
      parentNode.removeChild(node);
      continue;
    }

    const allowedAttrs = TAG_ATTR_ALLOWLIST[node.tagName];
    for (const attr of [...node.attributes]) {
      const name = attr.name.toLowerCase();
      if (node.tagName === "A" && name === "href") {
        if (!/^(https?:|mailto:)/i.test(attr.value)) node.removeAttribute(attr.name);
      } else if (node.tagName === "IMG" && name === "src") {
        if (!/^https?:/i.test(attr.value)) node.removeAttribute(attr.name);
      } else if (!allowedAttrs || !allowedAttrs.has(name)) {
        node.removeAttribute(attr.name);
      }
    }
    if (node.tagName === "A" && node.hasAttribute("href")) {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
    if (node.tagName === "INPUT") {
      // Force off regardless of the original markup - untrusted rendered
      // fields shouldn't get silently populated from the browser's saved
      // autofill data (address, email, etc.).
      node.setAttribute("autocomplete", "off");
    }

    sanitizeNode(node);
  }
}

/* ---------------------------------------------------------------------
 * Boot
 * ------------------------------------------------------------------- */

(async function init() {
  await initConfig();
  await loadFileList(false);
  const initialPath = new URL(location.href).searchParams.get("file");
  if (initialPath) {
    activePath = initialPath;
    renderTree(allFiles);
    loadAndRenderFile(initialPath);
  }
})();
