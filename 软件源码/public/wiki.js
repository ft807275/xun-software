"use strict";

function wikiPageRoute(project, slug = "", answer = 0) {
  return "#wiki/" + project + (slug ? "/" + slug + (answer ? "/" + answer : "") : "");
}

function wikiPageLink(project, slug = "") {
  return "/?" + qs({ industry: project.industry ?? industryId, section: project.section ?? activeAreaId }) +
    wikiPageRoute(project.id, slug);
}

function wikiTopicLinks(project, pages) {
  return '<ul class="wiki-topics">' + pages.map(item =>
    '<li><a href="' + esc(wikiPageLink(project, item.slug)) + '">' + esc(item.title) + '</a>' +
    '<p>' + esc(item.summary) + '</p></li>'
  ).join("") + '</ul>';
}

function wikiDirectory(projects, searching = false) {
  if (!projects.length) return '<p class="build-empty">' +
    (searching ? "没有找到匹配的知识页或项目。" : "可以在项目总览新建第一个项目。") + '</p>';
  return '<div class="project-directory">' + projects.map(p =>
    '<section class="directory-project"><small>' + esc(p.label) + '</small><h2><a href="' +
    esc(wikiPageLink(p)) + '">' + esc(p.name) + '</a></h2>' +
    (p.pending ? '<p><a class="text-button" href="' + esc(wikiPageLink(p)) + '">' + fmt(p.pending) + ' 条待补入知识页</a></p>' : '') +
    (p.pages.length ? wikiTopicLinks(p, p.pages) :
      '<p class="wiki-meta">待整理 · <a href="' + esc(wikiPageLink(p)) + '">打开项目知识库</a></p>') + '</section>'
  ).join("") + '</div>';
}

function wikiMarkdown(body) {
  return body.trim().split(/\n\s*\n/).map(block => {
    const lines = block.split(/\r?\n/);
    const heading = /^#{1,4} +(.+)$/.exec(lines[0]);
    const title = heading ? '<h3>' + esc(heading[1]) + '</h3>' : "";
    const content = heading ? lines.slice(1) : lines;
    if (!content.length) return title;
    if (content.every(line => /^[-*] +/.test(line))) {
      return title + '<ul>' + content.map(line =>
        '<li>' + esc(line.replace(/^[-*] +/, "")) + '</li>').join("") + '</ul>';
    }
    return title + '<p>' + content.map(esc).join("<br>") + '</p>';
  }).join("");
}

function wikiAutomation(p) {
  const state = p.automation || {enabled:0, folders:[]};
  const enabled = state.enabled && state.folders.length;
  const control = p.command.length && ((state.folders.length && p.pages.length) || state.enabled)
    ? buildButton("wiki-toggle-auto", state.enabled ? "暂停自动整理" : "开启自动整理", "secondary") : "";
  const help = enabled
    ? "在「" + Array.from(new Set(state.folders)).join("、") + "」文件夹里用 Codex 建站。软件会在每轮结束后归档，约 30 秒检查一次。"
    : state.folders.length ? "开启后，Codex 的建站结论会自动更新知识页。" : "在项目进度里关联 Codex 的建站文件夹后，可开启自动整理。";
  return '<section class="wiki-section"><div class="wiki-header"><h3>Codex 自动整理 · ' +
    (enabled ? "已开启" : "未开启") + '</h3><div class="step-actions">' +
    (enabled && p.command.length ? buildButton("wiki-sync", "立即检查新记录", "primary") : "") +
    (state.canChooseFolder ? buildButton("wiki-folders", "建站文件夹", "secondary") : "") +
    control + '</div></div><p class="wiki-meta">' + esc(help) + '</p>' +
    (state.checked ? '<p class="wiki-meta">最近收到更新 · ' + esc(state.checked) + '</p>' : "") +
    (state.warning ? '<p class="notice">' + esc(state.warning) + '</p>' : "") + '</section>';
}

async function wikiFolders(p) {
  const data = await get("build-archive-workspaces", {project:p.id});
  const bound = data.current.length ? '<h3>已关联的文件夹</h3><ul class="wiki-folders">' +
    data.current.map(row => '<li>' + esc(row.path) + '</li>').join("") + '</ul>' : "";
  const available = data.available.length ? '<h3>从本机 Codex 建站文件夹选择</h3><input type="search" id="wiki-folder-search" ' +
    'placeholder="输入域名或文件夹名称" aria-label="搜索 Codex 文件夹">' +
    '<ul class="wiki-folders">' + data.available.map(row =>
      '<li data-wiki-folder="' + esc(row.path.toLowerCase()) + '"><div><strong>' + esc(row.name) +
      '</strong><p>' + esc(row.path) + '</p></div>' +
      btn("build-wiki-add-folder", "关联", "secondary", 'data-thread="' + esc(row.thread) + '"') + '</li>'
    ).join("") + '</ul><p class="wiki-folder-empty" hidden>没有匹配的文件夹。</p>' :
    '<p>在新的建站文件夹里用 Codex 打开过一次对话，这里就可以选择它。</p>';
  dialog("管理建站文件夹", '<p>' + esc(p.name) + '</p>' + bound + available);
}

async function addWikiFolder(p, button) {
  if (button.disabled) return;
  button.disabled = true;
  try {
    const result = await post("build-archive-workspaces", {project:p.id, thread:button.dataset.thread});
    close();
    await load();
    toast("已关联 " + result.folder);
  } finally {
    button.disabled = false;
  }
}

async function toggleWikiAutomation(p) {
  const state = await post("build-wiki-automation", {project:p.id, enabled:!p.automation.enabled});
  await load();
  toast(state.enabled ? "已开启 Codex 自动整理" : "已暂停 Codex 自动整理");
}

async function syncWikiProject(p, button) {
  if (button.disabled) return;
  button.disabled = true;
  try {
    const result = await post("build-archive-sync", {project:p.id});
    await load();
    const changes = [result.added && "归档了 " + fmt(result.added) + " 条新对话记录",
      result.recovered && "补入了 " + fmt(result.recovered) + " 条知识记录"].filter(Boolean);
    toast(changes.join("，") || "目前没有新的可归档记录");
  } finally {
    button.disabled = false;
  }
}

function wikiPending(p) {
  if (!p.pending?.total) return "";
  return '<section class="wiki-section"><h3>待补入知识页（' + fmt(p.pending.total) + '）</h3>' +
    '<p class="wiki-meta">这些轮次的进度和对话已归档。可以打开原文核对，再补到对应的知识页。</p>' +
    (p.pending.total > p.pending.items.length ? '<p class="wiki-meta">当前显示最近 12 条，补录后会显示更早的记录。</p>' : '') +
    '<ul class="wiki-updates">' + p.pending.items.map(item => '<li><strong>' + esc(item.topic || item.title) + '</strong>' +
      '<p>' + esc(item.reason) + (item.slug ? ' 知识页编号 ' + esc(item.slug) : '') + '</p>' +
      '<small>' + esc(item.stamped) + '</small><div class="step-actions">' +
      buildButton("read-chat", "查看 Codex 回复", "secondary", item.answer) +
      (p.pages.length ? buildButton("wiki-file-pending", "补到知识页", "text-button", item.answer) : '') +
      '</div></li>').join('') + '</ul></section>';
}

async function wikiPendingForm(p, answer) {
  const item = await get("build-archive-wiki-pending", {project:p.id, answer});
  if (p !== currentBuildProject) return;
  buildForm("wiki-file-pending", "补到知识页", {}, '<p class="field full">' + esc(item.reason) +
    ' 保存后会附上这一轮的提示词和回复。</p>' +
    '<label class="field full">知识页<select name="slug" required><option value="">选择知识页</option>' +
    p.pages.map(page => option(page.slug, page.title, item.slug)).join('') + '</select></label>' +
    buildInput("topic", "主题", item.topic, true) + buildArea("body", "结论和待核实事项", item.body, true),
    {project:p.id, answer});
  $("#dialog input[name=topic]").maxLength = 100;
  $("#dialog textarea[name=body]").maxLength = 3000;
}

async function saveWikiPending(form, values) {
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const result = await post("build-archive-wiki-pending", values);
    close();
    openAppLocation(wikiPageRoute(values.project, result.slug, result.answer));
    toast("已补到知识页，并附上本轮原文");
  } finally {
    button.disabled = false;
  }
}

function wikiChatUpdates(project, items, answer) {
  if (!items.length) return "";
  const evidence = (item, showTopic) => '<div' + (item.answer === answer ? ' class="linked-receipt" tabindex="-1"' : '') + '>' +
    (showTopic || item.answer === answer ? '<h4>' + esc(item.topic) + '</h4>' : '') +
    '<p class="wiki-meta">' + esc(item.updated) + '</p>' +
    '<p class="wiki-chat-body">' + esc(item.body) + '</p><div class="step-actions">' +
    (item.prompt ? buildButton("read-chat", "本轮提示词", "secondary", item.prompt) : "") +
    buildButton("read-chat", "Codex 回复原文", "secondary", item.answer) + '</div>' +
    (item.websitePages?.length ? '<div class="step-actions wiki-work-links">' +
      item.websitePages.map(page => '<a class="text-button" href="#sitemap/' + project +
        '/live/' + encodeURIComponent(page.path) + '/' + item.answer + '">' +
        esc(page.title ? "页面工作记录 · " + page.title : "页面工作记录 · " + page.path) + '</a>').join("") + '</div>' : '') +
    '</div>';
  return '<section class="wiki-section"><h3>Codex 对话整理</h3><ul class="wiki-chat-updates">' + items.map(item => {
    const history = item.history || [];
    return '<li>' + evidence(item, true) +
      (history.length ? '<details class="wiki-chat-history" data-remember="' + esc(item.topic) + '"' +
        (history.some(prior => prior.answer === answer) ? ' open' : '') +
        '><summary>此前整理与原文</summary>' +
        history.map(prior => '<section>' + evidence(prior) + '</section>').join("") + '</details>' : "") + '</li>';
  }).join("") + '</ul></section>';
}

async function wikiPanel(params) {
  const skills = '<a class="secondary" href="/?' + esc(qs({section: 2})) + '#skillbank">Skills 技能包</a>';
  if (!params.project) {
    const projects = await get("build-wiki-index");
    return '<div class="wiki-index"><div class="directory-tools">' +
      '<input id="wiki-search" type="search" placeholder="搜索项目、域名或知识正文" aria-label="搜索项目、域名或知识正文" maxlength="400">' +
      '<span class="directory-count" aria-live="polite">共 ' + fmt(projects.length) + ' 个项目</span>' + skills + '</div>' +
      '<div class="wiki-results">' + wikiDirectory(projects) + '</div></div>';
  }
  const p = await get("build-wiki-project", { project: params.project, slug: params.slug || "" });
  if (view !== "wiki" || params !== filt) return "";
  currentBuildProject = p;
  const top = '<header class="wiki-header"><div><small>' +
    '<a href="/?' + esc(qs({ section: 2 })) + '#wiki">全部项目知识库</a></small><h2>' + esc(p.name) +
    '</h2></div><div class="step-actions"><a class="secondary" href="#buildhub/' + p.id + '">项目进度</a>' +
    buildButton("journal", "查原始记录", "secondary") + skills +
    buildButton("wiki-prepare", "让 Codex 整理", "primary") + '</div></header>';
  if (p.page) {
    const item = p.page;
    const sources = item.sources.map(s => '<li>' + (s.missing
      ? '找不到原文 ' + esc(s.ref)
      : buildButton(s.source === "chat" ? "read-chat" : "read-note", s.title, "text-button", s.id) +
        '<small>' + esc(s.kind) + (s.changed ? ' · 原文已更新' : '') + '</small>') + '</li>').join("");
    const related = p.pages.filter(link => item.related.includes(link.slug));
    return '<section class="wiki-sheet">' + top + '<p><a href="' + esc(wikiPageLink(p)) + '">← 返回本项目知识库</a></p>' +
      '<article class="wiki-article"><h2>' + esc(item.title) + '</h2><p class="wiki-meta">更新于 ' +
      esc(item.updated) + ' · 第 ' + fmt(item.version) + ' 版</p><p class="wiki-lead">' + esc(item.summary) + '</p>' +
      wikiMarkdown(item.body) + '</article>' + wikiChatUpdates(p.id, item.automatic, params.answer) +
      '<section class="wiki-section"><h3>原文依据（' + fmt(item.sources.length) +
      '）</h3><ul class="wiki-sources">' + sources + '</ul></section>' +
      (related.length ? '<section class="wiki-section"><h3>相关知识</h3>' + wikiTopicLinks(p, related) + '</section>' : '') +
      '</section>';
  }
  return '<section class="wiki-sheet">' + top + wikiAutomation(p) + wikiPending(p) +
    '<section class="wiki-section"><h3>知识页（' + fmt(p.pages.length) + '）</h3>' +
    (p.pages.length ? wikiTopicLinks(p, p.pages) :
      '<p class="wiki-meta">可以把项目里的对话、问题和资料请 Codex 整理成知识页。</p>') +
    '</section><details class="wiki-section"><summary>资料检查 · ' + fmt(p.issues.length) + ' 页待核对</summary>' +
    (p.issues.length ? '<ul class="wiki-updates">' + p.issues.map(item =>
      '<li><a href="' + esc(wikiPageLink(p, item.slug)) + '">' + esc(item.title) + '</a><p>' +
      item.reasons.map(esc).join('<br>') + '</p></li>').join("") + '</ul>' :
      '<p class="wiki-meta">未发现缺失的引用、已变更的原文或失效的关联页。</p>') +
    '</details><details class="wiki-section"><summary>更新记录</summary>' +
    (p.updates.length ? '<ol class="wiki-updates">' + p.updates.map(item =>
      '<li><small>' + esc(item.updated) + ' · 第 ' + fmt(item.version) + ' 版</small><p><a href="' +
      esc(wikiPageLink(p, item.slug)) + '">' + esc(item.title) + '</a> · ' + esc(item.change) + '</p></li>'
    ).join("") + '</ol>' : '<p class="wiki-meta">知识页保存后会在这里留下记录。</p>') + '</details></section>';
}

function prepareWiki(p) {
  const topic = p.page ? "更新「" + p.page.title + "」（编号 " + p.page.slug + "）" : "整理或更新项目知识页";
  const command = p.command.length ? "\n\n命令的参数数组（按本机 shell 正确转义，最后追加操作和参数）\n" +
    JSON.stringify(p.command) : "\n\n请在运行勋的软件的主机上打开同一项目的知识库，获取本机命令参数。";
  return copyBox("交给 Codex 整理",
    "请在「勋的软件」中为「" + p.name + "」" + topic + "。\n" +
    "先用 index 查现有页，records 检索项目记录，record note:编号 或 record chat:编号 读原文，show 页编号 读现有页。需要时加 --page 翻页。\n" +
    "写清已有依据的结论、可复用的做法、待核实的问题。遇到说法冲突，列清各自依据。保留原记录，优先更新已有知识页。\n" +
    "用 save 从标准输入读 JSON 保存。字段为 slug（稳定的英文短横线编号）、title、summary、body（Markdown）、sources（原文编号数组）、related（本项目知识页编号数组）、version（当前版本，新页为 0）、change（这次改了什么）。只整理知识页，不调整项目进度。保存后用 check 查引用，再告诉我这次更新了哪些页。" +
    command,
    '<p class="wiki-meta">复制后发给主机上的 Codex。整理完成，刷新知识库即可查看。</p>');
}

let wikiSearchTimer;
let wikiSearchRequest = 0;
document.addEventListener("input", event => {
  if (event.target.id === "wiki-folder-search") {
    const filter = event.target.value.trim().toLowerCase();
    const folders = $$("#dialog [data-wiki-folder]");
    for (const folder of folders) folder.hidden = !folder.dataset.wikiFolder.includes(filter);
    $("#dialog .wiki-folder-empty").hidden = folders.some(folder => !folder.hidden);
    return;
  }
  if (event.target.id !== "wiki-search") return;
  const index = event.target.closest(".wiki-index");
  const query = event.target.value.trim();
  const request = ++wikiSearchRequest;
  clearTimeout(wikiSearchTimer);
  wikiSearchTimer = setTimeout(async () => {
    if (!index.isConnected || request !== wikiSearchRequest) return;
    const status = index.querySelector(".directory-count");
    status.textContent = "正在查找…";
    try {
      const projects = await get("build-wiki-index", {find:query});
      if (!index.isConnected || request !== wikiSearchRequest) return;
      status.textContent = (query ? "找到 " : "共 ") + fmt(projects.length) + " 个项目";
      index.querySelector(".wiki-results").innerHTML = wikiDirectory(projects, !!query);
    } catch {
      if (index.isConnected && request === wikiSearchRequest) status.textContent = "搜索中断，请重新输入试一次。";
    }
  }, 220);
});
