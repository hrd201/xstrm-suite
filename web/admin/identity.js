/* Movie identity UI: candidates never apply without an explicit selection. */
(() => {
  const el = id => document.getElementById('identity' + id);
  const endpoint = '/api/admin/xstrm/identity/';
  const labels = {refreshing:'正在核对', completed:'修复完成', warning:'需要关注', failed:'处理失败'};
  let items = [], selected = null, candidates = [], loading = false, applying = false, generation = 0, excluded = 0;
  const polling = new Set();
  const message = (id, text, bad=false) => { el(id).textContent = text; el(id).classList.toggle('bad', bad); };
  const post = (path, body) => fetchJson(endpoint + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  function renderItems() {
    const term = el('Filter').value.trim().toLocaleLowerCase();
    const visible = items.filter(x => [x.id,x.name,x.path].join(' ').toLocaleLowerCase().includes(term));
    el('Items').innerHTML = visible.length ? visible.map(x => `<article class="source-row"><div class="toolbar"><h3>${escapeHtml(x.name)}</h3><span class="health-badge ${x.unmatched ? 'bad' : 'ok'}">${x.unmatched ? '缺少影片身份' : '已有身份信息'}</span></div><p class="muted" style="overflow-wrap:anywhere">${escapeHtml(x.path)}</p><p class="muted">编号 ${escapeHtml(x.id)} · ${x.has_poster ? '已有海报' : '缺少海报'} · ${x.has_overview ? '已有简介' : '缺少简介'}${x.binding ? ' · 已保存确认结果：' + escapeHtml(x.binding.name) : ''}</p><button class="secondary" data-identify-item="${escapeHtml(x.id)}">${x.binding ? '查看 / 恢复匹配' : '搜索影片及海报'}</button></article>`).join('') : '<p class="muted">当前范围没有符合条件的影片。识别错误的影片请切换到“全部影片”。</p>';
    message('Message', `当前筛选显示 ${visible.length} / ${items.length} 个条目。${excluded ? `另有 ${excluded} 个本地 STRM 不可用，已排除。` : ''}`);
  }
  async function loadItems() {
    if (loading || applying) return;
    loading = true; el('Refresh').disabled = true; el('Scope').disabled = true;
    message('Message', '正在读取 Emby 电影条目，不会扫描网盘视频…');
    try {
      const data = await fetchJson(endpoint + 'items?scope=' + encodeURIComponent(el('Scope').value));
      items = data.items; excluded = data.counts.excluded; renderItems();
      if (selected) { selected = items.find(x => x.id === selected.id) || null; if (!selected) el('Editor').close(); }
      el('Counts').innerHTML = [['电影 STRM',data.counts.total],['缺少影片身份',data.counts.unmatched],['缺少海报或简介',data.counts.incomplete]].map(([name,count]) => `<div class="kv"><strong>${name}</strong>${count}</div>`).join('');

    } catch (err) { message('Message',err.message,true); }
    finally { loading = false; el('Refresh').disabled = false; el('Scope').disabled = false; }
  }
  function selectItem(id) {
    if (applying) return;
    selected = items.find(x => x.id === id); if (!selected) return;
    generation++; candidates = []; el('Candidates').innerHTML = '';
    if (!el('Editor').open) el('Editor').showModal(); el('Title').textContent = '选择正确影片：' + selected.name;
    el('Path').textContent = selected.path;
    el('Warnings').textContent = selected.hints.warnings.join('；');
    el('Query').value = selected.hints.query; el('Year').value = selected.hints.year || '';
    el('Tmdb').value = selected.hints.tmdb_id || '';
    el('ReplaceImages').checked = false;
    el('Restore').hidden = !selected.binding;
    el('Alternatives').innerHTML = selected.hints.alternatives.map((q,i) => `<button type="button" class="secondary" data-identify-alt="${i}">改用目录片名：${escapeHtml(q)}</button>`).join('');
    message('SearchMessage',selected.binding ? `已确认过：${selected.binding.name}，TMDB ${selected.binding.tmdb_id}。可以复用此绑定重新搜索。` : '检查搜索词后点击“搜索候选”；也可以直接填写 TMDB ID。');
    el('Editor').scrollTop = 0;
    if (!selected.hints.warnings.length && (selected.hints.query || selected.hints.tmdb_id)) search();
  }
  async function search(event) {
    event?.preventDefault(); if (!selected || applying) return;
    const current = selected, version = ++generation;
    el('Search').disabled = true; el('Restore').disabled = true;
    el('Candidates').innerHTML = ''; candidates = [];
    message('SearchMessage','正在通过 Emby 搜索候选…');
    try {
      const result = await post('search',{item_id:current.id,revision:current.revision,query:el('Query').value,year:el('Year').value,tmdb_id:el('Tmdb').value});
      if (version !== generation) return;
      candidates = result.candidates;
      message('SearchMessage',result.message);
      el('Candidates').innerHTML = candidates.map((x,i) => `<article class="source-row" style="display:flex;gap:16px;align-items:flex-start"><div class="identity-poster">${x.poster ? `<img src="${escapeHtml(x.poster)}" alt="${escapeHtml(x.name)}候选海报" loading="lazy"><p hidden>海报加载失败，请重试；候选过期时需重新搜索。</p><button type="button" class="secondary" data-identify-poster="${i}" hidden>重试海报</button>` : '<p>暂无候选海报</p>'}</div><div style="min-width:0;flex:1"><h3>${escapeHtml(x.name)}${x.year ? '（'+escapeHtml(x.year)+'）' : ''}</h3><p class="muted">TMDB ${escapeHtml(x.tmdb_id)}${x.year_match ? '' : ' · 年份与搜索条件不同，请仔细核对'}</p><p style="white-space:pre-wrap;margin:8px 0">${escapeHtml(x.overview || '暂无简介，请核对影片编号和年份')}</p><div class="actions"><button data-identify-candidate="${i}">确认匹配此影片</button><a href="https://www.themoviedb.org/movie/${encodeURIComponent(x.tmdb_id)}" target="_blank" rel="noopener noreferrer">查看 TMDB</a></div></div></article>`).join('');
    } catch (err) { if (version === generation) message('SearchMessage',err.message,true); }
    finally { el('Search').disabled = false; el('Restore').disabled = false; }
  }
  async function apply(index) {
    const candidate = candidates[index]; if (!candidate || !selected || applying) return;
    if (!confirm(`将“${selected.name}”识别为“${candidate.name}（${candidate.year || '年份未知'}）”，TMDB ${candidate.tmdb_id}？确认后 Emby 会刷新元数据。`)) return;
    applying = true; el('Search').disabled = true; el('Restore').disabled = true;
    el('Candidates').querySelectorAll('button').forEach(x => x.disabled = true);
    message('SearchMessage','正在保存确认结果并提交 Emby，请等待…');
    try {
      const result = await post('apply',{candidate_id:candidate.id,confirmed:true,replace_images:el('ReplaceImages').checked});
      message('SearchMessage',result.message);
      await loadHistory(); poll(result.operation_id);
    } catch (err) { message('SearchMessage',err.message,true); }
    finally { applying = false; el('Search').disabled = false; el('Restore').disabled = false; el('Candidates').querySelectorAll('button').forEach(x => x.disabled = false); }
  }
  async function loadHistory() {
    const result = await fetchJson(endpoint+'history');
    el('History').innerHTML = result.history.length ? result.history.map(x => `<article class="source-row"><div class="toolbar"><h3>${escapeHtml(x.name)}</h3><span class="${x.state === 'completed' ? 'ok' : x.state === 'refreshing' ? 'muted' : 'bad'}">${escapeHtml(labels[x.state] || x.state)}</span></div><p>${escapeHtml(x.message)}</p><p class="muted">${escapeHtml(healthTime(new Date(x.created * 1000).toISOString()))}</p>${['refreshing','warning'].includes(x.state) ? `<button class="secondary" data-identify-check="${escapeHtml(x.id)}">重新核对结果</button>` : ''}</article>`).join('') : '<p class="muted">尚无确认记录。搜索候选不会修改影片。</p>';
    result.history.filter(x => x.state === 'refreshing').forEach(x => poll(x.id));
  }
  async function poll(id) {
    if (polling.has(id)) return; polling.add(id);
    const check = async () => {
      let again = false;
      try {
        const {operation} = await fetchJson(endpoint+'operation?id='+encodeURIComponent(id));
        again = operation.state === 'refreshing';
        if (!again) { showToast(operation.message, operation.state === 'completed' ? 'ok' : 'bad'); await loadItems(); }
        await loadHistory();
      } catch (err) { message('Message', '结果核对中断：'+err.message+'；恢复连接后点击“刷新记录”。',true); }
      if (again) setTimeout(check,4000); else polling.delete(id);
    };
    check();
  }
  el('Items').onclick = event => { const button = event.target.closest('[data-identify-item]'); if (button) selectItem(button.dataset.identifyItem); };
  el('Alternatives').onclick = event => { const button = event.target.closest('[data-identify-alt]'); if (button && selected) { el('Query').value = selected.hints.alternatives[Number(button.dataset.identifyAlt)]; el('Tmdb').value = ''; } };
  el('Candidates').onclick = event => {
    const retry = event.target.closest('[data-identify-poster]');
    if (retry) {
      const candidate = candidates[Number(retry.dataset.identifyPoster)], box = retry.closest('.identity-poster');
      if (!candidate?.poster) return;
      box.querySelector('p').hidden = true; retry.hidden = true;
      const img = box.querySelector('img'); img.hidden = false; img.src = candidate.poster + '&retry=' + Date.now();
      return;
    }
    const button = event.target.closest('[data-identify-candidate]'); if (button) apply(Number(button.dataset.identifyCandidate));
  };
  el('Candidates').addEventListener('error',event => { if (event.target.tagName === 'IMG') { event.target.hidden = true; const box = event.target.closest('.identity-poster'); box.querySelector('p').hidden = false; box.querySelector('button').hidden = false; } },true);
  el('History').onclick = event => { const button = event.target.closest('[data-identify-check]'); if (button) poll(button.dataset.identifyCheck); };
  el('Close').onclick = () => el('Editor').close();
  el('SearchForm').onsubmit = search;
  el('Restore').onclick = () => { if (selected?.binding) { el('Tmdb').value = selected.binding.tmdb_id; el('Year').value = ''; search(); } };
  el('Refresh').onclick = loadItems; el('Scope').onchange = loadItems; el('Filter').oninput = renderItems;
  el('HistoryRefresh').onclick = () => loadHistory().catch(err => message('Message',err.message,true));
  document.querySelector('[data-section="identity"]').addEventListener('click',() => { location.hash = 'identity'; loadItems(); loadHistory().catch(err => message('Message',err.message,true)); });
  if (location.hash === '#identity') document.querySelector('[data-section="identity"]').click();
})();
