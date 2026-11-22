"use strict";

const presetKeys = {
  words: ["q", "state", "ptype", "category", "traffic", "featured", "site", "market", "batch", "batch_scope", "mode", "type_review"],
  sites: ["q", "audience", "batch", "keyword_status"],
  gallery: ["q", "kind", "category", "role", "linkstate"],
};
const exportLabels = {
  words: "去重关键词 CSV",
  evidence: "关键词来源和指标 CSV",
  sites: "同行网站 CSV",
  ai: "AI 建站关键词 JSONL",
};

function presetIndustry(id) {
  return knownIndustries.find(item => item.id === id)?.name || "行业 " + id;
}

function readSavedFilters(kind, encoded) {
  try {
    const input = JSON.parse(decodeURIComponent(encoded));
    return Object.fromEntries(presetKeys[kind].flatMap(key =>
      typeof input?.[key] === "string" ? [[key, input[key]]] : []));
  } catch {
    return {};
  }
}

function presetRows(items, scope) {
  if (!items.length) return '<p class="inline-hint">还没有保存方案。</p>';
  return '<ul class="preset-list">' + items.map(item => {
    const exporting = item.kind === "export";
    const description = exporting
      ? item.ids.map(presetIndustry).join("、") + " · " + item.kinds.map(k => exportLabels[k]).join("、")
      : [presetIndustry(item.industry), titles[item.kind], item.filters.market && marketLabel(item.filters.market),
        siteKeywordLabels[item.filters.keyword_status], item.filters.q].filter(Boolean).join(" · ");
    const open = exporting
      ? btn("export-preset", "按方案生成", "secondary", 'data-selection="' +
        esc(JSON.stringify({ids:item.ids, kinds:item.kinds, title:item.name})) + '"')
      : btn("preset-open", "应用筛选", "secondary", 'data-url="' +
        esc("/?" + qs({industry: item.industry, section: 1}) + "#" + item.kind +
          "/saved/" + encodeURIComponent(JSON.stringify(item.filters))) + '"');
    const remove = btn("preset-remove-confirm", "移除方案", "text-button",
      'data-id="' + item.id + '" data-scope="' + scope + '" data-name="' + esc(item.name) + '"');
    return '<li><div><strong>' + esc(item.name) + '</strong><small>' + esc(description) +
      '</small></div><div class="step-actions">' + open + remove + '</div></li>';
  }).join("") + "</ul>";
}

function presetName(example, required = false) {
  return '<label class="field">方案名称<input name="name" maxlength="80" ' +
    'placeholder="' + esc(example) + '" ' + (required ? "required" : "") + '></label>';
}

async function showPresets(scope) {
  const items = await get("saved-presets", {scope});
  const filterPage = Object.prototype.hasOwnProperty.call(presetKeys, scope);
  const saveForm = filterPage
    ? '<form class="preset-save" data-form="preset-save"><p>下次可一键打开现在的筛选结果。</p>' +
      presetName("例如：采购词 · 有自然流量", true) + '<button class="primary">保存当前筛选</button></form>'
    : btn("bulkExport", "设置批量导出", "secondary");
  dialog(filterPage ? industryName + " · " + titles[scope] + "常用筛选" : "常用方案",
    presetRows(items, scope) + saveForm);
}

async function savePresetFilter(form, name) {
  const button = form.querySelector("button");
  button.disabled = true;
  modalBusy = true;
  try {
    await post("saved-presets", {kind: view, name, payload: {filters: filt}});
    await showPresets(view);
    toast("已保存常用筛选");
  } finally {
    modalBusy = false;
    button.disabled = false;
  }
}

async function presetAction(action, button) {
  if (action === "preset-list") return showPresets(button.dataset.scope || view);
  if (action === "preset-open") {
    close();
    return openAppLocation(button.dataset.url);
  }
  const {id, name, scope} = button.dataset;
  if (action === "preset-remove-confirm") {
    return dialog("移除常用方案", '<p>移除「' + esc(name) + '」？</p><div class="step-actions">' +
      btn("preset-list", "取消", "secondary", 'data-scope="' + scope + '"') +
      btn("preset-remove", "移除方案", "primary", 'data-id="' + id + '" data-scope="' + scope + '"') + '</div>');
  }
  if (action === "preset-remove") {
    button.disabled = true;
    try {
      await post("saved-preset-remove", {id});
      await showPresets(scope);
      toast("已移除常用方案");
    } finally {
      button.disabled = false;
    }
  }
}
