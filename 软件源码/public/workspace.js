"use strict";

function openWorkspaceRoute() {
  const [name, number, batch, clicked, revision] = location.hash.slice(1).split("/");
  if (name === "buildsearch") return openRecordSearch(number === "filter" ? batch : "");
  if (name === "prompts") {
    let find = "";
    try { find = decodeURIComponent(revision || "").trim().slice(0, 400); } catch {}
    return navigate(name, /^[1-9]\d{0,14}$/.test(number || "") ? {project:Number(number),
      step:/^(?:all|0|[1-9]\d{0,14})$/.test(batch || "") ? batch : "current",
      offset:/^\d{1,7}$/.test(clicked || "") ? Number(clicked) : 0, find} : {}, false);
  }
  if (name === "imports") return openImportHistory(number === "filter" ? batch : "");
  if (name === "gallery-all") {
    const filters = new URLSearchParams(number === "filter" ? batch : "");
    return navigate(name, Object.fromEntries(galleryAcrossFields.filter(key => filters.has(key))
      .map(key => [key, filters.get(key)])), false);
  }
  if (number === "saved" && Object.prototype.hasOwnProperty.call(presetKeys, name)) {
    const filters = readSavedFilters(name, batch);
    batchFilterName = filters.batch ? "导入批次 " + filters.batch : "";
    navigate(name, filters, false);
    if (name === "gallery" && /^[1-9]\d{0,14}$/.test(clicked || ""))
      photoDetail(Number(clicked)).catch(failure);
    return;
  }
  if (name === "words" && number === "review" && batch) {
    let key = "";
    try { key = decodeURIComponent(batch); } catch {}
    if (/^(?:manual|box|other|types-[1-9]\d*(?:,[1-9]\d*)+)$/.test(key)) {
      navigate("words", {ptype: "-1", type_review: key}, false);
      return;
    }
  }
  let search = "";
  if (name === "words" && number === "search" && batch) {
    try {
      search = decodeURIComponent(batch);
    } catch {
      search = "";
    }
  }
  const isBatch =
    ["words", "sites"].includes(name) &&
    number === "batch" &&
    /^\d+$/.test(batch || "");
  if (isBatch) batchFilterName = "导入批次 " + batch;
  const batchScope = name === "words" && ["new", "existing"].includes(clicked) ? clicked : "";
  const project = Number(number);
  const archive = name === "buildhub" && batch === "archive" && /^[1-9]\d{0,14}$/.test(clicked || "")
    ? Number(clicked) : 0;
  const selectedAnswer = name === "wiki" ? clicked : revision;
  const answer = /^[1-9]\d{0,14}$/.test(selectedAnswer || "") ? Number(selectedAnswer) : 0;
  let pageKey = "";
  if (name === "sitemap" && ["plan","live"].includes(batch) && clicked) {
    try { pageKey = decodeURIComponent(clicked); } catch {}
  }
  navigate(
    name || "home",
    isBatch
      ? { batch: Number(batch), state: "all", batch_scope: batchScope }
      : search
        ? { q: search }
        : name === "materials" && number !== undefined
          ? { sub: String(number) }
          : project > 0 &&
              ["buildhub", "workflows", "siteplan", "sitemap", "skills", "wiki"].includes(name)
            ? (pageKey ? {project, node:pageKey, mode:batch, answer} :
                name === "wiki" && /^[a-z0-9-]+$/.test(batch || "") ? {project, slug:batch, answer} :
                archive ? {project, archive} : {project})
            : {},
    false,
  );
  const wordId = search ? Number(clicked) : project;
  if (name === "words" && wordId > 0) word(wordId).catch(failure);
  if (name === "library" && ["manual-sites", "manual-words"].includes(number)) {
    history.replaceState(
      null,
      "",
      location.pathname + location.search + "#library",
    );
    manualBox(number === "manual-sites" ? "sites" : "words");
  }
}
function workspaceActions(v) {
  if (v === "gallery-all")
    return btn("gallery-codex-search", "交给 Codex 找图") +
      '<a class="secondary" href="' + esc(galleryIndustryLink(industryId)) + '">' +
      esc(industryName) + '图库</a>';
  if (v === "buildsearch") return projectOverviewLink();
  if (v === "wiki") return buildButton("wiki-refresh", "刷新");
  if (v === "prompts") return filt.project ? '<a class="secondary" href="/?' + esc(qs({section:2})) + '#prompts">所有网站的提示词</a>' : projectOverviewLink();
  if (v === "skillbank") return btn("bank-url","收藏网址")+btn("bank-upload","导入技能 ZIP","primary");
  if (v === "home")
    return (
      buildButton("new-section", "添加一级类目", "text-button") +
      buildButton("inbox", "快速存资料") + btn("bank-gallery","打开产品图库") +
      btn("export-backup-center", "备份与换机") +
      btn("upload", "批量导入", "primary")
    );
  if (v === "materials")
    return (
      buildButton("new-sub", "添加二级类目") +
      buildButton("new-material", "添加资料", "primary")
    );
  if (v === "sitemap")
    return (filt.project ? '<a class="secondary" href="#sitemap">所有网站地图</a>' : "") + projectOverviewLink();
  if (v === "skills" && activeAreaId === 2)
    return filt.project ? '<a class="secondary" href="#skills">所有项目的技能</a>' : "";
  if (v === "buildhub" && filt.archive) return projectOverviewLink();
  if (v === "buildhub") return (isProjectOverview(v, filt)
    ? '<button type="button" class="secondary" data-view="buildsearch">查找建站记录</button>' : projectOverviewLink()) +
    buildButton("new-project", "新建项目");
  if (v === "library")
    return (
      btn("newindustry", "添加行业") +
      btn("aiConnection", "AI 取词") +
      btn("bulkExport", "批量导出") +
      btn("upload", "批量导入", "primary")
    );
  return btn("build-new-project", "新建建站项目", "secondary");
}
function buildButton(action, label, cls = "secondary", id = 0) {
  return btn(
    "build-" + action,
    esc(label),
    cls,
    'data-id="' + Number(id) + '"',
  );
}
function isProjectOverview(v, params) {
  return v === "buildhub" && activeAreaId === 2 && !params.project;
}
function projectOverviewLink() {
  return '<a class="secondary" href="/?' + esc(qs({ section: 2 })) + '#buildhub">返回项目总览</a>';
}
function archiveShortcut(project) {
  const archived = project.latestArchive;
  if (!archived) return "";
  const url = "/?" + qs({industry:project.industry, section:project.section}) +
    "#buildhub/" + project.id + "/archive/" + archived.answer;
  return '<div class="directory-archive"><a class="directory-link" href="' + esc(url) +
    '" aria-label="' + esc("查看" + project.name + "最近一轮归档") +
    '">查看最近归档 ›</a><time>' + esc(archived.sent) + '</time></div>';
}

function projectNextCard(project) {
  return '<div class="directory-next"><small>下一件事</small><p>' +
    esc(project.nextTask || "待记录") + '</p>' +
    nextTaskOriginal(project, project.nextTaskSource) + '</div>';
}

function projectDirectory(projects, target) {
  if (!projects.length) return '<p class="build-empty">还没有建站项目。可以到项目总览新建项目。</p>';
  const cards = projects.map(p => {
    const base = "/?" + qs({ section: p.section, industry: p.industry });
    const map = esc(base + "#sitemap/" + p.id);
    const title = '<small>' + esc(p.label) + '</small><h2>' + esc(p.name) + '</h2>';
    const promptLink = esc(base + promptRoute(p.id));
    if (target === "prompts") return '<a class="directory-project directory-map" data-project-search="' +
      esc([p.name, p.site, p.label].join(" ").toLowerCase()) + '" href="' + promptLink + '">' + title +
      '<span class="directory-link">' + fmt(p.promptTotal) + ' 条提示词 ›</span></a>';
    if (target === "sitemap") return '<a class="directory-project directory-map" href="' + map + '">' +
      title + '<span class="directory-link">查看地图 ›</span></a>';
    const skills = esc(base + "#skills/" + p.id);
    const skillNames = p.skillNames || [];
    const preview = skillNames.length
      ? '<small class="directory-skill-preview">' + esc(skillNames.slice(0, 3).join(" · ")) +
        (skillNames.length > 3 ? ' 等' : '') + '</small>'
      : "";
    if (target === "skills") return '<a class="directory-project directory-map" href="' + skills + '">' +
      title + '<span class="directory-link">管理技能（' + fmt(skillNames.length) + '） ›</span>' + preview + '</a>';
    const step = activeStep(p);
    const done = p.steps.filter(s => s.status === "已完成").length;
    const project = esc(base + "#buildhub/" + p.id);
    const search = esc([p.name, p.site, p.label].join(" ").toLowerCase());
    return '<article class="directory-project" data-project-search="' + search + '"><small>' +
      esc(p.label) + '</small><h2><a href="' + project + '">' +
      esc(p.name) + '</a></h2><div class="directory-stage"><span>' +
      esc(step ? step.title : p.steps.length ? "全部步骤已完成" : "还没有步骤") +
      '</span><span>' + done + ' / ' + p.steps.length + ' 步完成</span></div>' +
      (p.steps.length ? '<progress aria-label="已完成步骤" value="' + done + '" max="' + p.steps.length + '"></progress>' : "") +
      (step ? projectNextCard(p) : "") + archiveShortcut(p) +
      (p.openIssues ? '<a class="directory-issues" href="' +
        esc("/?" + qs({section:2,industry:p.industry}) +
          recordSearchRoute({owner:[p.industry,p.section,p.id].join("/"),kind:"待解决"})) +
        '">' + fmt(p.openIssues) + ' 个问题待解决 ›</a>' : "") +
      '<div class="directory-project-links"><a class="directory-link" href="' + map +
      '" aria-label="' + esc(p.name + "的网站地图") + '">网站地图 ›</a>' +
      '<a class="directory-link" aria-label="' + esc(p.name + '的项目提示词') + '" href="' + promptLink + '">项目提示词 ›</a>' +
      '<a class="directory-link" href="' + esc(base + "#wiki/" + p.id) + '">建站知识库 ›</a>' +
      '<a class="directory-link" href="' + skills + '" aria-label="' +
      esc(p.name + '的 Skills 技能管理，共 ' + fmt(skillNames.length) + ' 个技能') +
      '">Skills 技能管理（' + fmt(skillNames.length) + '） ›</a></div>' +
      preview + '</article>';
  });
  const count = '<div class="directory-count" aria-live="polite">共 ' + fmt(projects.length) + ' 个项目</div>';
  const grid = '<div class="project-directory">' + cards.join("") + '</div>';
  if (!["buildhub", "prompts"].includes(target)) return count + grid;
  return '<section class="project-overview"><div class="directory-tools">' +
    '<input id="project-search" type="search" placeholder="搜索项目、域名或行业" aria-label="搜索项目、域名或行业">' +
    count + (target === "buildhub" ? pageTasksLink() + '<a class="secondary" href="' +
    esc(recordSearchRoute({kind:"待解决"})) + '">查看全部待解决问题</a>' : '') + '</div>' +
    grid + '<p class="build-empty directory-empty" hidden>没有找到匹配的项目。</p></section>';
}
function viewButton(target, heading, description, total) {
  return (
    '<button type="button" class="module-card" data-view="' +
    target +
    '"><strong>' +
    esc(heading) +
    "</strong><span>" +
    esc(description) +
    "</span><small>" +
    esc(total) +
    "</small></button>"
  );
}
async function refreshAreas() {
  areas = await get("sections");
  area = areas.find((x) => x.id === activeAreaId) || areas[1];
  $(".primary-nav").innerHTML = areas.map((a) => {
    const parent = buildButton("area", a.name, "nav-button", a.id);
    if (a.id !== 2) return parent;
    const tools = ["prompts", "wiki", "skills", "skillbank", "siteplan"].map((target) =>
      '<button type="button" class="nav-button" data-view="' + target + '">' + esc(titles[target]) + '</button>'
    ).join("");
    return '<div class="software-nav-group">' + parent +
      '<div id="software-subnav" class="software-subnav" role="group" aria-label="' +
      esc(a.name) + '的二级菜单" hidden>' + tools + '</div></div>';
  }).join("");
}
function openArea(id, sub) {
  const a = areas.find((x) => x.id === Number(id));
  if (!a) return;
  const leaf =
    a.kind === "keywords"
      ? "library"
      : a.kind === "notes" || sub !== undefined
        ? "materials"
        : "buildhub";
  openAppLocation(
    "/?industry=" +
      industryId +
      "&section=" +
      a.id +
      "#" +
      leaf +
      (sub !== undefined ? "/" + sub : ""),
  );
}
let homeImportIndustry = 0;
function workbench(desk) {
  homeImportIndustry = Number(desk.industry);
  const p = desk.project;
  const project = p ? "/?" + qs({ section:p.section, industry:p.industry }) : "";
  const resume = p
    ? '<section class="desk-task"><h2>' +
      (p.visited ? "继续上次建站" : "建站项目") +
      '</h2><p class="desk-project"><strong>' +
      esc(p.name) +
      "</strong> · " +
      esc(p.label) +
      '</p><p class="desk-progress">' +
      esc(p.step || (p.total ? "所有步骤已完成" : "还没有步骤")) +
      "　" +
      fmt(p.done) +
      " / " +
      fmt(p.total) +
      ' 步已完成</p>' +
      (p.nextTask ? projectNextCard(p) : "") + archiveShortcut(p) +
      (p.openIssues ? '<p class="desk-progress">' + fmt(p.openIssues) + ' 个问题待解决</p>' : "") +
      '<div class="step-actions"><a class="secondary" href="' +
      esc(project + "#buildhub/" + p.id) +
      '">打开建站工作台</a><a class="text-button" href="' + esc(project + "#wiki/" + p.id) +
      '">建站知识库</a>' + pageTasksLink() +
      '<a class="text-button" href="/?' + esc(qs({section:2})) + '#buildsearch">查找建站记录</a></div></section>'
    : '<section class="desk-task"><h2>建站项目</h2><p>建立项目后，可以从首页接着上次的步骤做。</p><a class="secondary" href="/?section=2&amp;industry=1#buildhub">进入建站流程</a></section>';
  return (
    '<div class="desk-tasks"><section class="desk-task"><h2>找关键词</h2>' +
    crossWordForm() +
    '<div class="step-actions">' + btn("preset-list", "常用方案", "text-button", 'data-scope="all"') +
    '<a class="text-button" href="/?' + esc(qs({section:1})) + '#imports/filter/scope=all">查找导入原表</a>' +
    btn("export-history", "导出记录", "text-button") + '</div>' +
    "</section>" +
    resume +
    '</div><h2 class="area-heading">资料类目</h2>' +
    homeModules()
  );
}

function homeModules() {
  const descriptions = {
    keywords: "按行业导入、查重和调取关键词、同行网站与产品图片。",
    build: "管理软件资料、建站流程、提示词和问题记录。",
    notes: "按主题保存研究笔记、原文和附件。",
    store: "管理零售商城的项目、商品页、支付与营销资料。",
  };
  return (
    '<div class="module-grid home-grid">' +
    areas
      .map(
        (a) =>
          '<button class="module-card" data-action="build-area" data-id="' +
          a.id +
          '"><strong>' +
          esc(a.name) +
          "</strong><span>" +
          esc(descriptions[a.kind]) +
          "</span><small>" +
          esc(
            a.kind === "keywords"
              ? knownIndustries
                  .map((x) => x.name)
                  .slice(0, 4)
                  .join(" · ")
              : a.children
                  .slice(0, 4)
                  .map((x) => x.name)
                  .join(" · ") || "可添加二级类目",
          ) +
          "</small></button>",
      )
      .join("") +
    "</div>"
  );
}
function subButtons() {
  return (
    '<div class="subtree"><b>二级类目</b>' +
    (area.id === 2 ? '<button type="button" class="secondary" data-view="skillbank">Skills 技能包</button>' : "") +
    area.children
      .map((c) => buildButton("sub", c.name, "secondary", c.id))
      .join("") +
    buildButton("sub", "仅存一级 / 待整理", "text-button", 0) +
    "</div>"
  );
}
function newCategory(child) {
  if (!child)
    return buildForm(
      "section",
      "添加一级类目",
      {},
      buildInput("name", "一级类目名称", "", true) +
        '<label class="field full">使用方式<select name="kind"><option value="notes">分类存资料和附件</option><option value="build">管理项目、流程和资料</option></select></label>',
    );
  return buildForm(
    "subsection",
    "添加二级类目",
    {},
    '<p class="field full">所属一级类目　' +
      esc(area.name) +
      "</p>" +
      buildInput("name", "二级类目名称", "", true) +
      buildArea("cues", "识别词（可选，每行一个）"),
    { section: area.id },
  );
}
function crossWordForm() {
  return '<form data-form="build-find-words" class="material-search"><input type="search" name="query" aria-label="跨行业搜索关键词" placeholder="输入关键词或中文翻译" maxlength="1000" required><button class="secondary">跨行业查词</button></form><div id="cross-word-results" aria-live="polite"></div>';
}
async function findWords(value) {
  const host = $("#cross-word-results");
  if (!host) return;
  host.dataset.query = value;
  host.textContent = "正在查找…";
  const list = await get("cross-words", { q: value });
  if (!host.isConnected || host.dataset.query !== value) return;
  host.innerHTML = list.length
    ? list
        .map((g) => {
          const base =
            "/?industry=" +
            g.id +
            "&amp;section=1#words/search/" +
            esc(encodeURIComponent(value));
          return (
            '<section class="cross-result"><h3>' +
            esc(g.name) +
            "</h3>" +
            g.rows
              .map(
                (w) =>
                  copyableValue('<a href="' + base + "/" + w.id + '">' + esc(w.term) + "</a>", w.term, "关键词"),
              )
              .join(" ") +
            '<p><a href="' +
            base +
            '">查看此行业的匹配词</a></p></section>'
          );
        })
        .join("")
    : '<p class="build-empty">各行业暂时都没有匹配的在库词。</p>';
}
function libraryModules(summary) {
  return (
    '<div class="module-grid">' +
    viewButton(
      "words",
      "关键词库",
      "导入、去重、查看指标和排名网址。",
      fmt(stats.words) + " 个关键词",
    ) +
    viewButton(
      "sites",
      "同行网站",
      "查看官网或按 B2B、B2C 类型筛选。",
      fmt(stats.sites) + " 家同行",
    ) +
    viewButton(
      "gallery",
      "产品图库",
      "按完整关键词匹配建站产品图。",
      fmt(summary.images) + " 张图片",
    ) +
    '</div><div class="industry-links">' +
    ["types", "imports", "rules"]
      .map(
        (v) =>
          '<button class="secondary" data-view="' +
          v +
          '">' +
          esc(titles[v]) +
          "</button>",
      )
      .join("") +
    "</div>"
  );
}
function projectGroups(localProjects, overview) {
  const groups = new Map();
  if (localProjects.length) groups.set(industryId, {
    industry: industryId, label: activeAreaId === 2 ? industryName : area.name, projects: localProjects
  });
  for (const project of overview) {
    if (project.section !== activeAreaId || project.industry === industryId) continue;
    if (!groups.has(project.industry)) {
      groups.set(project.industry, { industry: project.industry, label: project.label, projects: [] });
    }
    groups.get(project.industry).projects.push(project);
  }
  return [...groups.values()];
}

function selectBuildProject(destination, owner, id, section = activeAreaId) {
  if (owner === industryId && section === activeAreaId) return navigate(destination, { project: id });
  openAppLocation("/?" + qs({ industry: owner, section }) + "#" + destination + "/" + id);
}

function projectPicker(groups, selected) {
  if (!groups.length) return "";
  const value = industryId + "/" + selected;
  return (
    '<label class="project-picker">建站项目<select id="build-project-selector">' +
    (selected ? "" : '<option selected disabled>选择已有项目</option>') +
    groups.map(group => '<optgroup label="' + esc(group.label) + '">' +
      group.projects.map(p => option(group.industry + "/" + p.id, p.name, value)).join("") +
      '</optgroup>').join("") +
    "</select></label>"
  );
}
function projectToolbar(p) {
  return (
    '<div class="project-tools"><div><h2>' +
    esc(p.name) +
    "</h2>" +
    (p.site ? "<p>" + safeLink(p.site, p.site) + "</p>" : "") +
    (p.notes ? '<p class="build-copy">' + esc(p.notes) + "</p>" : "") +
    "</div>" +
    buildButton("edit-project", "编辑项目", "secondary", p.id) +
    "</div>"
  );
}
function entryLinks(step) {
  return step.entries.length
    ? '<ul class="entries">' +
        step.entries
          .map(
            (e) =>
              "<li><span>" +
              esc(e.kind) +
              "</span>" +
              buildButton("edit-entry", e.title, "text-button", e.id) +
              "</li>",
          )
          .join("") +
        "</ul>"
    : "";
}
function skillDetails(p) {
  const list = p.skills
    .map(
      (s) =>
        "<li><strong>" +
        esc(s.name) +
        '</strong><p class="build-copy">' +
        esc(s.description) +
        "</p>" +
        (s.instructions
          ? '<details><summary>使用方法</summary><p class="build-copy">' +
            esc(s.instructions) +
            "</p></details>"
          : "") +
        buildButton("edit-skill", "编辑 Skill", "text-button", s.id) +
        "</li>",
    )
    .join("");
  return (
    '<div class="project-tools"><h3>已登记技能 <small>' +
    fmt(p.skills.length) +
    ' 个</small></h3><div class="step-actions">' +
    buildButton("go-steps", "返回建站流程", "secondary", p.id) +
    buildButton("new-skill", "添加 Skill", "primary", p.id) +
    "</div></div>" +
    (list
      ? '<ul class="steps">' + list + "</ul>"
      : '<p class="build-empty">还没有 Skill。添加后可以在这里查看它的用途和使用方法。</p>')
  );
}
function skillForm(s, pid) {
  buildForm(
    "skill",
    s.id ? "编辑 Skill" : "添加 Skill",
    s,
    buildInput("name", "Skill 名称", s.name, true) +
      buildArea(
        "description",
        "用途说明（这个 Skill 具体做什么）",
        s.description,
        true,
      ) +
      buildArea("instructions", "使用方法或提示词（可选）", s.instructions),
    { project: pid },
  );
}
const stepExamples = {
  项目需求: "主推什么产品？卖给谁？希望客户在网站上做什么？",
  关键词与同行: "记下要用的词、参考的同行网址，以及你准备借鉴哪一点。",
  网站架构与一级栏目:
    "比如：首页、产品中心、关于我们、联系我们。打开栏目规划可以逐页填写。",
  页面内容与配图: "哪一页需要哪段文案、规格和图片？还缺什么？",
  设计与开发: "记下今天修改了哪个页面，或粘贴遇到的问题。",
  验收与上线: "手机显示、询价表单和主要链接检查过了吗？记下结果。",
  选品与客户定位: "准备卖哪款商品？谁会买？大约什么价位？",
  关键词与竞店: "粘贴目标商品词、参考店铺和你观察到的做法。",
  商品详情与配图: "写下产品卖点、规格和需要补拍的图片。",
  "支付、配送与退换": "支持哪些支付方式？运费和退换期限怎么写？",
  下单测试与上线: "记录一次测试订单的结账、运费和通知结果。",
};
const stepDrafts = new Map();
function draftFor(project, step) {
  const key = project + "/" + step;
  if (!stepDrafts.has(key))
    stepDrafts.set(key, { body: "", request: newRequestId() });
  return stepDrafts.get(key);
}
function workflowDetails(p) {
  const done = p.steps.filter((s) => s.status === "已完成").length;
  const current =
    p.steps.find((s) => s.status === "进行中") ||
    p.steps.find((s) => s.status !== "已完成");
  return (
    '<div class="project-tools"><h3>建站步骤 <small>' +
    done +
    " / " +
    p.steps.length +
    ' 已完成</small></h3><div class="step-actions">' +
    buildButton(
      "go-skills",
      "Skills 技能管理（" + fmt(p.skills.length) + "）",
      "secondary",
      p.id,
    ) +
    buildButton("new-step", "添加步骤", "text-button", p.id) +
    "</div></div>" +
    '<p class="flow-guide">' +
    (current
      ? "当前步骤：" +
        esc(current.title) +
        "。写下进展后点「保存记录」，做完点「完成此步」。"
      : p.steps.length
        ? "全部步骤已完成。点任一步可以查看记录或重新打开。"
        : "点「添加步骤」开始。") +
    "</p>" +
    '<ol class="steps flow-list">' +
    p.steps
      .map((s) => {
        const draft = draftFor(p.id, s.id);
        const expanded = current?.id === s.id || draft.body;
        const jump =
          s.title === "网站架构与一级栏目"
            ? buildButton("go-plan", "打开一级栏目规划", "secondary", p.id)
            : ["关键词与同行", "关键词与竞店"].includes(s.title)
              ? '<a class="secondary" href="/?industry=' +
                industryId +
                '&amp;section=1#library">打开行业关键词库</a>'
              : "";
        return (
          '<li><details class="flow-step" ' +
          (expanded ? "open" : "") +
          "><summary><strong>" +
          esc(s.title) +
          "</strong><span>" +
          esc(s.status) +
          (s.entries.length ? " · " + s.entries.length + " 条记录" : "") +
          "</span></summary>" +
          '<div class="flow-body"><p class="build-copy">' +
          esc(s.notes) +
          '</p><a class="secondary" href="' + promptRoute(p.id, s.id) + '">这一步的提示词</a>' +
          entryLinks(s) +
          (s.status !== "已完成" || draft.body
            ? '<form data-form="build-quick" data-step="' +
              s.id +
              '" data-project="' +
              p.id +
              '" class="flow-note"><label>这一步的记录<textarea name="body" maxlength="600000" rows="2" placeholder="' +
              esc(stepExamples[s.title] || "写下本步的进展、决定或问题。") +
              '">' +
              esc(draft.body) +
              '</textarea></label><div class="step-actions">' +
              '<button class="primary" type="submit">保存记录</button>' +
              buildButton("finish-step", "完成此步", "secondary", s.id) +
              jump +
              "</div></form>"
            : '<div class="step-actions">' +
              buildButton("resume-step", "重新打开这一步", "secondary", s.id) +
              jump +
              "</div>") +
          '<details class="flow-more"><summary>更多操作</summary><div class="step-actions">' +
          buildButton(
            "new-entry",
            "添加提示词、对话或附件",
            "text-button",
            s.id,
          ) +
          buildButton("edit-step", "编辑步骤 / 进度", "text-button", s.id) +
          "</div></details></div></details></li>"
        );
      })
      .join("") +
    "</ol>"
  );
}
function newRequestId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");
}
document.addEventListener("input", (e) => {
  if (e.target.id === "project-search") {
    const overview = e.target.closest(".project-overview");
    const query = e.target.value.trim().toLowerCase();
    const cards = overview.querySelectorAll("[data-project-search]");
    let visible = 0;
    for (const card of cards) {
      const match = card.dataset.projectSearch.includes(query);
      card.hidden = !match;
      visible += Number(match);
    }
    overview.querySelector(".directory-count").textContent = query
      ? "找到 " + fmt(visible) + " 个项目"
      : "共 " + fmt(cards.length) + " 个项目";
    overview.querySelector(".directory-empty").hidden = visible > 0;
    return;
  }
  const form = e.target.closest('form[data-form="build-quick"]');
  if (form)
    draftFor(form.dataset.project, form.dataset.step).body =
      form.elements.body.value;
});
async function storeStepNote(project, step) {
  const draft = draftFor(project, step);
  const title = draft.body.trim().split(/\r?\n/)[0].slice(0, 100);
  if (!title) throw Error("请先写下这一步的记录。");
  const body = draft.body;
  await post("build-entry", {
    kind: "步骤笔记",
    step,
    body,
    title,
    subcategory: "auto",
    request: draft.request,
  });
  if (draft.body === body) stepDrafts.delete(project + "/" + step);
  else draft.request = newRequestId();
}
async function advanceStep(p, id, finished, button) {
  const step = p.steps.find((s) => s.id === id);
  button.disabled = true;
  try {
    if (finished && draftFor(p.id, id).body.trim())
      await storeStepNote(p.id, id);
    await post("build-step", {
      id,
      version: step.version,
      title: step.title,
      notes: step.notes,
      status: finished ? "已完成" : "进行中",
    });
    await load();
    const focusTarget =
      document.querySelector(".flow-step[open] > summary") ||
      document.querySelector(".flow-step > summary");
    focusTarget?.focus();
    toast(finished ? "这一步已完成" : "这一步已重新打开");
  } finally {
    button.disabled = false;
  }
}
function planDetails(p) {
  const body = p.pages
    .map(
      (n) =>
        "<tr><td>" +
        n.seq +
        "</td><td>" +
        buildButton("edit-page", n.title, "record-name", n.id) +
        "</td><td><code>" +
        esc(n.path) +
        "</code></td><td>" +
        (n.keyword
          ? buildButton("find-word", n.keyword, "text-button", n.id)
          : "—") +
        "</td><td>" +
        esc(n.notes || "—") +
        "</td><td>" +
        esc(n.status) +
        "</td></tr>",
    )
    .join("");
  return (
    '<div class="project-tools"><h3>一级页面 <small>' +
    p.pages.length +
    ' 个</small></h3><div class="step-actions">' +
    buildButton("go-steps", "查看建站步骤", "secondary", p.id) +
    buildButton("new-page", "添加一级页面", "primary", p.id) +
    "</div></div>" +
    (body
      ? table(
          ["导航顺序", "一级栏目", "页面路径", "主关键词", "页面用途", "状态"],
          body,
        )
      : '<p class="build-empty">还没有一级页面。点「添加一级页面」开始规划。</p>')
  );
}
let currentBuildProject = null;
async function workspacePanel(v, params) {
  if (v === "gallery-all") return acrossGalleryPanel(params);
  if (v === "buildsearch") {
    currentBuildProject = null;
    return projectRecordSearch(params);
  }
  if (v === "wiki") return wikiPanel(params);
  if (v === "prompts") return promptPanel(params);
  if(v==="skillbank") return bankPanel();
  if (v === "materials") return materialsPanel(params);
  if (v === "home") return workbench(await get("desk"));
  if (v === "library")
    return crossWordForm() + libraryModules(await get("home"));
  if (v === "buildhub" && params.archive) {
    currentBuildProject = null;
    const [project, archive] = await Promise.all([
      get("build-project", {id:params.project}),
      get("build-archive-turns", {project:params.project, answer:params.archive}),
    ]);
    if (view !== v || params !== filt) return "";
    currentBuildProject = project;
    const turn = archive.turns[0];
    return '<section class="board-log board-archive"><div class="board-title"><h2>' + esc(project.name) +
      '</h2><a class="secondary" href="#buildhub/' + project.id + '">返回项目工作台</a></div>' +
      (turn ? archiveTurn(project, turn, true) : '<p>找不到这条归档记录。</p>') + '</section>';
  }
  if (isProjectOverview(v, params) || (!params.project &&
      (v === "sitemap" || (v === "skills" && activeAreaId === 2)))) {
    currentBuildProject = null;
    return projectDirectory(await get("build-archive-overview"), v);
  }
  if (v === "sitemap") {
    currentBuildProject = null;
    const [project, mapWork] = await Promise.all([
      get("build-project", {id:params.project}),
      params.node ? null : get("build-archive-map-work", {project:params.project}),
    ]);
    project.mapSnapshot = await readProjectMap(project).catch(() => {
      project.mapError = true;
      return null;
    });
    if (view !== v || params !== filt) return "";
    if (params.node) {
      const mode = params.mode === "plan" || !project.mapSnapshot ? "plan" : "live";
      const locate = rows => rows.find(item => item.id === params.node) ||
        rows.find(item => mapRoute(params.node) && mapRoute(item.path) &&
          item.path.replace(/\/$/, "") === params.node.replace(/\/$/, ""));
      const row = locate(mapRows(project, mode)) || (mode === "live" ? locate(mapRows(project, "plan")) : null);
      if (!row) return '<p class="build-empty">这个页面已移出当前地图。<a href="#sitemap/' + project.id + '">返回网站地图</a></p>';
      const scope = {project:project.id, key:row.path || row.id};
      [project.pageRecord, project.pageKeywords] = await Promise.all([
        get("build-archive-page-record", scope),
        mapRoute(row.path) ? get("build-page-keywords", scope) : null,
      ]);
      if (view !== v || params !== filt) return "";
      project.mapKey = row.path || row.id;
      project.mapPath = row.path || "";
      project.mapTitle = row.title;
      currentBuildProject = project;
      return mapWorkPage(project, row, project.pageRecord);
    }
    project.mapWork = mapWork;
    currentBuildProject = project;
    return siteMapPage(project);
  }
  const [list, overview] = await Promise.all([
    get("projects"), activeAreaId === 2 ? get("build-archive-overview") : []
  ]);
  if (view !== v || params !== filt) return "";
  const groups = projectGroups(list, overview);
  if (!list.length) {
    currentBuildProject = null;
    return (
      projectPicker(groups, 0) + '<div class="build-empty"><h2>' +
      esc(activeAreaId >= 3 ? area.name : industryName) +
      "还没有建站项目</h2><p>建立项目后，可以记录建站步骤、保存资料并规划一级栏目。</p>" +
      buildButton("new-project", "新建建站项目", "primary") +
      (v === "buildhub"
        ? '<p><button type="button" class="text-button" data-view="workflows">查看建站流程</button></p>' +
          projectOverviewLink() +
          guideLinks()
        : "") +
      "</div>"
    );
  }
  const key = "last-build-" + industryId + "-" + activeAreaId;
  let previous = 0;
  try {
    previous = Number(localStorage.getItem(key));
  } catch {}
  const id = list.some((p) => p.id === Number(params.project))
    ? Number(params.project)
    : list.some((p) => p.id === previous)
      ? previous
      : (list.find((p) => p.recent) || list[list.length - 1]).id;
  if (view !== v || params !== filt) return "";
  const project = await post("build-visit", { id });
  if (view !== v || params !== filt) return "";
  currentBuildProject = project;
  try {
    localStorage.setItem(key, id);
  } catch {}
  if (v === "buildhub") {
    const data = await get("build-archive-list", {project:id, dashboard:1});
    if (view !== v || params !== filt) return "";
    project.nextTask = data.nextTask;
    project.nextTaskStep = data.nextTaskStep;
    return projectGuide(project, data, groups);
  }
  return (
    projectPicker(groups, id) +
    '<section class="project-sheet">' +
    projectToolbar(project) +
    (v === "workflows"
      ? workflowDetails(project)
      : v === "skills"
        ? skillDetails(project)
        : planDetails(project)) +
    "</section>"
  );
}
function buildInput(key, title, value = "", required = false) {
  return (
    '<label class="field full">' +
    esc(title) +
    '<input name="' +
    key +
    '" value="' +
    esc(value) +
    '" ' +
    (required ? "required" : "") +
    "></label>"
  );
}
function buildArea(key, title, value = "", required = false) {
  return (
    '<label class="field full">' +
    esc(title) +
    '<textarea rows="' +
    (key === "body" ? 8 : 3) +
    '" name="' +
    key +
    '" ' +
    (required ? "required" : "") +
    ">" +
    esc(value) +
    "</textarea></label>"
  );
}
function buildSelect(key, title, choices, value) {
  return (
    '<label class="field">' +
    esc(title) +
    '<select name="' +
    key +
    '">' +
    choices.map((x) => option(x, x, value)).join("") +
    "</select></label>"
  );
}
function buildForm(action, title, record, html, parent) {
  const values = Object.assign(
    {
      id: record.id || 0,
      version: record.version || 0,
      request: newRequestId(),
    },
    parent,
  );
  const hidden = Object.entries(values)
    .map(
      ([k, v]) =>
        '<input type="hidden" name="' + k + '" value="' + esc(v) + '">',
    )
    .join("");
  dialog(
    title,
    '<form class="form-grid" data-form="build-' +
      action +
      '">' +
      hidden +
      html +
      '<div class="field full"><button class="primary" type="submit">保存</button></div></form>',
  );
}
function projectForm(p = {}) {
  buildForm(
    "project",
    p.id ? "编辑项目" : "新建建站项目",
    p,
    buildInput("name", "项目名称", p.name, true) +
      (isProjectOverview(view, filt) && !p.id ? projectDestination("项目归属") : "") +
      buildInput("site", "官网网址（可选）", p.site) +
      buildArea("notes", "建站目标与说明", p.notes) +
      (!p.id
        ? '<label class="field full"><span><input type="checkbox" name="template" checked> 加入可编辑的五个一级栏目草案</span></label>'
        : ""),
  );
}
function stepForm(s = {}, pid) {
  buildForm(
    "step",
    s.id ? "编辑建站步骤" : "添加建站步骤",
    s,
    buildInput("title", "步骤名称", s.title, true) +
      buildSelect(
        "status",
        "进度",
        ["待开始", "进行中", "已完成"],
        s.status || "待开始",
      ) +
      buildArea("notes", "步骤说明", s.notes),
    { project: pid },
  );
}
async function materialsPanel(params) {
  const cursor = params.trail?.at(-1) || {};
  const result = await get("materials", {
    find: params.find || "",
    sub: params.sub,
    scope: params.scope || "all",
    ...cursor,
  });
  const last = result.rows.at(-1);
  const next =
    last && result.more
      ? btn(
          "build-next-materials",
          "下一页",
          "secondary",
          'data-before="' +
            esc(last.created) +
            '" data-ind="' +
            last.industry +
            '" data-id="' +
            last.id +
            '"',
        )
      : "";
  const controls =
    (view === "materials" ? subButtons() : "") +
    '<form data-form="build-search" class="material-search"><input name="find" type="search" aria-label="搜索建站资料" placeholder="标题、正文、类型、项目或附件名" value="' +
    esc(params.find || "") +
    '">' +
    (activeAreaId === 2
      ? '<select name="scope" aria-label="行业范围">' +
        option("all", "全部行业", params.scope || "all") +
        option("current", "仅" + industryName, params.scope || "all") +
        "</select>"
      : "") +
    '<select name="sub" aria-label="二级类目筛选">' +
    option("", "全部二级类目", params.sub ?? "") +
    option(0, "仅存一级 / 待整理", params.sub ?? "") +
    area.children.map((c) => option(c.id, c.name, params.sub ?? "")).join("") +
    '</select><button class="secondary">搜索</button></form>';
  const body = result.rows
    .map(
      (r) =>
        "<tr><td>" +
        btn(
          "build-material",
          esc(r.title),
          "record-name",
          'data-id="' + r.id + '" data-ind="' + r.industry + '"',
        ) +
        "</td><td>" +
        esc(r.kind) +
        "</td><td>" +
        esc(
          area.children.find((c) => c.id === r.subcategory)?.name ||
            "仅存一级 / 待整理",
        ) +
        "</td><td>" +
        esc(
          [activeAreaId === 2 ? r.industryName : "", r.project, r.step]
            .filter(Boolean)
            .join(" / ") || "独立资料",
        ) +
        "</td><td>" +
        r.files +
        "</td></tr>",
    )
    .join("");
  return (
    controls +
    (body
      ? table(["资料标题", "类型", "二级类目", "所属项目 / 步骤", "附件"], body)
      : '<section class="build-empty"><h2>没有找到资料</h2><p>可以添加资料，或调整搜索条件。</p></section>') +
    '<div class="step-actions">' +
    (params.trail?.length ? buildButton("prev-materials", "上一页") : "") +
    next +
    "</div>"
  );
}
function entryForm(
  e = {},
  sid = 0,
  owner = industryId,
  destination = area,
  inbox = false,
) {
  const types = [
    ...(destination.kind === "notes" ? ["研究笔记", "文档", "参考网址"] : []),
    "步骤笔记",
    "提示词",
    "对话",
    "问题",
    "文档",
    "代码",
    "参考网址",
  ];
  const initialSub = e.id
    ? e.subcategory
    : filt.sub !== undefined && filt.sub !== ""
      ? filt.sub
      : "auto";
  const typeField =
    '<label class="field full">归属 · ' +
    esc(destination.name) +
    '<select name="subcategory">' +
    option("auto", "按内容自动归类", initialSub) +
    option(0, "仅存一级 / 待整理", initialSub) +
    destination.children.map((c) => option(c.id, c.name, initialSub)).join("") +
    "</select></label>" +
    '<label class="field full">资料类型<select name="kind">' +
    [...new Set([...types, ...(e.kind ? [e.kind] : [])])]
      .map((k) => option(k, k, e.kind || (sid ? "提示词" : "文档")))
      .join("") +
    option("__custom", "自定义类型", "") +
    '</select></label><label class="field full" id="custom-build-kind" hidden>新类型名称<input name="customKind" maxlength="70"></label>';
  const files = (e.files || [])
    .map(
      (f) =>
        '<li><a download href="/api/build-file?' +
        esc(qs({ section: destination.id, industry: owner, id: f.id })) +
        '">' +
        esc(f.filename) +
        "</a></li>",
    )
    .join("");
  buildForm(
    "entry",
    e.id ? "资料详情" : sid ? "添加阶段记录" : "添加资料",
    e,
    (inbox
      ? '<label class="field full">存入一级类目<select name="autoArea">' +
        option("auto", "根据内容识别", "auto") +
        areas
          .filter((a) => a.kind !== "keywords" && a.kind !== "skillbank")
          .map((a) => option(a.id, a.name, ""))
          .join("") +
        "</select></label>"
      : "") +
      (inbox
        ? typeField.slice(
            typeField.indexOf('<label class="field full">资料类型'),
          )
        : typeField) +
      buildInput("title", "标题", e.title, true) +
      buildArea("body", "原文、参考链接或说明", e.body) +
      buildArea("resolution", "处理结果或后续事项（可选）", e.resolution) +
      (files
        ? '<div class="field full">已保存的附件<ul>' + files + "</ul></div>"
        : "") +
      '<label class="field full">添加附件（可多选，每个最多 64 MB）<input type="file" multiple name="attachments"></label>',
    { step: sid || 0, owner, destination: destination.id },
  );
}
async function saveEntry(form, values) {
  const owner = Number(values.owner) || industryId;
  const files = Array.from(form.elements.attachments?.files || []);
  values.filenames = files.map((f) => f.name).join(" ");
  let target = areas.find((a) => a.id === Number(values.destination)) || area;
  if (values.autoArea) {
    if (values.autoArea === "auto") {
      const text = [values.title, values.body, values.filenames]
        .join(" ")
        .toLowerCase();
      const keywords = {
        2: ["软件", "wordpress"],
        3: ["价值投资"],
        4: ["b2c", "shopify", "零售商城"],
      };
      const candidates = areas.filter((a) => a.kind !== "keywords" && a.kind !== "skillbank");
      const obvious = candidates.filter((a) =>
        [a.name, ...(keywords[a.id] || [])].some((k) =>
          text.includes(k.toLowerCase()),
        ),
      );
      const relevant = candidates.filter((a) =>
        a.children.some((c) =>
          [c.name, ...c.cues.split("|")].some(
            (k) => k && text.includes(k.toLowerCase()),
          ),
        ),
      );
      const chosen = obvious.length ? obvious : relevant;
      if (chosen.length !== 1)
        throw Error(
          "这份资料的一级归属需要确认。请选择「存入一级类目」后保存。",
        );
      target = chosen[0];
    } else target = areas.find((a) => a.id === Number(values.autoArea));
    values.subcategory = "auto";
  }
  delete values.attachments;
  if (values.kind === "__custom") values.kind = values.customKind;
  if (files.some((f) => !f.size || f.size > 64 * 1024 * 1024))
    throw Error("每个附件需要有内容，最多 64 MB。");
  const res = await fetch(
    "/api/build-entry?" + qs({ section: target.id, industry: owner }),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    },
  ).then(check);
  const failed = [], mapResults = [];
  for (const file of files) {
    try {
      const saved = await fetch(
        "/api/build-file?" +
          qs({
            section: target.id,
            industry: owner,
            entry: res.id,
            filename: file.name,
          }),
        { method: "POST", body: file },
      ).then(check);
      if (saved.map?.pages) mapResults.push(file.name + " 已整理 " + saved.map.pages + " 个页面");
      if (saved.mapNotice) mapResults.push(file.name + " 已保存为附件，地图待整理");
    } catch (err) {
      failed.push(file.name + " · " + err.message);
    }
  }
  if (failed.length) {
    const entry = await get("build-entry", {
      section: target.id,
      industry: owner,
      id: res.id,
    });
    entryForm(entry, entry.step, owner, target);
    throw Error("文字已保存。请重新选择上传失败的附件：" + failed.join("、"));
  }
  return {
    ...res,
    storedIn:
      target.name +
      " → " +
      (target.children.find((c) => c.id === res.subcategory)?.name ||
        "仅存一级 / 待整理") + (mapResults.length ? " · " + mapResults.join("；") : ""),
  };
}
function planForm(n = {}, p) {
  const nextSeq = Math.min(
    100000,
    Math.max(0, ...p.pages.map((x) => x.seq)) + 10,
  );
  buildForm(
    "page",
    n.id ? "编辑一级页面" : "添加一级页面",
    n,
    buildInput("title", "导航显示名称", n.title, true) +
      buildInput("path", "页面路径，例如 /products/", n.path, true) +
      buildInput("keyword", "主关键词（保留完整原文）", n.keyword) +
      buildArea("notes", "页面用途", n.notes) +
      '<label class="field">导航顺序<input name="seq" type="number" min="1" max="100000" value="' +
      (n.seq || nextSeq) +
      '" required></label>' +
      buildSelect(
        "status",
        "页面状态",
        ["草案", "已确认", "已上线", "暂不采用"],
        n.status || "草案",
      ),
    { project: p.id },
  );
}
async function buildAction(action, t) {
  const id = Number(t.dataset.id),
    p = currentBuildProject;
  switch (action) {
    case "build-wiki-refresh":
      return load();
    case "build-wiki-prepare":
      return prepareWiki(p);
    case "build-wiki-toggle-auto":
      return toggleWikiAutomation(p);
    case "build-wiki-sync":
      return syncWikiProject(p, t);
    case "build-wiki-folders":
      return wikiFolders(p);
    case "build-wiki-add-folder":
      return addWikiFolder(p, t);
    case "build-wiki-file-pending":
      return wikiPendingForm(p, id);
    case "build-edit-map-work":
      return editMapWork(p);
    case "build-resume-codex":
      return showCodexHandoff(p);
    case "build-open-handoff":
      return openCodexHandoff(p, t);
    case "build-prepare-handoff":
      t.disabled = true;
      try {
        await post("build-archive-workcopy", {project:p.id});
        if (p === currentBuildProject) return showCodexHandoff(p);
      } finally {
        t.disabled = false;
      }
      return;
    case "build-page-bundle":
      return pageBundleForm(p);
    case "build-add-map-keyword":
      return mapKeywordForm();
    case "build-store-map-keyword":
    case "build-remove-map-keyword": {
      t.disabled = true;
      const store = action === "build-store-map-keyword";
      try {
        const result = await post("build-page-keywords", {
          project:p.id, key:p.mapKey, term:p.pageKeywords.keywords[id - 1].keyword,
          action:store ? "store" : "remove",
        });
        await load();
        return toast(store ? (result.duplicate ? "词库已有这个完整关键词" : "已加入行业词库") : "已移除本页关联");
      } finally {
        t.disabled = false;
      }
    }
    case "build-map-issue":
      return mapIssueForm(p, id);
    case "build-confirm-page-skill":
    case "build-remove-page-skill": {
      const remove = action === "build-remove-page-skill";
      t.disabled = true;
      try {
        const result = await post("build-archive-page-skill", {
          project:p.id, key:p.mapKey, answer:id, name:t.dataset.name, remove,
        });
        await load();
        if (!result.changed) return toast("本页关联已更新");
        return toast(remove ? "已移除本页关联" : "已关联本页技能及原文");
      } finally {
        t.disabled = false;
      }
    }
    case "build-choose-map-prompt":
    case "build-page-prompt-list":
      return chooseMapPrompt(p,t.dataset.query || "",Number(t.dataset.offset || 0));
    case "build-attach-map-prompt":
      await post("build-archive-page-record",{project:p.id,key:p.mapKey,attach:true,source:t.dataset.source,id});
      close();
      await load();
      return toast("提示词已关联到本页");
    case "build-all-prompts":
    case "build-step-prompts":
    case "build-prompts-prev":
    case "build-prompts-next":
    case "build-thread":
    case "build-thread-page":
    case "build-thread-original":
    case "build-back-prompts":
    case "build-prompt-answers":
    case "build-answer-text":
    case "build-prompt-original":
    case "build-reuse-site":
    case "build-folder-info":
    case "build-enable-folder":
    case "build-stop-folder":
    case "build-manage-chats":
    case "build-archive-turns":
    case "build-archive-turns-prev":
    case "build-archive-turns-next":
    case "build-archive-turns-return":
    case "build-archive-check":
    case "build-pick-chat":
    case "build-pause-chat":
    case "build-sync-now":
    case "build-receipt":
    case "build-guide-prompt":
    case "build-copy-text":
    case "build-issues":
    case "build-journal":
    case "build-journal-next":
    case "build-journal-prev":
    case "build-read-chat":
    case "build-read-note":
    case "build-resolve-note":
    case "build-capture-issue":
    case "build-capture-prompt":
    case "build-save-stage-prompt":
    case "build-capture-next":
      return guideAction(action.slice(6), t, p);
    case "build-inbox":
      return entryForm(
        {},
        0,
        industryId,
        areas.find((a) => a.id === 2),
        true,
      );
    case "build-area":
      return openArea(id);
    case "build-sub":
      return navigate("materials", { sub: String(id) });
    case "build-new-section":
      return newCategory(false);
    case "build-new-sub":
      return newCategory(true);
    case "build-new-material":
      return entryForm();
    case "build-material": {
      const owner = Number(t.dataset.ind);
      const e = await get("build-entry", { id, industry: owner });
      return entryForm(e, e.step, owner);
    }
    case "build-next-materials":
      return navigate("materials", {
        ...filt,
        trail: [
          ...(filt.trail || []),
          { before: t.dataset.before, lastindustry: t.dataset.ind, lastid: id },
        ],
      });
    case "build-prev-materials":
      return navigate("materials", { ...filt, trail: filt.trail.slice(0, -1) });
    case "build-industry":
      return changeIndustry(id, "library");
    case "build-new-project":
      return projectForm();
    case "build-edit-project":
      return projectForm(p);
    case "build-new-step":
      return stepForm({}, p.id);
    case "build-edit-step":
      return stepForm(
        p.steps.find((s) => s.id === id),
        p.id,
      );
    case "build-new-entry":
      return entryForm({}, id);
    case "build-edit-entry": {
      const e = await get("build-entry", { id });
      return entryForm(e, e.step);
    }
    case "build-new-page":
      return planForm({}, p);
    case "build-edit-page":
      return planForm(
        p.pages.find((n) => n.id === id),
        p,
      );
    case "build-find-word":
      return navigate("words", { q: p.pages.find((n) => n.id === id).keyword });
    case "build-finish-step":
      return advanceStep(p, id, true, t);
    case "build-resume-step":
      return advanceStep(p, id, false, t);
    case "build-go-skills":
      return navigate("skills", { project: id });
    case "build-new-skill":
      return skillForm({}, p.id);
    case "build-edit-skill":
      return skillForm(
        p.skills.find((s) => s.id === id),
        p.id,
      );
    case "build-switch-site":
      return selectBuildProject("buildhub", Number(t.dataset.industry), id);
    case "build-go-steps":
      return navigate("workflows", { project: id });
    case "build-go-plan":
      return navigate("siteplan", { project: id });
  }
}
async function submitBuild(form, values) {
  if (form.dataset.form === "build-wiki-file-pending") return saveWikiPending(form, values);
  if (form.dataset.form === "build-map-keyword") {
    const p = currentBuildProject;
    const submit = form.querySelector("[type=submit]");
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      const result = await post("build-page-keywords", {
        project:p.id, key:p.mapKey, term:values.term, action:"add",
      });
      close();
      await load();
      toast(result.changed ? "已保存本页关键词" : "本页已有这个完整关键词");
    } finally {
      submit.disabled = false;
    }
    return;
  }
  if (form.dataset.form === "build-map-prompt-search")
    return chooseMapPrompt(currentBuildProject, values.query || "");
  if (form.dataset.form === "build-page-issue") {
    const submit = form.querySelector("[type=submit]");
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      const result = await post("build-archive-page-issue", values);
      close();
      await load();
      toast(result.duplicate ? "本页已有相同的问题" :
        Number(values.id) ? "已保存解决办法" : "已把问题记到本页和项目");
    } finally {
      submit.disabled = false;
    }
    return;
  }
  if (form.dataset.form === "build-map-work") {
    const p = currentBuildProject;
    const submit = form.querySelector("[type=submit]");
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      await post("build-archive-page-record",{...values,project:p.id,key:p.mapKey,version:p.pageRecord.work?.version || 0});
      close();
      await load();
      toast("已保存本页进度与待办");
    } finally {submit.disabled = false;}
    return;
  }
  if (
    [
      "build-bind-chat",
      "build-capture",
      "build-resolve",
      "build-journal-search",
      "build-prompt-search",
      "build-thread-search",
      "build-reuse",
    ].includes(form.dataset.form)
  )
    return guideSubmit(form, values);
  if (form.dataset.form === "build-quick") {
    const button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    try {
      await storeStepNote(
        Number(form.dataset.project),
        Number(form.dataset.step),
      );
      await load();
      toast("记录已存入本步骤");
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (form.dataset.form === "build-find-words") return findWords(values.query);
  if (form.dataset.form === "build-search")
    return navigate("materials", {
      find: values.find,
      scope: values.scope || "all",
      sub: values.sub,
    });
  if (["build-section", "build-subsection"].includes(form.dataset.form)) {
    const result = await post(form.dataset.form.slice(6), values);
    close();
    await refreshAreas();
    if (form.dataset.form === "build-section") return openArea(result.id);
    navigate("materials", { sub: String(result.id) });
    return;
  }
  const button = form.querySelector("button[type=submit]");
  if (button.disabled) return;
  button.disabled = true;
  modalBusy = true;
  try {
    if (form.elements.template)
      values.template = form.elements.template.checked;
    const action = form.dataset.form;
    const [section, owner] = action === "build-project" && values.destination
      ? values.destination.split("/").map(Number) : [activeAreaId, industryId];
    if (action === "build-project") delete values.destination;
    const res =
      action === "build-entry"
        ? await saveEntry(form, values)
        : await post(action, values, { section, industry: owner });
    modalBusy = false;
    close();
    if (action === "build-project") selectBuildProject(view, owner, res.id, section);
    else if (action === "build-skill")
      navigate("skills", { project: Number(values.project) });
    else await load();
    toast(res.storedIn ? "已保存到 " + res.storedIn : "已保存");
  } finally {
    modalBusy = false;
    button.disabled = false;
  }
}
document.addEventListener("change", (e) => {
  if (e.target.name === "kind" && e.target.closest('[data-form="build-entry"]'))
    $("#custom-build-kind").hidden = e.target.value !== "__custom";
  if (e.target.id === "build-project-selector") {
    const [owner, project] = e.target.value.split("/").map(Number);
    selectBuildProject(view, owner, project);
  }
});
