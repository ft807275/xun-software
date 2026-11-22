"use strict";

const stageGuides = {
  项目需求: [
    "写下你的主推产品、买家和网站目标。",
    "请把我提供的产品、客户和目标整理成一份建站需求。缺少的信息请逐项问我。",
    "能用一句话说清楚卖什么、卖给谁，以及希望客户做什么。",
  ],
  关键词与同行: [
    "从行业词库挑出主推产品的词，再看哪些同行页面已经有流量。",
    "请整理这个行业已有的关键词和同行网站，把主推产品词、搜索意图和对应的同行排名网址列在一起。",
    "每个主推产品都有目标词和可参考的同行页面。",
  ],
  网站架构与一级栏目: [
    "先定首页导航，再给每个栏目指定用途和主关键词。",
    "请根据已选关键词规划官网一级栏目，逐项列出页面名称、路径、用途和主关键词。",
    "可以按这份清单逐页开始制作。",
  ],
  页面内容与配图: [
    "先选一个页面，准备它的文字、产品参数和图片。",
    "请按已确认的栏目逐页列出需要的文案和配图，先给我一个页面草稿，标出缺少的真实产品资料。",
    "该制作的页面已有可用文案和对应的图片。",
  ],
  设计与开发: [
    "先完成一个样板页，在电脑和手机上核对，再做其余页面。",
    "请根据已确认的文案和配图制作一个样板页，说明如何预览，并记录我的修改意见。",
    "关键页面可以打开，手机布局和主要操作已核对。",
  ],
  验收与上线: [
    "依次试一下导航、手机页面和询价表单，记录测试结果。",
    "请逐项检查导航、手机显示、询价表单与上线网址，列出实际测试结果和仍需处理的问题。",
    "已验证的上线网址、表单测试结果和遗留问题都已记录。",
  ],
  选品与客户定位: [
    "选一个主推商品，写出买家、使用场景和价位。",
    "请帮我把主推商品、目标买家、定价依据和购买场景整理成开店简报。",
    "主推商品、买家和价位已确认。",
  ],
  关键词与竞店: [
    "挑选商品词，保留同类店铺的商品链接和参考点。",
    "请把已收集的商品词和竞店页面整理成一份选词清单。",
    "商品词能对应到具体商品或集合。",
  ],
  商品详情与配图: [
    "准备规格、款式、价格和实物图。",
    "请根据真实资料整理商品详情页，列出仍缺的图片和规格。",
    "商品可凭现有资料制作详情页。",
  ],
  "支付、配送与退换": [
    "逐项确认收款方式、配送范围、运费和退换条件。",
    "请帮我整理结账、配送和退换的设置清单。",
    "买家能找到支付方式、配送范围和退换条件。",
  ],
  下单测试与上线: [
    "从选商品到订单通知，完整测试一次。",
    "请记录测试订单每一步的结果，以及上线前仍需解决的问题。",
    "测试订单、结账和通知均有验证记录。",
  ],
};
const activeStep = (p) =>
  p.steps.find((s) => s.id === p.nextTaskStep && s.status !== "已完成") ||
  p.steps.find((s) => s.status === "进行中") ||
  p.steps.find((s) => s.status !== "已完成");
function guideFor(s) {
  return (
    stageGuides[s.title] || [
      s.notes || "写下这一步需要做的事。",
      "请帮我推进「" +
        s.title +
        "」。" +
        (s.notes || "先问我需要哪些资料，再记录决定和下一步。"),
      "本步的结果和仍待处理的问题已经记入项目。",
    ]
  );
}
function cooperation(p) {
  return (
    "这个项目叫「" +
    p.name +
    "」。项目步骤依次是 " +
    p.steps.map((s) => s.title).join("、") +
    "。\n每次实际推进后，请在最终回复末尾另起一行，填写实际项目名、步骤名和状态，使用全角分隔符。例如：\n【建站进度】" +
    p.name +
    "｜" +
    (activeStep(p)?.title || p.steps[0]?.title || "步骤名称") +
    "｜进行中\n【下次继续】写清下次要做的一件事\n如遇到未解决的问题，可另起一行写【待解决】和问题。做完并核实该步骤后把状态写为「已完成」。每次回报一个步骤，使用实际结果；只是讨论计划时不用报完成。"
  );
}
function copyBox(title, body, extra = "", copyLabel = "复制原文", rows = 11) {
  dialog(
    title,
    '<label class="field">原文<textarea id="archive-copy" rows="' + rows + '" readonly></textarea></label>' +
      '<button class="primary" type="button" data-action="build-copy-text">' + esc(copyLabel) + '</button>' +
      extra,
  );
  $("#archive-copy").value = body ?? "";
}
async function copyArchiveText(announce = true) {
  const field = $("#archive-copy");
  const details = field.closest("details");
  if (details) details.open = true;
  field.select();
  try {
    await navigator.clipboard.writeText(field.value);
  } catch {
    if (!document.execCommand("copy")) {
      toast("原文已选中，可以按复制快捷键。");
      return false;
    }
  }
  if (announce) toast("已复制，可以粘贴到 Codex");
  return true;
}
function journalRows(items) {
  return items
    .map(
      (r) =>
        '<button class="journal-row" type="button" data-action="build-' +
        (r.src === "chat" ? "read-chat" : "read-note") +
        '" data-id="' +
        r.id +
        '"><span class="journal-meta">' +
        esc(
          [
            r.kind,
            r.unresolved ? "待解决" : "",
            r.step || "项目记录",
            r.created,
          ]
            .filter(Boolean)
            .join(" · "),
        ) +
        "</span><strong>" +
        esc(r.title) +
        "</strong></button>",
    )
    .join("");
}
function guideLinks() {
  return (
    '<details class="guide-resources"><summary>栏目规划和分类资料</summary><div class="step-actions"><button type="button" class="secondary" data-view="materials">建站资料库</button>' +
    (currentBuildProject
      ? buildButton(
          "go-plan",
          "官网一级栏目规划",
          "secondary",
          currentBuildProject.id,
        )
      : "") +
    buildButton("new-sub", "添加二级类目") +
    "</div>" +
    subButtons() +
    "</details>"
  );
}
async function readProjectMap(project) {
  const entry = project.steps.flatMap(step => step.entries || [])
    .filter(item => item.title === "网站地图 · 官网与规划快照")
    .sort((a, b) => b.id - a.id)[0];
  if (!entry) return null;
  const note = await get("build-entry", { id: entry.id });
  const file = note.files.find(item => item.filename === "网站地图.json");
  if (!file) throw Error("地图附件缺失");
  const response = await fetch("/api/build-file?" + qs({ id: file.id }), { cache: "no-store" });
  if (!response.ok) throw Error("地图附件读取失败");
  const data = await response.json();
  if (data.version !== 1 || !Array.isArray(data.live) || !Array.isArray(data.plan)) throw Error("地图格式无法识别");
  if (!project.site || new URL(project.site).origin !== new URL(data.site).origin) return null;
  return data;
}

function mapRoute(path) {
  return typeof path === "string" && path.startsWith("/") && !path.startsWith("//") && !/[\\?#\s]/.test(path);
}

function mapRows(project, mode) {
  const snapshot = project.mapSnapshot;
  const liveMode = mode === "live" && snapshot;
  const planned = new Map();
  if (liveMode) {
    const order = new Map(project.pages.map((page,index) => [page.path,index]));
    const live = snapshot.live.filter(row => mapRoute(row.path)).slice()
      .sort((a,b) => (order.get(a.path) ?? 9999) - (order.get(b.path) ?? 9999));
    for (const row of live) planned.set(row.path,{...row,id:row.path,status:""});
  } else {
    for (const row of snapshot?.plan || []) planned.set(row.id,{...row,status:"",sourcePlan:true});
    for (const page of project.pages) {
      const prior = planned.get(page.path);
      planned.set(page.path, { ...prior, id:page.path, path:page.path, title:page.title, status:page.status,
        parent:prior?.parent || "", userPage:true });
    }
  }
  for (const item of project.importedPages || []) {
    const alias = item.path === "/" ? "/" : item.path.replace(/\/$/, "");
    const key = planned.has(alias) ? alias : item.path;
    const prior = planned.get(key);
    if (liveMode && prior) continue;
    planned.set(key, { ...prior, id:key, path:item.path,
      title:item.title || prior?.title || (item.path === "/" ? "首页" : item.path.split("/").filter(Boolean).pop()),
      parent:item.parent || prior?.parent || "", userPage:true });
  }
  for (const row of planned.values()) {
    if (row.parent && !planned.has(row.parent)) row.parent = "";
    if (!row.userPage || row.parent || !mapRoute(row.path)) continue;
    const parts = row.path.split("/").filter(Boolean);
    while (parts.length > 1) {
      parts.pop();
      const parent = "/" + parts.join("/") + "/";
      if (planned.has(parent)) { row.parent = parent; break; }
    }
  }
  // Imported parent links can come from hand-authored files.
  for (const row of planned.values()) {
    const seen = new Set([row.id]);
    let next = row.parent;
    while (next) {
      if (seen.has(next)) { row.parent = ""; break; }
      seen.add(next);
      next = planned.get(next)?.parent;
    }
  }
  return [...planned.values()].sort((a,b) => Number(b.id === "/") - Number(a.id === "/"));
}

function mapWorkKey(row) {
  if (!mapRoute(row.path)) return row.id;
  return row.path.replace(/\/+$/, "") + (row.path.split("/").at(-1).includes(".") ? "" : "/");
}

function siteMapPage(project) {
  return '<section class="map-browser map-page" aria-label="项目网站地图"><header class="map-heading"><div><h2>' +
    esc(project.name) + '</h2></div><div class="step-actions"><label class="secondary map-file-label">导入网站资料<input title="可多选网站 ZIP、地图清单或含页面路径的建站文档" type="file" multiple accept=".zip,.json,.xml,.csv,.xlsx,.md,.txt,.docx" data-map-files></label><a class="text-button" href="#buildhub/' + project.id + '">查看项目进度</a></div></header><p aria-live="polite" data-map-import-result hidden></p>' +
    (project.mapError ? '<p class="notice">官网快照读取失败，当前显示已保存的栏目规划。</p>' : '') +
    '<div class="map-controls">' +
    (project.mapSnapshot ? '<div class="map-tabs" role="group" aria-label="地图来源"><button type="button" data-map-mode="live">官网页面</button><button type="button" data-map-mode="plan">栏目规划</button></div>' : '') +
    '<input type="search" aria-label="搜索地图" placeholder="搜索页面名称或网址路径">' +
    '<select aria-label="筛选页面进度" data-map-work-filter><option value="">全部页面</option>' +
    '<option value="todo">有待办</option><option value="untracked">进度待记录</option></select></div>' +
    '<div class="map-heading"><p class="map-summary" aria-live="polite"></p><button class="text-button" type="button" data-map-expand>展开全部</button></div>' +
    '<div class="map-tree"></div><div class="map-footer"><a class="text-button" href="#siteplan/' +
    project.id + '">编辑项目栏目</a>' + pageTasksLink(project, "text-button") + '</div></section>';
}

function bindMapTree(box, project) {
  const saved = history.state?.mapTree || {};
  let mode = saved.mode === "plan" || !project.mapSnapshot ? "plan" : "live";
  let closed = new Set(saved.closed || []);
  const input = box.querySelector('input[type="search"]');
  const workFilter = box.querySelector("[data-map-work-filter]");
  const tree = box.querySelector(".map-tree");
  const expand = box.querySelector("[data-map-expand]");
  input.value = saved.query || "";
  workFilter.value = saved.workFilter || "";
  function remember(link) {
    history.replaceState({...history.state, mapTree: {
      mode, query: input.value, workFilter: workFilter.value, closed: [...closed], focus: link?.dataset.key, scroll: window.scrollY
    }}, "");
  }
  function draw() {
    const rows = mapRows(project, mode);
    const byParent = new Map();
    for (const row of rows) {
      const parent = row.parent || "";
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(row);
    }
    const query = input.value.trim().toLocaleLowerCase();
    const filter = workFilter.value;
    const planned = new Map(project.pages.map(row => [mapWorkKey(row), row.status]));
    let matches = 0;
    let withTasks = 0;
    let withoutProgress = 0;
    function render(row, ancestors) {
      if (ancestors.has(row.id)) return "";
      const next = new Set(ancestors).add(row.id);
      const children = (byParent.get(row.id) || []).map(child => render(child, next)).join("");
      const path = mapWorkKey(row);
      const work = Object.hasOwn(project.mapWork, path) ? project.mapWork[path] : {};
      const hasTasks = Boolean(work.todo || work.issues);
      const untracked = Boolean(mapRoute(row.path) && !work.stage);
      if (hasTasks) withTasks++;
      if (untracked) withoutProgress++;
      const textMatches = !query || (row.title + " " + (row.path || "")).toLocaleLowerCase().includes(query);
      const match = textMatches && (!filter || (filter === "todo" ? hasTasks : untracked));
      if (match) matches++;
      if (!match && !children) return "";
      const key = esc(row.id);
      const open = !closed.has(row.id);
      const toggle = children ? '<button class="node-toggle" type="button" data-toggle-node="' + key +
        '" aria-expanded="' + open + '" aria-label="' + esc((open ? "收起" : "展开") + row.title) + '">' +
        (open ? "▾" : "▸") + '</button>' : '<span class="node-dot" aria-hidden="true">•</span>';
      const href = "#sitemap/" + project.id + "/" + mode + "/" + encodeURIComponent(row.id);
      const stage = work.stage || planned.get(path) || (untracked ? "进度待记录" : "");
      const labels = (stage ? '<span class="map-node-stage">' + esc(stage) + '</span>' : '') +
        (work.issues ? '<span class="map-node-pending">' + fmt(work.issues) + ' 项待处理</span>' : '') +
        (work.todo && filter !== "todo" ? '<span class="map-node-pending">有待办</span>' : '');
      const details = match && filter === "todo" && work.todo ? '<div class="map-task-preview">' +
        '<p>' + esc(work.todo) + '</p>' + nextTaskOriginal({...project, mapPath:row.path}, work.todoSource) + '</div>' : '';
      return '<li' + (match ? ' data-map-match' : '') + '><div class="node-line">' + toggle + '<a class="map-node-link" data-key="' + key + '" href="' +
        esc(href) + '">' + esc(row.title) + '</a>' + (row.path ? '<span class="node-path">' + esc(row.path) + '</span>' : '') +
        (match && labels ? '<div class="map-node-labels">' + labels + '</div>' : '') + '</div>' + details +
        (children ? '<ul' + (open ? '' : ' hidden') + '>' + children + '</ul>' : '') + '</li>';
    }
    const html = (byParent.get("") || []).map(row => render(row,new Set())).join("");
    tree.innerHTML = html ? '<ul>' + html + '</ul>' : '<p>' + (query || filter ? '没有符合当前筛选的页面。' : '还没有栏目，可以从下方开始规划。') + '</p>';
    workFilter.options[1].textContent = "有待办（" + fmt(withTasks) + "）";
    workFilter.options[2].textContent = "进度待记录（" + fmt(withoutProgress) + "）";
    box.querySelector(".map-summary").textContent = query || filter ? "找到 " + fmt(matches) + " 项" :
      (mode === "live" ? project.mapSnapshot.date + " 核查 · " + fmt(project.mapSnapshot.live.length) + " 个页面" + (rows.length > project.mapSnapshot.live.length ? "，另有 " + fmt(rows.length-project.mapSnapshot.live.length) + " 个导入页面" : "") : fmt(rows.length) + " 项栏目与内容主题") +
      "。点页面名称查看进度、待办和提示词。";
    const controls = [...tree.querySelectorAll("[data-toggle-node]")];
    expand.hidden = controls.length === 0;
    expand.textContent = controls.every(el => el.getAttribute("aria-expanded") === "true") ? "收起全部" : "展开全部";
    box.querySelectorAll("[data-map-mode]").forEach(el => el.setAttribute("aria-pressed", String(el.dataset.mapMode === mode)));
  }
  const picker = box.querySelector("[data-map-files]");
  picker.addEventListener("change", async () => {
    const results = box.querySelector("[data-map-import-result]");
    const scope = qs({project:project.id});
    const messages = [];
    picker.disabled = true;
    results.hidden = false;
    for (const file of Array.from(picker.files)) {
      results.textContent = "正在整理 " + file.name + "…";
      try {
        const stats = await fetch("/api/build-map-import?" + scope + "&filename=" + encodeURIComponent(file.name),
          {method:"POST",body:file}).then(check);
        messages.push(file.name + " · 已整理 " + stats.pages + " 页，新增 " + stats.addedPrompts + " 条提示词关联" +
          (stats.skipped ? "，跳过 " + stats.skipped + " 条其他域名或无效路径" : ""));
      } catch(err) { messages.push(file.name + " · " + err.message); }
    }
    try {
      const [updated, work] = await Promise.all([get("build-project", {id:project.id}),
        get("build-archive-map-work", {project:project.id})]);
      project.importedPages = updated.importedPages;
      project.mapWork = work;
      closed.clear(); input.value = ""; draw(); remember();
    } catch(err) { messages.push(err.message); }
    results.textContent = messages.join("　");
    picker.value = ""; picker.disabled = false;
  });
  tree.addEventListener("click", e => {
    const link = e.target.closest(".map-node-link");
    if (link) { remember(link); return; }
    const toggle = e.target.closest("[data-toggle-node]");
    if (!toggle) return;
    const key = toggle.dataset.toggleNode;
    if (closed.has(key)) closed.delete(key); else closed.add(key);
    draw();
    [...tree.querySelectorAll("[data-toggle-node]")].find(el => el.dataset.toggleNode === key)?.focus({preventScroll:true});
  });
  expand.addEventListener("click", () => {
    const controls = [...tree.querySelectorAll("[data-toggle-node]")];
    closed = controls.some(el => el.getAttribute("aria-expanded") === "false") ? new Set() : new Set(controls.map(el => el.dataset.toggleNode));
    draw();
  });
  box.querySelectorAll("[data-map-mode]").forEach(el => el.addEventListener("click", () => {
    mode = el.dataset.mapMode;
    closed.clear();
    draw();
  }));
  workFilter.addEventListener("change", () => {closed.clear(); draw(); remember();});
  input.addEventListener("input", () => {closed.clear(); draw();});
  draw();
  if (saved.focus) {
    [...tree.querySelectorAll(".map-node-link")].find(el => el.dataset.key === saved.focus)?.focus({preventScroll:true});
    window.scrollTo(0,saved.scroll || 0);
  }
}

function mapKeywordSection(data) {
  const entries = data.keywords.map((item, index) => {
    const main = item.keyword === data.main;
    const url = "/?" + qs({section:1}) + "#words/search/" + encodeURIComponent(item.keyword) + "/" + item.id;
    const title = item.id ? '<a href="' + esc(url) + '">' + esc(item.keyword) + '</a>' : esc(item.keyword);
    const details = [main ? "主关键词" : "补充词", item.status, item.market,
      item.traffic == null ? "" : "自然流量 " + fmt(item.traffic),
      item.dr == null ? "" : "DR " + fmt(item.dr)].filter(Boolean).join(" · ");
    return '<li><div><strong>' + title + '</strong><small>' + esc(details) + '</small></div><div class="step-actions">' +
      (item.id ? "" : buildButton("store-map-keyword", "加入行业词库", "secondary", index + 1)) +
      (main ? "" : buildButton("remove-map-keyword", "移除关联", "text-button", index + 1)) +
      '</div></li>';
  }).join("");
  return '<section><div class="map-heading"><h3>页面关键词</h3>' +
    buildButton("add-map-keyword", "补充关键词", "secondary") + '</div>' +
    (entries ? '<ul class="page-keywords">' + entries + '</ul>' : '<p>这页还没有保存关键词。</p>') + '</section>';
}

function mapKeywordForm() {
  dialog("补充本页关键词", '<form class="form-grid" data-form="build-map-keyword">' +
    '<label class="field full">完整关键词<input name="term" required maxlength="1000"></label>' +
    '<p class="field full inline-hint">词库里已有完全相同的词时，会直接显示它的指标和来源入口。</p>' +
    '<div class="field full"><button class="primary" type="submit">保存到本页</button></div></form>');
}

function mapPageSkills(record) {
  const rows = (items, confirmed) => '<ul class="skill-history">' + items.map(item => {
    const attrs = 'data-id="' + Number(item.answer) + '" data-name="' + esc(item.name) + '"';
    const actions = confirmed
      ? '<small>' + esc([item.used,item.origin].filter(Boolean).join(" · ")) + '</small>' +
        (item.origin === "已核对历史原文" ? btn("build-remove-page-skill","移除关联","text-button",attrs) : "")
      : btn("build-confirm-page-skill","关联到本页","secondary",attrs);
    return '<li><strong>' + esc(item.name) + '</strong><p>' + esc(item.detail) + '</p><div class="step-actions">' +
      buildButton("read-chat","查看回复原文","text-button",item.answer) + actions + '</div></li>';
  }).join("") + '</ul>';
  return '<section class="page-skill-section"><h3>本页用过的技能（' + fmt(record.skills.length) + '）</h3>' +
    (record.skills.length ? rows(record.skills,true) : '<p>本页还没有已确认的技能使用记录。</p>') +
    (record.relatedSkills.length ? '<details><summary>待核对的历史技能（' + fmt(record.relatedSkills.length) +
      '）</summary>' + rows(record.relatedSkills,false) + '</details>' : '') + '</section>';
}

function mapWorkPage(project, row, record) {
  const work = record.work;
  const updates = record.automatic || [];
  const latest = updates[0];
  const current = record.current;
  const useLatest = latest && current?.answer === latest.answer;
  const live = project.mapSnapshot?.live.some(item => item.path === row.path);
  const plan = row.path && project.pages.find(item => item.path === row.path);
  const stage = current?.stage || plan?.status || (live ? "官网快照已收录，制作阶段待记录" : "待记录");
  const source = useLatest ? "" :
    work?.source || (plan ? "项目栏目规划" : live ? "官网快照 · " + project.mapSnapshot.date : "");
  const website = live && mapRoute(row.path) ? safeLink(new URL(row.path, project.mapSnapshot.site).href,"打开官网页面 ↗") : "";
  const promptRows = list => list.map(item => btn("build-prompt-original",esc(item.label),"journal-row",
    'data-id="' + Number(item.id) + '" data-source="' + esc(item.source) + '"')).join("");
  const prompts = promptRows(record.prompts);
  const pending = record.issues.filter(item => !item.resolution.trim());
  const finished = record.issues.filter(item => item.resolution.trim());
  const issueRows = (list, solved = false) => list.map(item =>
    '<li class="map-issue"><details data-remember="issue-' + item.id + '"><summary>' + esc(item.title) + '</summary>' +
    (item.stepTitle ? '<small>' + esc(item.stepTitle) + '</small>' : '') +
    (item.title !== item.body ? '<p class="work-todo">' + esc(item.body) + '</p>' : '') +
    (solved ? '<p class="work-todo"><strong>解决办法</strong> ' + esc(item.resolution) + '</p>' : '') +
    (item.kind === "问题" && mapRoute(row.path) ?
      buildButton("map-issue", solved ? "编辑解决办法" : "填写解决办法", "text-button", item.id) : '') +
    '</details></li>').join("");
  const auditEntry = (item, showProgress) =>
    '<article class="map-audit' + (filt.answer === item.answer ? ' linked-receipt" tabindex="-1">' : '">') +
    '<small>' + esc(item.updated + " · " + item.origin) + '</small>' +
    (showProgress ? '<p><strong>' + esc(item.stage) + '</strong></p>' : '') +
    '<p class="work-todo">' + esc(item.evidence) + '</p>' +
    (item.issue && (item !== latest || !record.issues.some(issue => issue.body === item.issue)) ?
      '<p class="work-todo"><strong>这次记录的问题</strong> ' + esc(item.issue) + '</p>' : '') +
    (showProgress && item.todo ? '<p class="work-todo"><strong>当时的下一件事</strong> ' + esc(item.todo) + '</p>' : '') +
    '<div class="step-actions">' +
    (item.prompt ? buildButton("read-chat", "本轮提示词", "secondary", item.prompt) : '') +
    buildButton("read-chat", "Codex 回复原文", "secondary", item.answer) +
    (item.wikiSlug ? '<a class="secondary" href="' + esc(wikiPageRoute(project.id, item.wikiSlug, item.answer)) +
      '" title="' + esc(item.wikiTopic) + '">查看对应知识更新</a>' : '') + '</div></article>';
  const showHistory = updates.slice(1).some(item => item.answer === filt.answer);
  return '<article class="map-page page-work"><small>' + esc(project.name) + '</small><header class="map-heading"><h2>' +
    esc(row.title) + '</h2><div class="step-actions">' +
    buildButton("resume-codex", "让 Codex 接着做", "primary") +
    (mapRoute(row.path) ? buildButton("page-bundle", "下载本页资料") : '') + website +
    '</div></header><div class="map-path">' + esc(row.path || "规划中的内容主题") + '</div>' +
    '<section><div class="map-heading"><h3>页面进度</h3>' + buildButton("edit-map-work","更新进度与待办","text-button") +
    '</div><strong>' + esc(stage) + '</strong>' + (source ? '<p class="work-source">来源 · ' + esc(source) + '</p>' : '') + '</section>' +
    '<section><div class="map-heading"><h3>接下来要做</h3>' +
    (mapRoute(row.path) && project.steps.length ? buildButton("map-issue","记录本页问题","secondary") : '') +
    '</div><p class="work-todo">' + esc(current?.todo || (pending.length ? "" : "这页还没有已记录的待办。")) + '</p>' +
    nextTaskOriginal(project, record.todoSource) +
    (pending.length ? '<ul class="map-issue-list">' + issueRows(pending) + '</ul>' : '') +
    (finished.length ? '<details data-remember="finished-issues"><summary>已处理的问题（' + finished.length + '）</summary><ul class="map-issue-list">' +
      issueRows(finished, true) + '</ul></details>' : '') + '</section>' +
    (project.pageKeywords ? mapKeywordSection(project.pageKeywords) : '') +
    (latest ? '<section class="map-audit-section"><h3>最近一次 Codex 页面记录</h3>' + auditEntry(latest, !useLatest) +
      (updates.length > 1 ? '<details data-remember="page-history"' + (showHistory ? ' open' : '') + '><summary>查看此前页面记录（' + (updates.length - 1) + '）</summary>' +
        updates.slice(1).map(item => auditEntry(item, true)).join("") + '</details>' : '') +
      (useLatest && work ? '<details data-remember="page-original"><summary>查看原有页面记录</summary><p>' +
        esc(work.stage) + '</p><p class="work-todo">' + esc(work.todo) + '</p></details>' : '') + '</section>' : '') +
    (mapRoute(row.path) ? mapPageSkills(record) : "") +
    '<section><div class="map-heading"><h3>本页用过的提示词（' + fmt(record.prompts.length) + '）</h3>' +
    buildButton("choose-map-prompt","关联项目提示词","text-button") + '</div>' +
    (prompts || '<p>项目资料里还没有确认用于本页的原文。</p>') + '</section>' +
    (record.related.length ? '<section><details><summary>提到本页、待核对的提示词（' + record.related.length + '）</summary>' +
      promptRows(record.related) + '</details></section>' : '') + '</article>';
}

function editMapWork(p) {
  const work = p.pageRecord.current;
  dialog("更新页面进度与待办", '<form class="form-grid" data-form="build-map-work">' +
    buildInput("stage","这页做到哪一步", work?.stage || "",true) +
    buildArea("todo","接下来要做",work?.todo || "") +
    '<div class="field full"><button type="submit" class="primary">保存到本页</button></div></form>');
}

function mapIssueForm(p, id) {
  const parent = {project:p.id, key:p.mapKey};
  if (id) {
    const issue = p.pageRecord.issues.find(item => item.id === id && item.kind === "问题");
    if (!issue) throw Error("找不到本页的这条问题。");
    return buildForm("page-issue", issue.resolution ? "编辑解决办法" : "填写解决办法", issue,
      '<p class="field full build-copy">' + esc(issue.body) + '</p>' +
      buildArea("resolution", "解决办法", issue.resolution, true), parent);
  }
  const recent = p.pageRecord.automatic?.[0];
  const step = p.steps.find(item => item.id === recent?.step) || activeStep(p) || p.steps.at(-1);
  return buildForm("page-issue", "记录本页问题", {},
    '<p class="field full">' + esc(p.mapTitle) + '</p>' +
    '<label class="field">相关步骤<select name="step" required>' +
    p.steps.map(item => option(item.id, item.title, step?.id)).join("") + '</select></label>' +
    buildArea("body", "遇到的问题", "", true), parent);
}

function codexHandoffFields(p, context) {
  const record = context?.record || p.pageRecord;
  const current = record?.current;
  const latest = record ? record.automatic?.[0] : p.recentTurn;
  const step = activeStep(p);
  const assets = context?.assets;
  const handoff = {
    previousProjectStep:(record && latest?.stepTitle) || step?.title || "",
    stage:current?.stage || context?.page?.status || step?.status || "",
    nextTask:record ? current?.todo || "" : p.nextTask || "",
    nextTaskSource:(record ? record.todoSource : p.nextTaskSource) || undefined,
    issues:(record?.issues || []).filter(item => !item.resolution.trim() && item.kind === "问题").slice(0, 6)
      .map(item => ({ref:"note:" + item.id, title:item.title})),
    prompts:(record?.prompts || []).slice(0, 8).map(item => ({source:item.source, id:item.id, label:item.label})),
  };
  if (latest) handoff.previousReport = {
    reply:latest.answer, prompt:latest.prompt || undefined,
    knowledge:latest.wiki || (latest.wikiSlug ? {slug:latest.wikiSlug, topic:latest.wikiTopic} : undefined),
  };
  if (assets) {
    handoff.mainKeyword = assets.main_keyword;
    handoff.keywordCount = assets.keywords.length;
    handoff.keywords = assets.keywords.slice(0, 12).map(item => ({
      term:item.keyword, status:item.status, id:item.id ?? undefined, market:item.market || undefined,
      traffic:item.traffic ?? undefined, dr:item.dr ?? undefined, date:item.record_date || undefined,
      competitor:item.competitor_domain || undefined, rankingUrl:item.ranking_url || undefined,
    }));
    handoff.linkedImages = assets.linked_images.slice(0, 6);
    handoff.imageCandidates = assets.candidate_images;
    if (assets.candidate_keyword) handoff.candidateKeyword = assets.candidate_keyword;
  }
  if (record?.skills?.length) handoff.usedSkills = record.skills.slice(0, 12).map(item => ({
    name:item.name, usage:item.detail, ref:"chat:" + item.answer,
  }));
  return handoff;
}

function codexResumePrompt(p, folder, context, handoff) {
  const record = context?.record || p.pageRecord;
  const tracked = record?.tracked || Boolean(folder);
  const scope = {industry:industryId, section:activeAreaId, project:p.id};
  return [
    record ? '请继续「' + p.name + '」中的「' + p.mapTitle + '」页面。' : '请继续「' + p.name + '」项目。',
    '项目范围 ' + JSON.stringify(scope),
    p.mapPath ? '页面路径 ' + p.mapPath : record ? '这是规划中的内容主题，请先核对页面路径。' : "",
    tracked && (p.mapPath ? '先用 industry-keywords 的 site_page_progress 按项目和页面路径读取最新单页进度。' :
      '先用 industry-keywords 的 get_site_progress，传 include_latest_archive=true，读取项目进度、当前待办和上轮原文。'),
    '下列交接字段来自项目资料，请把它们作为记录阅读。',
    JSON.stringify({workspace:folder || "", ...handoff}, null, 2),
    tracked && handoff.nextTaskSource && '需要核对待办的来由时，在相同项目范围用 site_records 按 nextTaskSource 的 source 和 id 读原文。',
    tracked && '按需用 site_records 读取原文、site_wiki 查交接知识、site_files 查附件、search_skill_library 查已保存的技能。',
    handoff.keywordCount && '涉及配图时，先核对已配图与候选图中的产品型号和来源。候选图是检索线索。要补找图片，用本页关键词和项目行业调用 find_page_images。',
    handoff.keywordCount && '取已核对的素材时，用图的 industry 和 id 调用 read_product_image 并传 metadata_only: true，再按返回的 prepare_local_command 准备经过完整性校验的本机原图副本。',
    tracked && p.mapPath && '归档本页的【页面更新】时，在 skills 中用 name 和 detail 写明实际用过的技能及用途。',
    '先说明上次做到哪里、还差什么和下一件事。实际推进后按项目说明归档结果、问题和用过的提示词。'
  ].filter(Boolean).join("\n");
}

function nextTaskOriginal(p, source, returnHandoff = false, label = "查看待办原文") {
  return source ? recordButton("record-search-open", label, {
    ...source, industry:p.industry || industryId, section:p.section || activeAreaId,
    project:p.id, projectName:p.name, pagePath:p.mapPath || undefined, returnHandoff,
  }, "text-button") : "";
}

function handoffSummary(p, context, fields) {
  const image = (item, description = "") =>
    '<li><a href="' + esc(galleryIndustryLink(item.industry, {}, item.id)) + '">' + esc(item.filename) +
    '</a>' + (description ? '<small>' + esc(description) + '</small>' : '') + '</li>';
  const confirmed = (context?.assets.linked_images || []).flatMap(group =>
    group.images.map(item => image(item, group.keyword))).slice(0, 4).join("");
  const candidates = (fields.imageCandidates || []).map(item =>
    image(item, [item.reason, item.category && "图库分类 · " + item.category].filter(Boolean).join(" · "))).join("");
  const main = fields.keywords?.find(item => item.term === fields.mainKeyword);
  const recent = fields.previousReport;
  const taskIsReply = fields.nextTaskSource?.source === "chat" && fields.nextTaskSource.id === recent?.reply;
  const stage = context ? fields.stage : [fields.previousProjectStep, fields.stage].filter(Boolean).join(" · ");
  return '<div class="handoff-summary"><dl>' +
    '<div><dt>当前进度</dt><dd>' + esc(stage || "待记录") + '</dd></div>' +
    '<div><dt>下一件事</dt><dd>' + esc(fields.nextTask || "还没有记录待办") + '</dd></div>' +
    (main ? '<div><dt>主关键词</dt><dd>' + esc(main.term) + '<small>' + esc(main.status) + '</small></dd></div>' : '') +
    '</dl>' + nextTaskOriginal(p, fields.nextTaskSource, true) + (confirmed ? '<h3>已配图</h3><ul>' + confirmed + '</ul>' : '') +
    (candidates ? '<h3>候选图 · 使用前核对</h3><ul>' + candidates + '</ul>' : '') +
    (recent ? '<div class="step-actions">' +
      (recent.prompt ? nextTaskOriginal(p,{source:"chat",id:recent.prompt},true,"上轮提问") : "") +
      (taskIsReply ? "" : nextTaskOriginal(p,{source:"chat",id:recent.reply},true,"上轮回复原文")) +
      (recent.knowledge ? '<a class="text-button" href="' +
        esc(wikiPageRoute(p.id,recent.knowledge.slug,recent.reply)) + '">对应知识更新</a>' : "") +
      '</div>' : '') + '</div>';
}

async function showCodexHandoff(p) {
  const data = await get("build-archive-handoff", {project:p.id, path:p.mapPath || ""});
  if (currentBuildProject !== p) return;
  const fields = codexHandoffFields(data.projectContext ? {...p, ...data.projectContext} : p, data.pageContext);
  const available = data.folders.filter(item => item.available);
  const opening = data.codex ? "复制交接并打开 Codex" : "复制交接并打开文件夹";
  const select = available.length
    ? '<label class="field">建站文件夹<select id="handoff-folder">' +
      available.map(f => option(f.id, f.path, available[0].id)).join("") + '</select></label>'
    : data.local && data.folders.length ? '<p class="inline-hint">本机暂时找不到已关联的文件夹。</p>' : "";
  const open = available.length ? buildButton("open-handoff", opening, "primary", p.id) : "";
  const recovery = !data.local || available.length ? "" :
    (data.archive ? buildButton("prepare-handoff", "准备源码副本") :
      buildButton("wiki-folders", "关联建站文件夹", "text-button"));
  const guide = !available.length ? "" : '<p class="inline-hint">' +
    (data.codex ? "打开后，在对应的 Codex 对话里粘贴这段交接。" :
      "在 Codex 里选择这个文件夹，再粘贴这段交接。") + '</p>';
  dialog("交给 Codex 继续", '<p><strong>' + esc(p.mapTitle || p.name) + '</strong></p>' +
    handoffSummary(p,data.pageContext,fields) +
    select + '<div class="step-actions">' + open +
    buildButton("copy-text", "复制交接提示词", open ? "secondary" : "primary") + recovery + '</div>' +
    guide +
    '<details class="handoff-source"><summary>查看交接提示词</summary>' +
    '<textarea id="archive-copy" aria-label="交接提示词" rows="9" readonly></textarea></details>' +
    (data.local ? btn("aiConnection", "连接本机 Codex", "text-button") : ""));
  const field = $("#handoff-folder");
  const fill = () => {
    const folder = available.find(item => item.id === Number(field?.value));
    $("#archive-copy").value = codexResumePrompt(p, folder?.path, data.pageContext, fields);
  };
  field?.addEventListener("change", fill);
  fill();
}

async function openCodexHandoff(p, button) {
  if (button.disabled) return;
  const field = $("#handoff-folder");
  const folder = Number(field.value);
  button.disabled = true;
  field.disabled = true;
  try {
    if (!await copyArchiveText(false)) return;
    const result = await post("build-archive-handoff", {project:p.id, folder});
    toast(result.opened === "codex" ? "已复制交接提示词，并打开 Codex 工作区" :
      "已复制交接提示词，并打开项目文件夹");
  } finally {
    button.disabled = false;
    field.disabled = false;
  }
}

function pageBundleForm(p) {
  dialog("下载本页建站资料", '<form method="post" action="/api/build-page-bundle?' + esc(qs({})) + '">' +
    '<p><strong>' + esc(p.mapTitle) + '</strong></p><p class="inline-hint">' +
    esc(industryName) + '词库 · 压缩包包含进度、待办、原文、关键词来源和已配图的原图。</p>' +
    '<input type="hidden" name="project" value="' + esc(p.id) + '">' +
    '<input type="hidden" name="key" value="' + esc(p.mapKey) + '">' +
    '<label class="field">页面关键词，每行一个<textarea name="terms" rows="5">' +
    esc(p.pageKeywords.keywords.map(item => item.keyword).join("\n")) + '</textarea></label>' +
    '<button class="primary" type="submit">下载 ZIP</button></form>');
}
async function chooseMapPrompt(p, query = "", offset = 0) {
  const data = await get("build-archive-prompts", {project:p.id,find:query,offset});
  if (currentBuildProject !== p) return;
  const links = data.items.map(item => btn("build-attach-map-prompt",esc(item.preview),"journal-row",
    'data-id="' + item.id + '" data-source="' + esc(item.source) + '"')).join("");
  const move = (n,name) => btn("build-page-prompt-list",name,"text-button",'data-offset="'+n+'" data-query="'+esc(query)+'"');
  dialog("关联这页用过的提示词",'<form data-form="build-map-prompt-search"><label class="field">搜索本项目提示词<input name="query" value="' +
    esc(query) + '"></label><button type="submit" class="secondary">搜索</button></form><p>点一条原文，将它关联到当前页面。</p>' +
    (links || '<p>没有匹配的提示词。</p>') + (offset ? move(offset-20,"上一页") : "") + (data.more ? move(offset+20,"下一页") : ""));
}


var guideRevision = "";
function archiveTurn(p, record, showNext) {
  const pages = record.pages.map(page =>
    '<li><a href="#sitemap/' + p.id + '/live/' + encodeURIComponent(page.path) + '/' + record.answer + '">' +
    esc(page.title || page.path) + '</a><small>' + esc(page.stage) + '</small>' +
    (page.issue ? '<p>' + esc(page.issue) + '</p>' : '') + '</li>').join("");
  const issues = record.issues.map(issue => '<li>' +
    (issue.id ? buildButton("read-note", issue.title, "text-button archive-issue-link", issue.id) : esc(issue.title)) +
    (issue.id ? '<small>' + (issue.resolved ? "已处理" : "待解决") + '</small>' : '') + '</li>').join("");
  const wiki = record.wiki ? '<a href="' + esc(wikiPageRoute(p.id, record.wiki.slug, record.answer)) +
    '">' + esc(record.wiki.topic) + '</a>' : "";
  return '<article class="archive-turn" data-answer="' + record.answer + '">' +
    '<div class="board-title"><strong>' + esc(record.stepTitle + ' · ' + record.status) + '</strong>' +
    '<time>' + esc(record.sent) + '</time></div><p class="archive-chat-title">' + esc(record.chat) + '</p>' +
    '<div class="step-actions">' +
    (record.prompt ? buildButton("read-chat", "本轮提问", "secondary", record.prompt) : "") +
    buildButton("read-chat", "Codex 回复原文", "secondary", record.answer) + '</div>' +
    (showNext && record.nextTask ? '<p class="archive-next"><strong>当时的下一件事</strong> ' + esc(record.nextTask) + '</p>' : '') +
    (wiki ? '<p class="archive-destination"><strong>知识更新</strong> ' + wiki + '</p>' : '') +
    (pages ? '<div class="archive-destination"><strong>页面记录</strong><ul>' + pages + '</ul></div>' : '') +
    (issues ? '<div class="archive-destination"><strong>本轮记录的问题</strong><ul>' + issues + '</ul></div>' : '') +
    '</article>';
}

let archiveTurnPages = [""];

async function showArchiveTurns(p, pages = [""], answer = 0) {
  const data = await get("build-archive-turns", {project:p.id, before:pages.at(-1)});
  if (currentBuildProject !== p) return;
  archiveTurnPages = pages;
  dialog("建站归档记录",
    (data.turns.map(record => archiveTurn(p, record, true)).join("") ||
      '<p>收到 Codex 建站进度后，这里会显示每轮保存的资料。</p>') +
    '<div class="step-actions archive-turn-pages">' +
    (archiveTurnPages.length > 1 ? buildButton("archive-turns-prev", "更新的记录") : "") +
    (data.before ? buildButton("archive-turns-next", "更早的记录", "secondary", data.before) : "") + '</div>');
  if (answer) $("#dialog .archive-turn[data-answer='" + Number(answer) + "']")?.scrollIntoView({block:"center"});
}

function projectGuide(p, data, groups) {
  guideRevision = JSON.stringify(data.revision);
  const step = activeStep(p);
  const done = p.steps.filter(s => s.status === "已完成").length;
  const index = step ? p.steps.indexOf(step) + 1 : 0;
  const instruction = step ? guideFor(step) : null;
  const links = data.links;
  const enabled = links.filter(link => link.enabled).length;
  const syncIssue = links.find(link => link.enabled && link.issue)?.issue;
  const archived = links.filter(link => link.thread.startsWith("archive:")).length;
  const records = links.reduce((n,link) => n + Number(link.total), 0);
  const backup = links.find(link => link.issue)?.issue ||
    (enabled ? "自动备份已开启" : archived ? "已导入历史对话" : links.length ? "自动备份已暂停" : "尚未关联对话");
  const task = p.nextTask || (step ? instruction[0] : "");
  const nameList = groups.map(group => {
    const choices = group.projects.map(item => {
      const current = group.industry === industryId && item.id === p.id;
      return btn("build-switch-site", esc(item.name), current ? "switch-choice chosen" : "switch-choice",
        'data-industry="' + group.industry + '" data-id="' + item.id + '"' + (current ? ' aria-current="true"' : ""));
    }).join("");
    return '<div class="switch-group" role="group" aria-label="' + esc(group.label) + '">' +
      '<small>' + esc(group.label) + '</small>' + choices + '</div>';
  }).join("");
  const countFor = id => data.promptCounts[String(id)] || 0;
  const tracker = p.steps.map((item,i) =>
    '<li data-state="'+esc(item.status)+'"><span class="stage-dot" aria-hidden="true">'+
    (item.status==="已完成" ? "✓" : i+1)+'</span><a class="step-query" href="'+promptRoute(p.id,item.id)+'">'+
    esc(item.title)+'<small>'+fmt(countFor(item.id))+' 条提示词</small></a><small>'+esc(item.status)+'</small></li>').join("");
  const resume = buildButton("resume-codex", "让 Codex 接着做", "primary");
  const promptCount = step ? countFor(step.id) : 0;
  const hubCard = (title, description, actions) => '<section class="shelf-card"><h3>'+title+'</h3><p>'+description+
    '</p><div class="step-actions">'+actions+'</div></section>';

  return '<div class="build-board"><header class="board-project"><details class="board-switch"><summary>'+
    '<span><small>当前项目</small><strong>'+esc(p.name)+'</strong></span><span class="switch-cue">切换项目 ▾</span></summary>'+
    '<div class="switch-menu">'+nameList+'</div></details><div class="project-shortcuts">'+
    (data.guideId ? buildButton("read-note","这个项目怎么用","text-button",data.guideId) : "") +
    '<a class="secondary" href="'+promptRoute(p.id)+'">项目提示词</a>'+
    '<a class="secondary" href="#sitemap/'+p.id+'">网站地图</a>'+
    pageTasksLink(p, "text-button") +
    buildButton("go-skills","Skills 技能管理（"+fmt(p.skills.length)+"）","secondary",p.id)+'</div></header>'+
    '<div class="board-columns"><section class="board-next"><span class="board-kicker">当前阶段</span><h2>'+
    esc(step ? "第 "+index+" 步 · "+step.title : p.steps.length ? "全部步骤已完成" : "还没有建站步骤")+'</h2>'+
    (step ? '<div class="board-prompt-highlight"><a class="board-prompt-link" href="'+promptRoute(p.id,step.id)+'">本步提示词（'+
      fmt(promptCount)+'） <span aria-hidden="true">›</span></a>'+
      (data.promptHighlights || []).map(item => '<button type="button" class="board-prompt-snippet" data-action="build-prompt-original" data-id="'+
        item.id+'" data-source="'+esc(item.source)+'"><span>'+esc(item.preview.replace(/\s+/g," "))+'</span></button>').join("")+ '</div>' : '')+
    (step ? '<div class="next-work"><div class="board-title"><h3>下一件事</h3>'+
      buildButton("capture-next",p.nextTask ? "更新下一步" : "记录下一步","text-button")+'</div>'+
      '<p>'+esc(task)+'</p>' + nextTaskOriginal(p, data.nextTaskSource) + '</div>' :
      '<p>'+ (p.steps.length ? '可以回看工作记录，或把这套流程用于下一个网站。' : '打开建站流程，添加第一个步骤。') +'</p>')+
    '<div class="step-actions">'+resume+'</div>'+
    (step ? '<details class="board-accept"><summary>完成标准与步骤操作</summary><p>'+esc(instruction[2])+'</p><div class="step-actions">'+
      buildButton("guide-prompt","拿这一步问 Codex","secondary")+
      buildButton("finish-step","完成这一步","secondary",step.id)+'</div></details>' : '')+'</section>'+
    '<section class="board-stages"><div class="board-title"><h3>建站进度</h3><span>'+done+' / '+p.steps.length+' 步已完成</span></div>'+
    (tracker ? '<ol>'+tracker+'</ol>' : '')+buildButton("go-steps","查看全部步骤","text-button",p.id)+'</section></div>'+
    ((data.recentTurn || enabled || data.folders.length) ?
      '<section class="board-log board-archive"><div class="board-title"><h3>最近一轮建站归档</h3><div class="step-actions">' +
      (data.local && (enabled || data.folders.length) ? buildButton("archive-check", "检查新记录", "text-button") : "") +
      (data.recentTurn ? buildButton("archive-turns", "全部归档", "text-button") : "") +
      '</div></div>' + (syncIssue ? '<p class="notice">' + esc(syncIssue) + '</p>' : '') +
      (data.recentTurn ? archiveTurn(p, data.recentTurn, false) :
        '<p>收到 Codex 建站进度后，这里会显示每轮保存的资料。</p>') + '</section>' : '') +
    '<h2 class="shelf-title">项目资料</h2><div class="board-shelf">'+
    hubCard("Codex 对话", esc(backup)+(links.length ? ' · '+fmt(records)+' 条记录' : ''),
      buildButton("manage-chats",enabled ? "管理自动备份" : archived ? "查看已导入的对话" : "关联对话","text-button")+
      (step ? buildButton("capture-prompt","存一段提示词","text-button") : ""))+
    hubCard("问题与解决办法","当前还有 "+fmt(data.openIssues)+" 个问题待解决。",
      buildButton("issues","查看待解决问题","text-button")+(step ? buildButton("capture-issue","记一个问题","text-button") : ""))+
    hubCard("建站工具与资料","查找建站参考、技能用法和原文件。",
      '<a class="text-button" href="#wiki/'+p.id+'">建站知识库</a>' +
      (activeAreaId===2 ? '<button type="button" class="text-button" data-view="skillbank">Skills 技能包</button>' : '')+
      '<button type="button" class="text-button" data-view="materials">建站资料库</button>'+buildButton("go-plan","官网一级栏目规划","text-button",p.id))+
    '</div><section class="board-log"><div class="board-title"><h3>最近的工作记录</h3>'+
    buildButton("journal","查找全部记录","text-button")+'</div>'+
    (journalRows(data.items.slice(0,3)) || '<p>关联对话或保存第一条记录后，会显示在这里。</p>')+'</section>'+
    '<section class="board-tools">'+buildButton("reuse-site","复用流程到新网站","secondary")+
    btn("export-backup-center", "备份与换机", "text-button")+'</section>'+guideLinks()+'</div>';
}

let journalQuery = {};
async function showJournal(p, q = {}) {
  journalQuery = q;
  const data = await get("build-archive-list", { project: p.id, ...q });
  dialog(
    "项目工作记录",
    '<form class="material-search" data-form="build-journal-search"><input type="search" aria-label="搜索项目记录" name="find" placeholder="搜索提示词、回复、问题或步骤" value="' +
      esc(q.find || "") +
      '"><select aria-label="记录类型" name="kind">' +
      ["", "提示词", "Codex 回复", "问题", "待解决", "步骤笔记", "对话"]
        .map((k) => option(k, k || "全部记录", q.kind || ""))
        .join("") +
      '</select><button class="secondary" type="submit">查找</button></form><div class="journal-list">' +
      (journalRows(data.items) || "<p>没有符合条件的记录。</p>") +
      '</div><div class="step-actions">' +
      (q.offset ? buildButton("journal-prev", "上一页") : "") +
      (data.more ? buildButton("journal-next", "下一页") : "") +
      "</div>",
  );
}
function captureForm(p, kind, selectedStep = null) {
  const next = kind === "下一步";
  const s = selectedStep || (next && p.steps.find(step => step.id === p.nextTaskStep)) || activeStep(p);
  if (!s) return;
  buildForm(
    "capture",
    next ? "记录下一步" : kind === "问题" ? "记一个问题" : "保存提示词",
    {},
    '<p class="field full">' +
      esc(p.name + " / " + s.title) +
      "</p>" +
      buildArea(
        "body",
        next ? "接下来要做什么？" : kind === "问题" ? "遇到什么问题？" : "把提示词粘贴在这里",
        next ? p.nextTask : "",
        true,
      ) +
      (kind === "问题"
        ? buildArea("resolution", "解决办法（可以以后补）", "")
        : ""),
    { step: s.id, kind },
  );
}
async function chatSettings(p) {
  const data = await get("build-archive-list", { project: p.id });
  const linked = data.links;
  const controls = data.local
    ? buildButton(
        "pick-chat",
        "选择本机对话",
        linked.length ? "secondary" : "primary",
      ) +
      (linked.some((l) => l.enabled) || data.folders.length ? buildButton("sync-now", "立即同步") : "")
    : "";
  dialog(
    "Codex 对话备份",
    "<p><strong>" +
      esc(p.name) +
      "</strong></p><p>关联一次后，主机上的软件每 30 秒保存新提问和回复；下次打开也会补齐。换机包包含已保存的文字。</p>" +
      linked
        .map(
          (l) =>
            '<div class="archive-link"><strong>' +
            esc(l.title) +
            "</strong><p>" +
            esc(
              (l.step || "整个项目") +
                " · " +
                l.prompts +
                " 条提问 · " +
                (l.total - l.prompts) +
                " 条回复",
            ) +
            "</p><small>" +
            esc(
              l.enabled
                ? l.issue || "自动备份中"
                : l.thread.startsWith("archive:")
                  ? "已从文件导入"
                  : "已暂停",
            ) +
            "</small>" +
            buildButton("thread", "按时间看整段对话", "secondary", l.id) +
            (data.local && l.enabled
              ? buildButton("pause-chat", "暂停", "text-button", l.id) +
                buildButton(
                  "folder-info",
                  data.folders.length
                    ? "更新项目文件夹说明"
                    : "以后新开的建站对话也自动收录",
                  "text-button",
                  l.id,
                )
              : "") +
            "</div>",
        )
        .join("") +
      data.folders
        .map(
          (f) =>
            "<p>已启用项目文件夹　" +
            esc(f.name) +
            (data.local
              ? buildButton(
                  "stop-folder",
                  "暂停识别新对话",
                  "text-button",
                  f.id,
                )
              : "") +
            "</p>",
        )
        .join("") +
      '<div class="step-actions">' +
      controls +
      buildButton("receipt", "复制给 Codex 的进度说明", "text-button") +
      "</div>" +
      (data.local ? "" : "<p>请在主机的桌面版关联新对话。</p>") +
      '<p class="inline-hint">日常沿用已关联的对话。启用项目文件夹后，新的建站对话在首次回报本项目进度时会自动归档。Codex 按项目说明回报进度后，步骤会自动更新。</p>',
  );
}
async function pickChat(p) {
  const list = await get("build-archive-sources", { project: p.id });
  if (!list.length) {
    dialog(
      "关联 Codex 对话",
      "<p>这台电脑还没有可读取的 Codex 对话。可以在使用 Codex 的主机打开软件再关联，或先把提示词粘贴到项目里。</p>",
    );
    return;
  }
  buildForm(
    "bind-chat",
    "关联本机 Codex 对话",
    {},
    '<p class="field full">存入 ' +
      esc(p.name) +
      '</p><label class="field full">对话<select name="thread" required><option value="">选择一段对话</option>' +
      list
        .map((t) => option(t.id, t.title + " · " + t.workspace, ""))
        .join("") +
      '</select></label><label class="field full">这段对话的归属<select name="step">' +
      option("", "整个项目", "") +
      p.steps.map((s) => option(s.id, s.title, "")).join("") +
      "</select></label>",
    { project: p.id },
  );
}
async function guideAction(action, t, p) {
  const id = Number(t.dataset.id);
  switch (action) {
    case "all-prompts":
      return stepPrompts(p);
    case "step-prompts":
      return stepPrompts(p, { step: String(id) });
    case "prompts-prev":
    case "prompts-next":
      return stepPrompts(p, {
        ...promptFilter,
        offset: Math.max(
          0,
          (promptFilter.offset || 0) + (action === "prompts-next" ? 20 : -20),
        ),
      });
    case "thread":
      return showThread(p, id, "", 0);
    case "thread-page":
      return showThread(
        p,
        threadCursor.id,
        threadCursor.find,
        Number(t.dataset.offset || 0),
      );
    case "thread-original": {
      const r = await get("build-archive-text", { project: p.id, id });
      return copyBox(
        r.role === "user" ? "我的提问" : "Codex 回复",
        r.body,
        btn(
          "build-thread-page",
          "回到整段对话",
          "secondary",
          'data-offset="' + threadCursor.offset + '"',
        ),
      );
    }
    case "back-prompts":
      if (view === "prompts") return close();
      return stepPrompts(p, promptFilter);
    case "prompt-answers": {
      const offset = Number(t.dataset.offset || 0),
        data = await get("build-archive-replies", {
          project: p.id,
          id,
          offset,
        });
      const move = (n, label) =>
        btn(
          "build-prompt-answers",
          label,
          "secondary",
          'data-id="' + id + '" data-offset="' + n + '"',
        );
      return dialog(
        "这句提问之后的回复",
        (data.items
          .map((r) =>
            btn(
              "build-answer-text",
              esc(r.preview),
              "journal-row",
              'data-id="' +
                r.id +
                '" data-question="' +
                id +
                '" data-offset="' +
                offset +
                '"',
            ),
          )
          .join("") || "<p>这句之后没有单独保存的回复。</p>") +
          '<div class="step-actions">' +
          (offset ? move(Math.max(0, offset - 20), "上一页") : "") +
          (data.more ? move(offset + 20, "下一页") : "") +
          buildButton("back-prompts", "回到提示词", "text-button") +
          "</div>",
      );
    }
    case "answer-text": {
      const r = await get("build-archive-text", { project: p.id, id });
      return copyBox(
        "Codex 回复 · " + r.title,
        r.body,
        btn(
          "build-prompt-answers",
          "回到这组回复",
          "secondary",
          'data-id="' +
            Number(t.dataset.question) +
            '" data-offset="' +
            Number(t.dataset.offset || 0) +
            '"',
        ),
      );
    }
    case "prompt-original": {
      const r = await get("build-archive-prompt-text", {
        project: p.id,
        id,
        source: t.dataset.source,
      });
      return copyBox(
        "提示词原文 · " + r.origin,
        r.body,
        (t.dataset.source === "chat"
          ? buildButton("prompt-answers", "看当时的回复", "secondary", id)
          : "") + (view === "buildhub" && !t.closest("#dialog")
            ? '<a class="text-button" href="'+promptRoute(p.id)+'">打开项目提示词</a>'
            : buildButton("back-prompts", "回到提示词", "text-button")),
      );
    }
    case "reuse-site":
      return reuseForm(p);
    case "folder-info":
      return dialog(
        "自动收录今后的建站对话",
        "<p>软件会在这段对话所属的网站文件夹里补上 Codex 项目说明（AGENTS.md）。以后在该文件夹开新对话，Codex 首次回报本网站的进度后，整段提问与回复会自动归到这里。已连接本机资料库的 Codex 也可以读取这个项目的步骤和提示词。</p>" +
          buildButton("enable-folder", "启用项目文件夹", "primary", id),
      );
    case "enable-folder":
      await post("build-archive-folder", { project: p.id, id });
      await chatSettings(p);
      return toast("已启用项目文件夹");
    case "stop-folder":
      await post("build-archive-stop-folder", { project: p.id, id });
      await chatSettings(p);
      return toast("已暂停识别新对话");
    case "manage-chats":
      return chatSettings(p);
    case "archive-turns":
      return showArchiveTurns(p);
    case "archive-turns-prev":
      return showArchiveTurns(p, archiveTurnPages.slice(0, -1));
    case "archive-turns-next":
      return showArchiveTurns(p, [...archiveTurnPages, id]);
    case "archive-turns-return":
      return showArchiveTurns(p, archiveTurnPages, id);
    case "archive-check": {
      t.disabled = true;
      try {
        const result = await post("build-archive-sync", {project:p.id});
        if (currentBuildProject?.id === p.id) await load();
        toast("检查完成 · 本次处理 " + fmt(result.added) + " 条对话记录");
      } finally {
        t.disabled = false;
      }
      return;
    }
    case "pick-chat":
      return pickChat(p);
    case "pause-chat":
      await post("build-archive-pause", { project: p.id, id });
      await chatSettings(p);
      return load();
    case "sync-now": {
      t.disabled = true;
      try {
        const r = await post("build-archive-sync", { project: p.id });
        await chatSettings(p);
        await load();
        toast("已同步，新增 " + r.added + " 条");
      } finally {
        t.disabled = false;
      }
      return;
    }
    case "receipt":
      return copyBox("给 Codex 的进度说明", cooperation(p));
    case "guide-prompt": {
      const s = activeStep(p);
      return copyBox(
        "拿这一步问 Codex",
        guideFor(s)[1] + "\n\n" + cooperation(p),
      );
    }
    case "copy-text":
      return copyArchiveText();
    case "issues":
      return showJournal(p, { kind: "待解决" });
    case "journal":
      return showJournal(p);
    case "journal-next":
    case "journal-prev":
      return showJournal(p, {
        ...journalQuery,
        offset: Math.max(
          0,
          (journalQuery.offset || 0) + (action === "journal-next" ? 20 : -20),
        ),
      });
    case "read-chat": {
      const r = await get("build-archive-text", { project: p.id, id });
      const turn = t.closest("#dialog .archive-turn");
      return copyBox(
        r.role === "user" ? "提问原文 · " + r.title : "Codex 回复 · " + r.title,
        r.body,
        turn ? buildButton("archive-turns-return", "返回归档记录", "secondary", turn.dataset.answer) : "",
      );
    }
    case "read-note": {
      const record = {industry:industryId, section:activeAreaId, project:p.id, source:"note", id, projectName:p.name};
      const r = await get("build-archive-original", {project:p.id, source:"note", id});
      const turn = t.closest("#dialog .archive-turn");
      return dialog(
        r.kind,
        "<p>" +
          esc(r.title) +
          '</p><textarea id="archive-copy" rows="' + (r.kind === "问题" ? 4 : 7) + '" readonly>' +
          esc(r.body) +
          "</textarea>" +
          (r.files?.length
            ? '<div class="archive-files"><strong>下载附件</strong><ul>' +
              r.files
                .map(
                  (f) =>
                    '<li><a download href="/api/build-file?' +
                    esc(qs({ id: f.id })) +
                    '">' +
                    esc(f.filename) +
                    "</a></li>",
                )
                .join("") +
              "</ul></div>"
            : "") +
          (r.resolution
            ? '<p class="build-copy">解决办法　' + esc(r.resolution) + "</p>"
            : "") +
          '<div class="step-actions">' +
          buildButton("copy-text", "复制原文") +
          (turn ? buildButton("archive-turns-return", "返回归档记录", "secondary", turn.dataset.answer) : "") +
          (r.kind === "问题"
            ? buildButton("resolve-note", "填写解决办法", "primary", r.id)
            : buildButton("edit-entry", "编辑记录", "secondary", r.id)) +
          "</div>" + issueOriginLinks(record, r.issueOrigins),
      );
    }
    case "resolve-note": {
      const r = await get("build-entry", { id });
      return buildForm(
        "resolve",
        "填写解决办法",
        r,
        '<p class="field full build-copy">' +
          esc(r.body) +
          "</p>" +
          buildArea("resolution", "解决办法", r.resolution, true),
        { id: r.id, version: r.version },
      );
    }
    case "capture-issue":
      return captureForm(p, "问题");
    case "capture-prompt":
      return captureForm(p, "提示词");
    case "save-stage-prompt": {
      const step = p.steps.find(item => item.id === id);
      if (step) return captureForm(p, "提示词", step);
      return;
    }
    case "capture-next":
      return captureForm(p, "下一步");
  }
}
async function guideSubmit(form, values) {
  const action = form.dataset.form,
    p = currentBuildProject;
  if (action === "build-thread-search")
    return showThread(p, threadCursor.id, values.find || "", 0);
  if (action === "build-prompt-search") return stepPrompts(p, values);
  if (action === "build-journal-search") return showJournal(p, values);
  const button = form.querySelector("button[type=submit]");
  if (button.disabled) return;
  modalBusy = true;
  button.disabled = true;
  try {
    if (action === "build-reuse") {
      const [destSection, destIndustry] = values.destination
        .split("/")
        .map(Number);
      const r = await post("build-archive-copy-workflow", {
        ...values,
        destSection,
        destIndustry,
      });
      modalBusy = false;
      close();
      openAppLocation(
        "/?" +
          qs({ section: destSection, industry: destIndustry }) +
          "#buildhub/" +
          r.id,
      );
      return;
    }
    if (action === "build-bind-chat") {
      await post("build-archive-bind", values);
      await chatSettings(p);
    }
    if (action === "build-capture") {
      await post("build-entry", {
        ...values,
        subcategory: "auto",
        title: values.body.trim().split(/\r?\n/)[0].slice(0, 120),
      });
    }
    if (action === "build-resolve") {
      const entry = await get("build-entry", { id: values.id });
      await post("build-entry", {
        ...entry,
        version: values.version,
        subcategory: entry.subcategory,
        resolution: values.resolution,
      });
    }
    modalBusy = false;
    if (action !== "build-bind-chat") close();
    await load();
    toast(
      action === "build-bind-chat"
        ? "历史对话已读取，自动备份已开启"
        : "已保存到项目",
    );
  } finally {
    modalBusy = false;
    button.disabled = false;
  }
}

setInterval(async () => {
  if (
    document.hidden ||
    view !== "buildhub" ||
    !currentBuildProject ||
    $("#dialog").open ||
    $(".guide-resources[open], .board-switch[open], .board-accept[open]")
  )
    return;
  const id = currentBuildProject.id;
  try {
    const rev = await get("build-archive-revision", { project: id });
    if (
      view === "buildhub" &&
      currentBuildProject?.id === id &&
      !$("#dialog").open &&
      JSON.stringify(rev) !== guideRevision
    )
      await load();
  } catch {}
}, 15000);

document.addEventListener("click", (e) => {
  if (e.target.closest('#dialog .archive-link a[href*="#buildhub/"]')) close();
});

let promptFilter = {};
function promptRoute(project, step = "", query = "", offset = 0) {
  return "#prompts/" + Number(project) + (step || query || offset ? "/" + (step || "all") : "") +
    (query || offset ? "/" + offset : "") + (query ? "/" + encodeURIComponent(query) : "");
}

async function promptPanel(params) {
  if (!params.project) {
    currentBuildProject = null;
    return projectDirectory(await get("build-archive-overview", {prompts:1}), "prompts");
  }
  const data = await get("build-archive-prompt-board", {project:params.project, step:params.step,
    find:params.find, offset:params.offset});
  if (view !== "prompts" || filt !== params) return "";
  const p = currentBuildProject = data.project;
  const steps = new Map(p.steps.map((step, index) => [String(step.id), {...step, sequence:index + 1}]));
  const selection = steps.get(data.selected);
  const total = Object.values(data.counts).reduce((a,b) => a + b, 0);
  const route = (step, offset = 0, query = params.find) => esc(promptRoute(p.id, step, query, offset));
  const link = (id, title, count, info = "") => '<a class="prompt-stage" href="'+route(id)+'"'+
    (data.selected === id ? ' aria-current="page"' : '')+'><span>'+esc(title)+
    (info ? '<small>'+esc(info)+'</small>' : '')+'</span><b>'+fmt(count)+'</b></a>';
  const sources = {chat:"Codex 提问", note:"手动保存", template:"流程模板", reference:"其他项目复用"};
  const title = selection ? '第 '+selection.sequence+' 步 · '+selection.title : data.selected === "0" ? "未归步骤" : "全部提示词";
  const items = data.items.map(item => '<button type="button" class="journal-row prompt-result" data-action="build-prompt-original" data-id="'+
    item.id+'" data-source="'+esc(item.source)+'"><span class="journal-meta">'+
    [steps.get(String(item.step))?.title || "未归步骤", sources[item.source], item.shown_at].filter(Boolean).map(esc).join(" · ")+
    '</span><strong>'+esc(item.preview.replace(/\s+/g," "))+'</strong><small>'+esc(item.origin)+'</small></button>').join("");
  return '<section class="prompt-board"><header class="wiki-header"><div><h2>'+esc(p.name)+'</h2><p class="wiki-meta">'+
    (steps.has(String(data.current)) ? '当前阶段 · 第 '+steps.get(String(data.current)).sequence+' 步 '+esc(steps.get(String(data.current)).title) :
      p.steps.length ? '全部步骤已完成' : '还没有建站步骤')+
    '</p></div><a class="secondary" href="#buildhub/'+p.id+'">返回项目工作台</a></header>'+
    '<form class="material-search" data-form="project-prompt-search"><input type="search" name="find" aria-label="搜索本项目的提示词" maxlength="400" '+
    'placeholder="搜索本项目的提示词或对话名称" value="'+esc(params.find || "")+'"><button class="secondary">查找</button>'+
    (params.find ? '<a class="text-button" href="'+route(data.selected,0,"")+'">清除搜索</a>' : '')+'</form>'+
    '<div class="prompt-board-grid"><nav aria-label="按建站步骤查看提示词">'+link("all","全部提示词",total)+
    [...steps].map(([id,step]) => link(id, step.sequence+'. '+step.title, data.counts[id],
      step.id === data.current ? '当前阶段 · '+step.status : step.status)).join("")+
    link("0","未归步骤",data.counts[0])+'</nav><div class="prompt-board-list"><div class="board-title"><h3>'+esc(title)+'</h3>'+
    (selection ? buildButton("save-stage-prompt","保存到这一步","secondary",selection.id) : '')+'</div>'+
    (params.find ? '<p class="wiki-meta">搜索「'+esc(params.find)+'」</p>' :
      '<p class="wiki-meta">'+fmt(data.selected === "all" ? total : data.counts[data.selected])+' 条记录</p>')+
    (items ? '<div class="journal-list">'+items+'</div>' : '<p class="build-empty">'+
      (params.find ? '没有找到符合条件的提示词。' : '这里还没有提示词。Codex 回报这一阶段的进度后，可以在对应步骤查看。')+'</p>')+
    (params.offset || data.more ? '<div class="step-actions">'+(params.offset ? '<a class="secondary" href="'+
      route(data.selected,Math.max(0,params.offset-20))+'">上一页</a>' : '')+(data.more ? '<a class="secondary" href="'+
      route(data.selected,(params.offset || 0)+20)+'">下一页</a>' : '')+'</div>' : '')+'</div></div></section>';
}

async function stepPrompts(p, filter = {}) {
  promptFilter = filter;
  const result = await get("build-archive-prompts", {
    project: p.id,
    ...filter,
  });
  const groups = new Map();
  for (const r of result.items) {
    const step = p.steps.find((s) => s.id === r.step)?.title || "整个项目";
    if (!groups.has(step)) groups.set(step, []);
    groups.get(step).push(r);
  }
  dialog(
    "按步骤找提示词",
    "<p>" +
      esc(p.name) +
      '</p><form class="material-search" data-form="build-prompt-search"><select name="step" aria-label="按步骤筛选">' +
      option("", "全部步骤", filter.step ?? "") +
      p.steps.map((s) => option(s.id, s.title, filter.step ?? "")).join("") +
      option("0", "整个项目", filter.step ?? "") +
      '</select><input name="find" type="search" placeholder="输入你记得的几个字" aria-label="搜索提示词" value="' +
      esc(filter.find || "") +
      '"><button type="submit" class="secondary">查找</button></form>' +
      (Array.from(
        groups,
        ([title, items]) =>
          "<h3>" +
          esc(title) +
          "</h3>" +
          items
            .map(
              (r) =>
                '<button class="journal-row" type="button" data-action="build-prompt-original" data-source="' +
                esc(r.source) +
                '" data-id="' +
                r.id +
                '"><span class="journal-meta">' +
                esc((r.source === "reference" ? "沿用自 " : "") + r.origin) +
                "</span><strong>" +
                esc(r.preview) +
                "</strong></button>",
            )
            .join(""),
      ).join("") ||
        "<p>这一步还没有保存的提示词。在关联的 Codex 对话中做这一步，回报进度后就能在这里找到原话。</p>") +
      '<div class="step-actions">' +
      (filter.offset ? buildButton("prompts-prev", "上一页") : "") +
      (result.more ? buildButton("prompts-next", "下一页") : "") +
      "</div>",
  );
}
function projectDestination(label) {
  const choices = knownIndustries
    .map((i) => ["2/" + i.id, "行业 · " + i.name])
    .concat(
      areas
        .filter((a) => a.id !== 2 && ["build", "store"].includes(a.kind))
        .map((a) => [a.id + "/1", a.name]),
    );
  return '<label class="field full">' + esc(label) + '<select name="destination">' +
    choices.map(([value, name]) => option(value, name,
      activeAreaId + "/" + (activeAreaId === 2 ? industryId : 1))).join("") + "</select></label>";
}
function reuseForm(p) {
  buildForm(
    "reuse",
    "给下一个网站用",
    {},
    '<p class="field full">从「' +
      esc(p.name) +
      "」沿用步骤和提示词原文。新网站从第一步开始，单独记录进度。</p>" +
      buildInput("name", "新网站叫什么？", "", true) +
      (p.steps.some((s) => s.entries.some((e) => e.kind === "复用模板"))
        ? '<label class="field full">带哪些提示词<select name="promptMode"><option value="templates">各步骤的通用模板（适合新行业）</option><option value="all">全部历史提问和模板</option></select></label>'
        : "") +
      projectDestination("新网站放在哪里"),
    { project: p.id },
  );
}

let threadCursor = {};
async function showThread(p, id, find, offset) {
  const r = await get("build-archive-thread", {
    project: p.id,
    id,
    find,
    offset,
  });
  threadCursor = { id, find, offset };
  const pageLink = (page, label) =>
    btn("build-thread-page", label, "secondary", 'data-offset="' + page + '"');
  dialog(
    r.title,
    '<form class="material-search" data-form="build-thread-search"><input type="search" aria-label="在这段对话里查找" name="find" placeholder="在这段对话里查找" value="' +
      esc(find) +
      '"><button class="secondary" type="submit">查找</button></form>' +
      (r.items
        .map((m) =>
          btn(
            "build-thread-original",
            '<span class="journal-meta">' +
              esc(
                [
                  m.role === "user" ? "我" : "Codex",
                  m.sent,
                  m.step || "项目记录",
                ].join(" · "),
              ) +
              "</span><strong>" +
              esc(m.preview) +
              "</strong>",
            "journal-row",
            'data-id="' + m.id + '"',
          ),
        )
        .join("") || "<p>没有匹配的对话记录。</p>") +
      '<div class="step-actions">' +
      (offset ? pageLink(Math.max(0, offset - 20), "上一页") : "") +
      (r.more ? pageLink(offset + 20, "下一页") : "") +
      "</div>",
  );
}
