"use strict";

let importHistoryPages = [null];

function importHistoryRoute(values) {
  const scope = values.scope === "all" || /^\d+$/.test(values.scope) ? values.scope : "";
  const status = values.status === "pending" ? "pending" : "";
  const find = String(values.find || "").trim().slice(0, 300);
  const query = new URLSearchParams(Object.entries({scope, status, find}).filter(([, v]) => v));
  const text = query.toString();
  return "#imports" + (text ? "/filter/" + text : "");
}

function openImportHistory(query) {
  const params = new URLSearchParams(query);
  const scope = params.get("scope");
  const filters = {
    scope: scope === "all" || knownIndustries.some(i => String(i.id) === scope) ? scope : "",
    status: params.get("status") === "pending" ? "pending" : "",
    find: (params.get("find") || "").slice(0, 300),
  };
  navigate("imports", filters, false);
}

function importHistoryFilters() {
  return '<form class="toolbar import-search" data-form="import-history-filter">' +
    '<label class="searchbox"><input type="search" id="import-filename" name="find" maxlength="300" aria-label="搜索原文件名" placeholder="输入原文件名，例如 39332" value="' +
    esc(filt.find || "") + '"></label>' +
    '<select class="filter" name="scope" aria-label="搜索行业">' +
    option("all", "全部行业", filt.scope) +
    knownIndustries.map(i => option(i.id, i.name, filt.scope || industryId)).join("") +
    '</select><select class="filter" name="status" aria-label="处理状态">' +
    option("", "全部文件", filt.status || "") + option("pending", "只看待处理", filt.status) +
    '</select><button class="secondary">搜索</button>' +
    (filt.find ? btn("import-history-clear", "清除搜索", "text-button") : "") + '</form>';
}

function loadImportHistory() {
  const before = importHistoryPages.at(-1);
  return get("import-history", {...filt, before: before ? JSON.stringify(before) : ""});
}

function importFileStatus(item) {
  if (item.state === "queued") return "排队中";
  if (item.state === "running") return "正在导入";
  if (item.state === "replaced") return "已补传";
  if (item.state === "needs_file") return "需更换文件";
  if (item.pending) return fmt(item.pending) + " 张表待处理";
  if (item.state === "error" || (item.state && item.state !== "done")) return "待继续导入";
  return item.batches ? fmt(item.batches) + " 次入库" : "已处理";
}

function importHistoryPanel(result) {
  const items = result.items.map(item => {
    const download = item.run ? "/api/import-original?" + qs({industry: item.industry, run: item.run})
      : item.archived ? "/api/raw?" + qs({industry: item.industry, id: item.batch}) : "";
    const pending = item.pending || (item.state && !["done", "replaced"].includes(item.state));
    const alias = filt.find && item.matched_filename !== item.filename
      ? '<small class="history-file-alias">匹配文件名 ' + esc(item.matched_filename) + '</small>' : "";
    return '<article class="history-file"><header><div><h3>' + esc(item.filename) + '</h3>' + alias +
      '<p>' + esc(item.industry_name) + ' · ' + esc(item.stamp) +
      ' <span class="history-state' + (pending ? ' needs-attention' : '') + '">' + esc(importFileStatus(item)) + '</span></p>' +
      '</div>' + (download ? '<a download class="secondary" href="' + esc(download) + '">' +
        (["needs_file", "replaced"].includes(item.state) ? "下载原文件" : "下载原表") + '</a>' : "") +
      '</header><details class="history-file-detail" data-key="' + esc(item.key) + '" data-industry="' + item.industry +
      '"><summary>查看导入结果</summary><div class="history-file-body"></div></details></article>';
  }).join("");
  const title = filt.status === "pending" ? "待处理文件" : "导入文件";
  const empty = filt.find ? "没有找到匹配的文件。可以换个文件名片段，或查找全部行业。" :
    filt.status === "pending" ? "没有待处理的文件。" : "还没有导入文件。";
  return '<section class="import-history"><div class="list-caption"><h2>' + title + '</h2>' +
    btn("import-history-refresh", "刷新", "text-button") + '</div>' +
    (items || '<p class="wiki-meta history-empty">' + empty + '</p>') +
    '<div class="step-actions history-pages">' +
    (importHistoryPages.length > 1 ? btn("import-history-prev", "上一页") : "") +
    (result.before ? btn("import-history-next", "更早的文件", "secondary", 'data-before="' +
      esc(JSON.stringify(result.before)) + '"') : "") + '</div></section>';
}

function importBatchRows(batches, industry) {
  if (!batches.length) return "";
  return table(["入库时间", "入库结果", "资料"], batches.map(batch => {
    const sites = batch.site_valid != null;
    const summary = sites ? "新增 " + fmt(batch.added) + " 个网站 · 有效 " + fmt(batch.site_valid) + " 行" +
      (batch.blank ? " · 跳过 " + fmt(batch.blank) + " 行" : "") : importWordBatchSummary(batch);
    return '<tr><td>' + esc(batch.created) + '</td><td>' + esc(summary) + '</td><td>' +
      importBatchLinks(batch, industry, !sites) + '</td></tr>';
  }).join(""));
}

document.addEventListener("toggle", async e => {
  const node = e.target;
  if (!node.matches?.(".history-file-detail") || !node.open || node.dataset.loaded) return;
  const body = node.querySelector(".history-file-body");
  node.dataset.loaded = "loading";
  body.innerHTML = '<p role="status">正在读取导入结果…</p>';
  try {
    const result = await get("import-history-file", {industry: node.dataset.industry, key: node.dataset.key});
    body.innerHTML = (result.run ? importResultDetails(result.run, node.dataset.industry) : "") +
      (result.run && result.other_batches.length ? '<h4>其他入库记录</h4>' : "") +
      importBatchRows(result.other_batches, node.dataset.industry);
    node.dataset.loaded = "done";
  } catch (error) {
    delete node.dataset.loaded;
    body.innerHTML = '<p class="error" role="alert">' + esc(error.message) + '</p>';
  }
}, true);

function importHistoryAction(action, button) {
  if (action === "import-history-clear") return openAppLocation(importHistoryRoute({...filt, find: ""}));
  if (action === "import-history-next") importHistoryPages.push(JSON.parse(button.dataset.before));
  if (action === "import-history-prev" && importHistoryPages.length > 1) importHistoryPages.pop();
  history.replaceState({...history.state, importHistoryPages}, "");
  return load();
}
