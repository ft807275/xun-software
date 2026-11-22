"use strict";

const recordKinds = ["", "提示词", "Codex 回复", "问题", "待解决", "下一步", "页面待办", "步骤笔记", "对话"];
const recordQueryLimit = 2048;
let recordSearchPages = [null];
let recordOpenRequest = 0;

function recordSearchRoute(values) {
  const query = new URLSearchParams();
  const find = String(values.find || "").trim().slice(0, recordQueryLimit);
  if (find) query.set("find", find);
  if (recordKinds.includes(values.kind) && values.kind) query.set("kind", values.kind);
  if (values.owner) query.set("owner", values.owner);
  const encoded = query.toString();
  return "#buildsearch" + (encoded ? "/filter/" + encoded : "");
}

function pageTasksLink(project, style = "secondary") {
  const industry = project?.industry || industryId;
  const section = project?.section || activeAreaId;
  const owner = project ? [industry, section, project.id].join("/") : "";
  const link = "/?" + qs({industry, section:2}) + recordSearchRoute({kind:"页面待办", owner});
  return '<a class="' + style + '" href="' + esc(link) + '">页面待办</a>';
}

function openRecordSearch(query) {
  const p = new URLSearchParams(query);
  navigate("buildsearch", {
    find: (p.get("find") || "").slice(0,recordQueryLimit),
    owner: p.get("owner") || "",
    kind: recordKinds.includes(p.get("kind")) ? p.get("kind") : "",
  }, false);
}

function searchMarkup(value, find) {
  if (!find) return esc(value);
  const plain = find.replace(/[.*+?^\${}()|[\]\\]/g, "\\$&");
  return String(value || "").split(new RegExp("(" + plain + ")", "gi"))
    .map((part, n) => n % 2 ? "<mark>" + esc(part) + "</mark>" : esc(part)).join("");
}

function recordPageLinks(record, pages) {
  if (!pages?.length) return "";
  const base = "/?" + qs({industry:record.industry, section:record.section}) + "#sitemap/" + record.project + "/live/";
  const link = page => '<a class="directory-link" href="' + esc(base + encodeURIComponent(page.path)) +
    '" title="' + esc(page.path) + '">' + esc(page.title || page.path) + ' ›</a>';
  return '<div class="record-page-links"><small>关联页面</small> ' +
    pages.slice(0, 2).map(link).join("") +
    (pages.length > 2 ? '<details><summary>另外 ' + fmt(pages.length - 2) + ' 页</summary>' +
      pages.slice(2).map(link).join("") + '</details>' : '') + '</div>';
}

function pageTaskCard(item, find) {
  const link = "/?" + qs({industry:item.industry, section:item.section}) +
    "#sitemap/" + item.project + "/live/" + encodeURIComponent(item.path);
  const project = {id:item.project, industry:item.industry, section:item.section, name:item.project_name, mapPath:item.path};
  return '<article class="project-search-record"><div><p class="project-search-context">' +
    [item.project_name, item.label].map(value => searchMarkup(value,find)).join(" · ") +
    '</p><h3><a href="' + esc(link) + '">' + searchMarkup(item.title,find) + '</a></h3>' +
    '<small class="map-path">' + searchMarkup(item.path,find) + '</small>' +
    '<p class="project-search-preview work-todo">' + searchMarkup(item.preview,find) + '</p><small>' +
    [item.stage, item.origin, item.created].filter(Boolean).map(esc).join(" · ") +
    '</small></div><div class="step-actions record-card-actions"><a class="secondary" href="' + esc(link) +
    '">打开页面</a>' + nextTaskOriginal(project, item.todoSource) + '</div></article>';
}

function projectRecordCard(item, find) {
  const address = {industry: item.industry, section: item.section, project: item.project, source: item.source,
    id: item.id, projectName: item.project_name, step: item.step, created: item.created};
  return '<article class="project-search-record"><div><p class="project-search-context">' +
    [item.project_name, item.label, item.step].filter(Boolean).map(value => searchMarkup(value,find)).join(" · ") +
    '</p><h3>' + searchMarkup(item.title || item.kind, find) + '</h3>' +
    (item.preview !== item.title ? '<p class="project-search-preview">' + searchMarkup(item.preview, find) + '</p>' : "") +
    '<small>' + esc(item.kind) +
    (item.kind === "问题" ? (item.unresolved ? ' · <strong>待解决</strong>' : ' · 已解决') : "") +
    (item.reportCount ? " · " + fmt(item.reportCount) + " 次 Codex 报告" : "") +
    (item.created ? ' · ' + esc(item.created) : "") + '</small>' + recordPageLinks(address, item.pages) + '</div>' +
    '<div class="step-actions record-card-actions">' + recordButton("record-search-open", "打开原文", address) +
    (item.unresolved ? recordButton("record-search-resolve", "填写解决办法", address, "text-button") : "") + '</div></article>';
}

async function projectRecordSearch(params) {
  const tasks = params.kind === "页面待办";
  const before = recordSearchPages.at(-1);
  const result = await get("project-search", {...params, before: before ? JSON.stringify(before) : ""});
  const waiting = params.kind === "待解决";
  const selectProjects = result.projects.map(p => option([p.industry,p.section,p.id].join("/"),
    p.name + " · " + p.label + (waiting ? " · " + fmt(p.openIssues) + " 个待解决" : ""), params.owner)).join("");
  const form = '<form class="toolbar project-search-form" data-form="record-search">' +
    '<label class="searchbox"><input type="search" name="find" aria-label="搜索建站原文或页面网址" maxlength="' + recordQueryLimit +
    '" placeholder="' + (tasks ? "找页面名称、网址或待办内容" : "输入页面网址、路径或原文关键词") + '" value="' +
    esc(params.find || "") + '"></label><select name="owner" class="filter" aria-label="网站项目">' +
    option("", "全部网站项目", params.owner || "") + selectProjects + '</select>' +
    '<select name="kind" class="filter" aria-label="记录类型">' + recordKinds.map(k =>
      option(k,k || "全部记录类型",params.kind || "")).join("") +
    '</select><button class="primary">查找</button></form>';
  const results = result.items.map(item => tasks ? pageTaskCard(item,params.find) : projectRecordCard(item,params.find)).join("");
  const quick = [["页面待办","页面待办"],["待解决","待解决问题"],["下一步","下一步记录"],["","全部记录"]].map(([kind, title]) =>
    btn("record-search-kind", title, (params.kind || "") === kind ? "primary" : "secondary",
      'data-kind="' + esc(kind) + '" aria-pressed="' + ((params.kind || "") === kind) + '"')).join("");
  const issueProjects = waiting ? '<div class="step-actions issue-projects" aria-label="待解决问题按项目">' +
    [["", "全部项目", result.projects.reduce((total,p) => total + p.openIssues, 0)],
      ...result.projects.filter(p => p.openIssues > 0 || params.owner === [p.industry,p.section,p.id].join("/"))
        .map(p => [[p.industry,p.section,p.id].join("/"), p.name, p.openIssues])].map(([owner, name, count]) =>
      btn("record-search-owner", esc(name) + ' <span>' + fmt(count) + '</span>', params.owner === owner ? "primary" : "secondary",
        'data-owner="' + esc(owner) + '" aria-pressed="' + (params.owner === owner) + '"')).join("") + '</div>' : "";
  return '<section class="project-search"><div class="step-actions record-quick" aria-label="常用记录筛选">' +
    quick + '</div>' + form + issueProjects + '<div class="project-search-list">' +
    (results || '<p class="build-empty">' + (tasks ? "没有找到待办。可以在任一页面的工作记录里添加。" :
      "没有找到匹配的记录。可以换个词，或选全部网站项目。") + '</p>') + '</div>' +
    '<div class="step-actions">' + (recordSearchPages.length>1 ? btn("record-search-prev", "上一页") : "") +
    (result.before ? btn("record-search-next", tasks ? "下一页" : "更早的记录", "secondary", 'data-before="' +
      esc(JSON.stringify(result.before)) + '"') : "") + '</div></section>';
}

function issueOriginLinks(issue, reports) {
  if (!reports?.length) return "";
  const base = "/?" + qs({industry:issue.industry, section:issue.section});
  return '<section class="issue-reports"><h3>Codex 报告原文</h3><ul>' +
    reports.map(report => '<li><div><p>' + esc(report.chat) + '</p><small>' + esc(report.sent) +
      '</small></div><div class="step-actions">' +
      recordButton("record-search-open", "打开报告", {...issue, source:"chat", id:report.answer,
        created:report.sent, returnIssue:issue}) +
      (report.wikiSlug ? '<a class="text-button" href="' + esc(base +
        wikiPageRoute(issue.project, report.wikiSlug, report.answer)) + '" title="' + esc(report.wikiTopic) +
        '">对应知识更新</a>' : '') + '</div></li>').join("") + '</ul></section>';
}

async function openProjectRecord(button) {
  const record = JSON.parse(button.dataset.record);
  const {industry,section,project,source,id,projectName,step,created} = record;
  const token = ++recordOpenRequest;
  const params = filt, currentView = view;
  const data = await get("build-archive-original", {industry, section, project, source, id, pagePath:record.pagePath});
  if (token !== recordOpenRequest || view !== currentView || filt !== params) return;
  const projectLink = "/?" + qs({industry,section}) + "#buildhub/" + project;
  const resolution = data.resolution ? '<details class="project-original-solution"><summary>查看解决办法</summary><pre>' +
    esc(data.resolution) + '</pre></details>' : "";
  const attachments = (data.files || []).map(file => '<li><a download href="/api/build-file?' +
    esc(qs({industry,section,id:file.id})) + '">' + esc(file.filename) + '</a></li>').join("");
  const replyAction = data.role === "user" || record.prompt
    ? recordButton("record-search-replies", record.prompt ? "返回本轮回复" : "查看这轮回复",
      {...record,id:record.prompt || id, prompt:undefined, source:"chat"}) : "";
  const knowledge = record.knowledge?.slug
    ? '<a class="text-button" href="' + esc("/?" + qs({industry,section}) +
      wikiPageRoute(project, record.knowledge.slug, id)) + '">对应知识更新</a>'
    : "";
  const pageTask = data.pageTask ? '<section class="detail-section"><h3>页面待办摘要</h3><p class="work-todo">' +
    esc(data.pageTask.todo) + '</p><small class="map-path">' + esc(data.pageTask.path) + '</small></section>' : "";
  copyBox(data.title || data.kind, data.body,
    '<div class="step-actions project-original-actions">' + replyAction + knowledge +
    (record.returnIssue ? recordButton("record-search-open", "返回问题原文", record.returnIssue) : "") +
    (record.returnHandoff ? buildButton("resume-codex", "返回交接", "secondary") : "") +
    (data.kind === "问题" ? recordButton("record-search-resolve",
      data.resolution.trim() ? "编辑解决办法" : "填写解决办法", record) : "") +
    '<a class="secondary" href="' + esc(projectLink) + '">打开所属项目</a>' +
    btn("close", currentView === "buildsearch" ? "返回搜索结果" : "关闭原文", "text-button") + '</div>' +
    '<p class="inline-hint">' + [projectName, data.stepTitle || step, data.kind, data.created || created].filter(Boolean).map(esc).join(" · ") + '</p>' +
    pageTask + recordPageLinks(record, data.pages) + resolution + issueOriginLinks(record, data.issueOrigins) +
    (attachments ? '<h3>附件</h3><ul>' + attachments + '</ul>' : ""),
    "复制原文", data.kind === "问题" ? 4 : 11);
}

async function resolveSearchIssue(button) {
  const record = JSON.parse(button.dataset.record);
  const {industry, section, project, source, id} = record;
  const token = ++recordOpenRequest;
  const params = filt, currentView = view;
  const issue = await get("build-archive-original", {industry,section,project,source,id});
  if (token !== recordOpenRequest || view !== currentView || filt !== params) return;
  if (issue.kind !== "问题") throw Error("找不到这条问题。");
  const target = esc(JSON.stringify({industry,section,project,id,version:issue.version}));
  dialog("填写解决办法", '<form class="form-grid" data-form="record-search-resolution" data-target="' + target + '">' +
    '<p class="field full build-copy">' + esc(issue.body) + '</p>' +
    buildArea("resolution", "解决办法", issue.resolution, true) +
    '<div class="field full"><button class="primary" type="submit">保存解决办法</button></div></form>');
}

async function submitSearchResolution(form, values) {
  const button = form.querySelector("[type=submit]");
  if (button.disabled) return;
  const target = JSON.parse(form.dataset.target);
  button.disabled = true;
  try {
    await post("build-archive-resolve-issue",
      {project:target.project,id:target.id,version:target.version,resolution:values.resolution},
      {industry:target.industry,section:target.section});
    if (!form.isConnected) return;
    close();
    await load();
    toast("已保存解决办法");
  } finally { button.disabled = false; }
}

function recordButton(action, label, record, style = "secondary") {
  return btn(action, label, style, 'data-record="' + esc(JSON.stringify(record)) + '"');
}

async function projectRecordReplies(button) {
  const record = JSON.parse(button.dataset.record);
  const {industry,section,project,id,offset=0} = record;
  const token = ++recordOpenRequest;
  const params = filt;
  const data = await get("build-archive-replies", {industry,section,project,id,offset});
  if (token !== recordOpenRequest || view !== "buildsearch" || filt !== params) return;
  const replies = data.items.map(item => recordButton("record-search-open", esc(item.preview),
    {...record, id:item.id, prompt:id, created:item.sent}, "journal-row")).join("");
  dialog("本轮 Codex 回复", '<p>' + esc(record.projectName) + '</p><div class="journal-list">' +
    (replies || '<p>这轮还没有已归档的回复。</p>') + '</div><div class="step-actions">' +
    recordButton("record-search-open", "返回原提示词", {...record,offset:undefined}) +
    (offset ? recordButton("record-search-replies", "上一页", {...record,offset:offset-20}) : "") +
    (data.more ? recordButton("record-search-replies", "下一页", {...record,offset:offset+20}) : "") +
    '</div>');
}

function recordSearchAction(action, button) {
  if (action === "record-search-open") return openProjectRecord(button);
  if (action === "record-search-replies") return projectRecordReplies(button);
  if (action === "record-search-resolve") return resolveSearchIssue(button);
  if (action === "record-search-kind") {
    return openAppLocation(recordSearchRoute({...filt, kind:button.dataset.kind}));
  }
  if (action === "record-search-owner") {
    return openAppLocation(recordSearchRoute({...filt, owner:button.dataset.owner}));
  }
  if (action === "record-search-next") recordSearchPages.push(JSON.parse(button.dataset.before));
  if (action === "record-search-prev" && recordSearchPages.length > 1) recordSearchPages.pop();
  history.replaceState({...history.state, recordSearchPages}, "");
  window.scrollTo(0, 0);
  return load();
}
