"use strict";

let bankQuery = "", bankPage = 1, bankHistory = false;
function skillButton(action, label, id=0, style="secondary") {
  return btn("bank-"+action, esc(label), style, 'data-id="'+Number(id)+'"');
}
function skillHistory(items) {
  if (!items.length) return '<p class="empty">还没有项目使用记录。</p>';
  return '<ul class="skill-history">'+items.map(u=>'<li><strong>'+esc(u.name)+'</strong> · '+esc(u.kind)+
    '　<a href="/?'+esc(qs({industry:u.industry,section:u.section}))+
    (u.page ? '#sitemap/'+u.project+'/live/'+encodeURIComponent(u.page) : '#buildhub/'+u.project)+'">'+
    esc(u.page ? u.project_name + " · " + u.page : u.project_name)+'</a>'+
    '<p>'+esc(u.detail)+'</p></li>').join("")+'</ul>';
}
async function bankPanel() {
  const toolbar='<div class="step-actions">'+skillButton("cards","全部技能",0,bankHistory?"secondary":"primary")+
    skillButton("history","实际使用记录",0,bankHistory?"primary":"secondary")+btn("aiConnection","连接 Codex","text-button")+'</div>';
  if(bankHistory) {
    const history=await get("skillbank-usage");
    return toolbar+'<h2>实际使用记录</h2>'+skillHistory(history.filter(u=>u.kind==="实际使用" || u.kind==="页面实际使用"));
  }
  const data=await get("skillbank-list",{query:bankQuery,page:bankPage});
  return toolbar+'<form id="bank-search" class="step-actions"><label class="field">找技能<input name="query" type="search" value="'+
    esc(bankQuery)+'" placeholder="例如 验收、产品页、wordpress"></label><button class="secondary">搜索</button></form>'+
    '<div class="module-grid">'+data.items.map(c=>'<button type="button" class="module-card" data-action="bank-open" data-id="'+c.id+
      '"><strong>'+esc(c.name)+'</strong><span>'+esc(c.description)+'</span><small>'+
      (c.offline?"已保存原包":c.url?"已收藏网址":"项目资料")+'</small></button>').join("")+'</div>'+
    (!data.items.length?'<p class="empty">没有找到技能，可以收藏网址或导入 ZIP。</p>':'')+
    '<div class="step-actions">'+(bankPage>1?skillButton("prev","上一页"):"")+(data.more?skillButton("next","下一页"):"")+'</div>';
}
async function showSkill(id) {
  const c=await get("skillbank-detail",{id});
  const download=c.package?'<a class="secondary" href="/api/skillbank-download?'+esc(qs({id}))+'">下载原 ZIP</a>':'';
  dialog(c.name,'<h3>这个技能做什么</h3><p>'+esc(c.description)+'</p><h3>怎样使用</h3><p>'+
    esc(c.guidance || (c.package?"告诉 Codex 你正在做哪一页、想改什么，它可以从本库读取技能原文和配套文件。":"可以保存自己的用法，或导入带 SKILL.md 的原包。"))+
    '</p>'+(c.url?'<p><a target="_blank" rel="noreferrer" href="'+esc(c.url)+'">查看来源网址</a></p>':'')+
    '<div class="step-actions">'+skillButton("copy","交给 Codex",id,"primary")+skillButton("edit","编辑说明",id)+(c.package?skillButton("prepare","准备本机技能文件",id):"")+download+'</div>'+
    '<h3>哪些项目用过</h3>'+skillHistory(c.history));
}

const photoClassificationReviews = new WeakMap();

function photoClassificationDialog(title, preview) {
  const categories = (galleryFilters.categories || []).map(c=>'<option value="'+esc(c.name)+'"></option>').join("");
  dialog(title, '<form id="gallery-classify-selected" class="form-grid">' +
    preview +
    '<label class="field full">产品分类<input name="category" list="photo-batch-categories" required maxlength="120" ' +
    'placeholder="选择已有分类，或输入新分类"></label><datalist id="photo-batch-categories">' + categories + '</datalist>' +
    '<button class="primary" type="submit">保存分类</button></form>');
  return $("#gallery-classify-selected");
}

function updatePhotoReviewCount(form, review) {
  const selected = review.count - review.excluded.size;
  form.querySelector(".classification-count").textContent =
    "将归类 " + fmt(selected) + " 张 · 留待确认 " + fmt(review.excluded.size) + " 张";
  form.querySelector('button[type="submit"]').disabled = selected === 0;
}

function photoReviewGrid(preview, excluded, inputAttr, verb) {
  return '<div class="classification-thumbnails">' +
    preview.photos.map(photo => {
      const skipped = excluded.has(photo.id);
      return '<label class="classification-thumbnail' + (skipped ? ' skipped' : '') + '">' +
        '<img loading="lazy" src="' + photoUrl(photo.id, {preview:1}) + '" alt="">' +
        '<span title="' + esc(photo.filename) + '">' + esc(photo.filename) + '</span>' +
        '<small>' + esc(photo.sources?.join(" · ") || photo.category || "") + '</small>' +
        '<input type="checkbox" ' + inputAttr + '="' + photo.id + '" aria-label="' + verb + ' ' +
        esc(photo.filename) + '"' + (skipped ? '' : ' checked') + '></label>';
    }).join("") + '</div>';
}

function photoReviewPages(preview, page) {
  return preview.pages > 1
      ? '<div class="classification-pages"><span>第 ' + fmt(preview.page) + ' / ' + fmt(preview.pages) +
        ' 页</span>' + page("上一页图片", preview.page - 1, preview.page === 1) +
        page("下一页图片", preview.page + 1, preview.page === preview.pages) + '</div>' : "";
}

function renderPhotoReview(form, review, preview) {
  const page = (label, number, disabled) => btn(
    "bank-photo-review-page", label, "secondary",
    'data-page="' + number + '"' + (disabled ? ' disabled' : ''),
  );
  form.querySelector(".classification-photos").innerHTML = photoReviewGrid(preview, review.excluded, "data-review-photo", "归类") +
    photoReviewPages(preview, page);
  updatePhotoReviewCount(form, review);
}

async function movePhotoReview(button) {
  const form = button.form;
  const review = photoClassificationReviews.get(form);
  if (!review || review.loading || modalBusy) return;
  review.loading = true;
  button.disabled = true;
  try {
    const preview = await post("gallery-classify-preview", {
      filters:review.filters, page:Number(button.dataset.page),
    });
    if (!form.isConnected) return;
    if (preview.revision !== review.revision) throw Error("图片筛选结果已有变化，请关闭后重新预览。");
    renderPhotoReview(form, review, preview);
    form.querySelector("[data-review-photo]")?.focus();
  } finally {
    review.loading = false;
    button.disabled = false;
  }
}

async function previewFilteredPhotoClassification() {
  const keys = ["q", "category", "kind", "role", "linkstate"];
  const filters = Object.fromEntries(keys.filter(key => filt[key]).map(key => [key, filt[key]]));
  const preview = await post("gallery-classify-preview", {filters});
  if (view !== "gallery" || keys.some(key => (filters[key] || "") !== (filt[key] || ""))) return;
  if (!preview.count) return toast("当前没有可分类的图片");
  const filterLabels = [filters.kind, filters.category, filters.role, filters.q,
    {ready:"已配在库词", pending:"待关联在库词"}[filters.linkstate]].filter(Boolean);
  const hasOriginFilter = filters.category || filters.kind || filters.role;
  const form = photoClassificationDialog("按筛选批量分类",
    '<div class="field full"><p><strong>' + esc(industryName) + ' · ' + fmt(preview.count) + ' 张图片</strong></p>' +
    '<p>' + esc(filterLabels.join(" · ") || "当前行业的全部图片") + '</p>' +
    '<p class="inline-hint">' +
    (hasOriginFilter ? "只调整符合当前分类、来源和用途筛选的记录。" : "这一批图片的所有来源分类都会更新。") +
    ' 取消勾选可留待确认。</p><p class="classification-count" aria-live="polite"></p>' +
    '<div class="classification-photos"></div></div>');
  const review = {filters, revision:preview.revision, count:preview.count, excluded:new Set(), loading:false};
  photoClassificationReviews.set(form, review);
  renderPhotoReview(form, review, preview);
}

async function bulkPhotoLink(button) {
  const keys = ["q", "category", "kind", "role", "linkstate"];
  const filters = Object.fromEntries(keys.filter(key => filt[key]).map(key => [key, filt[key]]));
  const selection = selectedPhotos.size ? {ids:[...selectedPhotos]} : {filters};
  const scope = {industry:industryId, section:1};
  button.disabled = true;
  let first;
  try {
    first = await post("gallery-link-preview", {selection}, scope);
  } finally {
    button.disabled = false;
  }
  if (view !== "gallery" || scope.industry !== industryId ||
      (selection.ids ? selection.ids.length !== selectedPhotos.size || selection.ids.some(id => !selectedPhotos.has(id)) :
        keys.some(key => (filters[key] || "") !== (filt[key] || "")))) return;
  const skipped = first.total - first.eligible;
  const description = esc(industryName) + " · " + (selection.ids ? "已选 " : "当前筛选 ") + fmt(first.total) + " 张";
  const filterLabels = selection.filters ? [filters.kind, filters.category, filters.role, filters.q,
    {ready:"已配在库词", pending:"待关联在库词"}[filters.linkstate]].filter(Boolean) : [];
  if (!first.eligible) {
    return dialog("批量配图", '<p>' + description + '</p><p>当前没有可用于建站的产品图。可选择来源为产品素材的 JPG、PNG、WebP 或 GIF。</p>');
  }
  dialog("批量配图", '<form id="gallery-link-review" class="form-grid"><div class="field full">' +
    '<p><strong>' + description + '</strong></p>' +
    (filterLabels.length ? '<p class="inline-hint">' + esc(filterLabels.join(" · ")) + '</p>' : '') +
    (skipped ? '<p class="inline-hint">将跳过 ' + fmt(skipped) + ' 张参考图、来源待核实或无法直接用于建站的图片。</p>' : '') +
    '<p class="classification-count" aria-live="polite"></p></div>' +
    '<label class="field full">选择一个完整关键词<input type="search" data-link-query maxlength="1000" placeholder="搜索本行业词库中的关键词"></label>' +
    '<div class="field full photo-link-words" data-link-words></div>' +
    '<div class="field full step-actions"><button class="primary" type="submit" disabled>保存批量配图</button></div>' +
    '<div class="field full" data-link-photos></div></form>');
  const form = $("#gallery-link-review");
  const wordHost = form.querySelector("[data-link-words]");
  const submit = form.querySelector('[type="submit"]');
  const excluded = new Set();
  let word = 0, pendingPage = false, timer, searchRevision = 0;

  function update() {
    const count = first.eligible - excluded.size;
    form.querySelector(".classification-count").textContent = "将关联 " + fmt(count) + " 张" +
      (excluded.size ? " · 已取消勾选 " + fmt(excluded.size) + " 张" : "");
    submit.disabled = modalBusy || pendingPage || !count || !word;
  }

  function render(preview) {
    const page = (label, number, disabled) => '<button type="button" class="secondary" data-link-page="' + number + '"' +
      (disabled ? ' disabled' : '') + '>' + label + '</button>';
    form.querySelector("[data-link-photos]").innerHTML = photoReviewGrid(preview, excluded, "data-link-photo", "关联") +
      photoReviewPages(preview, page);
  }

  function renderWords(words, suggested = false) {
    wordHost.innerHTML = words.length ? (suggested ? '<p class="inline-hint">匹配分类或文件名的在库词</p>' : '') +
      words.map(item => '<label><input type="radio" name="word" value="' + item.id + '"> ' + esc(item.term) + '</label>').join('') :
      '<p class="inline-hint">' + (suggested ? '搜索并选择要关联的在库词。' : '没有找到可用关键词。') + '</p>';
  }

  render(first);
  renderWords(first.suggested, true);
  update();
  form.addEventListener("change", event => {
    const input = event.target;
    if (input.hasAttribute("data-link-photo")) {
      const id = Number(input.dataset.linkPhoto);
      if (input.checked) excluded.delete(id); else excluded.add(id);
      input.closest(".classification-thumbnail").classList.toggle("skipped", !input.checked);
    }
    if (input.name === "word") word = Number(input.value);
    update();
  });
  form.addEventListener("input", event => {
    if (!event.target.hasAttribute("data-link-query")) return;
    clearTimeout(timer);
    const request = ++searchRevision;
    const query = event.target.value.trim();
    word = 0;
    update();
    if (!query) return renderWords(first.suggested, true);
    wordHost.textContent = "正在找关键词…";
    timer = setTimeout(async () => {
      try {
        const words = await get("gallery-link-words", {...scope, q:query});
        if (form.isConnected && request === searchRevision) renderWords(words);
      } catch (err) {
        if (form.isConnected && request === searchRevision) failure(err);
      }
    }, 220);
  });
  form.addEventListener("keydown", event => {
    if (event.key === "Enter" && event.target.hasAttribute("data-link-query")) event.preventDefault();
  });
  form.addEventListener("click", async event => {
    const page = event.target.closest("[data-link-page]");
    if (!page || pendingPage || modalBusy) return;
    pendingPage = true;
    page.disabled = true;
    update();
    try {
      const preview = await post("gallery-link-preview", {selection, page:Number(page.dataset.linkPage)}, scope);
      if (!form.isConnected) return;
      if (preview.revision !== first.revision) throw Error("图片筛选结果已有变化，请关闭后重新预览。");
      render(preview);
      form.querySelector("[data-link-photo]")?.focus();
    } catch (err) { if (form.isConnected) failure(err); }
    finally {pendingPage = false; page.disabled = false; update();}
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submit.disabled || modalBusy) return;
    modalBusy = true;
    update();
    let result;
    try {
      result = await post("gallery-link-batch", {selection, word, revision:first.revision, excluded:[...excluded]}, scope);
    } catch (err) {failure(err);}
    finally {modalBusy = false; update();}
    if (!result || !form.isConnected) return;
    selectedPhotos.clear();
    close();
    toast("「" + result.term + "」新增配图 " + fmt(result.added) + " 张" +
      (result.existing ? "，原有 " + fmt(result.existing) + " 张" : ""));
    await load().catch(failure);
  });
}

async function bankAction(action, target) {
  const id=Number(target.dataset.id);
  if (action === "bank-category") {
    filt.category = target.dataset.category;
    paging = [0];
    return load();
  }
  if (action === "bank-clear-photos") {
    selectedPhotos.clear();
    return updatePhotoSelection();
  }
  if (action === "bank-classify-selected") {
    if (!selectedPhotos.size) return;
    return photoClassificationDialog("批量分类",
      '<p class="field full">将「' + esc(industryName) + '」的 ' + fmt(selectedPhotos.size) +
      ' 张已选图片归到同一产品分类。</p>');
  }
  if (action === "bank-classify-filtered") return previewFilteredPhotoClassification();
  if (action === "bank-photo-review-page") return movePhotoReview(target);
  if (action === "bank-bulk-link") return bulkPhotoLink(target);
  if (action === "bank-export") {
    const form = (fields,label,style) => '<form action="/api/gallery-pack?'+esc(qs({}))+'" method="post">'+
      Object.entries({...fields,scope:"gallery"}).map(([k,v])=>'<input type="hidden" name="'+esc(k)+'" value="'+esc(v)+'">').join("")+
      '<button class="'+style+'">'+esc(label)+'</button></form>';
    const selected = selectedPhotos.size ? form({ids:JSON.stringify([...selectedPhotos])},"下载已选 "+fmt(selectedPhotos.size)+" 张","primary") : "";
    const filtered = galleryMatched ? form(filt, "下载当前筛选的 "+fmt(galleryMatched)+" 张",selected?"secondary":"primary") : "";
    return dialog("批量下载",'<p>'+esc([industryName,filt.kind,filt.category,filt.role,filt.q].filter(Boolean).join(" · "))+
      '</p><p>ZIP 包含原图和来源清单。</p><div class="step-actions">'+(selected || filtered ? selected+filtered : "当前没有可下载的图片。")+'</div>');
  }
  if(action==="bank-gallery"){openAppLocation("/?industry="+industryId+"&section=1#gallery");return;}
  if(action==="bank-peer"){filt.kind=filt.kind==="同行参考"?"":"同行参考";paging=[0];return load();}
  if(action==="bank-photo-edit"){
    const c=await get("gallery-detail",{id});
    const origins=c.origins.length?c.origins:[{path:"",kind:"产品素材",category:"待细分",role:"产品展示"}];
    const form=o=>'<form class="form-grid photo-classify" data-id="'+id+'"><input name="path" type="hidden" value="'+esc(o.path)+'"><p>'+esc(o.path||"手动上传")+'</p><label>来源<select name="kind">'+["产品素材","同行参考","来源待核实","示例素材","设计源文件","教程参考"].map(k=>option(k,k,o.kind)).join("")+'</select></label><label>产品分类<input required name="category" value="'+esc(o.category)+'"></label><label>用途<input required name="role" value="'+esc(o.role)+'"></label><button class="primary">保存分类</button></form>';
    return dialog("调整图片分类",origins.map(form).join(""));
  }
  if(action==="bank-open")return showSkill(id);
  if(action==="bank-history" || action==="bank-cards"){bankHistory=action==="bank-history";return load();}
  if(action==="bank-prev"||action==="bank-next"){bankPage+=action==="bank-next"?1:-1;return load();}
  if(action==="bank-prepare"){
    const r=await post("skillbank-prepare",{id});
    return copyBox("可直接交给 Codex 的技能文件",r.skill_file);
  }
  if(action==="bank-copy"){
    const c=await get("skillbank-detail",{id});
    const instructions=c.package?'从 industry-keywords 的 read_skill_package 读取编号 '+id+' 的 SKILL.md，再按需读取包内引用文件。需要脚本或整套本机文件时使用 local_skill_file 或运行返回的 prepare_local_command。':
      '请先查看已收藏的说明及来源，核实是否有可以调用的本机技能或原包。';
    return copyBox("交给 Codex","为当前建站任务调用「"+c.name+"」。"+instructions+"\n用途："+c.description+
      (c.guidance?"\n我的用法："+c.guidance:"")+(c.url?"\n来源："+c.url:"")+"\n完成后记录实际使用的项目、步骤和结果。");
  }
  if(action==="bank-connect"){
    if(target.disabled) return;
    target.disabled=true;
    try {
      const result=await post("connect-codex",{switchFrom:target.dataset.switchFrom});
      if(target.isConnected) codexConnectionDialog(result);
      toast(result.message);
    } finally {
      target.disabled=false;
    }
    return;
  }
  if(action==="bank-url"){
    return dialog("收藏技能网址",'<form id="bank-url-form"><label class="field">技能网址<textarea required name="urls" rows="4" placeholder="每行一个，可粘贴 GitHub、skills.sh 或技能介绍页"></textarea></label><p>公开 GitHub 技能会尝试读取原包；其他网址可自行补充用途。</p><button class="primary">保存到技能包</button></form>');
  }
  if(action==="bank-upload"){
    return dialog("批量导入技能 ZIP",'<form id="bank-zip-form"><label class="field">选择包含 SKILL.md 的压缩包<input type="file" name="files" multiple required accept=".zip"></label><p>同一个 ZIP 中的多个技能会分别建卡。相同包重复导入会沿用已有记录。</p><button class="primary">开始导入</button></form>');
  }
  if(action==="bank-edit"){
    const c=await get("skillbank-detail",{id});
    return dialog("编辑技能说明",'<form id="bank-edit" data-id="'+id+'"><label class="field">技能名称<input name="name" required maxlength="180" value="'+esc(c.name)+'"></label><label class="field">用来做什么<textarea name="description" rows="3">'+esc(c.description)+'</textarea></label><label class="field">我的用法<textarea name="guidance" rows="5">'+esc(c.guidance)+'</textarea></label><button class="primary">保存说明</button></form>');
  }
}
document.addEventListener("change", e => {
  const input = e.target;
  if (!input.matches("input[data-review-photo]")) return;
  const review = photoClassificationReviews.get(input.form);
  if (!review) return;
  const id = Number(input.dataset.reviewPhoto);
  if (modalBusy) {
    input.checked = !review.excluded.has(id);
    return;
  }
  if (input.checked) review.excluded.delete(id);
  else review.excluded.add(id);
  input.closest(".classification-thumbnail").classList.toggle("skipped", !input.checked);
  updatePhotoReviewCount(input.form, review);
});

document.addEventListener("submit",async e=>{
  const f=e.target;
  if (f.id === "gallery-classify-selected") {
    e.preventDefault();
    const button = f.querySelector('button[type="submit"]');
    const review = photoClassificationReviews.get(f);
    if (button.disabled || modalBusy || review?.loading) return;
    button.disabled = true;
    modalBusy = true;
    try {
      const category = f.elements.category.value.trim();
      const result = review
        ? await post("gallery-classify-filtered", {
          filters:review.filters, revision:review.revision, excluded:[...review.excluded], category,
        })
        : await post("gallery-classify-batch", {ids:[...selectedPhotos], category});
      selectedPhotos.clear();
      galleryFilters = {};
      paging = [0];
      if (review) filt.category = result.category;
      modalBusy = false;
      close();
      await load();
      toast("已将 " + fmt(result.count) + " 张图片归到「" + result.category + "」");
    } catch (err) {
      failure(err);
    } finally {
      modalBusy = false;
      if (review && f.isConnected) updatePhotoReviewCount(f, review);
      else button.disabled = false;
    }
    return;
  }
  if(f.classList.contains("photo-classify")){
    e.preventDefault();
    try{await post("gallery-classify",{id:Number(f.dataset.id),...Object.fromEntries(new FormData(f))});galleryFilters = {};await load();await photoDetail(Number(f.dataset.id));}catch(err){failure(err);}
    return;
  }
  if(!["bank-search","bank-edit","bank-url-form","bank-zip-form"].includes(f.id))return;
  e.preventDefault();
  const fields=new FormData(f);
  try{
    if(f.id==="bank-search"){bankQuery=String(fields.get("query")).trim();bankPage=1;return await load();}
    if(f.id==="bank-edit"){
      await post("skillbank-edit",{...Object.fromEntries(fields),id:Number(f.dataset.id)});
      await load();return await showSkill(Number(f.dataset.id));
    }
    const files=f.id==="bank-zip-form";
    const inputs=files?[...f.elements.files.files]:String(fields.get("urls")).split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    f.querySelector("button").disabled=true;
    const lines=[],ids=new Set();
    for(const item of inputs) {
      const label=files?item.name:item;
      try {
        const result=files?await fetch("/api/skillbank-upload?"+qs({filename:item.name}),{method:"POST",body:item}).then(check):
          await post("skillbank-url",{url:item});
        result.ids.forEach(x=>ids.add(x));lines.push(label+" · "+(result.message || result.ids.length+" 个技能已在库"));
      } catch(err){lines.push(label+" · "+err.message);}
    }
    bankHistory=false;bankQuery="";bankPage=1;await load();
    dialog("导入结果",'<ul>'+lines.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul>'+[...ids].slice(0,40).map(id=>skillButton("open","查看技能 #"+id,id)).join(" "));
  } catch(err){failure(err);}
});

