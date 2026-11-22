"use strict";
const $ = (s) => document.querySelector(s),
  $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (n) => Number(n || 0).toLocaleString("zh-CN"),
  states = ["待筛选", "保留", "排除"];
const titles = {
  skillbank: "Skills 技能包",
  wiki: "建站知识库",
  prompts: "项目提示词",
  buildhub: "软件与建站资料",
  buildsearch: "查找建站记录",
  materials: "建站资料库",
  home: "系统首页",
  library: "行业关键词库",
  workflows: "建站流程",
  skills: "Skills 技能管理",
  sitemap: "网站地图",
  siteplan: "官网一级栏目规划",
  types: "产品分类",
  words: "关键词库",
  gallery: "产品图库",
  "gallery-all": "跨行业图库",
  sites: "同行网站",
  imports: "导入记录",
  rules: "排除规则",
};
const desc = {
  skillbank: "收藏建站技能，按名称或用途查找，下次直接交给 Codex。",
  wiki: "查找整理好的项目交接和建站做法，点引用查看原文。",
  prompts: "按网站和建站步骤查找用过的提示词和 Codex 回复。",
  buildhub:
    "查看网站进度，找回提示词，接着上次的工作做。",
  buildsearch: "跨网站查找用过的提示词、Codex 回复和问题，点开即可复制原文。",
  materials: "查找和保存建站资料、提示词、对话、问题与附件。",
  home: "",
  library: "",
  workflows: "一个网站对应一个项目。选好项目后，接着已展开的步骤做。",
  skills: "按项目保存建站技能的用途和使用方法。",
  sitemap: "",
  siteplan: "为每个项目维护导航顺序、一级页面、路径和目标关键词。",
  types:
    "查看各产品类型的词数。可以编辑识别词，也可以手动调整单个关键词的类型。",
  gallery: "上传产品图，按完整关键词配图，或下载建站用的图片和清单。",
  "gallery-all": "按文件名、型号或配图关键词查找各行业的图片。",
  words: "按词查找，查看各家同行的排名、流量和来源。",
  sites: "查看每家同行的网站资料和已导入的关键词。",
  imports: "搜索以前导入的文件，查看入库结果、下载原表或继续处理。",
  rules: "先预览匹配结果，再决定是否排除。已手动标记的词优先。",
};
const industryId =
  Number(new URLSearchParams(location.search).get("industry")) || 1;
let industryName = "包装袋";
const activeAreaId =
  Number(new URLSearchParams(location.search).get("section")) ||
  (location.hash.startsWith("#words") || location.hash.startsWith("#library") || location.hash.startsWith("#gallery")
    ? 1
    : 2);
let areas = [],
  area = null;
let knownIndustries = [];
const channelNames = ["未标注", "B2B", "B2C", "B2B + B2C"];
const siteKeywordLabels = { ready: "已有关键词", missing: "待补关键词" };
let fileKind = "words";
function channelField(name, label, value = 0) {
  return (
    '<label class="field">' +
    label +
    '<select name="' +
    name +
    '">' +
    channelNames.map((t, n) => option(n, t, value)).join("") +
    "</select></label>"
  );
}
function changeIndustry(id, destination = view) {
  openAppLocation(
    "/?industry=" +
      encodeURIComponent(id) +
      "&section=" +
      activeAreaId +
      "#" +
      encodeURIComponent(destination),
  );
}
let view = "words",
  filt = {},
  paging = [0],
  shown = [],
  tick = 0,
  stats = {},
  opt = { sites: [], categories: [], markets: [] },
  selection = new Set(),
  waitTimer,
  toastTime,
  modalBusy = false,
  uploads = [],
  staged = null,
  importBusy = false,
  activeRule = null,
  batchFilterName = "";
let importReviewState = null;
let observedImport = null;
const qs = (obj) =>
  new URLSearchParams(
    Object.entries({
      section: activeAreaId,
      industry: industryId,
      ...obj,
    }).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  ).toString();
const get = async (path, params = {}) =>
  fetch("/api/" + path + "?" + qs(params), { cache: "no-store" }).then(check);
const post = async (path, p, params = {}) =>
  fetch("/api/" + path + "?" + qs(params), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(p),
  }).then(check);
async function check(r) {
  const d = await r.json();
  if (!r.ok) throw Error(d.error || "操作失败，请重试。");
  return d;
}
const btn = (action, label, cls = "secondary", extra = "") =>
  '<button type="button" class="' +
  cls +
  '" data-action="' +
  action +
  '" ' +
  extra +
  ">" +
  label +
  "</button>";
const safeLink = (url, label) =>
  /^https?:\/\//i.test(url || "")
    ? '<a href="' +
      esc(url) +
      '" target="_blank" rel="noopener noreferrer">' +
      esc(label || url) +
      "</a>"
    : esc(label || "—");
const option = (value, label, selected) =>
  '<option value="' +
  esc(value) +
  '" ' +
  (String(value) === String(selected) ? "selected" : "") +
  ">" +
  esc(label) +
  "</option>";
const select = (id, label, pairs, val) =>
  '<select class="filter" aria-label="' +
  label +
  '" id="' +
  id +
  '">' +
  pairs.map(([k, v]) => option(k, v, val)).join("") +
  "</select>";
const field = (name, label, placeholder = "", req = false) =>
  '<label class="field"><span>' +
  esc(label) +
  '</span><input name="' +
  name +
  '" placeholder="' +
  esc(placeholder) +
  '" ' +
  (req ? "required" : "") +
  "></label>";
const badge = (n) =>
  '<span class="status" data-state="' + n + '">' + states[n] + "</span>";
function toast(s) {
  $("#toast").hidden = false;
  $("#toast").textContent = s;
  clearTimeout(toastTime);
  toastTime = setTimeout(() => ($("#toast").hidden = true), 3500);
}
function failure(e) {
  const host = $("#dialog").open ? $("#dialog-body") : $("#feedback");
  let box = host.querySelector(".live-error");
  if (!box) {
    box = document.createElement("div");
    box.className = "error live-error";
    box.setAttribute("role", "alert");
    host.prepend(box);
  }
  box.textContent = e.message || String(e);
}
function dialog(title, html) {
  $("#dialog-title").textContent = title;
  $("#dialog-body").innerHTML = html;
  const d = $("#dialog");
  if (!d.open) d.showModal();
  d.scrollTop = 0;
}
function close() {
  if (modalBusy || importBusy) return;
  $("#dialog").close();
  if (staged) {
    post("discard", { token: staged.token }).catch(() => {});
    staged = null;
  }
  uploads = [];
}
$("#dialog").addEventListener("cancel", (e) => {
  e.preventDefault();
  close();
});
let galleryFilters = {};
let galleryMatched = 0;
let siteCoverage = null;
let siteKeywordBatch = null;
const selectedPhotos = new Set();
let metaReady = false;
let metaPending = null;
async function refreshMeta() {
  [stats, opt] = await Promise.all([get("stats"), get("options")]);
  metaReady = true;
  metrics();
}
function ensureMeta() {
  if (metaReady) return Promise.resolve();
  if (!metaPending)
    metaPending = refreshMeta().finally(() => {
      metaPending = null;
    });
  return metaPending;
}
function metrics() {
  const summary = $("#summary");
  if (view === "sites") {
    if (!summary.classList.contains("site-metrics")) {
      summary.classList.add("site-metrics");
      summary.innerHTML = Object.entries({"": "全部同行", ...siteKeywordLabels})
        .map(([status, label]) => btn(
          "site-coverage",
          '<strong>…</strong><span>' + esc(label) + '</span>',
          "metric coverage-button",
          'data-coverage="' + status + '" aria-controls="panel"',
        )).join("");
    }
    for (const control of summary.querySelectorAll(".coverage-button")) {
      const status = control.dataset.coverage;
      const count = siteCoverage?.[status || "total"];
      control.firstElementChild.textContent = count == null ? "…" : fmt(count);
      control.setAttribute("aria-pressed", String(status === (filt.keyword_status || "")));
    }
    return;
  }
  summary.classList.remove("site-metrics");
  const blocks = view === "gallery" ? [
    ["全部行业图片（去重）", galleryFilters.global_total],
    [industryName + "图片", galleryFilters.industry_total],
    ["当前行业同行参考图", galleryFilters.peers],
    ["当前筛选图片", galleryMatched],
  ] : [
    ["唯一关键词", stats.words],
    ["原始来源记录", stats.observations],
    ["同行网站", stats.sites],
    ["已保留关键词", stats.keep],
  ];
  summary.innerHTML = blocks
    .map(
      ([k, v]) =>
        '<div class="metric"><strong>' +
        (v == null ? "…" : fmt(v)) +
        "</strong><span>" +
        esc(k) +
        "</span></div>",
    )
    .join("");
}
const marketNames = typeof Intl.DisplayNames === "function"
  ? new Intl.DisplayNames(["zh-CN"], {type:"region", fallback:"none"})
  : null;
function marketLabel(value) {
  if (!marketNames || !/^[a-z]{2}$/i.test(value)) return value;
  const code = value.toUpperCase();
  const name = marketNames.of(code === "UK" ? "GB" : code);
  return name ? name + "（" + value + "）" : value;
}

function filters() {
  if (view === "imports") {
    $("#filters").innerHTML = importHistoryFilters();
    return;
  }
  if (!["words", "sites", "gallery"].includes(view)) {
    $("#filters").innerHTML = "";
    return;
  }
  const search =
    '<label class="searchbox"><input type="search" id="search" aria-label="搜索资料" placeholder="' +
    (view === "words"
      ? "搜索关键词或中文翻译"
      : view === "gallery"
        ? "搜索文件名、型号或配图关键词"
        : "搜索公司、域名或产品") +
    '" value="' +
    esc(filt.q || "") +
    '"><kbd>/</kbd></label>';
  let html = '<div class="toolbar">' + search;
  if (view === "words") {
    html += select(
      "state",
      "跟进状态",
      [
        ["active", "全部在库"],
        ["0", "待筛选"],
        ["1", "已保留"],
        ["2", "已排除"],
        ["all", "含已排除"],
      ],
      filt.state || "active",
    );
    html += select(
      "ptype",
      "产品类型",
      [["", "全部产品类型"], ...typeList().map((x) => [x.id, x.name])],
      filt.ptype ?? "",
    );
    html += select(
      "category",
      "一级分类",
      [["", "全部分类"], ...opt.categories.map((x) => [x, x])],
      filt.category || "",
    );
    html += select(
      "traffic",
      "自然流量",
      [
        ["", "全部流量"],
        ["1", "原表自然流量大于 0"],
      ],
      filt.traffic || "",
    );
    const markets = opt.markets || [];
    const selectedMarket = filt.market || "";
    if (markets.length || selectedMarket) {
      const listedMarket = markets.find(value => value.toUpperCase() === selectedMarket.toUpperCase());
      const choices = [...markets];
      if (selectedMarket && !listedMarket) choices.push(selectedMarket);
      html += select("market", "市场",
        [["", "全部市场"], ...choices.map(value => [value, marketLabel(value)])],
        listedMarket || selectedMarket);
    }
    if (industryId === 1)
      html += select(
        "featured",
        "原表精选",
        [
          ["", "所有来源词"],
          ["1", "原表包装袋精选"],
        ],
        filt.featured || "",
      );
    html += btn(
      "chooseSite",
      esc(
        filt.site
          ? opt.sites.find((x) => String(x.id) === String(filt.site))?.domain ||
              "已选同行"
          : "全部同行",
      ),
      "secondary",
    );
  }
  if (view === "gallery") {
    for (const [key,label] of [["kind","图片来源"],["category","产品分类"],["role","图片用途"]]) {
      html += select(key,label,[["","全部"+label],...(galleryFilters[key] || []).map(x=>[x,x])],filt[key] || "");
    }
  }
  if (view === "gallery")
    html += select(
      "linkstate",
      "配图状态",
      [
        ["", "全部图片"],
        ["ready", "已配在库词"],
        ["pending", "待关联在库词"],
      ],
      filt.linkstate || "",
    );
  if (view === "sites") {
    html += select(
      "audience",
      "客户类型",
      [
        ["", "全部客户类型"],
        [1, "B2B（含兼营）"],
        [2, "B2C（含兼营）"],
        [3, "B2B + B2C"],
        [0, "未标注"],
      ],
      filt.audience ?? "",
    );
    html += select(
      "keyword_status",
      "同行关键词状态",
      [["", "全部关键词状态"], ...Object.entries(siteKeywordLabels)],
      filt.keyword_status || "",
    );
  }
  html += btn("preset-list", "常用筛选") + "</div>";
  if (filt.batch)
    html +=
      '<p class="notice">正在查看 ' +
      esc(batchFilterName) +
      (view === "words" && filt.batch_scope
        ? ' · ' + (filt.batch_scope === "new" ? "新增词" : "已有词") + ' ' +
          '<a class="text-button" href="#words/batch/' + Number(filt.batch) + '">查看整批</a>'
        : '') +
      " " +
      btn("clearbatch", "清除", "text-button") +
      "</p>";
  if (view === "words" && filt.type_review)
    html += '<div class="notice type-review-scope"><strong>' + esc(typeReviewLabel(filt.type_review)) +
      '</strong><div class="step-actions">' + btn("typeReview", "查看其他分组", "text-button") +
      btn("clearTypeReview", "清除分组", "text-button") + '</div></div>';
  $("#filters").innerHTML = html;
}
function hasAppPrevious() {
  const ref = document.referrer ? new URL(document.referrer) : null;
  return !!history.state?.appBack || (history.length > 1 && ref?.origin === location.origin && ref.pathname === "/");
}

function rememberWorkspace() {
  const workspace = {
    view, filters: filt, pages: paging, scroll: window.scrollY,
    expanded: $$("#panel details[data-remember][open]").map(item => item.dataset.remember),
  };
  history.replaceState({...history.state, workspace}, "");
}

function pushWorkspaceRoute(route) {
  rememberWorkspace();
  history.pushState({appBack:true}, "", route);
}

function restoreWorkspace(position) {
  const expanded = new Set(position.expanded);
  $$("#panel details[data-remember]").forEach(item => { item.open = expanded.has(item.dataset.remember); });
  window.scrollTo(0, position.scroll);
}

function returnInApp() {
  if (hasAppPrevious()) {
    rememberWorkspace();
    history.back();
    return;
  }
  let parent = "#home";
  if (view === "sitemap") parent = filt.node ? "#sitemap/" + filt.project : filt.project ? "#sitemap" : "#buildhub";
  else if (view === "buildhub" && filt.archive) parent = "#buildhub/" + filt.project;
  else if (view === "wiki") parent = filt.slug ? "#wiki/" + filt.project : filt.project ? "#wiki" : "#buildhub";
  else if (view === "prompts") parent = filt.project ? "#buildhub/" + filt.project : "#buildhub";
  else if (view === "skills" && filt.project && activeAreaId === 2) parent = "#skills";
  else if (filt.project) parent = view === "buildhub" ? "#buildhub" : "#buildhub/" + filt.project;
  else if (["workflows", "materials", "skills", "siteplan", "skillbank", "buildsearch"].includes(view) && area?.kind === "build") parent = "#buildhub";
  else if (view === "words" && filt.type_review) parent = "#types";
  else if (["words", "types", "sites", "gallery", "gallery-all", "imports", "rules"].includes(view)) parent = "#library";
  history.replaceState(null, "", parent);
  openWorkspaceRoute();
  window.scrollTo(0,0);
}
function openAppLocation(destination) {
  const url = new URL(destination, location.href);
  if (url.origin !== location.origin || url.pathname !== location.pathname || url.search !== location.search) {
    if (url.origin === location.origin && url.pathname === location.pathname) rememberWorkspace();
    location.assign(url.href);
    return;
  }
  if (url.hash !== location.hash) pushWorkspaceRoute(url.hash);
  openWorkspaceRoute();
}
$("#go-back").addEventListener("click", returnInApp);
document.addEventListener("click", e => {
  const link = e.target.closest("a[href]");
  if (!link || link.target || link.hasAttribute("download") || e.defaultPrevented || e.button !== 0 ||
      e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const url = new URL(link.href);
  if (!url.hash || url.origin !== location.origin || url.pathname !== location.pathname) return;
  if (!Object.prototype.hasOwnProperty.call(titles, url.hash.slice(1).split("/")[0])) return;
  if (url.hash === location.hash && url.search === location.search) return;
  e.preventDefault();
  if (link.closest("#dialog")) close();
  openAppLocation(url.href);
});
function navigate(v, params = {}, record = true) {
  if (v === "skillbank" && activeAreaId !== 2) {
    location.replace("/?" + qs({section: 2}) + "#skillbank");
    return;
  }
  if (v === "buildsearch" && activeAreaId !== 2) {
    location.assign("/?" + qs({section: 2}) + recordSearchRoute(params));
    return;
  }
  if (!Object.prototype.hasOwnProperty.call(titles, v)) v = "home";
  if (record) {
    const route =
      "#" +
      v +
      (params.project
        ? "/" + Number(params.project)
        : v === "materials" && params.sub !== undefined && params.sub !== ""
          ? "/" + Number(params.sub)
          : "");
    if (location.hash !== route) pushWorkspaceRoute(route);
  }
  const position = !record && history.state?.workspace?.view === v ? history.state.workspace : null;
  if (position) params = position.filters;
  if (v === "imports") importHistoryPages = history.state?.importHistoryPages || [null];
  if (v === "buildsearch") recordSearchPages = history.state?.recordSearchPages || [null];
  $("#panel").innerHTML = '<p class="loading" role="status">正在打开…</p>';
  if (v !== "words" || view !== "words" || params.type_review !== filt.type_review) selection.clear();
  if (v === "gallery" || view === "gallery") {
    selectedPhotos.clear();
    galleryMatched = null;
    galleryFilters = {};
  }
  if (v === "sites") siteCoverage = null;
  siteKeywordBatch = null;
  view = v;
  const back = $("#go-back");
  back.disabled = v === "home" && !hasAppPrevious();
  back.title = back.disabled ? "当前没有上一页" : "返回上一页";
  filt = params;
  metrics();
  paging = position?.pages || [0];
  $("#feedback").innerHTML = "";
  $("#heading").textContent = $("#crumb").textContent = titles[v];
  if (v === "buildhub" || (v === "materials" && area?.kind === "notes"))
    $("#heading").textContent = $("#crumb").textContent = area.name;
  $("#sub").textContent =
    v === "materials" && area?.kind === "notes"
      ? "按二级类目收集、查找原文和附件。"
      : desc[v];
  $("#sub").hidden = !desc[v];
  if (v === "sitemap" && params.node)
    $("#heading").textContent = $("#crumb").textContent = "页面工作记录";
  if (v === "buildsearch" && params.kind === "页面待办") {
    $("#heading").textContent = $("#crumb").textContent = "页面待办";
    $("#sub").textContent = "查看各网站页面接下来要做的事，点页面打开进度、问题和提示词原文。";
  }
  if (v === "buildsearch" && params.kind === "待解决") {
    $("#heading").textContent = $("#crumb").textContent = "待解决问题";
    $("#sub").textContent = "按项目核对问题和报告原文，处理后填写解决办法。";
  }
  const overview = isProjectOverview(v, params);
  const mapsIndex = v === "sitemap" && !params.project;
  const skillsIndex = v === "skills" && !params.project && activeAreaId === 2;
  if (skillsIndex) {
    $("#sub").textContent = "选择项目，查看或登记该项目的技能、用途和使用方法。";
    $("#sub").hidden = false;
  }
  if (mapsIndex) {
    $("#sub").textContent = "选择一个项目，查看它的网站栏目和页面。";
    $("#sub").hidden = false;
  }
  if (overview) {
    $("#heading").textContent = $("#crumb").textContent = "项目总览";
    $("#sub").textContent = "查看各项目的进度和下一件事。点项目名称可以接着做。";
  }
  if (v === "buildhub" && params.archive) {
    $("#heading").textContent = $("#crumb").textContent = "建站归档";
    $("#sub").hidden = true;
  }
  $("#summary").hidden = [
    "home",
    "library",
    "buildhub",
    "buildsearch",
    "workflows",
    "siteplan",
    "sitemap",
    "skillbank",
    "wiki",
    "prompts",
    "skills",
    "materials",
    "imports",
    "gallery-all",
  ].includes(v);
  $("#panel").classList.toggle(
    "workspace-panel",
    [
      "home",
      "library",
      "buildhub",
      "buildsearch",
      "workflows",
      "siteplan",
      "sitemap",
      "skillbank",
      "wiki",
      "prompts",
      "skills",
      "materials",
      "gallery-all",
    ].includes(v),
  );
  $("#workspace-name").textContent = v === "home" ? "我的工作区" : overview || mapsIndex || skillsIndex ? area.name : industryName;
  if (v === "imports" && params.scope) {
    $("#workspace-name").textContent = params.scope === "all" ? "全部行业" :
      knownIndustries.find(item => String(item.id) === params.scope)?.name || industryName;
  }
  if (v === "gallery-all") $("#workspace-name").textContent = "全部行业";
  $$("[data-view]").forEach((x) =>
    x.classList.toggle("active", x.dataset.view === v),
  );
  const buildArea = [
    "buildhub",
    "buildsearch",
    "workflows",
    "materials",
    "siteplan",
    "sitemap",
    "skillbank",
    "wiki",
    "prompts",
    "skills",
  ].includes(v);
  $("#library-nav").hidden = v === "home" || buildArea;
  $("#build-nav").hidden = !buildArea || area?.kind === "notes";
  $("#software-subnav").hidden = activeAreaId !== 2 || !buildArea;
  $('#build-nav [data-view="siteplan"]').hidden = activeAreaId === 2;
  if (["skillbank", "wiki", "buildsearch", "prompts"].includes(v)) $("#workspace-name").textContent = area.name;
  $(".industry-box").hidden = v === "home" || v === "gallery-all" || overview || skillsIndex || v === "sitemap" || v === "wiki" || v === "prompts" || v === "buildsearch" || activeAreaId >= 3;
  $(".back-home").hidden = v === "home";
  if (activeAreaId >= 3 && v !== "home")
    $("#workspace-name").textContent = area.name;
  $$(".primary-nav [data-id]").forEach((x) =>
    x.classList.toggle(
      "active",
      v !== "home" && Number(x.dataset.id) === activeAreaId,
    ),
  );
  $("#actions").innerHTML = [
    "home",
    "library",
    "buildhub",
    "buildsearch",
    "workflows",
    "siteplan",
    "sitemap",
    "skillbank",
    "wiki",
    "prompts",
    "skills",
    "materials",
    "gallery-all",
  ].includes(v)
    ? workspaceActions(v)
    : v === "words"
      ? btn("addword", "＋ 加一个词") +
        btn("export", "导出当前筛选") +
        btn("bulkExport", "批量导出") +
        btn("upload", "批量导入", "primary")
      : v === "sites"
        ? btn("addsite", "＋ 添加同行") +
          btn("exportSites", "导出当前筛选") +
          btn("bulkExport", "批量导出") +
          btn("uploadSites", "批量导入", "primary")
        : v === "gallery"
          ? '<button type="button" class="secondary" data-view="gallery-all">跨行业找图</button>' +
            btn("bank-export","批量下载") + btn("buildPhotos", "建站配图") +
            btn("uploadPhoto", "批量上传", "primary")
          : v === "imports"
            ? btn("upload", "批量导入", "primary")
            : v === "types"
              ? btn("typeReview", "复核待确认") + btn("typeSuggestions", "找识别词建议") +
                btn("newType", "＋ 添加类型", "primary")
              : btn("newrule", "＋ 新建规则", "primary");
  filters();
  if (!position) window.scrollTo(0,0);
  load(position).catch(failure);
}
function table(headers, body) {
  return (
    '<div class="table-scroll"><table class="records-table"><thead><tr>' +
    headers.map((h) => "<th>" + h + "</th>").join("") +
    "</tr></thead><tbody>" +
    body +
    "</tbody></table></div>"
  );
}
function selectedControls() {
  return (
    '<div class="selection-tools">' +
    '<span class="count" id="selection-count" aria-live="polite">已选 ' +
    fmt(selection.size) +
    " 个词</span>" +
    btn(
      "clearSelection",
      "清空选择",
      "text-button",
      selection.size ? "" : "hidden",
    ) +
    btn(
      "brief",
      "给 AI 建站用",
      "secondary",
      selection.size ? "" : 'disabled title="请先勾选关键词"',
    ) +
    btn("batchstate", "批量标记", "text-button") +
    btn("typeBatch", "批量归类", "secondary") +
    "</div>"
  );
}
function syncSelection() {
  const count = $("#selection-count");
  if (!count) return;
  count.textContent = "已选 " + fmt(selection.size) + " 个词";
  const group = count.parentElement;
  group.querySelector('[data-action="brief"]').disabled = !selection.size;
  group.querySelector('[data-action="clearSelection"]').hidden =
    !selection.size;
  const all = $("#checkall");
  if (all) {
    const checked = shown.filter((w) => selection.has(w.id)).length;
    all.checked = !!shown.length && checked === shown.length;
    all.indeterminate = checked > 0 && checked < shown.length;
  }
}
async function openBrief() {
  const scope = filt.market
    ? {market:filt.market, site:filt.site, batch:filt.batch, traffic:filt.traffic}
    : {};
  const result = await post("selected-brief", { ids: [...selection] }, scope);
  if (!result.rows.length) {
    dialog(
      "给 AI 建站用",
      "<p>当前范围内没有可用的已选词。请勾选待筛选或已保留的关键词。</p>",
    );
    return;
  }
  dialog(
    "给 AI 建站用",
    "<p><strong>" +
      esc(industryName) +
      "</strong> · " +
      (filt.market ? esc(marketLabel(filt.market)) + " · " : "") +
      fmt(result.rows.length) +
      " 个关键词" +
      (result.skipped
        ? "，已跳过 " + fmt(result.skipped) + " 个范围外或已排除的词"
        : "") +
      "</p>" +
      '<label class="field">要写什么内容<select id="brief-purpose"><option>产品分类页</option><option>产品详情页</option><option>行业文章</option></select></label>' +
      '<label class="field">发给 AI 的内容<textarea id="brief-text" rows="10" class="connection-config brief-text" readonly></textarea></label>' +
      btn("copyBrief", "复制给 AI", "primary"),
  );
  const evidence = result.rows
    .map((r, i) => {
      const metrics = [
        ["市场", r.market],
        ["自然流量", r.traffic],
        ["DR", r.dr],
      ]
        .filter(([, value]) => value != null && value !== "")
        .map(([label, value]) => label + " " + value)
        .join("　·　");
      return [
        i + 1 + ". " + r.keyword,
        r.translation ? "中文翻译　" + r.translation : "",
        r.product_type ? "产品类型　" + r.product_type : "",
        metrics,
        r.competitor_url ? "同行官网　" + r.competitor_url : "",
        r.ranking_url ? "排名网址　" + r.ranking_url : "",
        ...(r.manual_sources || []).map(
          (ref) =>
            "手动来源　" +
            [ref.url, ref.competitor_url].filter(Boolean).join("　"),
        ),
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n\n");
  const update = () => {
    $("#brief-text").value =
      "请用下列「" +
      industryName +
      "」行业关键词写一份" +
      $("#brief-purpose").value +
      "草稿。按搜索意图组织小标题和正文，自然使用相关词；缺少的产品规格、资质或数据请标成待补充。\n\n词库资料按词排列。自然流量和 DR 来自对应来源记录，空缺值已省略。\n" +
      evidence;
  };
  $("#brief-purpose").addEventListener("change", update);
  update();
}

function toolRow(total) {
  return (
    '<div class="list-caption"><span>' +
    esc(titles[view]) +
    (total == null ? "" : ' <span class="keyword-result-count">共 ' + fmt(total) + ' 个词</span>') +
    "</span>" +
    (view === "words" ? selectedControls() : "") +
    "</div>"
  );
}
function pager(more) {
  return (
    '<div class="pagination"><span class="left">第 ' +
    paging.length +
    " 页 · 每页最多 50 条</span>" +
    btn("prev", "上一页", "secondary", paging.length === 1 ? "disabled" : "") +
    btn("next", "下一页", "secondary", more ? "" : "disabled") +
    "</div>"
  );
}
const nothing = '<div class="empty">没有匹配记录。</div>';
function applyTableFilter(key, value) {
  filt[key] = value;
  paging = [0];
  return load();
}

async function load(position = null) {
  const k = ++tick;
  const target = view;
  if (
    ![
      "home",
      "buildhub",
      "buildsearch",
      "workflows",
      "siteplan",
      "sitemap",
      "skillbank",
      "wiki",
      "prompts",
      "skills",
      "materials",
      "gallery-all",
      "sites",
    ].includes(target) &&
    !metaReady
  ) {
    await ensureMeta();
    if (k !== tick) return;
    filters();
  }
  if (
    [
      "home",
      "library",
      "buildhub",
      "buildsearch",
      "workflows",
      "siteplan",
      "sitemap",
      "skillbank",
      "wiki",
      "prompts",
      "skills",
      "materials",
      "gallery-all",
    ].includes(target)
  ) {
    const page = await workspacePanel(target, filt);
    if (k === tick) {
      $("#panel").innerHTML = page;
      if (target === "sitemap" && currentBuildProject && filt.project && !filt.node)
        bindMapTree($("#panel .map-browser"), currentBuildProject);
      const receipt = $("#panel .linked-receipt");
      if (position) restoreWorkspace(position);
      else if (receipt) {
        receipt.focus({preventScroll:true});
        receipt.scrollIntoView({block:"start"});
      }
    }
    return;
  }
  if (target === "gallery") {
    if (galleryFilters.categories === undefined) {
      const data = await get("gallery-filters");
      if (k !== tick) return;
      galleryFilters = data;
      filters();
    } else {
      for (const key of ["category","kind","role","linkstate"]) {
        const control = document.getElementById(key);
        if (control) control.value = filt[key] || "";
      }
    }
  }
  const d = target === "imports" ? await loadImportHistory() : await get(target, {
    ...filt,
    after: paging.at(-1) || "",
  });
  if (k !== tick) return;
  let html = "";
  if (target === "words") {
    shown = d.rows;
    const b = shown
      .map((w) => {
        const chineseOriginal = /\p{Script=Han}/u.test(w.term) && !/[\p{Script=Hiragana}\p{Script=Katakana}]/u.test(w.term);
        const chinese = w.translation || (chineseOriginal ? w.term : "");
        return '<tr><td class="check"><input type="checkbox" data-id="' +
          w.id +
          '" ' +
          (selection.has(w.id) ? "checked " : "") +
          'aria-label="选择 ' +
          esc(w.term) +
          '"></td><td>' +
          btn("word", esc(w.english || w.term), "record-name", 'data-id="' + w.id + '"') +
          (w.english && w.english !== w.term && w.term !== chinese
            ? '<small class="secondary-text">' + esc(w.term) + "</small>"
            : "") +
          '</td><td>' + (chinese ? esc(chinese) : '<span class="secondary-text">待翻译</span>') +
          "</td><td>" +
          esc(typeName(w.product_type)) +
          (w.category
            ? '<small class="secondary-text">' + esc(w.category) + "</small>"
            : "") +
          "</td><td>" +
          badge(w.state) +
          "</td><td>" +
          fmt(w.sites) +
          "</td><td>" +
          esc(w.traffic ?? "—") +
          "</td><td>" +
          esc(w.dr ?? "—") +
          "</td><td>" +
          (w.url ? safeLink(w.url, w.domain || w.url) : esc(w.domain || "—")) +
          (w.market ? '<small class="secondary-text">' + esc(marketLabel(w.market)) + '</small>' : "") +
          "</td></tr>";
      })
      .join("");
    html =
      toolRow(d.total) +
      (b
        ? table(
            [
              '<input type="checkbox" id="checkall" aria-label="选择本页全部">',
              "关键词 / 英文",
              "中文翻译",
              "产品类型 / 原分类",
              "状态",
              filt.batch ? "本批同行数" : "来源同行数",
              filt.batch ? "本批流量" : "自然流量",
              "DR",
              filt.batch ? "本批来源" : "最近来源",
            ],
            b,
          )
        : nothing) +
      pager(d.more);
  } else if (target === "types") {
    html = typeOverview(d);
  } else if (target === "sites") {
    shown = d.rows;
    siteCoverage = d.coverage;
    siteKeywordBatch = d.keyword_batch;
    const status = filt.keyword_status;
    metrics();
    html =
      '<div class="list-caption" role="status">' +
      esc(siteKeywordLabels[status] || "全部同行") + ' · ' + fmt(siteCoverage[status || "total"]) + ' 家</div>' +
      (shown.length
        ? table(
            ["同行", "官网", "客户类型", "地区", "状态", "关键词"],
            shown
              .map(
                (s) =>
                  "<tr><td>" +
                  btn(
                    "site",
                    esc(s.name),
                    "record-name",
                    'data-id="' + s.id + '"',
                  ) +
                  "</td><td>" +
                  safeLink(s.url, s.domain) +
                  "</td><td>" +
                  esc(channelNames[s.audience]) +
                  " </td><td>" +
                  esc(s.region || "—") +
                  "</td><td>" +
                  esc(s.status) +
                  "</td><td>" +
                  (s.has_keywords
                    ? btn("sitewords", siteKeywordBatch ? "查看本批关键词" : "查看关键词",
                        "text-button", 'data-id="' + s.id + '"')
                    : '<span class="secondary-text">' + siteKeywordLabels.missing + '</span>') +
                  "</td></tr>",
              )
              .join(""),
          )
        : nothing) +
      pager(d.more);
  } else if (target === "gallery") {
    shown = d.rows;
    galleryMatched = d.total;
    metrics();
    html = galleryCategories() +
      '<div class="list-caption"><span>'+esc(industryName)+' · '+fmt(d.total)+' 张</span>'+btn("bank-peer",filt.kind==="同行参考"?"返回全部来源":"只看同行参考图","text-button")+'</div>' +
      '<div id="photo-selection" class="photo-selection">'+photoSelectionTools()+'</div>' +
      (shown.length
        ? photoGrid(shown)
        : '<div class="empty"><b>没有匹配的产品图片</b><p>可在此行业上传产品图，也可在关键词详情里直接配图。</p></div>') +
      pager(d.more);
  } else if (target === "imports") {
    html = importHistoryPanel(d);
  } else {
    html =
      toolRow() +
      (d.length
        ? table(
            ["排除短语", "操作"],
            d
              .map(
                (r) =>
                  "<tr><td>" +
                  esc(r.phrase) +
                  "</td><td>" +
                  btn(
                    "removeRule",
                    "撤销",
                    "text-button",
                    'data-id="' + r.id + '" data-name="' + esc(r.phrase) + '"',
                  ) +
                  "</td></tr>",
              )
              .join(""),
          )
        : '<div class="empty">当前没有排除规则。新导入的词会保留在库中，等你筛选。</div>');
  }
  $("#panel").innerHTML = html;
  if (target === "gallery") updatePhotoSelection();
  if (target === "words") syncSelection();
  if (position) restoreWorkspace(position);
}
async function word(id, after = 0, scoped = view === "words" && Boolean(filt.batch || filt.market)) {
  await ensureMeta();
  const scope = scoped
    ? {batch:filt.batch, site:filt.site, market:filt.market, traffic:filt.traffic}
    : {};
  const d = await get("word", { id, after, ...scope });
  const w = d.word;
  const images = await get("gallery-match", { term: w.term });
  const obs = d.rows
    .map(
      (o) =>
        '<div class="detail-item"><strong>' +
        safeLink(o.site_url, o.domain || "原表未列同行") +
        "</strong><p>" +
        safeLink(o.url, o.url) +
        "</p><p>自然流量　" +
        esc(o.traffic ?? "—") +
        "　 DR　" +
        esc(o.dr ?? "—") +
        "　 排名　" +
        esc(o.position ?? "—") +
        "　 搜索量　" +
        esc(o.volume ?? "—") +
        "</p><p>市场　" +
        esc(o.market || "—") +
        "　 报告日期　" +
        esc(o.report_date || "—") +
        "</p><small>" +
        esc(o.filename) +
        " · 第 " +
        fmt(o.rownum) +
        " 条数据</small>" +
        (o.raw
          ? '<details><summary>查看原表字段</summary><dl class="kv">' +
            o.raw
              .map(([k, v]) => "<dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd>")
              .join("") +
            "</dl></details>"
          : "") +
        "</div>",
    )
    .join("");
  const refs = d.refs
    .map((r) => "<p>" + safeLink(r.url, r.name || r.url) + "</p>")
    .join("");
  dialog(
    w.term,
    "<p>" +
      badge(w.state) +
      "　" +
      esc([w.english !== w.term ? w.english : "", w.translation !== w.term ? w.translation : "",
        w.category, w.subtype].filter(Boolean).join(" / ")) +
      "</p>" +
      (w.reason ? '<p class="inline-hint">' + esc(w.reason) + "</p>" : "") +
      '<div class="button-line">' +
      [0, 1, 2]
        .filter((n) => n !== w.state)
        .map((n) =>
          btn(
            "oneState",
            n === 0 ? "恢复待筛选" : states[n],
            "secondary",
            'data-id="' + id + '" data-state="' + n + '"',
          ),
        )
        .join("") +
      "</div>" +
      wordTypeForm(w) +
      '<p class="inline-hint">归类依据 · ' + esc(d.typeReason) + '</p>' +
      wordPhotoSection(w, images) +
      sourceSummary(d.summaries, scope.market && scope.traffic === "1") +
      '<details><summary>分类与笔记</summary><form data-form="edit" data-id="' +
      id +
      '" class="form-grid"><label class="field">一级分类<input name="category" value="' +
      esc(w.category) +
      '"></label><label class="field">研究备注<input name="notes" value="' +
      esc(w.notes) +
      '"></label><button class="secondary">保存笔记</button></form></details>' +
      '<section class="detail-section"><div class="board-title"><h3>' +
      (scope.market ? esc(marketLabel(scope.market)) + "来源记录" : d.batch ? "本批来源记录" : "来源记录") +
      '</h3>' + (view === "words" && (filt.batch || filt.market)
        ? btn("word-sources", scoped ? "查看全部来源" : filt.market ? "回到筛选来源" : "回到本批来源", "text-button",
          'data-id="' + id + '" data-scoped="' + (scoped ? 0 : 1) + '"') : '') + '</div>' +
      (d.batch ? '<p class="inline-hint">' + esc(d.batch.filename) + '</p>' : '') +
      (obs || (scoped ? "<p>该筛选范围没有这个词的来源记录。</p>" : "<p>尚无排名导入记录。</p>")) +
      (d.more
        ? btn(
            "moreobs",
            "后 100 条",
            "secondary",
            'data-id="' + id + '" data-after="' + d.rows.at(-1).id + '" data-scoped="' + (scoped ? 1 : 0) + '"',
          )
        : "") +
      "</section>" +
      (refs
        ? '<section class="detail-section"><h3>官网证据 / 手动来源</h3>' +
          refs +
          "</section>"
        : ""),
  );
}
async function site(id) {
  const batch = siteKeywordBatch;
  const s = await get("site", { id, batch: batch || "" });
  dialog(
    s.name,
    "<p>" +
      safeLink(s.url, s.domain) +
      "</p><p>" +
      esc(
        [channelNames[s.audience], s.region, s.role, s.status]
          .filter(Boolean)
          .join(" · "),
      ) +
      "</p><p>" +
      esc(s.products) +
      "</p><p>" +
      esc(s.notes) +
      '</p><form data-form="site-channel" data-id="' +
      id +
      '" class="form-grid">' +
      channelField("audience", "客户类型", s.audience) +
      '<button class="secondary">保存类型</button></form>' +
      (s.audience_inferred ? '<p class="inline-hint">当前客户类型根据导入名单的名称识别。</p>' : "") +
      '<p class="secondary-text">' + (batch ? "本批在库关键词" : "在库关键词") + ' · ' +
      fmt(s.keyword_count) + ' 个</p>' +
      '<div class="section-actions">' +
      btn("sitewords", batch ? "查看本批关键词" : "查看这家同行的词",
        "primary", 'data-id="' + id + '"') +
      "</div>" +
      (s.evidence.length
        ? '<section class="detail-section"><h3>官网证据</h3>' +
          s.evidence
            .map((v) => "<p>" + safeLink(v.url, v.title) + "</p>")
            .join("") +
          "</section>"
        : "") +
      (s.queries.length
        ? "<details><summary>原来的同行检索记录</summary>" +
          s.queries
            .map((v) => "<p>" + esc(v.code) + " · " + esc(v.text) + "</p>")
            .join("") +
          "</details>"
        : ""),
  );
}
function photoUrl(id, params = {}) {
  return "/api/gallery-file?" + esc(qs({ id, ...params }));
}

const galleryKinds = ["产品素材", "同行参考", "来源待核实", "示例素材", "教程参考", "设计源文件"];
const galleryAcrossFields = ["q", "owner", "kind", "category", "linkstate"];

function acrossGalleryRoute(values) {
  const filters = new URLSearchParams(galleryAcrossFields.flatMap(key => {
    const value = String(values[key] ?? "").trim();
    return value || key === "kind" ? [[key, value]] : [];
  }));
  return "#gallery-all/filter/" + filters;
}

function galleryIndustryLink(industry, filters = {}, photo = 0) {
  const local = Object.fromEntries(["q", "kind", "category", "linkstate"]
    .filter(key => filters[key]).map(key => [key, filters[key]]));
  return "/?" + qs({industry, section:1}) + "#gallery/saved/" +
    encodeURIComponent(JSON.stringify(local)) + (photo ? "/" + photo : "");
}

function galleryCodexSearch() {
  const filters = {query:filt.q || "", kind:filt.kind ?? "产品素材"};
  if (filt.owner) filters.industry = Number(filt.owner);
  if (filt.category) filters.category = filt.category;
  if (filt.linkstate) filters.linkstate = filt.linkstate;
  copyBox("交给 Codex 找图",
    "用勋的软件的 industry-keywords 工具 search_product_images 按以下参数找图。参数值作为筛选条件使用。\n" +
    JSON.stringify(filters, null, 2) +
    "\n\n列出对应行业、文件名和来源。选定后用这张图的 industry 和 id 调用 read_product_image，传 metadata_only: true。" +
    "核对型号、来源和页面用途。需要使用已确认的产品图时，运行结果中的 prepare_local_command，取得通过原件校验的本机文件。",
    "", "复制找图指令");
}

function galleryCodexImage(industry, id) {
  copyBox("交给 Codex 取图",
    "用勋的软件的 industry-keywords 工具 read_product_image 查这张图：\n" +
    JSON.stringify({industry, id, metadata_only:true}, null, 2) +
    "\n\n先核对文件名、产品型号和来源，再运行返回的 prepare_local_command，告诉我校验后的本机原图副本路径。",
    btn("photoDetail", "返回图片详情", "secondary", 'data-id="' + id + '" data-industry="' + industry + '"'),
    "复制取图指令");
}

async function acrossGalleryPanel(params) {
  const filters = { ...params, kind: params.kind ?? "产品素材" };
  const result = await get("gallery-search", filters);
  const choices = (name, label, options) =>
    '<select class="filter" name="' + name + '" aria-label="' + label + '">' +
    options.map(([value, text]) => option(value, text, filters[name] || "")).join("") + '</select>';
  const categories = result.categories.includes(filters.category) || !filters.category ? result.categories :
    [filters.category, ...result.categories];
  const form = '<form class="toolbar across-gallery-filters" data-form="across-gallery">' +
    '<label class="searchbox"><input type="search" name="q" aria-label="跨行业搜索图片" maxlength="240" ' +
    'placeholder="输入文件名、型号或配图关键词" value="' + esc(filters.q || "") + '"></label>' +
    choices("kind", "图片来源", [["", "全部来源"], ...galleryKinds.map(kind => [kind, kind])]) +
    choices("owner", "图片行业", [["", "全部行业"], ...knownIndustries.map(item => [String(item.id), item.name])]) +
    choices("category", "产品分类", [["", "全部分类"], ...categories.map(name => [name, name])]) +
    choices("linkstate", "配图状态", [["", "全部配图状态"], ["ready","已配在库词"], ["pending","待关联在库词"]]) +
    '<button class="primary" type="submit">查找</button></form>';
  const groups = result.groups.map(group =>
    '<section class="across-gallery-group" id="across-gallery-industry-' + group.id + '" tabindex="-1" aria-labelledby="across-gallery-title-' +
    group.id + '"><div class="list-caption"><h2 id="across-gallery-title-' + group.id + '">' + esc(group.name) + '</h2><small>' +
    fmt(group.total) + ' 张</small><a class="secondary" href="' + esc(galleryIndustryLink(group.id,filters)) +
    '">查看行业图库</a></div>' + photoGrid(group.images.map(photo => ({...photo, industry:group.id}))) + '</section>'
  ).join("");
  const shortcuts = result.groups.length > 1 ?
    '<div class="photo-chips across-gallery-jumps" aria-label="跳转到匹配行业">' +
    result.groups.map(group => btn("gallery-group", esc(group.name) + " " + fmt(group.total), "category-chip",
      'data-id="' + group.id + '"')).join("") + '</div>' : "";
  return '<section class="across-gallery">' + form + '<p class="inline-hint">匹配 ' + fmt(result.groups.length) +
    ' 个行业、' + fmt(result.total) + ' 条图片记录</p>' + shortcuts +
    (groups || '<p class="build-empty">没有匹配的图片。可以换个搜索词或调整筛选。</p>') + '</section>';
}

function galleryCategories() {
  const categories = galleryFilters.categories || [];
  const pending = categories.find(category => category.name === "待细分");
  const all = pending ? [pending, ...categories.filter(category => category !== pending)] : categories;
  if (!all.length) return "";
  const chip = (name, count) => btn("bank-category", esc(name || "全部分类") + " " + fmt(count),
    "category-chip", 'aria-pressed="' + ((filt.category || "") === name) + '" data-category="' + esc(name) + '"');
  return '<section class="photo-categories" aria-label="按产品分类浏览"><h2>产品分类</h2><div class="photo-chips">' +
    chip("", galleryFilters.industry_total) + all.slice(0,6).map(c=>chip(c.name,c.count)).join("") + '</div>' +
    (all.length > 6 ? '<details' + (all.slice(6).some(c=>c.name===filt.category) ? ' open' : '') +
      '><summary>查看全部 ' + fmt(all.length) + ' 个分类</summary><div class="photo-chips">' +
      all.slice(6).map(c=>chip(c.name,c.count)).join("") + '</div></details>' : '') + '</section>';
}
function photoSelectionTools() {
  const allChecked = shown.length > 0 && shown.every(p=>selectedPhotos.has(p.id));
  return '<label><input type="checkbox" id="select-page-photos" ' + (allChecked ? "checked " : "") +
    (shown.length ? "" : "disabled") + '> 全选本页</label><span aria-live="polite">已选 ' + fmt(selectedPhotos.size) + ' 张</span>' +
    (selectedPhotos.size ? btn("bank-classify-selected","批量分类","text-button") +
      btn("bank-export","下载已选图片","text-button") + btn("bank-clear-photos","清空选择","text-button") : "") +
    (selectedPhotos.size || galleryMatched ? btn("bank-bulk-link","批量配图","text-button") : "") +
    (galleryMatched ? btn("bank-classify-filtered","按筛选批量分类","text-button") : "");
}
function updatePhotoSelection() {
  document.querySelectorAll("input[data-photo-select]").forEach(el=>{el.checked = selectedPhotos.has(Number(el.dataset.photoSelect));});
  $("#photo-selection").innerHTML = photoSelectionTools();
  $("#select-page-photos").indeterminate = shown.some(p=>selectedPhotos.has(p.id)) && shown.some(p=>!selectedPhotos.has(p.id));
}
function photoGrid(entries, pickTerm) {
  return (
    '<div class="photo-grid">' +
    entries
      .map((photo) => {
        const action = pickTerm !== undefined ? "choosePhoto" : "photoDetail";
        const scope = photo.industry ? {industry:photo.industry, section:1} : {};
        const extra = (photo.industry ? ' data-industry="' + photo.industry + '"' : "") +
          (pickTerm !== undefined ? ' data-term="' + esc(pickTerm) + '"' : "");
        const selectable = pickTerm === undefined && view === "gallery";
        return (
          (selectable ? '<div class="photo-tile"><label class="photo-pick"><input type="checkbox" data-photo-select="' + photo.id +
            '" aria-label="选择 ' + esc(photo.filename) + '" ' + (selectedPhotos.has(photo.id) ? "checked" : "") + '></label>' : "") +
          '<button type="button" class="photo-card" data-action="' +
          action +
          '" data-id="' +
          photo.id +
          '"' +
          extra +
          ">" +
          '<img loading="lazy" src="' +
          photoUrl(photo.id, { ...scope, preview: 1 }) +
          '" alt=""><strong>' +
          esc(photo.filename) +
          "</strong>" +
          (photo.category ? "<small>"+esc([photo.category,photo.origin_kind].filter(Boolean).join(" · "))+"</small>" : "") +
          (photo.matches !== undefined
            ? "<small>" +
              (photo.matches
                ? fmt(photo.matches) + " 个在库词已配图"
                : "待关联在库词") +
              "</small>"
            : "") +
          "</button>" + (selectable ? "</div>" : "")
        );
      })
      .join("") +
    "</div>"
  );
}
async function uploadPhotos(wordId) {
  const options = galleryFilters.categories ? galleryFilters : await get("gallery-filters");
  dialog(
    industryName + " · 批量上传",
    '<div class="form-grid"><label class="field">整批图片分类<input id="photo-upload-category" list="photo-category-names" maxlength="120" placeholder="自动按文件名识别，也可填写新分类" value="'+esc(view === "gallery" ? filt.category || "" : "")+'"><datalist id="photo-category-names">'+
      options.category.map(name=>'<option value="'+esc(name)+'"></option>').join("")+'</datalist></label>'+
      '<label class="field">整批图片来源<select id="photo-upload-kind">'+galleryKinds.map(k=>option(k,k,view === "gallery" ? filt.kind||"产品素材" : "产品素材")).join("")+'</select></label></div>'+
      '<label class="drop"><b>选择多张产品图</b><span>JPG、PNG、WebP，每张最多 32 MB。</span>' +
      '<input type="file" id="photo-files" data-word="' +
      (wordId || "") +
      '" multiple accept="image/jpeg,image/png,image/webp"></label>' +
      '<p class="inline-hint">' +
      (wordId
        ? "选中的图片都将配给这个关键词。"
        : "文件名去掉扩展名后会作为配图词。例如 custom poly mailers.jpg 对应 custom poly mailers。也可以先传图，再指定关键词。") +
      "</p>",
  );
}
async function thumbnail(file) {
  const image = new Image();
  const local = URL.createObjectURL(file);
  try {
    await new Promise((ok, fail) => {
      image.onload = ok;
      image.onerror = () => fail(Error("无法读取这张图片，请检查格式。"));
      image.src = local;
    });
    const ratio = Math.min(
      1,
      480 / image.naturalWidth,
      360 / image.naturalHeight,
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    return await new Promise((ok) =>
      canvas.toBlob((blob) => ok(blob || new Blob()), "image/jpeg", 0.78),
    );
  } finally {
    URL.revokeObjectURL(local);
  }
}
async function savePhotos(files, wordId, category, kind) {
  modalBusy = true;
  let added = 0,
    repeated = 0;
  const errors = [];
  try {
    for (const [index, file] of Array.from(files).entries()) {
      dialog(
        "正在保存产品图",
        "<p>" +
          (index + 1) +
          " / " +
          files.length +
          "　" +
          esc(file.name) +
          "</p>",
      );
      try {
        if (file.size > 32 * 1024 * 1024) throw Error("超过 32 MB");
        const thumb = await thumbnail(file);
        const res = await fetch(
          "/api/gallery-upload?" +
            qs({ filename: file.name, word: wordId || undefined, category, kind }),
          {
            method: "POST",
            headers: { "X-Thumbnail-Length": String(thumb.size) },
            body: new Blob([thumb, file]),
          },
        ).then(check);
        res.duplicate ? repeated++ : added++;
      } catch (error) {
        errors.push(file.name + " · " + error.message);
      }
    }
  } finally {
    modalBusy = false;
  }
  galleryFilters = {};
  await load();
  if (errors.length) {
    dialog(
      "上传结果",
      "<p>新增 " +
        added +
        " 张，复用 " +
        repeated +
        " 张。</p><ul>" +
        errors.map((x) => "<li>" + esc(x) + "</li>").join("") +
        "</ul>",
    );
  } else {
    if (wordId) await word(Number(wordId));
    else close();
    toast("新增 " + added + " 张，复用 " + repeated + " 张");
  }
}
let photoDetailRequest = 0;
async function photoDetail(id, industry = industryId) {
  const request = ++photoDetailRequest;
  const target = view;
  const across = target === "gallery-all";
  const filters = filt;
  const scope = {industry, section:1};
  const p = await get("gallery-detail", {...scope,id});
  if (request !== photoDetailRequest || view !== target || filt !== filters) return;
  const tags = p.tags
    .map(
      (t) =>
        '<li><span class="literal">' +
        esc(t.term) +
        "</span><small>" +
        (t.word
          ? t.state === 2
            ? "词已排除"
            : "已入词库"
          : "等待关键词入库") +
        "</small>" +
        (across ? "" : btn(
          "unlinkPhoto",
          "解除关联",
          "text-button",
          'data-id="' + id + '" data-term="' + esc(t.term) + '"',
        )) +
        "</li>",
    )
    .join("");
  dialog(
    across ? (knownIndustries.find(item => item.id === industry)?.name || "") + " · " + p.filename : p.filename,
    '<img class="photo-large" src="' +
      photoUrl(id, {...scope, preview:p.mime === "image/vnd.adobe.photoshop" || p.mime === "application/octet-stream" ? 1 : ""}) +
      '" alt="' +
      esc(p.filename) +
      '"><div class="step-actions photo-detail-actions"><a class="secondary" href="' +
      photoUrl(id, {...scope, download:1}) +
      '">下载原图</a>' + btn("gallery-codex-image", "交给 Codex 取图", "secondary",
        'data-id="' + id + '" data-industry="' + industry + '"') + (across ? '<a class="secondary" href="' +
        esc(galleryIndustryLink(industry, {...filters, kind:filters.kind ?? "产品素材"}, id)) + '">进入所属行业管理</a>' : "") + '</div>' +
      (p.origins?.length ? "<h3>分类与来源</h3><ul>"+p.origins.map(o=>"<li>"+esc([o.kind,o.category,o.role].join(" · "))+"<br><small>"+esc(o.path)+"</small></li>").join("")+"</ul>" : "") +
      (across ? "" : btn("bank-photo-edit","调整分类","secondary",'data-id="'+p.id+'"')) +
      (tags ? '<h3>配图关键词</h3><ul class="photo-tags">' + tags + '</ul>' : "") +
      (across ? "" : '<form data-form="linkPhoto" data-id="' +
      id +
      '" class="form-grid">' +
      field("term", "添加完整关键词", "例如 custom poly mailers", true) +
      '<button class="primary">保存关联</button></form>'),
  );
}
let pickerVersion = 0;
async function searchPhotoChoices(input, after = "") {
  const sequence = ++pickerVersion,
    term = input.dataset.term;
  const found = await get("gallery", { q: input.value, after });
  if (sequence !== pickerVersion || !input.isConnected) return;
  const cards = found.rows.length
    ? photoGrid(found.rows, term)
    : "<p>没有找到图片。</p>";
  const container = $("#photo-choices");
  if (after) {
    container.querySelector("[data-action=morePhotoChoices]")?.remove();
    container.insertAdjacentHTML("beforeend", cards);
  } else container.innerHTML = cards;
  if (found.more)
    container.insertAdjacentHTML(
      "beforeend",
      btn(
        "morePhotoChoices",
        "更多图片",
        "secondary",
        'data-id="' + found.rows.at(-1).id + '"',
      ),
    );
}
async function choosePhoto(term, wordId) {
  dialog(
    "从图库选图",
    "<p>为 <b>" +
      esc(term) +
      '</b> 选择一张产品图。</p><div class="button-line">' +
      btn("uploadPhoto", "上传新图", "primary", 'data-id="' + wordId + '"') +
      "</div>" +
      '<label class="field">搜索图片<input id="photo-search" data-term="' +
      esc(term) +
      '" placeholder="文件名或配图关键词"></label><div id="photo-choices" data-word="' +
      wordId +
      '"></div>',
  );
  await searchPhotoChoices($("#photo-search"));
}
function wordPhotoSection(w, images) {
  const controls =
    btn(
      "pickPhoto",
      "从图库选图",
      "secondary",
      'data-id="' + w.id + '" data-term="' + esc(w.term) + '"',
    ) +
    btn("uploadPhoto", "上传并配给此词", "secondary", 'data-id="' + w.id + '"');
  const items = images
    .map(
      (p, i) =>
        '<div class="word-photo"><img loading="lazy" src="' +
        photoUrl(p.id, { preview: 1 }) +
        '" alt="' +
        esc(p.filename) +
        '"><div><b>' +
        esc(p.filename) +
        "</b><small>" +
        (i === 0
          ? "首图"
          : btn(
              "coverPhoto",
              "设为首图",
              "text-button",
              'data-id="' +
                p.id +
                '" data-word="' +
                w.id +
                '" data-term="' +
                esc(w.term) +
                '"',
            )) +
        "</small>" +
        btn(
          "unlinkWordPhoto",
          "解除关联",
          "text-button",
          'data-id="' +
            p.id +
            '" data-word="' +
            w.id +
            '" data-term="' +
            esc(w.term) +
            '"',
        ) +
        "</div></div>",
    )
    .join("");
  return (
    '<section class="detail-section"><h3>产品图片</h3><div class="button-line">' +
    controls +
    "</div>" +
    items +
    "</section>"
  );
}
function buildPhotos() {
  dialog(
    "建站配图",
    '<form id="build-photo-form" method="post" action="/api/gallery-pack?' +
      esc(qs({})) +
      '">' +
      '<div id="build-photo-wordlist"><label class="field">页面关键词，每行一个<textarea name="terms" rows="5" placeholder="custom poly mailers"></textarea></label>' +
      '<div class="button-line">' +
      btn("previewPhotos", "检查配图", "primary") +
      '<button class="secondary" name="scope" value="list">下载这些词的配图包</button></div></div>' +
      '<div id="photo-results" aria-live="polite"></div><section id="build-photo-picker" hidden></section>' +
      '<div id="build-photo-footer"><hr><button class="secondary" name="scope" value="all">下载本行业全部已配图的词</button>' +
      '<p class="inline-hint">压缩包包含原图、Excel 配图清单和建站程序可读的 JSON。</p></div></form>',
  );
}
const photoStatus = {
  matched: "已配图", unmatched: "待配图", absent: "未入词库", excluded: "已排除",
};

function photoMode(form, picking) {
  for (const id of ["build-photo-wordlist", "photo-results", "build-photo-footer"]) {
    form.querySelector("#" + id).hidden = picking;
  }
  form.querySelector("#build-photo-picker").hidden = !picking;
}

async function previewPhotos(form, offset = 0, unmatched = false) {
  const terms = form.elements.terms.value;
  const host = form.querySelector("#photo-results");
  const picker = form.querySelector("#build-photo-picker");
  const request = String(Number(host.dataset.request || 0) + 1);
  host.dataset.request = request;
  photoMode(form, false);
  picker.replaceChildren();
  host.innerHTML = '<p class="inline-hint">正在核对配图…</p>';
  const result = await post("gallery-preview", { terms, offset, unmatched });
  if (!form.isConnected || !$("#dialog").open || host.dataset.request !== request) return;
  if (form.elements.terms.value !== terms) {
    host.textContent = "词表已修改，点「检查配图」重新核对。";
    return;
  }
  if (offset && !result.rows.length) {
    const visible = result.total - (unmatched ? result.matched : 0);
    return previewPhotos(form, Math.floor(Math.max(0, visible - 1) / 100) * 100, unmatched);
  }
  host.dataset.offset = String(offset);
  host.dataset.unmatched = unmatched ? "1" : "0";
  const pageButton = (label, start) => btn("buildPhotoPage", label, "secondary",
    'data-offset="' + start + '" data-unmatched="' + (unmatched ? "1" : "0") + '"');
  const counts = Object.entries(photoStatus).map(([status, label]) =>
    '<span><b>' + fmt(result[status]) + '</b> ' + label + '</span>').join("");
  host.innerHTML =
    '<div class="build-photo-summary"><div>' + counts + '</div>' +
    btn("buildPhotoPage", unmatched ? "查看全部" : "只看未配图", "text-button",
      'data-offset="0" data-unmatched="' + (unmatched ? "0" : "1") + '"') + '</div>' +
    result.rows.map(r =>
      '<div class="match-row">' +
      (r.first ? '<img loading="lazy" src="' + photoUrl(r.first.id, {preview:1}) + '" alt="">' : '') +
      '<span>' + esc(r.term) + '</span><small>' +
      (r.count ? fmt(r.count) + ' 张' : photoStatus[r.status]) + '</small>' +
      (r.status !== "excluded" ?
        btn("buildPhotoPick", r.count ? "管理配图" : r.status === "absent" ? "查找候选图" : "从图库选图", "secondary",
          'data-term="' + esc(r.term) + '"') : '') + '</div>').join("") +
    (result.rows.length ? '' : '<p class="inline-hint">这批词都已配图。</p>') +
    (offset || result.more ? '<div class="button-line">' +
      (offset ? pageButton("上一页", Math.max(0, offset - 100)) : '') +
      (result.more ? pageButton("下一页", offset + 100) : '') + '</div>' : '');
}

async function pickBuildPhoto(form, term, options = {}) {
  const {category = "", query = "", offset = 0, browse = false} = options;
  const host = form.querySelector("#build-photo-picker");
  const request = String(Number(host.dataset.request || 0) + 1);
  host.dataset.request = request;
  host.dataset.term = term;
  host.dataset.browse = browse ? "1" : "0";
  photoMode(form, true);
  $("#dialog").scrollTop = 0;
  host.innerHTML = '<div class="button-line">' +
    btn("buildPhotoBack", "← 返回配图清单", "text-button") +
    '</div><h3>' + esc(term) + '</h3><p class="inline-hint">正在查找产品图…</p>';
  const found = await get("gallery-suggest", {term, category, query, offset, browse:browse ? "1" : ""});
  if (!form.isConnected || !$("#dialog").open || host.hidden || host.dataset.request !== request) return;
  const canLink = found.status === "unmatched" || found.status === "matched";
  const pageButton = (label, start) => btn("buildPhotoFind", label, "secondary", 'data-offset="' + start + '"');
  const listed = found.rows.map(photo => {
    const data = 'data-id="' + photo.id + '"';
    let controls = "";
    if (canLink) {
      controls = photo.cover ? '<b class="photo-current-cover">当前首图</b>' :
        btn("buildPhotoLink", photo.linked ? "设为首图" : "选用这张图", "secondary",
          data + (photo.linked ? ' data-cover="1"' : ''));
      if (!photo.linked) {
        controls += btn("buildPhotoLink", "作为首图", "text-button", data + ' data-cover="1"');
      }
    }
    return '<article class="build-photo-candidate">' +
      '<img loading="lazy" src="' + photoUrl(photo.id, {preview:1}) + '" alt="' + esc(photo.filename) + '">' +
      '<div><b>' + esc(photo.filename) + '</b><small>' + esc(photo.category) +
      ' · ' + esc(photo.reason) + '</small>' +
      '<div class="button-line">' + controls +
      ' <a class="text-button" download href="' + photoUrl(photo.id, {download:1}) + '">下载原图</a></div></div></article>';
  }).join("");
  host.innerHTML = '<div class="button-line">' + btn("buildPhotoBack", "← 返回配图清单", "text-button") +
    '</div><h3>' + esc(term) + '</h3>' +
    '<p class="inline-hint">' + (canLink
      ? "确认图片与关键词相符后，再选用图片。首图会排在配图包的第一张。"
      : photoStatus[found.status] + "。可查看或下载候选原图。关键词可用后即可保存配图。") + '</p>' +
    '<div class="build-photo-search"><label class="field">产品分类<select id="build-photo-category">' +
    option("", "全部分类", category) + found.categories.map(name => option(name, name, category)).join("") +
    '</select></label><label class="field">文件名或型号<input id="build-photo-query" maxlength="180" value="' +
    esc(query) + '"></label>' + btn("buildPhotoFind", "搜索图库") + '</div>' +
    (listed ? '<p class="inline-hint">' + (category || query || browse ? "可选图片" : "建议先看") +
      ' · ' + fmt(found.total) + ' 张</p><div class="build-photo-candidates">' + listed + '</div>' :
      '<p class="inline-hint">暂时没有符合条件的照片。可以选分类或搜索文件名。</p>' +
      (!category && !query && !browse ? btn("buildPhotoBrowse", "浏览全部可用产品图") : '')) +
    (offset || found.more ? '<div class="button-line">' +
      (offset ? pageButton("上一页", Math.max(0, offset - 16)) : '') +
      (found.more ? pageButton("下一页", offset + 16) : '') + '</div>' : '');
}

async function buildPhotoAction(action, button) {
  const form = button.closest("#build-photo-form");
  const picker = form.querySelector("#build-photo-picker");
  const results = form.querySelector("#photo-results");
  if (action === "previewPhotos") return previewPhotos(form);
  if (action === "buildPhotoPage") {
    return previewPhotos(form, Number(button.dataset.offset), button.dataset.unmatched === "1");
  }
  if (action === "buildPhotoPick") return pickBuildPhoto(form, button.dataset.term);
  if (action === "buildPhotoBack") {
    photoMode(form, false);
    picker.replaceChildren();
    return;
  }
  if (action === "buildPhotoLink") {
    button.disabled = true;
    try {
      await post("gallery-build-link", {
        term:picker.dataset.term, id:Number(button.dataset.id), cover:button.dataset.cover === "1",
      });
      if (form.isConnected && $("#dialog").open) {
        toast(button.dataset.cover ? "首图已更新" : "已保存到配图清单");
        await previewPhotos(form, Number(results.dataset.offset), results.dataset.unmatched === "1");
      }
    } finally {
      button.disabled = false;
    }
    return;
  }
  return pickBuildPhoto(form, picker.dataset.term, {
    category:form.querySelector("#build-photo-category").value,
    query:form.querySelector("#build-photo-query").value,
    offset:Number(button.dataset.offset || 0),
    browse:action === "buildPhotoBrowse" || picker.dataset.browse === "1",
  });
}

document.addEventListener("keydown", event => {
  if (event.key === "Enter" && event.target.id === "build-photo-query" && !event.isComposing) {
    event.preventDefault();
    event.target.closest("#build-photo-form").querySelector(".build-photo-search button").click();
  }
});

function sourceSummary(items, positiveOnly = false) {
  if (!items.length) return "";
  const note = positiveOnly
    ? "每家同行显示最近一条自然流量大于 0 的来源记录。"
    : "同一同行、同一市场内，按报告日期取最近的非空值。缺少报告日期时采用导入日期。原始各行记录在下方。";
  return (
    '<section class="detail-section"><h3>各同行最新数据</h3><p class="inline-hint">' + note + '</p>' +
    table(
      ["同行 / 市场", "最近记录", "自然流量", "DR", "排名网址"],
      items
        .slice(0, 100)
        .map(
          (r) =>
            "<tr><td>" +
            esc(
              [r.domain, r.market].filter(Boolean).join(" / ") || "未列来源",
            ) +
            "</td><td>" +
            esc(r.sort_day) +
            "</td><td>" +
            esc(r.traffic ?? "—") +
            "</td><td>" +
            esc(r.dr ?? "—") +
            "</td><td>" +
            safeLink(r.url, r.url || "—") +
            "</td></tr>",
        )
        .join(""),
    ) +
    (items.length > 100
      ? "<p>这里显示最近 100 组，全部来源可通过来源明细导出。</p>"
      : "") +
    "</section>"
  );
}

function typeList() {
  return [
    ...(opt.types || []),
    { id: 0, name: "待归类" },
    { id: -1, name: "待确认" },
  ];
}
function typeName(id) {
  return typeList().find((t) => Number(t.id) === Number(id))?.name || "待归类";
}
function wordTypeForm(w) {
  return (
    '<form class="type-assign" data-form="assignType" data-id="' +
    w.id +
    '"><label class="field">产品类型<select name="type">' +
    option(
      "auto",
      "自动归类 · " + (w.type_manual ? "重新判断" : typeName(w.product_type)),
      w.type_manual ? "" : "auto",
    ) +
    typeList()
      .map((t) => option(t.id, t.name, w.type_manual ? w.product_type : ""))
      .join("") +
    '</select></label><button class="secondary">保存类型</button></form>'
  );
}
function typeBatchForm() {
  const ids = [...selection];
  dialog("批量归类关键词", '<form data-form="typeBatch" class="form-grid">' +
    '<label class="field">归类范围<select name="scope">' +
    (ids.length ? option("selected", "已勾选的 " + fmt(ids.length) + " 个词", "selected") : "") +
    option("filtered", "当前筛选的全部结果", ids.length ? "" : "filtered") +
    '</select></label><label class="field">归到<select name="type" required>' +
    option("", "选择产品类型", "") + typeList().map(t => option(t.id,t.name,"")).join("") +
    option("auto", "恢复自动归类", "") + '</select></label>' +
    '<label class="batch-type-preserve"><input type="checkbox" name="preserve" checked> 保留已手动归类的词</label>' +
    '<div class="batch-type-actions"><button class="secondary" type="submit" value="preview">预览影响</button></div>' +
    '<div class="field full" data-batch-type-preview aria-live="polite"></div></form>');
  const form = $('[data-form="typeBatch"]');
  form.dataset.scope = JSON.stringify({ids, filters:{...filt}});
  form.addEventListener("change", () => {
    form.dataset.preview = "";
    form.querySelector("[data-batch-type-preview]").innerHTML = "";
  });
}

async function submitTypeBatch(form, values, button) {
  if (!button || button.disabled) return;
  const scope = JSON.parse(form.dataset.scope);
  const apply = button.value === "apply";
  if (apply && !form.dataset.preview) return;
  const params = {
    scope:values.scope, type:values.type, preserve:values.preserve === "on",
    ...(values.scope === "selected" ? {ids:scope.ids} : {filters:scope.filters}),
    ...(apply ? {preview:form.dataset.preview} : {}),
  };
  const controls = Array.from(form.elements);
  controls.forEach(control => { control.disabled = true; });
  if (apply) modalBusy = true;
  try {
    const result = await post("type-batch", params);
    if (!form.isConnected) return;
    if (apply) {
      selection.clear();
      paging = [0];
      modalBusy = false;
      close();
      await load();
      return toast("已更新 " + fmt(result.changed) + " 个关键词的产品类型");
    }
    form.dataset.preview = result.preview;
    const sample = result.sample.map(item =>
      '<li><strong>' + esc(item.term) + '</strong><small>' + esc(typeName(item.old_type)) +
      ' → ' + esc(typeName(item.next_type)) + '</small></li>').join("");
    form.querySelector("[data-batch-type-preview]").innerHTML =
      '<p><strong>' + esc(result.label) + '</strong> · 范围内 ' + fmt(result.total) +
      ' 个词，预计更新 ' + fmt(result.changed) + ' 个' +
      (result.held ? '，保留 ' + fmt(result.held) + ' 个手动分类' : '') + '。</p>' +
      (sample ? '<ul class="batch-type-sample">' + sample + '</ul><button class="primary" type="submit" value="apply">确认归类</button>' : "");
  } catch (error) {
    if (form.isConnected) {
      form.dataset.preview = "";
      form.querySelector("[data-batch-type-preview]").innerHTML = "";
    }
    throw error;
  } finally {
    if (apply) modalBusy = false;
    controls.forEach(control => { control.disabled = false; });
  }
}

function typeOverview(groups) {
  return (
    toolRow() +
    table(
      ["产品类型", "关键词数", "识别词", ""],
      groups
        .map(
          (g) =>
            "<tr><td>" +
            btn(
              "typeWords",
              esc(g.name),
              "record-name",
              'data-id="' + g.id + '"',
            ) +
            "</td><td>" +
            fmt(g.count) +
            "</td><td>" +
            esc(
              g.id === 0
                ? "没有命中识别词"
                : g.id === -1
                  ? "命中多个类型或词义可能有歧义"
                  : g.phrases.slice(0, 6).join(" · ") || "沿用同名原分类",
            ) +
            "</td><td>" +
            (g.id > 0
              ? btn("editType", "编辑", "text-button", 'data-id="' + g.id + '"')
              : "") +
            "</td></tr>",
        )
        .join(""),
    )
  );
}

function typeReviewLabel(key) {
  if (key === "manual") return "手动标为待确认";
  if (key === "box") return "箱盒词义待核对";
  if (key === "other") return "其他待确认词";
  return key.slice(6).split(",").map(typeName).join(" ＋ ");
}

async function showTypeReview() {
  const currentView = view;
  const result = await get("type-review");
  if (view !== currentView) return;
  const items = result.items.map(item =>
    '<article class="project-search-record"><div><h3>' + esc(typeReviewLabel(item.key)) + '</h3>' +
    '<small>' + fmt(item.count) + ' 个词</small><p>' + item.examples.map(esc).join(" · ") + '</p></div>' +
    '<a class="secondary" href="#words/review/' + encodeURIComponent(item.key) + '">查看这组词</a></article>'
  ).join("");
  dialog("复核待确认", result.total
    ? '<p class="inline-hint">当前行业有 ' + fmt(result.total) +
      ' 个待确认的在库词。打开一组后，可以逐词核对或批量归类。</p>' + items
    : '<p>当前行业没有待确认的在库词。</p>');
}

let typeSuggestionFilters = {};

async function showTypeSuggestions(values = typeSuggestionFilters, source) {
  const params = {q: String(values.q || "").trim(), category:values.category || ""};
  const result = await get("type-suggestions", params);
  if (view !== "types" || (source && !source.isConnected)) return;
  typeSuggestionFilters = params;
  const rows = result.items.map(item => {
    const proof = item.suggested
      ? '已归类样本中 ' + fmt(item.suggested.hits) + '/' + fmt(item.suggested.total) + ' 属于「' + item.suggested.label + '」'
      : "";
    return '<article class="project-search-record"><div><h3>' + esc(item.phrase) + '</h3>' +
      '<small>' + fmt(item.count) + ' 个待归类词包含该短语' + (proof ? ' · ' + esc(proof) : "") + '</small>' +
      '<p>' + item.examples.map(esc).join(" · ") + '</p></div>' +
      btn("chooseTypeSuggestion", "带入规则", "secondary",
        'data-phrase="' + esc(item.phrase) + '" data-id="' + Number(item.suggested?.id || 0) + '"') +
      '</article>';
  }).join("");
  dialog("找识别词建议", '<form class="form-grid" data-form="typeSuggestions">' +
    '<label class="field">搜索词<input name="q" type="search" maxlength="200" value="' + esc(params.q) +
    '" placeholder="例如蜂窝纸或 wrapping"></label>' +
    '<label class="field">来源分类<select name="category">' + option("", "全部原表分类", params.category) +
    opt.categories.map(name => option(name,name,params.category)).join("") + '</select></label>' +
    '<div class="batch-type-actions"><button class="secondary" type="submit">找词组</button></div></form>' +
    '<p class="inline-hint">扫描了 ' + fmt(result.sampled) + ' 个待归类词' +
    (result.bounded ? '的最近样本' : '') + '。选中词组后，可以在规则预览里核对全库会怎样变化。</p>' +
    (rows || '<p>这次筛选下没有找到重复词组。可以试试其他搜索词或原表分类。</p>'));
}

function chooseTypeSuggestion(button) {
  const phrase = button.dataset.phrase;
  const known = opt.types || [];
  dialog("带入识别词", '<form class="form-grid" data-form="useTypeSuggestion" data-phrase="' + esc(phrase) + '">' +
    '<p class="field full"><strong>' + esc(phrase) + '</strong></p>' +
    '<label class="field full">产品类型<select name="type" required>' +
    (known.length ? option("", "选择产品类型", "") : "") +
    known.map(item => option(item.id, item.name, button.dataset.id)).join("") +
    option("0", "新建产品类型", known.length ? "" : "0") +
    '</select></label><div class="batch-type-actions step-actions"><button class="primary" type="submit">进入规则编辑</button>' +
    btn("typeSuggestions","返回词组建议","text-button") + '</div></form>');
}

function typeForm(id, phrase = "") {
  const item = (opt.types || []).find((t) => t.id === id) || {
    id: 0,
    name: "",
    phrases: [],
  };
  const phrases = [...new Set([...item.phrases, ...(phrase ? [phrase] : [])])];
  dialog(
    item.id ? "编辑产品类型" : "添加产品类型",
    '<form data-form="saveType" data-id="' +
      item.id +
      '" class="form-grid"><label class="field full">类型名称<input name="name" maxlength="60" required value="' +
      esc(item.name) +
      '"></label>' +
      '<label class="field full">识别词，每行一个<textarea name="phrases" rows="7" placeholder="pouch">' +
      esc(phrases.join("\n")) +
      "</textarea></label>" +
      '<p class="inline-hint full">保存后，新词会沿用这套规则。预览会列出已有词的变化，手动归类仍优先。</p>' +
      '<div class="batch-type-actions step-actions"><button class="secondary" type="submit" value="preview">预览规则影响</button>' +
      (phrase ? btn("typeSuggestions","返回词组建议","text-button") : "") + '</div>' +
      '<div class="field full" data-type-rule-preview aria-live="polite"></div></form>',
  );
  const form = $('[data-form="saveType"]');
  form.addEventListener("input", () => {
    form.dataset.preview = "";
    form.querySelector("[data-type-rule-preview]").innerHTML = "";
  });
}

async function submitTypeRule(form, values, button) {
  if (!button || button.disabled) return;
  const apply = button.value === "apply";
  if (apply && !form.dataset.preview) return;
  const controls = Array.from(form.elements);
  controls.forEach(control => { control.disabled = true; });
  const payload = {...values, id:form.dataset.id};
  if (apply) modalBusy = true;
  try {
    const result = await post(apply ? "type-save" : "type-preview",
      apply ? {...payload, preview:form.dataset.preview} : payload);
    if (!form.isConnected) return;
    if (apply) {
      modalBusy = false;
      close();
      await refreshMeta();
      await load();
      return toast("规则已保存，已更新 " + fmt(result.changed) + " 个词的产品类型");
    }
    form.dataset.preview = result.preview;
    const examples = result.sample.map(item =>
      '<li><div><strong>' + esc(item.term) + '</strong><br><small>' + esc(item.reason) +
      '</small></div><small>' + esc(item.before) + ' → ' + esc(item.after) + '</small></li>').join("");
    const summary = ["预计更新 " + fmt(result.changed) + " 个词",
      ...(result.entering ? ["归入「" + result.label + "」" + fmt(result.entering) + " 个"] : []),
      ...(result.leaving ? ["移出「" + result.label + "」" + fmt(result.leaving) + " 个"] : []),
      ...(result.review ? [fmt(result.review) + " 个会转入待确认"] : []),
      ...(result.manual ? ["保留 " + fmt(result.manual) + " 个手动分类"] : [])];
    form.querySelector("[data-type-rule-preview]").innerHTML = '<p>' + summary.map(esc).join(" · ") + '</p>' +
      (examples ? '<ul class="batch-type-sample">' + examples + '</ul>' : "") +
      '<button class="primary" type="submit" value="apply">确认保存规则</button>';
  } catch (error) {
    if (form.isConnected) {
      form.dataset.preview = "";
      form.querySelector("[data-type-rule-preview]").innerHTML = "";
    }
    throw error;
  } finally {
    if (apply) modalBusy = false;
    controls.forEach(control => { control.disabled = false; });
  }
}
function newWord() {
  dialog(
    "添加关键词",
    '<form data-form="word" class="form-grid">' +
      field("term", "关键词", "只填关键词即可", true) +
      field("category", "分类") +
      field("url", "来源网址", "可选") +
      field("notes", "备注") +
      '<div class="field full"><button class="primary">保存并查重</button></div></form>',
  );
}
function siteChoices(query = "") {
  const looking = query.trim().toLowerCase();
  return (
    btn("useSite", "全部同行", "text-button") +
    opt.sites
      .filter((x) => (x.domain + " " + x.name).toLowerCase().includes(looking))
      .slice(0, 30)
      .map(
        (x) =>
          "<div>" +
          btn(
            "useSite",
            esc(x.name + " · " + x.domain),
            "text-button",
            'data-id="' + x.id + '"',
          ) +
          "</div>",
      )
      .join("")
  );
}
function newSite() {
  dialog(
    "添加同行",
    '<form data-form="site" class="form-grid">' +
      field("url", "官网域名或网址", "例如 example.com", true) +
      field("name", "企业或品牌") +
      channelField("audience", "客户类型") +
      field("region", "地区") +
      field("products", "产品") +
      '<button class="primary">保存并查重</button></form>',
  );
}
function exportBox() {
  const q = { ...filt };
  const scope = [industryName, q.market && marketLabel(q.market), q.q].filter(Boolean).join(" · ");
  dialog(
    "导出当前筛选结果",
    '<p>' + esc(scope) + '</p><p>可把去重词表和来源明细一起打包。生成时可以继续查词。</p>' +
    '<div class="section-actions">' + btn("export-filtered", "打包两份 CSV", "primary",
      'data-filters="' + esc(JSON.stringify(q)) + '"') +
    '<a class="secondary" href="/api/export?' +
      esc(qs({ ...q, kind: "evidence" })) +
      '">只下载来源明细</a><a class="secondary" href="/api/export?' +
      esc(qs(q)) +
      '">只下载去重词表</a></div><p class="inline-hint">原 Excel 可在「导入记录」下载。</p><hr>' +
      btn("export-backup-center", "备份与换机"),
  );
}
function batchMark() {
  dialog(
    "批量标记",
    '<form data-form="group" class="form-grid"><label class="field">范围<select name="scope">' +
      (selection.size
        ? option("selected", "已勾选的 " + selection.size + " 个词", "selected")
        : "") +
      option("filter", "全部当前筛选结果", selection.size ? "" : "filter") +
      '</select></label><label class="field">标记为<select name="state">' +
      option(1, "保留", 1) +
      option(2, "排除", 1) +
      option(0, "待筛选", 1) +
      '</select></label><div class="field full"><button class="primary">预览影响范围</button></div></form><div id="confirmarea"></div>',
  );
}
const siteLabels = {
  url: "官网或域名（必选）",
  name: "企业名称",
  audience: "B2B / B2C 类型",
  region: "地区",
  products: "产品",
  notes: "备注",
};
const labels = {
  word: "关键词（必选）",
  url: "排名网址",
  site: "同行域名",
  traffic: "自然流量",
  dr: "DR（域名评级）",
  volume: "搜索量",
  position: "排名",
  market: "市场 / 数据库",
  date: "报告日期",
};
function uploadBox(targetIndustry = 0, replaces = "") {
  const initial = targetIndustry || (
    view === "home" ? homeImportIndustry || industryId :
    view === "imports" ? Number(filt.scope) || industryId : industryId);
  const picker =
    '<label class="field import-target">导入到哪个行业<select id="import-industry"' +
    (replaces ? " disabled" : "") + ">" +
    knownIndustries.map((i) => option(i.id, i.name, initial)).join("") +
    "</select></label>";
  dialog(
    replaces ? "补传正确的表格" : "批量导入",
    picker +
      '<label class="drop" id="batch-drop" data-replaces="' + esc(replaces) + '"><b>' +
      (replaces ? "选择重新导出的文件，或拖到这里" : "选择多个文件，或拖到这里") +
      '</b><span>' + (replaces ? "" : "关键词表和同行名单可以一起选。") +
      '支持 XLSX、CSV、TSV。</span><input id="files" type="file"' +
      (replaces ? "" : " multiple") + ' accept=".csv,.tsv,.txt,.xlsx"></label>' +
      (replaces ? '<p class="inline-hint">补传文件入库后，原记录会标记为已补传。</p>' :
        '<p class="inline-hint">每张表自动识别字段，归入当前行业。完全相同的词合并，来源、流量、DR 和网址按原表保存。</p><details><summary>特殊表格手动匹配</summary><div class="step-actions">' +
        btn("manualWords", "手动导入关键词表", "text-button") +
        btn("manualSites", "手动导入网站表", "text-button") +
        "</div></details>"),
  );
}

function importBatchUrl(batch, industry, words, scope = "") {
  return "/?" + qs({industry, section:1}) + "#" + (words ? "words" : "sites") +
    "/batch/" + Number(batch.id) + (scope ? "/" + scope : "");
}

function importWordBatchSummary(batch) {
  const parts = ["新增 " + fmt(batch.added) + " 个词"];
  if (batch.distinct_words != null) {
    parts.push("已有 " + fmt(batch.distinct_words - batch.added) + " 个词");
    const repeated = batch.written - batch.distinct_words;
    if (repeated) parts.push("表内同词多出 " + fmt(repeated) + " 条记录");
  }
  parts.push("保存 " + fmt(batch.written) + " 条来源记录");
  if (batch.source_sites) {
    parts.push(fmt(batch.source_rows) + " 条关联 " + fmt(batch.source_sites) + " 家同行");
  }
  if (batch.unlinked_rows) parts.push(fmt(batch.unlinked_rows) + " 条未关联同行");
  if (batch.blank) parts.push("跳过 " + fmt(batch.blank) + " 行");
  return parts.join(" · ");
}

function importBatchLinks(batch, industry, words) {
  const link = (label, scope = "") => '<a href="' + esc(importBatchUrl(batch, industry, words, scope)) +
    '">' + label + '</a>';
  return '<div class="step-actions import-batch-links">' + link(words ? "查看这批词" : "查看这批同行") +
    (words && batch.prior_word_id != null
      ? (batch.added > 0 ? link("查看新增词", "new") : "") +
        (batch.distinct_words > batch.added ? link("查看已有词", "existing") : "")
      : "") +
    (words && batch.source_sites
      ? '<a href="' + esc(importBatchUrl(batch, industry, false)) + '">查看来源同行</a>'
      : "") + '</div>';
}

function importResultDetails(item, industry, showDownload = false) {
  const run = item.id || "";
  const target = 'data-run="' + esc(run) + '" data-industry="' + Number(industry) + '" data-filename="' + esc(item.filename) + '"';
  const unfinished = item.state === "error" || item.state === "interrupted";
  const replacement = item.replacement_file;
  const result = item.sheets.map(row => {
    const words = row.kind === "words";
    const summary = words ? importWordBatchSummary(row) :
      "同行网站 · 新增 " + fmt(row.added) + "，已有或表内重复 " + fmt(row.site_valid - row.added) +
      (row.inferred_sites ? "，为 " + fmt(row.inferred_sites) + " 家按名单标注客户类型" : "") +
      (row.blank ? "，空白或无效 " + fmt(row.blank) + " 行" : "");
    const message = row.empty ? "空表已跳过" : row.error || row.reference ||
      (row.duplicate ? "本次沿用原批次 · " : "") + summary;
    const defaults = [row.market, row.report_date].filter(Boolean).join(" · ");
    const action = row.replace_file
      ? (item.state === "replaced" ? "" : btn("replaceImportFile", "重新上传文件", "secondary",
          target + (item.state === "needs_file" ? ' data-replace="1"' : "")))
      : row.error ? (row.empty || !run ? "" : btn("reviewSavedImport", "调整字段", "secondary", target +
          ' data-sheet="' + esc(row.sheet) + '" data-kind="' + (row.kind === "sites" ? "sites" : "words") + '"'))
      : row.id ? importBatchLinks(row, industry, words) : "";
    return '<li><div>' + (row.sheet ? '<strong>' + esc(row.sheet) + '</strong>' : "") + '<p>' + esc(message) +
      '</p>' + (words && !row.error && defaults ? '<p>源表缺项时使用 ' + esc(defaults) + '</p>' : "") +
      '</div>' + action + '</li>';
  }).join("");
  return (replacement ? '<p>已补传 ' + esc(replacement.filename) + '</p>' +
    btn("openReplacementFile", "查看补传结果", "secondary",
      'data-industry="' + industry + '" data-key="' + esc(replacement.digest) + '"') : "") +
    (item.error ? '<p class="notice">' + esc(item.error) + '</p>' : "") +
    (result ? '<ul>' + result + '</ul>' : "") + '<div class="step-actions">' +
    (showDownload && run ? '<a download href="/api/import-original?' + esc(qs({industry, run})) + '">下载原文件</a>' : "") +
    (run && unfinished ? btn("retrySavedImport", "继续导入", "secondary", target) : "") +
    '</div>';
}

function importResultCard(item, industry, expand = false) {
  const trouble = item.sheets.filter(row=>row.error && !row.empty).length;
  const replace = item.sheets.some(row => row.replace_file);
  const replaced = item.state === "replaced";
  const pending = !replaced && (item.state !== "done" || trouble);
  return '<details class="import-file-result"' + (pending || expand ? " open" : "") + '><summary><strong>' +
    esc(item.filename) + '</strong><span>' + (replaced ? "已补传" : replace ? "需更换文件" : trouble ? fmt(trouble) + " 张表待处理" :
      pending ? "尚未完成" : "已处理") + '</span></summary>' +
    importResultDetails(item, industry, true) + '</details>';
}

async function waitImportJob(id, industry, progress, observation) {
  for (;;) {
    const state = await get("jobs", {id, industry});
    if (state.status === "done" || state.status === "error") return state;
    const text = state.status === "queued" ? "排队中" : "已读取 " + fmt(state.count) + " 行";
    if (!observation?.detached && $("#progress")) $("#progress").textContent = progress + text;
    await new Promise(resolve => setTimeout(resolve, 400));
  }
}

function importJobReport(file, state, run) {
  return {
    id:state.result?.run || run || "", filename:file,
    state:state.result?.state || state.status, error:state.status === "error" ? state.error : "",
    sheets:state.result?.sheets || [],
    replacement_file:state.result?.replacement_file,
  };
}

function showImportResult(report, industry, name) {
  const route = importHistoryRoute({find: report.length === 1 ? report[0].filename : ""});
  dialog("批量导入结果",
    '<p>目标行业 <strong>' + esc(name) + '</strong></p>' +
    report.map(item=>importResultCard(item, industry, report.length <= 4)).join("") +
    '<div class="section-actions"><a class="primary" href="/?' +
    esc(qs({industry, section:1}) + route) + '">查看导入记录</a></div>');
}

async function importReview(context, skip = 0) {
  const preview = await post("import-review", {run:context.run, sheet:context.sheet, kind:context.kind, skip},
    {industry:context.industry});
  importReviewState = {...context, skip, preview};
  reviewFields();
}

function reviewFields() {
  const {kind, sheet, skip, preview} = importReviewState;
  const heads = kind === "sites" ? preview.siteHeaders : preview.headers;
  const mapping = kind === "sites" ? preview.siteMapping : preview.mapping;
  dialog("调整这张表的导入字段", '<p><strong>' + esc(preview.name) + '</strong>' +
    (sheet ? " · " + esc(sheet) : "") + '</p>' +
    '<form data-form="saved-import"><div class="form-grid"><label class="field">导入类型<select id="saved-import-kind">' +
    option("words", "关键词", kind) + option("sites", "同行网站", kind) + '</select></label>' +
    '<label class="field">表头行<input type="number" name="headerRow" min="1" step="1" required value="' + (skip + 1) +
    '"></label></div><div class="step-actions">' + btn("previewImportHeader", "预览表头", "secondary") +
    '</div><div class="map-grid">' + importColumnFields(kind, heads, mapping) + '</div>' +
    '<div class="form-grid">' + importDefaults(kind) + '</div>' +
    '<p class="inline-hint">首行预览　' + esc((preview.examples[0] || []).slice(0, 5).join("　·　")) +
    '</p><div class="section-actions"><button class="primary">导入这张表</button></div></form>');
}

async function retrySavedImport(context, opts = {}) {
  if (importBusy) return;
  importBusy = true;
  try {
    const job = await post("import-retry", {run:context.run, ...opts}, {industry:context.industry});
    dialog("正在导入", '<p id="progress" role="status">排队中</p>');
    const state = await waitImportJob(job.id, context.industry, "");
    const name = knownIndustries.find(x=>x.id === context.industry)?.name || industryName;
    showImportResult([importJobReport(context.preview?.name || context.filename, state, context.run)], context.industry, name);
    if (context.industry === industryId) {
      if (view === "home" || view === "sites") metaReady = false;
      else await refreshMeta();
    }
    await load();
  } finally {
    importBusy = false;
  }
}

document.addEventListener("dragover", (e) => {
  if (e.target.closest("#batch-drop")) e.preventDefault();
});
document.addEventListener("drop", (e) => {
  if (!e.target.closest("#batch-drop")) return;
  e.preventDefault();
  autoFiles(Array.from(e.dataTransfer.files)).catch(failure);
});
async function autoFiles(files) {
  if (importBusy || !files.length) return;
  const replaces = $("#batch-drop").dataset.replaces;
  if (replaces && files.length !== 1) throw Error("请只选择一份补传文件。");
  const target = knownIndustries.find(
    (i) => i.id === Number($("#import-industry").value),
  );
  if (!target) throw Error("请选择目标行业。");
  importBusy = true;
  const observation = {detached:false};
  const uploaded = [];
  try {
    for (const [i, file] of files.entries()) {
      dialog(
        target.name + " · 正在上传文件",
        '<div class="detail-item"><strong>' +
          esc(file.name) +
          '</strong><p id="progress" role="status">第 ' +
          (i + 1) +
          " / " +
          files.length +
          " 个文件</p></div>",
      );
      try {
        const job = await fetch(
          "/api/auto-import?" +
            qs({ filename: file.name, industry: target.id, replaces }),
          { method: "POST", body: file },
        ).then(check);
        uploaded.push({name:file.name, job});
      } catch (err) {
        uploaded.push({name:file.name, error:err.message});
      }
    }
    observedImport = observation;
    const failed = uploaded.filter(item=>!item.job);
    if (failed.length < uploaded.length) {
      dialog(target.name + " · 正在处理已上传文件",
        '<p id="progress" role="status">正在检查导入结果…</p>' +
        (failed.length ? '<ul>' + failed.map(item=>'<li>' + esc(item.name + " · " + item.error) + '</li>').join("") + '</ul>' : "") +
        '<div class="step-actions">' + btn("leaveImportRunning", "后台继续", "secondary") + '</div>' +
        '<p class="inline-hint">已上传的文件会继续处理，结果可在导入记录查看。</p>');
    }
    const report = [];
    for (const [i, entry] of uploaded.entries()) {
      const job = entry.job;
      if (!job) {
        report.push(importJobReport(entry.name, {status:"error", error:entry.error}));
        continue;
      }
      try {
        const state = await waitImportJob(job.id, target.id, "第 " + (i + 1) + " / " + files.length + " 个文件 · ", observation);
        const item = importJobReport(entry.name, state, job.run || job.id);
        if (job.duplicate) item.sheets = item.sheets.map(row=>row.error ? row : {...row, duplicate:true});
        report.push(item);
      } catch (err) {
        report.push(importJobReport(entry.name, {status:"error", error:err.message}, job.run || job.id));
      }
    }
    if (observation.detached) {
      if (target.id === industryId) metaReady = false;
      return;
    }
    showImportResult(report, target.id, target.name);
    if (target.id === industryId) {
      if (view === "home" || view === "sites") metaReady = false;
      else await refreshMeta();
    }
    await load();
  } finally {
    if (observedImport === observation) observedImport = null;
    if (!observation.detached) importBusy = false;
  }
}
async function bulkExportBox(ids = [String(industryId)], kinds = Object.keys(exportLabels)) {
  const saved = await get("saved-presets", {scope: "export"});
  const checks = (name, value, label, on) =>
    '<label><input type="checkbox" name="' +
    name +
    '" value="' +
    esc(value) +
    '" ' +
    (on ? "checked" : "") +
    "> " +
    esc(label) +
    "</label>";
  dialog(
    "批量导出",
    '<div class="step-actions">' + btn("export-history", "查看导出记录", "text-button") + '</div>' +
    (saved.length ? '<h3>常用导出方案</h3>' + presetRows(saved, "export") : "") +
    '<form data-form="bulk-export" class="bulk-form"><fieldset><legend>选择行业</legend>' +
      knownIndustries
        .map((i) => checks("industry", i.id, i.name, ids.includes(String(i.id))))
        .join("") +
      "</fieldset><fieldset><legend>选择资料</legend>" +
      Object.entries(exportLabels)
        .map(([k, v]) => checks("kind", k, v, kinds.includes(k)))
        .join("") +
      '</fieldset><p class="inline-hint">每个行业单独一个文件夹。CSV 包含所有筛选状态，AI 用的词表自动跳过已排除词。</p><button class="primary">后台生成 ZIP</button>' +
      '<details class="preset-save"><summary>将当前勾选保存为常用方案</summary>' +
      presetName("例如：每周 AI 建站资料") + '<button name="intent" value="save" class="secondary">保存导出方案</button></details></form>',
  );
}
async function aiConnection() {
  return codexConnectionDialog(await get("codex-status"));
}

function codexConnectionDialog(data) {
  const states = {
    missing: ["本机尚未连接", "连接这台电脑的 Codex", "连接后可在 Codex 里读取词库、建站进度、技能包和产品图库。"],
    ready: ["本机读取测试已通过", "", "共读到 " + fmt(data.industryCount) + " 个行业。打开新的 Codex 对话后，可用 industry-keywords 查词，也可以从跨行业图库复制找图指令。"],
    stale: ["连接路径或版本需要更新", "更新本机连接", "更新后，Codex 会用当前版本读取这份资料库。"],
    different: ["本机连接指向另一份资料库", "切换到当前资料库", "切换后，新的 Codex 对话可以从这份资料库取词。"],
    disabled: ["本机连接已停用", "启用连接", "启用后会检查当前资料库是否可读。"],
    invalid: ["配置文件需要核对", "", "可以复制下方配置，在 Codex 的 MCP 设置里检查。"],
    custom: ["此名称已有自定义连接", "", "可以复制下方的本机配置，在 Codex 设置里核对。"],
    failed: ["已找到连接，读取测试未通过", "", "重新打开软件后，可以再次检查这份资料库。"],
    limited: ["词库可读，Codex 的取词工具受设置限制", "", "在 Codex 的 MCP 设置里核对已启用的工具。"],
  };
  const [title, action, help] = states[data.state];
  const paths = data.state === "different" ? '<p class="inline-hint">Codex 当前连接<br><code>' +
    esc(data.configured) + '</code></p>' : "";
  dialog(
    "连接本机 Codex",
    '<section class="codex-connection-state"><h3>' + esc(title) + '</h3><p>' + esc(help) + '</p>' +
      '<p class="inline-hint">当前资料库<br><code>' + esc(data.current) + '</code></p>' + paths +
      '<div class="step-actions">' +
      (action ? btn("bank-connect",action,"primary",
        data.state === "different" ? 'data-switch-from="' + esc(data.configured) + '"' : "") : "") +
      btn("aiConnection", "重新检查", "secondary") + '</div></section>' +
      '<details><summary>手动配置</summary><label class="field">本机连接配置<textarea readonly rows="8" id="ai-config" class="connection-config">' +
      esc(JSON.stringify(data.config, null, 2)) + '</textarea></label>' +
      btn("copyAI", "复制配置", "secondary") + '</details>',
  );
}

function manualBox(kind = "words") {
  fileKind = kind;
  dialog(
    industryName +
      " · " +
      (fileKind === "sites" ? "导入同行网站" : "导入关键词"),
    '<label class="drop"><b>选择一个或多个导出文件</b><span>支持 CSV、TSV 和 XLSX。原表会保存在库内。</span><input id="manual-files" type="file" multiple accept=".csv,.tsv,.txt,.xlsx"></label><p class="inline-hint">' +
      (fileKind === "sites"
        ? "每行一个官网或域名，可带公司名、B2B / B2C 类型及产品。也可在下一步为整份清单选择类型。"
        : "同一行业内只合并原文完全一致的关键词。词序、拼写、大小写或空格不同均分别保留。排名网址或域名可关联到同行。") +
      "</p>",
  );
}
function mapForm(p) {
  const heads = fileKind === "sites" ? p.siteHeaders || p.headers : p.headers,
    m = fileKind === "sites" ? p.siteMapping : p.mapping;
  dialog(
    "核对导入字段",
    "<p><b>" +
      esc(staged.name) +
      "</b> · 已选 " +
      uploads.length +
      " 个文件</p>" +
      (p.sheets.length > 1
        ? '<label class="field">Excel 工作表<select id="worksheet">' +
          p.sheets
            .map((n) => option(n, n, staged.sheet || p.sheets[0]))
            .join("") +
          "</select></label>"
        : "") +
      '<form data-form="import"><div class="map-grid">' +
      importColumnFields(fileKind, heads, m) +
      '</div><div class="form-grid">' +
      importDefaults(fileKind) +
      '</div><p class="inline-hint">完全相同的文件和导入设置只记一次。各行已有来源或类型时，会保留并归入当前行业。</p><p class="inline-hint">首行预览　' +
      esc((p.examples[0] || []).slice(0, 5).join("　·　")) +
      '</p><div class="section-actions"><button class="primary">开始导入</button></div></form>',
  );
}
function importColumnFields(kind, heads, mapping) {
  return Object.entries(kind === "sites" ? siteLabels : labels).map(([key, label]) =>
    '<label class="field">' + label + '<select name="' + key + '">' +
    option(-1, "未提供", mapping[key]) +
    heads.map((head, i) => option(i, head || "第 " + (i + 1) + " 列", mapping[key])).join("") +
    '</select></label>'
  ).join("");
}
function importDefaults(kind) {
  return kind === "sites" ? channelField("audience", "缺少类型时使用") :
    field("domain", "统一同行域名（可选）", "留空时从各行网址识别") +
    field("defaultMarket", "缺失市场时填写", "例如 US") +
    field("defaultDate", "缺失报告日期时填写", "例如 2026-11-21");
}
function readImportMapping(form, kind) {
  const mapping = Object.fromEntries(
    Object.keys(kind === "sites" ? siteLabels : labels).map(key => [key, Number(form[key])]),
  );
  if (kind === "sites" && mapping.url < 0) throw Error("请选择官网或域名列。");
  if (kind === "words" && mapping.word < 0) throw Error("请选择关键词列。");
  return mapping;
}
async function stageFile(f) {
  const r = await fetch("/api/stage?" + qs({ filename: f.name }), {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: f,
  });
  return check(r);
}
let summary = [];
async function processFiles(form) {
  if (importBusy) return;
  const mapping = readImportMapping(form, fileKind);
  const first = staged,
    signature = JSON.stringify(first.headers);
  importBusy = true;
  let ok = false;
  try {
    while (uploads.length) {
      const f = uploads[0];
      if (!staged) staged = await stageFile(f);
      if (
        signature !== JSON.stringify(staged.headers) ||
        (staged !== first &&
          ((staged.sheets || []).length > 1 ||
            (fileKind === "sites" && Number(form.audience)) ||
            form.domain ||
            form.defaultMarket ||
            form.defaultDate))
      ) {
        mapForm(staged);
        return;
      }
      dialog(
        "正在导入",
        '<div class="detail-item"><strong>' +
          esc(staged.name) +
          '</strong><p id="progress" role="status">正在排队…</p></div><p class="inline-hint">请保持窗口打开，完成后自动处理下一份。</p>',
      );
      const job = await post("import", {
        token: staged.token,
        kind: fileKind,
        audience: form.audience || "",
        sheet: staged.sheet || "",
        mapping,
        domain: form.domain,
        market: form.defaultMarket,
        date: form.defaultDate,
      });
      staged = null;
      while (true) {
        const j = await get("jobs", { id: job.id });
        if (j.status === "error") throw Error(j.error);
        if (j.status === "done") {
          summary.push({ name: f.name, ...j.result });
          break;
        }
        $("#progress").textContent =
          (j.status === "queued"
            ? "排队中"
            : "已读取 " + fmt(j.count) + " 行") +
          " · 剩余 " +
          uploads.length +
          " 份";
        await new Promise((r) => setTimeout(r, 450));
      }
      uploads.shift();
    }
    ok = true;
  } finally {
    importBusy = false;
    if (ok) {
      if (view === "sites") metaReady = false;
      else await refreshMeta();
      dialog(
        "导入完成",
        '<div class="import-file-result">' + importResultDetails({
          state:"done",
          sheets:summary.map(r => ({...r, sheet:r.name, kind:r.site_valid == null ? "words" : "sites"})),
        }, industryId) + '</div><div class="section-actions">' +
          btn("seeimports", "查看导入记录", "primary") +
          "</div>",
      );
      await load();
    }
  }
}
function ruleBox() {
  activeRule = null;
  dialog(
    "添加排除规则",
    '<form data-form="rule" class="form-grid">' +
      field("phrase", "排除短语", "填写可以明确判定无关的词", true) +
      '<button class="primary">预览匹配结果</button></form><p class="inline-hint">英语按完整词或短语匹配，中文按连续文字匹配；规则对以后导入的词同样生效。</p><div id="confirmarea"></div>',
  );
}
let stagedGroup = null;
document.addEventListener("submit", async (e) => {
  const f = e.target;
  if (!f.dataset.form) return;
  e.preventDefault();
  const v = Object.fromEntries(new FormData(f));
  try {
    if (f.dataset.form.startsWith("build-")) return await submitBuild(f, v);
    if (f.dataset.form === "import-history-filter") return openAppLocation(importHistoryRoute(v));
    if (f.dataset.form === "record-search") return openAppLocation(recordSearchRoute(v));
    if (f.dataset.form === "project-prompt-search")
      return openAppLocation(promptRoute(filt.project, "all", v.find.trim()));
    if (f.dataset.form === "across-gallery") return openAppLocation(acrossGalleryRoute(v));
    if (f.dataset.form === "record-search-resolution") return await submitSearchResolution(f, v);
    if (f.dataset.form === "preset-save") return await savePresetFilter(f, v.name);
    if (f.dataset.form === "typeBatch") return await submitTypeBatch(f, v, e.submitter);
    if (f.dataset.form === "typeSuggestions") return await showTypeSuggestions(v, f);
    if (f.dataset.form === "useTypeSuggestion") return typeForm(Number(v.type), f.dataset.phrase);
    if (f.dataset.form === "saveType") return await submitTypeRule(f, v, e.submitter);
    if (f.dataset.form === "assignType") {
      await post("type-assign", { ...v, id: f.dataset.id });
      await word(f.dataset.id);
      await load();
      toast("已保存产品类型");
      return;
    }
    if (f.dataset.form === "linkPhoto") {
      await post("gallery-change", {
        id: f.dataset.id,
        term: v.term,
        action: "link",
      });
      await photoDetail(f.dataset.id);
      await load();
      return;
    }
    if (f.dataset.form === "industry") {
      const ws = await post("industry", v);
      changeIndustry(ws.id);
      return;
    }
    if (f.dataset.form === "site-channel") {
      await post("site-channel", { id: f.dataset.id, ...v });
      await load();
      await site(Number(f.dataset.id));
      return;
    }
    if (f.dataset.form === "bulk-export") {
      const form = new FormData(f),
        ids = form.getAll("industry"),
        kinds = form.getAll("kind");
      if (!ids.length || !kinds.length)
        throw Error("至少勾选一个行业和一种资料。");
      if (e.submitter?.value === "save") {
        const button = e.submitter;
        button.disabled = true;
        modalBusy = true;
        try {
          await post("saved-presets", {kind: "export", name: v.name, payload: {ids, kinds}});
          await bulkExportBox(ids, kinds);
          toast("已保存常用导出方案");
        } finally {
          modalBusy = false;
          button.disabled = false;
        }
        return;
      }
      return await beginExport(e.submitter, "export-records", {ids, kinds});
    }
    if (f.dataset.form === "import") return await processFiles(v);
    if (f.dataset.form === "saved-import") {
      const {kind, sheet, skip} = importReviewState;
      const header = Number(v.headerRow);
      if (header !== skip + 1) return await importReview(importReviewState, header - 1);
      return await retrySavedImport(importReviewState, {kind,sheet,skip,mapping:readImportMapping(v,kind),
        audience:v.audience || "", domain:v.domain || "", market:v.defaultMarket || "", date:v.defaultDate || ""});
    }
    if (f.dataset.form === "group") {
      const state = Number(v.state);
      const d =
        v.scope === "selected"
          ? {
              count: selection.size,
              examples: shown
                .filter((w) => selection.has(w.id))
                .slice(0, 5)
                .map((w) => w.term),
            }
          : await post("group-preview", { filter: filt, state });
      stagedGroup = {
        scope: v.scope,
        state,
        count: d.count,
        filter: { ...filt },
        ids: [...selection],
      };
      $("#confirmarea").innerHTML =
        '<div class="notice">将 ' +
        fmt(d.count) +
        " 个词标为「" +
        states[state] +
        "」。<p>" +
        esc(d.examples.join("、")) +
        "</p></div>" +
        btn("commitgroup", "确认标记", "primary");
      return;
    }
    if (f.dataset.form === "rule") {
      activeRule = await post("rule-preview", v);
      $("#confirmarea").innerHTML =
        '<div class="notice">当前命中 ' +
        fmt(activeRule.count) +
        " 个词。<p>" +
        esc(activeRule.examples.join("、")) +
        "</p></div>" +
        btn("commitRule", "启用排除规则", "primary");
      return;
    }
    const res = await post(f.dataset.form, { ...v, id: f.dataset.id });
    if (view === "sites") metaReady = false;
    else await refreshMeta();
    await load();
    if (f.dataset.form === "word") {
      await word(res.id);
      toast(res.duplicate ? "库中已有这个词，已打开原记录" : "已保存关键词");
    } else if (f.dataset.form === "site") {
      await site(res.id);
      toast(res.duplicate ? "同一域名已收录" : "已保存同行");
    } else {
      await word(Number(f.dataset.id));
      toast("已保存");
    }
  } catch (er) {
    failure(er);
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "photo-search") {
    searchPhotoChoices(e.target).catch(failure);
    return;
  }
  if (e.target.id === "choose-domain") {
    $("#domain-results").innerHTML = siteChoices(e.target.value);
  }
  if (e.target.id === "search") {
    filt.q = e.target.value;
    paging = [0];
    clearTimeout(waitTimer);
    waitTimer = setTimeout(() => load().catch(failure), 200);
  }
});
document.addEventListener("change", async (e) => {
  try {
    const el = e.target;
    if (el.matches('form[data-form="import-history-filter"] select')) {
      return openAppLocation(importHistoryRoute(Object.fromEntries(new FormData(el.form))));
    }
    if (el.matches('form[data-form="across-gallery"] select')) {
      const values = Object.fromEntries(new FormData(el.form));
      if (el.name === "owner") values.category = "";
      return openAppLocation(acrossGalleryRoute(values));
    }
    if (el.id === "photo-files" && el.files.length) {
      await savePhotos(Array.from(el.files), el.dataset.word, $("#photo-upload-category").value.trim(), $("#photo-upload-kind").value);
      return;
    }
    if (el.id === "select-page-photos" || el.dataset.photoSelect) {
      const ids = el.dataset.photoSelect ? [Number(el.dataset.photoSelect)] : shown.map(row=>row.id);
      ids.forEach(id => el.checked ? selectedPhotos.add(id) : selectedPhotos.delete(id));
      updatePhotoSelection();
      return;
    }
    if (el.id === "industry") {
      changeIndustry(el.value);
      return;
    }
    if (
      [
        "ptype",
        "linkstate",
        "role",
        "kind",
        "state",
        "site",
        "featured",
        "traffic",
        "market",
        "category",
        "audience",
        "keyword_status",
      ].includes(el.id)
    ) {
      if (el.id === "ptype" && el.value !== "-1" && filt.type_review) {
        const {type_review, ...other} = filt;
        return navigate("words", {...other, ptype:el.value});
      }
      await applyTableFilter(el.id, el.value);
    }
    if (el.id === "checkall") {
      $$("#panel [data-id][type=checkbox]").forEach((x) => {
        x.checked = el.checked;
        const id = Number(x.dataset.id);
        el.checked ? selection.add(id) : selection.delete(id);
      });
    } else if (el.type === "checkbox" && el.dataset.id) {
      const id = Number(el.dataset.id);
      el.checked ? selection.add(id) : selection.delete(id);
    }
    if (el.id === "checkall" || (el.type === "checkbox" && el.dataset.id))
      syncSelection();
    if (el.id === "files") return await autoFiles(Array.from(el.files));
    if (el.id === "saved-import-kind") {
      importReviewState.kind = el.value;
      return reviewFields();
    }
    if (el.id === "manual-files" && el.files.length) {
      uploads = Array.from(el.files);
      summary = [];
      modalBusy = true;
      dialog("正在读取表头", "<p>" + esc(uploads[0].name) + "</p>");
      try {
        staged = await stageFile(uploads[0]);
        mapForm(staged);
      } finally {
        modalBusy = false;
      }
    }
    if (el.id === "worksheet") {
      const d = await post("sample", { token: staged.token, sheet: el.value });
      staged = { ...staged, ...d, sheet: el.value };
      mapForm(staged);
    }
  } catch (er) {
    failure(er);
  }
});
document.addEventListener("click", async (e) => {
  if (
    e.target.closest(
      '#dialog a[href*="#words/batch/"],#dialog a[href*="#sites/batch/"],#dialog a[href$="#imports"]',
    )
  )
    close();
  const t = e.target.closest("button");
  if (!t) return;
  try {
    if (t.dataset.view) {
      navigate(t.dataset.view);
      return;
    }
    const a = t.dataset.action,
      id = Number(t.dataset.id);
    if (a === "site-coverage") {
      const status = t.dataset.coverage;
      if (status === (filt.keyword_status || "")) return;
      $("#keyword_status").value = status;
      return await applyTableFilter("keyword_status", status);
    }
    if (a?.startsWith("bank-")) return await bankAction(a,t);
    if (a?.startsWith("preset-")) return await presetAction(a,t);
    if (a?.startsWith("export-")) return await exportAction(a,t);
    if (a?.startsWith("record-search-")) return await recordSearchAction(a,t);
    if (a === "bulkExport") return await bulkExportBox();
    if (a === "aiConnection") return await aiConnection();
    if (a === "brief") return await openBrief();
    if (a === "typeBatch") return typeBatchForm();
    if (a === "clearSelection") {
      selection.clear();
      $$("#panel input[type=checkbox][data-id]").forEach(
        (input) => (input.checked = false),
      );
      syncSelection();
      return;
    }
    if (a === "copyAI" || a === "copyBrief") {
      const field = $(a === "copyBrief" ? "#brief-text" : "#ai-config");
      field.select();
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(field.value);
          toast("已复制");
          return;
        } catch {}
      }
      toast(
        document.execCommand("copy") ? "已复制" : "内容已选中，可用复制快捷键",
      );
      return;
    }
    if (a === "manualWords" || a === "manualSites") {
      const target = Number($("#import-industry").value);
      if (target !== industryId || activeAreaId !== 1) {
        openAppLocation(
          "/?industry=" +
            target +
            "&section=1#library/" +
            (a === "manualSites" ? "manual-sites" : "manual-words"),
        );
        return;
      }
      return manualBox(a === "manualSites" ? "sites" : "words");
    }
    if (a?.startsWith("import-history-")) return await importHistoryAction(a, t);
    if (a === "reviewSavedImport" || a === "retrySavedImport") {
      const context = {run:t.dataset.run, industry:Number(t.dataset.industry), filename:t.dataset.filename,
        sheet:t.dataset.sheet || "", kind:t.dataset.kind || "words"};
      return a === "reviewSavedImport" ? await importReview(context) : await retrySavedImport(context);
    }
    if (a === "previewImportHeader") {
      const input = $('#dialog input[name="headerRow"]');
      if (input.reportValidity()) return await importReview(importReviewState, Number(input.value) - 1);
      return;
    }
    if (a === "leaveImportRunning" && observedImport) {
      observedImport.detached = true;
      observedImport = null;
      importBusy = false;
      close();
      metaReady = false;
      if (view === "imports") await load();
      return toast("正在后台导入，结果可在导入记录查看");
    }
    if (a && a.startsWith("build-")) return await buildAction(a, t);
    if (a === "newType" || a === "editType") return typeForm(id);
    if (a === "typeReview") return showTypeReview();
    if (a === "clearTypeReview") {
      const {type_review, ...other} = filt;
      return navigate("words", other);
    }
    if (a === "typeSuggestions") return showTypeSuggestions();
    if (a === "chooseTypeSuggestion") return chooseTypeSuggestion(t);
    if (a === "typeWords")
      return navigate("words", { ptype: String(id), state: "all" });
    if (a === "uploadPhoto") return uploadPhotos(id);
    if (a === "photoDetail") return await photoDetail(id, Number(t.dataset.industry) || industryId);
    if (a === "gallery-codex-search") return galleryCodexSearch();
    if (a === "gallery-codex-image") return galleryCodexImage(Number(t.dataset.industry), id);
    if (a === "gallery-group") {
      const group = $("#across-gallery-industry-" + id);
      group?.focus({preventScroll:true});
      return group?.scrollIntoView({block:"start"});
    }
    if (a === "pickPhoto") return await choosePhoto(t.dataset.term, id);
    if (a === "morePhotoChoices")
      return await searchPhotoChoices($("#photo-search"), id);
    if (a === "choosePhoto") {
      const wid = $("#photo-choices").dataset.word;
      await post("gallery-change", {
        id,
        term: t.dataset.term,
        action: "link",
      });
      await word(wid);
      await load();
      return;
    }
    if (["unlinkPhoto", "unlinkWordPhoto", "coverPhoto"].includes(a)) {
      await post("gallery-change", {
        id,
        term: t.dataset.term,
        action: a === "coverPhoto" ? "cover" : "unlink",
      });
      if (a === "unlinkPhoto") await photoDetail(id);
      else await word(t.dataset.word);
      await load();
      return;
    }
    if (a === "buildPhotos") return buildPhotos();
    if (["previewPhotos", "buildPhotoPage", "buildPhotoPick", "buildPhotoBack",
      "buildPhotoFind", "buildPhotoBrowse", "buildPhotoLink"].includes(a)) {
      return await buildPhotoAction(a, t);
    }
    if (a === "newindustry") {
      dialog(
        "添加行业",
        '<form data-form="industry" class="form-grid">' +
          field("name", "行业名称", "例如 电池", true) +
          '<button class="primary">建立行业</button></form>',
      );
      return;
    }
    if (a === "uploadSites") return uploadBox();
    if (a === "replaceImportFile") return uploadBox(Number(t.dataset.industry),
      t.dataset.replace === "1" ? t.dataset.run : "");
    if (a === "openReplacementFile") {
      const industry = Number(t.dataset.industry);
      const {run} = await get("import-history-file", {industry, key:t.dataset.key});
      return dialog("补传结果", importResultCard(run, industry, true));
    }
    if (a === "exportSites") {
      dialog(
        industryName + " · 导出同行网站",
        '<a class="primary" href="/api/export?' +
          esc(qs({ ...filt, kind: "sites" })) +
          '">下载当前网站清单 CSV</a>',
      );
      return;
    }
    if (a === "close") {
      close();
      return;
    }
    if (a === "chooseSite") {
      dialog(
        "筛选来源同行",
        '<label class="searchbox"><input id="choose-domain" placeholder="输入公司或域名"></label><div id="domain-results">' +
          siteChoices() +
          "</div>",
      );
      return;
    }
    if (a === "useSite") {
      close();
      filt.site = id || "";
      paging = [0];
      filters();
      await load();
      return;
    }
    if (a === "word") await word(id);
    else if (a === "moreobs" || a === "word-sources")
      await word(id, Number(t.dataset.after || 0), t.dataset.scoped === "1");
    else if (a === "site") await site(id);
    else if (a === "sitewords") {
      const batch = siteKeywordBatch;
      close();
      if (batch) {
        return openAppLocation("#words/saved/" + encodeURIComponent(JSON.stringify({
          site: String(id), batch: String(batch),
        })));
      }
      navigate("words", { site: id });
    } else if (a === "clearbatch") {
      delete filt.batch;
      delete filt.batch_scope;
      paging = [0];
      filters();
      await load();
    } else if (a === "next") {
      paging.push(shown.at(-1).id);
      await load();
    } else if (a === "prev") {
      paging.pop();
      await load();
    } else if (a === "upload") uploadBox();
    else if (a === "addword") newWord();
    else if (a === "addsite") newSite();
    else if (a === "export") exportBox();
    else if (a === "batchstate") batchMark();
    else if (a === "newrule") ruleBox();
    else if (a === "oneState") {
      await post("state", { ids: [id], state: Number(t.dataset.state) });
      await refreshMeta();
      await load();
      await word(id);
    } else if (a === "commitgroup") {
      const g = stagedGroup;
      if (g.scope === "selected") await post("state", g);
      else await post("group-apply", g);
      selection.clear();
      close();
      await refreshMeta();
      await load();
      toast("已更新筛选状态");
    } else if (a === "commitRule") {
      await post("rule", activeRule);
      close();
      await refreshMeta();
      await load();
      toast("规则已启用");
    } else if (a === "removeRule") {
      dialog(
        "撤销排除规则",
        "<p>撤销「" +
          esc(t.dataset.name) +
          '」后仍会应用其他规则。其余匹配词恢复为原表精选或待筛选。</p><div class="section-actions">' +
          btn("undoRule", "确认撤销", "primary", 'data-id="' + id + '"') +
          "</div>",
      );
    } else if (a === "undoRule") {
      await post("unrule", { id });
      close();
      await refreshMeta();
      await load();
    } else if (a === "seeimports") {
      close();
      navigate("imports");
    } else if (a === "logout") {
      await post("logout", {});
      location.reload();
    }
  } catch (er) {
    failure(er);
  }
});
document.addEventListener("keydown", (e) => {
  if (
    e.key === "/" &&
    !$("#dialog").open &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
  ) {
    const input = $("#search") || $('[aria-label="跨行业搜索关键词"]');
    if (input) {
      input.focus();
      e.preventDefault();
    }
  }
});
(async () => {
  try {
    const all = (knownIndustries = await get("industries"));
    await refreshAreas();
    const current = all.find((i) => i.id === industryId);
    if (!current) {
      changeIndustry(all[0].id);
      return;
    }
    industryName = current.name;
    $("#workspace-name").textContent = industryName;
    $("#industry").innerHTML = all
      .map((i) => option(i.id, i.name, industryId))
      .join("");
    const a = await get("auth");
    if (!a.version || Number.parseFloat(a.version) < 2.9) {
      $("#panel").innerHTML =
        '<div class="build-empty"><h2>新版软件已安装</h2><p>请先保存工作，退出主机上的旧版程序，再重新打开软件。</p></div>';
      return;
    }
    $("#privacy").textContent = a.local ? "本机私有数据库" : "已登录私人资料库";
    $("#access").innerHTML = a.local
      ? "本机桌面窗口 · v" + esc(a.version)
      : btn("logout", "退出登录", "text-button");
    if (a.startBuildHub && !location.hash && !location.search)
      history.replaceState(null, "", "#buildhub");
    openWorkspaceRoute();
    window.addEventListener("popstate", openWorkspaceRoute);
  } catch (e) {
    failure(e);
  }
})();
