/* ── State ───────────────────────────────────────────────────────────────── */
let currentMission = null;

/* ── View switching ──────────────────────────────────────────────────────── */

function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + name).classList.remove('hidden');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'draw')   refreshStatus();
  if (name === 'manage') loadItems();
  if (name === 'history') loadHistory();
}

/* ── Pool status ─────────────────────────────────────────────────────────── */

async function refreshStatus() {
  const { total, remaining } = await apiFetch('/api/status');
  const el = document.getElementById('pool-status');
  if (total === 0) {
    el.innerHTML = 'Pool is empty — add items in <b>Manage Pool</b>';
  } else {
    el.innerHTML = `<span>${remaining}</span> / ${total} remaining this cycle`;
  }
}

/* ── Draw ────────────────────────────────────────────────────────────────── */

async function drawMission() {
  const btn = document.getElementById('draw-btn');
  btn.disabled = true;
  btn.classList.add('spinning');

  // Fetch result while animation plays
  const fetchPromise = apiFetch('/api/draw');
  await sleep(1200); // let the animation run

  const { mission } = await fetchPromise;
  btn.disabled = false;
  btn.classList.remove('spinning');

  if (!mission) {
    alert('No items in the pool yet!');
    return;
  }
  currentMission = mission;

  const path = mission.path;
  const leaf = path[path.length - 1];
  const crumbs = path.slice(0, -1);

  const bc = document.getElementById('mission-breadcrumb');
  bc.innerHTML = crumbs.map(p => `<span>${esc(p.name)}</span><span class="sep">›</span>`).join('');

  document.getElementById('mission-leaf').textContent = leaf.name;

  const progressEl = document.getElementById('mission-progress');
  if (leaf.required_count > 1) {
    const done = leaf.draw_count || 0;
    progressEl.textContent = `${done + 1} of ${leaf.required_count} completions`;
    progressEl.classList.remove('hidden');
  } else {
    progressEl.classList.add('hidden');
  }

  const notesEl = document.getElementById('mission-notes');
  notesEl.textContent = leaf.notes || '';
  notesEl.classList.toggle('hidden', !leaf.notes);

  document.getElementById('mission-card').classList.remove('hidden');
  btn.classList.add('hidden');
  refreshStatus();
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function acceptMission() {
  if (!currentMission) return;
  await apiFetch('/api/accept', { method: 'POST', body: { path: currentMission.path } });
  resetDrawArea();
  refreshStatus();
}

async function skipMission() {
  if (!currentMission) return;
  await apiFetch('/api/skip', { method: 'POST', body: { path: currentMission.path } });
  resetDrawArea();
}

function resetDrawArea() {
  currentMission = null;
  document.getElementById('mission-card').classList.add('hidden');
  document.getElementById('draw-btn').classList.remove('hidden');
}

async function toggleConsumed(id) {
  await apiFetch(`/api/items/${id}/toggle`, { method: 'POST' });
  loadItems();
  refreshStatus();
}

/* ── Manage: load & render tree ──────────────────────────────────────────── */

async function loadItems() {
  const { items } = await apiFetch('/api/items');
  const container = document.getElementById('items-tree');
  container.innerHTML = '';
  if (!items.length) {
    container.innerHTML = '<div class="tree-empty">No items yet. Use "+ Add Item" to start.</div>';
    return;
  }
  container.appendChild(buildUl(items, 0));
}

function buildUl(items, depth) {
  const ul = document.createElement('ul');
  ul.className = `tree-ul depth-${depth}`;
  items.forEach(item => ul.appendChild(buildLi(item, depth)));
  return ul;
}

function buildLi(item, depth) {
  const li = document.createElement('li');
  li.dataset.id = item.id;
  li.dataset.depth = depth;

  const row = document.createElement('div');
  row.className = 'tree-row' + (item.consumed ? ' is-consumed' : '');

  // iOS-style toggle switch
  const toggleSwitch = document.createElement('button');
  toggleSwitch.className = 'toggle-switch' + (item.consumed ? ' is-done' : '');
  toggleSwitch.title = item.consumed ? 'Mark as not done' : 'Mark as done';
  toggleSwitch.innerHTML = '<span class="toggle-thumb"></span>';
  toggleSwitch.onclick = () => toggleConsumed(item.id);
  row.appendChild(toggleSwitch);

  // Name + notes wrapper
  const nameWrap = document.createElement('div');
  nameWrap.className = 'name-wrap';

  const nameSpan = document.createElement('span');
  nameSpan.className = 'item-name';
  nameSpan.textContent = item.name;
  nameWrap.appendChild(nameSpan);

  if (item.notes) {
    const notesSpan = document.createElement('span');
    notesSpan.className = 'item-notes';
    notesSpan.textContent = item.notes;
    nameWrap.appendChild(notesSpan);
  }

  row.appendChild(nameWrap);

  // Progress badge for multi-draw items
  if (item.required_count > 1) {
    const badge = document.createElement('span');
    if (item.consumed) {
      badge.className = 'progress-badge done';
      badge.textContent = `×${item.required_count}`;
    } else if (item.draw_count > 0) {
      badge.className = 'progress-badge in-progress';
      badge.textContent = `${item.draw_count}/${item.required_count}`;
    } else {
      badge.className = 'progress-badge pending';
      badge.textContent = `×${item.required_count}`;
    }
    row.appendChild(badge);
  }

  // Actions
  const actions = document.createElement('div');
  actions.className = 'item-actions';

  if (depth < 2) {
    actions.appendChild(makeBtn('+', 'Add sub-item', () => openAddModal(item.id)));
  }
  const editBtn = makeBtn('✎', 'Edit', () => showEditForm(li, item));
  const delBtn  = makeBtn('✕', 'Delete', () => deleteItem(item.id));
  delBtn.classList.add('del-btn');
  actions.appendChild(editBtn);
  actions.appendChild(delBtn);
  row.appendChild(actions);

  li.appendChild(row);

  if (item.children && item.children.length) {
    li.appendChild(buildUl(item.children, depth + 1));
  }

  return li;
}

/* ── Item modal (shared for add & edit) ──────────────────────────────────── */

let modalMode   = null; // 'add' | 'edit'
let modalItemId = null; // item id when editing
let modalParentId = null; // parent id when adding
let selectedDrawCount = 1;

function selectDrawCount(val) {
  selectedDrawCount = val;
  document.querySelectorAll('.dcp-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.val) === val);
  });
}

function openAddModal(parentId) {
  removeInlineForms();
  modalMode = 'add';
  modalParentId = parentId;
  document.getElementById('modal-title').textContent =
    parentId ? 'Add Sub-item' : 'Add Item';
  document.getElementById('modal-name').value = '';
  document.getElementById('modal-notes').value = '';
  selectDrawCount(1);
  openItemModal();
}

function showEditForm(_li, item) {
  modalMode = 'edit';
  modalItemId = item.id;
  document.getElementById('modal-title').textContent = 'Edit Item';
  document.getElementById('modal-name').value = item.name;
  document.getElementById('modal-notes').value = item.notes || '';
  selectDrawCount(item.required_count || 1);
  openItemModal();
}

function openItemModal() {
  const modal = document.getElementById('item-modal');
  modal.classList.remove('hidden');
  requestAnimationFrame(() => modal.classList.add('is-open'));
  document.getElementById('modal-name').focus();
}

function closeItemModal(e) {
  if (e && e.target !== document.getElementById('item-modal')) return;
  const modal = document.getElementById('item-modal');
  modal.classList.remove('is-open');
  modal.addEventListener('transitionend', () => modal.classList.add('hidden'), { once: true });
  modalMode = modalItemId = modalParentId = null;
}

// Keep old name working for Escape handler
function closeEditModal() { closeItemModal(); }

async function saveItemModal() {
  const name = document.getElementById('modal-name').value.trim();
  if (!name) { document.getElementById('modal-name').focus(); return; }
  const notes = document.getElementById('modal-notes').value.trim() || null;
  const required_count = selectedDrawCount;

  if (modalMode === 'edit') {
    await apiFetch(`/api/items/${modalItemId}`, {
      method: 'PUT', body: { name, notes, required_count }
    });
  } else {
    const res = await fetch('/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, notes, required_count, parent_id: modalParentId ?? null })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || 'Error adding item');
      return;
    }
  }
  closeItemModal();
  loadItems();
}

// alias so old save call still works
function saveEditModal() { saveItemModal(); }

function makeBtn(label, title, onclick) {
  const b = document.createElement('button');
  b.textContent = label;
  b.title = title;
  b.onclick = onclick;
  return b;
}

function removeInlineForms() {
  document.querySelectorAll('.inline-form-li').forEach(el => el.remove());
}

/* ── Delete ──────────────────────────────────────────────────────────────── */

async function deleteItem(id) {
  if (!confirm('Delete this item and all its sub-items?')) return;
  await apiFetch(`/api/items/${id}`, { method: 'DELETE' });
  loadItems();
}

/* ── Reset all ───────────────────────────────────────────────────────────── */

async function resetAll() {
  if (!confirm('Reset all "done" states? Everything goes back into the pool.')) return;
  await apiFetch('/api/reset', { method: 'POST' });
  loadItems();
  refreshStatus();
}

/* ── History ─────────────────────────────────────────────────────────────── */

async function loadHistory() {
  const { history } = await apiFetch('/api/history');
  const container = document.getElementById('history-list');
  container.innerHTML = '';

  if (!history.length) {
    container.innerHTML = '<div class="history-empty">No history yet. Start drawing!</div>';
    return;
  }

  // Group by local date
  const groups = new Map();
  for (const entry of history) {
    const key = localDateKey(entry.created_at);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }

  for (const [key, entries] of groups) {
    const section = document.createElement('div');
    section.className = 'history-section';

    const header = document.createElement('div');
    header.className = 'history-date-header';
    header.textContent = key;
    section.appendChild(header);

    for (const entry of entries) {
      section.appendChild(buildHistoryEntry(entry));
    }
    container.appendChild(section);
  }
}

function buildHistoryEntry(entry) {
  const row = document.createElement('div');
  row.className = 'history-entry';

  const time = document.createElement('span');
  time.className = 'history-time';
  time.textContent = localTime(entry.created_at);

  const pathWrap = document.createElement('span');
  pathWrap.className = 'history-path';
  pathWrap.innerHTML = entry.path.map((p, i) => {
    const isLeaf = i === entry.path.length - 1;
    return (i > 0 ? '<span class="hp-sep">›</span>' : '') +
           `<span class="${isLeaf ? 'hp-leaf' : 'hp-crumb'}">${esc(p.name)}</span>`;
  }).join('');

  const badge = document.createElement('span');
  badge.className = 'history-badge ' + entry.action;
  badge.textContent = entry.action === 'accepted' ? '✓ Accepted' : '↩ Skipped';

  row.appendChild(time);
  row.appendChild(pathWrap);
  row.appendChild(badge);
  return row;
}

async function clearHistory() {
  if (!confirm('Clear all history?')) return;
  await apiFetch('/api/history', { method: 'DELETE' });
  loadHistory();
}

function localDateKey(iso) {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function localTime(iso) {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

async function apiFetch(url, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, init);
  return res.json();
}

function esc(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ── Init ────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  refreshStatus();
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeItemModal();
  });
  document.getElementById('modal-name').addEventListener('keydown', e => {
    if (e.key === 'Enter') saveItemModal();
  });
});
