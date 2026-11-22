"use strict";

const renderedExports = new WeakMap();

function exportSize(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + " GB";
  if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(1) + " MB";
  return Math.max(1, Math.round(bytes / 1024)).toLocaleString("zh-CN") + " KB";
}

function exportRecord(item) {
  const backup = item.task === "backup" || item.task === "transfer";
  const total = item.files_total || (backup ? 0 : item.ids.length * item.kinds.length);
  const working = ["queued", "running"].includes(item.state);
  const selected = backup ? (item.task === "transfer" ? "软件与完整资料库" : "") :
    [item.ids.map(presetIndustry).join("、"),
      item.filters?.market && marketLabel(item.filters.market), item.filters?.q,
      item.kinds.map(kind => exportLabels[kind]).join("、")].filter(Boolean).join(" · ");
  const date = new Date(item.created * 1000).toLocaleString("zh-CN", {hour12: false});
  let detail, action = "";
  if (item.state === "ready") {
    detail = "可下载 · " + exportSize(item.size);
    action = '<a class="secondary" download href="/api/export-download?id=' + esc(item.id) + '">下载 ZIP</a>';
  } else if (item.state === "error" || item.state === "expired") {
    detail = item.state === "expired" ? "下载文件已过期" : item.error || "生成失败";
    action = btn("export-retry", "重新生成", "secondary", 'data-job="' + esc(item.id) + '"');
  } else if (item.state === "queued") {
    detail = "排队中";
  } else if (backup) {
    detail = item.kind === "program" ? "正在准备软件" : !total ? "正在读取资料目录" :
      item.kind === "packaging" && item.files_done === total ? "正在封装 ZIP" :
      item.files_done + " / " + total + " 个资料库已保存";
    if (item.industry) detail += " · " + item.industry;
    if (item.kind === "database") detail += " · 正在备份数据库";
    if (item.kind === "archive") detail += " · 已打包 " + fmt(item.written) + " / " + fmt(item.written_total) + " 个文件";
  } else {
    detail = item.files_done + " / " + total + " 份文件已生成";
    if (item.kind) detail += " · " + item.industry + " · " + exportLabels[item.kind] +
      (item.written ? " · 已写 " + fmt(item.written) + " 行" : "");
  }
  return '<article class="export-record" data-job="' + esc(item.id) + '"><div><h3>' + esc(item.title) +
    '</h3>' + (selected ? '<p>' + esc(selected) + '</p>' : '') + '<p class="export-record-status">' + esc(detail) +
    ' <span>· ' + esc(date) + '</span></p>' + (working ? '<progress aria-label="' +
      (backup ? "已保存资料库" : "已生成文件") + '" max="' + Math.max(1,total) + '"' +
      (item.state === "running" && !item.files_done ? '' : ' value="' + item.files_done + '"') + '></progress>' : '') + '</div>' + action + '</article>';
}

function updateExportList(host, records) {
  const html = records.map(exportRecord).join("");
  if (renderedExports.get(host) === html) return;
  renderedExports.set(host, html);
  host.innerHTML = html;
}

async function refreshExportHistory(host) {
  const present = () => host.isConnected && $("#dialog").open;
  if (!present()) return;
  const sync = host.querySelector(".export-sync");
  try {
    const records = await get("export-records");
    if (!present()) return;
    const pending = records.filter(item => item.state === "queued" || item.state === "running");
    const recent = records.filter(item => item.state !== "queued" && item.state !== "running");
    updateExportList(host.querySelector(".export-active"), pending);
    updateExportList(host.querySelector(".export-recent"), recent);
    host.querySelector(".export-empty").hidden = records.length > 0;
    host.querySelector(".export-empty").textContent = "还没有导出记录。";
    host.querySelector('[data-action="export-background"]').textContent = pending.length ? "后台继续" : "关闭";
    sync.textContent = pending.length ? fmt(pending.length) + " 项正在生成或排队" : "";
    if (pending.length) setTimeout(() => refreshExportHistory(host), 850);
  } catch {
    if (!present()) return;
    sync.textContent = "正在重新连接导出记录…";
    setTimeout(() => refreshExportHistory(host), 2500);
  }
}

function showExportHistory() {
  dialog("导出记录",
    '<div class="export-history"><p class="inline-hint">ZIP 保留 7 天。下载中断后，可从同一条记录重新下载。</p>' +
    '<p class="export-sync" aria-live="polite"></p><div class="export-active"></div>' +
    '<div class="export-recent"></div><p class="export-empty">正在查找导出记录…</p>' +
    '<div class="step-actions export-history-actions">' + btn("export-background", "关闭") +
    btn("bulkExport", "发起新导出", "text-button") + btn("export-backup-center", "备份与换机", "text-button") + '</div></div>');
  return refreshExportHistory($("#dialog .export-history"));
}

async function backupCenter() {
  const {local} = await get("auth");
  dialog("备份与换机", '<p>打包可在后台继续，完成后到「导出记录」下载。</p>' +
    '<div class="backup-choices"><section><h3>只升级程序</h3>' +
    '<p>把新版解压到新文件夹。打开新版时，选择旧版的「我的资料」，以后从新版继续使用。</p>' +
    '<a class="secondary" href="/api/program-update" download>下载程序升级包</a></section>' +
    '<section><h3>整库备份</h3>' +
    '<p>保存全部行业的关键词、同行、图库和建站记录，供留存或恢复资料。</p>' +
    btn("export-backup-start", "生成整库备份", "secondary", 'data-task="backup"') + '</section>' +
    '<section><h3>Win11 / Mac 换机包</h3><p>把软件和完整资料库装进同一个 ZIP。新电脑完整解压后，首次打开会显示恢复进度。</p>' +
    btn("export-backup-start", "生成换机包", "primary", 'data-task="transfer"') + '</section></div>' +
    '<div class="step-actions">' + (local ? btn("export-backup-check", "检查备份 ZIP", "secondary") : "") +
    btn("export-history", "查看导出记录", "text-button") + '</div>');
}

async function checkBackup(button) {
  if (modalBusy) return;
  modalBusy = true;
  button.disabled = true;
  const label = button.textContent;
  button.textContent = "等待选择文件…";
  let info;
  try {
    const native = window.webkit?.messageHandlers?.backupCheck;
    info = native ? JSON.parse(await native.postMessage({})) : await post("backup-check", {});
    if (info.error) throw new Error(info.error);
  } finally {
    button.disabled = false;
    button.textContent = label;
    modalBusy = false;
  }
  if (info.cancelled) return;
  const types = {backup:"整库备份", transfer:"完整换机包", program:"程序升级包"};
  const size = bytes => bytes >= 10 ** 9 ? (bytes / 10 ** 9).toFixed(2) + " GB" :
    (bytes / 10 ** 6).toFixed(2) + " MB";
  const rows = [["文件类型", types[info.type]], ["ZIP 大小", size(info.archive_bytes)]];
  if (info.version) rows.push(["软件版本", info.version]);
  if (info.created) rows.push(["打包时间", info.created]);
  if (info.unpack_bytes) rows.push(["解压软件及随附文件", "约 " + size(info.unpack_bytes)]);
  if (info.restore_bytes) {
    rows.push(["首次恢复资料", "约 " + size(info.restore_bytes)], ["资料库", fmt(info.databases) + " 个"],
      ["上传原件", fmt(info.originals) + " 份"], ["单独保存的图库原件", fmt(info.media) + " 张"]);
  }
  const message = info.type === "program" ? "打开新版时，可选择原来的「我的资料」文件夹。" :
    info.type === "transfer" && !info.restore_bytes ?
      "这是旧版换机包。解压后可选择里面的 library-data.zip，查看恢复资料所需的空间。" :
      "正式恢复时会检查原件完整性和数据库。";
  dialog("备份文件检查", '<p><strong>' + esc(info.name) + '</strong></p>' +
    (info.unpack_bytes && info.restore_bytes ? '<p>在同一磁盘解压并恢复，还需要约 <strong>' +
      size(info.unpack_bytes + info.restore_bytes) + '</strong> 可用空间。</p>' : '') +
    '<dl class="backup-inventory">' + rows.map(([key,value]) =>
      '<div><dt>' + esc(key) + '</dt><dd>' + esc(value) + '</dd></div>').join('') + '</dl>' +
    (info.libraries?.length ? '<p><strong>包含的资料库</strong></p><p>' + esc(info.libraries.join('、')) + '</p>' : '') +
    '<p class="inline-hint">' + esc(message) + '</p><div class="step-actions">' +
    btn("export-backup-center", "返回备份与换机", "secondary") + '</div>');
}

async function beginExport(button, request, payload) {
  if (modalBusy) return;
  modalBusy = true;
  if (button) button.disabled = true;
  try {
    await post(request, payload);
  } finally {
    if (button) button.disabled = false;
    modalBusy = false;
  }
  return showExportHistory();
}

function exportAction(action, button) {
  if (action === "export-history") return showExportHistory();
  if (action === "export-backup-center") return backupCenter();
  if (action === "export-backup-check") return checkBackup(button);
  if (action === "export-backup-start") return beginExport(button, "export-backup", {task:button.dataset.task});
  if (action === "export-background") return close();
  if (action === "export-retry") return beginExport(button, "export-retry", {id:button.dataset.job});
  if (action === "export-preset") return beginExport(button, "export-records", JSON.parse(button.dataset.selection));
  if (action === "export-filtered") return beginExport(button, "export-records",
    {ids:[industryId], kinds:["words","evidence"], filters:JSON.parse(button.dataset.filters)});
}
