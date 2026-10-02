const apiRoot = `/api/games/${encodeURIComponent(document.body.dataset.slug)}`;
const esc = Admin.escapeHtml;
const studio = document.getElementById('story-studio');
let draft = null;
let saved = '';
let selectedQuest = 0;
let selectedMission = null;
let busy = false;
let mapFilter = 'all';
let view = 'split';
const map = new GameMap.Controller({
  onSelect: (point) => selectMission(point.questIndex, point.missionIndex),
  onPick: (target, coords) => {
    const mission = draft.document.quests[target.questIndex].missions[target.missionIndex];
    mission[`${target.endpoint}_lat`] = Number(coords.lat.toFixed(6));
    mission[`${target.endpoint}_lng`] = Number(coords.lng.toFixed(6));
    markChanged();
    render();
    Admin.notify('Pin updated in the draft. Save when ready.');
  },
});

function unsaved() { return draft && JSON.stringify(draft.document) !== saved; }

function updateStatus() {
  if (!draft) return;
  document.getElementById('draft-title').textContent = draft.published_version ? `Draft / live version ${draft.published_version}` : 'Draft / not published yet';
  document.getElementById('draft-status').textContent = unsaved()
    ? 'Unsaved edits. Save the draft before publishing.'
    : draft.dirty ? 'Draft saved. Unpublished changes.' : 'Draft matches the published story.';
  document.getElementById('save-draft').disabled = busy || !unsaved();
  document.getElementById('publish-draft').disabled = busy || unsaved() || !draft.dirty;
  for (const id of ['reload-draft', 'import-json', 'export-json', 'add-quest', 'apply-json', 'import-seed']) {
    document.getElementById(id).disabled = busy;
  }
}

function markChanged() {
  document.getElementById('raw-quests').value = JSON.stringify(draft.document, null, 2);
  document.getElementById('validation-summary').hidden = true;
  updateStatus();
}

function feedback(errors = [], warnings = []) {
  const box = document.getElementById('validation-summary');
  box.hidden = !errors.length && !warnings.length;
  box.innerHTML = [
    errors.length ? `<strong>Before publishing</strong><ul>${errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>` : '',
    warnings.length ? `<strong>Map checks</strong><ul>${warnings.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>` : '',
  ].join('');
}

function acceptDraft(result) {
  const initial = draft === null;
  draft = result;
  saved = JSON.stringify(draft.document);
  selectedQuest = Math.max(0, Math.min(selectedQuest, draft.document.quests.length - 1));
  document.getElementById('raw-quests').value = JSON.stringify(draft.document, null, 2);
  studio.setAttribute('aria-busy', 'false');
  feedback(result.errors, result.warnings);
  render();
  if (initial) syncMap(true);
}

async function action(callback) {
  if (busy || !draft) return;
  busy = true;
  studio.inert = true;
  updateStatus();
  try { await callback(); }
  catch (error) { Admin.notify(error.message, true); }
  finally { busy = false; studio.inert = false; updateStatus(); }
}

function syncMap(fit = false) {
  if (!draft) return;
  map.update(draft.document, { filter: mapFilter, fit,
    selected: selectedMission === null ? null : { questIndex: selectedQuest, missionIndex: selectedMission } });
}

function selectMission(qi, mi) {
  if (qi == null || mi == null) return;
  selectedQuest = qi;
  selectedMission = mi;
  render();
  if (view === 'map') setView('split');
  document.getElementById(`mission-${mi}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function setView(next) {
  view = next;
  studio.dataset.view = next;
  if (map.pending) { map.pending = null; syncMap(); }
  document.querySelectorAll('button[data-view]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.view === next)));
  requestAnimationFrame(() => map.resize());
}

function field(label, path, value, { multiline = false, type = 'text', hint = '' } = {}) {
  const id = `field-${path.replaceAll('.', '-')}`;
  const input = multiline
    ? `<textarea id="${id}" data-field="${path}" rows="4">${esc(value ?? '')}</textarea>`
    : `<input id="${id}" data-field="${path}" type="${type}" ${type === 'number' ? 'step="any"' : ''} value="${esc(value ?? '')}" />`;
  return `<div class="field"><label for="${id}">${esc(label)}</label>${input}${hint ? `<small>${esc(hint)}</small>` : ''}</div>`;
}

function sceneCard(section, title, content) {
  const prefix = `quests.${selectedQuest}.${section}`;
  return `<article class="story-card story-bookend"><span class="eyebrow">${esc(title)}</span>
    <p class="story-prose">${esc(content.prompt || 'No scene written yet.')}</p>
    ${content.flavor ? `<p class="story-flavor">${esc(content.flavor)}</p>` : ''}
    <details class="scene-edit"><summary>Edit ${section === 'begin' ? 'opening' : 'ending'}</summary>
      ${field('Scene text', `${prefix}.prompt`, content.prompt, { multiline: true })}
      ${field('Atmosphere / flavor', `${prefix}.flavor`, content.flavor, { multiline: true })}
    </details></article>`;
}

function endpointFields(mission, mi, endpoint) {
  const path = `quests.${selectedQuest}.missions.${mi}.${endpoint}`;
  const available = GameMap.valid(mission[`${endpoint}_lat`], mission[`${endpoint}_lng`]);
  return `<fieldset class="location-fields"><legend>${endpoint === 'start' ? 'Origin' : 'Destination'} ${available ? '' : '<span class="coordinate-warning">Needs a map pin</span>'}</legend>
    ${field('Address', `${path}_address`, mission[`${endpoint}_address`])}
    <div class="coordinate-fields">${field('Latitude', `${path}_lat`, mission[`${endpoint}_lat`], { type: 'number' })}${field('Longitude', `${path}_lng`, mission[`${endpoint}_lng`], { type: 'number' })}</div>
    <div class="actions"><button class="button button-quiet" data-action="geocode" data-mi="${mi}" data-endpoint="${endpoint}">Look up address</button>
    <button class="button button-quiet" data-action="pick" data-mi="${mi}" data-endpoint="${endpoint}">Pick on map</button></div>
    <div id="candidates-${mi}-${endpoint}" class="geocode-candidates" role="status"></div>
  </fieldset>`;
}

function missionCard(mission, mi, count) {
  const path = `quests.${selectedQuest}.missions.${mi}`;
  const moving = mission.type === 'move';
  const title = moving ? `${mission.start_address || 'Choose origin'} → ${mission.end_address || 'Choose destination'}`
    : mission.mission || 'Write your question';
  return `<article id="mission-${mi}" class="story-card mission-card ${moving ? 'travel-card' : 'question-card'} ${selectedMission === mi ? 'is-selected' : ''}" data-mi="${mi}">
    <div class="scene-heading"><span class="mission-number">${String(mi + 1).padStart(2, '0')}</span>
      <div><span class="eyebrow">${moving ? 'TRAVEL' : 'QUESTION'} / ${esc(mission.id)}</span><h3>${esc(title)}</h3></div></div>
    <p class="story-prose">${esc(mission.arrival_prompt || 'No arrival scene written yet.')}</p>
    ${mission.complete_prompt ? `<details class="completion-scene"><summary>After completing this mission</summary><p class="story-prose">${esc(mission.complete_prompt)}</p></details>` : ''}
    <details class="scene-edit"><summary>Edit mission</summary>
      ${field('Mission ID', `${path}.id`, mission.id)}
      ${!moving ? field('Question', `${path}.mission`, mission.mission, { multiline: true }) : ''}
      ${field('Arrival scene', `${path}.arrival_prompt`, mission.arrival_prompt, { multiline: true })}
      ${field('Completion scene', `${path}.complete_prompt`, mission.complete_prompt, { multiline: true })}
      ${moving ? endpointFields(mission, mi, 'start') + endpointFields(mission, mi, 'end') : ''}
      ${field(moving ? 'Accepted transport choices (optional)' : 'Accepted answers — operator only', `${path}.valid_answers`, (mission.valid_answers || []).join('\n'), { multiline: true, hint: moving ? 'One per line. Leave empty for car, walking, and bike.' : 'One accepted answer per line. Hidden in story preview.' })}
    </details>
    <div class="scene-actions">
      <button class="button button-quiet" data-action="up" data-mi="${mi}" ${mi === 0 ? 'disabled' : ''} aria-label="Move mission ${mi + 1} up">↑ Up</button>
      <button class="button button-quiet" data-action="down" data-mi="${mi}" ${mi === count - 1 ? 'disabled' : ''} aria-label="Move mission ${mi + 1} down">↓ Down</button>
      <button class="button button-quiet" data-action="duplicate-mission" data-mi="${mi}">Duplicate</button>
      <button class="button button-danger" data-action="delete-mission" data-mi="${mi}">Remove</button>
    </div>
  </article>`;
}

function render() {
  map.pending = null;
  const quests = draft.document.quests;
  document.getElementById('quest-list').innerHTML = quests.map((quest, qi) =>
    `<button class="quest-link ${qi === selectedQuest ? 'selected' : ''}" data-quest="${qi}" ${qi === selectedQuest ? 'aria-current="true"' : ''}>
      <span>${String(qi + 1).padStart(2, '0')}</span><span>${esc(quest.name || 'Untitled quest')}<small>${quest.missions.length} missions</small></span></button>`).join('');
  const filter = document.getElementById('map-quest-filter');
  if (mapFilter !== 'all' && !quests[Number(mapFilter)]) mapFilter = 'all';
  filter.innerHTML = '<option value="all">All quests</option>' + quests.map((q, qi) => `<option value="${qi}">${esc(q.name || 'Untitled quest')}</option>`).join('');
  filter.value = mapFilter;
  const quest = quests[selectedQuest];
  document.getElementById('story-pane').innerHTML = !quest
    ? '<div class="empty-state"><h2>Your next story starts here.</h2><p>Add a quest or import a JSON file. Nothing goes live until you publish.</p></div>'
    : `<div class="quest-heading"><span class="eyebrow">QUEST ${esc(quest.id)}</span><h2>${esc(quest.name || 'Untitled quest')}</h2>
      <details class="scene-edit"><summary>Quest settings</summary>${field('Quest name', `quests.${selectedQuest}.name`, quest.name)}
      <div class="actions"><button class="button button-quiet" data-action="duplicate-quest">Duplicate quest</button><button class="button button-danger" data-action="delete-quest">Remove quest</button></div></details></div>
      <div class="story-timeline">${sceneCard('begin', 'OPENING SCENE', quest.begin || {})}
      ${quest.missions.map((m, mi) => missionCard(m, mi, quest.missions.length)).join('')}
      <div class="add-mission-actions"><button class="button button-quiet" data-action="add-move">+ Travel mission</button><button class="button button-quiet" data-action="add-question">+ Question mission</button></div>
      ${sceneCard('end', 'ENDING SCENE', quest.end || {})}</div>`;
  syncMap();
  updateStatus();
}

async function previewImport(document, source) {
  const result = await Admin.api(`${apiRoot}/validate`, { method: 'POST', body: JSON.stringify({ document }) });
  if (result.errors.length) { feedback(result.errors, result.warnings); throw new Error('Import was not applied. Correct the validation errors above.'); }
  const dialog = window.document.getElementById('import-dialog');
  const count = document.quests.reduce((total, quest) => total + quest.missions.length, 0);
  window.document.getElementById('import-summary').innerHTML = `<p><strong>${esc(source)}</strong></p><p>${document.quests.length} quests / ${count} missions</p>
    <ul>${document.quests.map((q) => `<li>${esc(q.name || 'Untitled quest')} — ${q.missions.length} missions</li>`).join('')}</ul>
    ${result.warnings.length ? `<p>${result.warnings.length} endpoints need map coordinates.</p>` : ''}`;
  dialog.returnValue = '';
  const accepted = await new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    dialog.showModal();
  });
  if (!accepted) return;
  draft.document = document;
  selectedQuest = 0;
  selectedMission = null;
  mapFilter = 'all';
  markChanged();
  feedback([], result.warnings);
  render();
  map.fit();
  Admin.notify('Imported into the editor. Save draft, then publish when ready.');
}

document.getElementById('story-pane').addEventListener('input', (event) => {
  const path = event.target.dataset.field;
  if (!path || busy) return;
  const keys = path.split('.');
  let target = draft.document;
  keys.slice(0, -1).forEach((key) => { if (!target[key]) target[key] = {}; target = target[key]; });
  const key = keys.at(-1);
  let value = event.target.value;
  if (key === 'valid_answers') value = value.split('\n').map((line) => line.trim()).filter(Boolean);
  else if (event.target.type === 'number') value = value === '' ? null : Number(value);
  target[key] = value;
  markChanged();
  syncMap();
  const card = event.target.closest('.story-card');
  if (card && (key === 'arrival_prompt' || key === 'prompt')) card.querySelector('.story-prose').textContent = value;
  if (card && key === 'mission') card.querySelector('h3').textContent = value;
  if (key === 'name') document.querySelector('.quest-heading h2').textContent = value;
});

document.getElementById('quest-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-quest]');
  if (!button || busy) return;
  selectedQuest = Number(button.dataset.quest);
  selectedMission = null;
  mapFilter = String(selectedQuest);
  render(); map.fit();
});

document.getElementById('story-pane').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button || busy) {
    const card = event.target.closest('.mission-card');
    if (card && draft) { selectedMission = Number(card.dataset.mi); syncMap(); }
    return;
  }
  const quest = draft.document.quests[selectedQuest];
  const mi = Number(button.dataset.mi);
  const endpoint = button.dataset.endpoint;
  const actionName = button.dataset.action;
  try {
    if (actionName === 'pick') {
      selectedMission = mi;
      mapFilter = String(selectedQuest);
      setView('split');
      syncMap();
      map.pick({ questIndex: selectedQuest, missionIndex: mi, endpoint });
      document.getElementById('editor-map-panel').scrollIntoView({ block: 'nearest' });
      return;
    }
    if (actionName === 'geocode') {
      const address = quest.missions[mi][`${endpoint}_address`] || '';
      if (address.trim().length < 3) throw new Error('Enter a full address first.');
      const resultBox = document.getElementById(`candidates-${mi}-${endpoint}`);
      resultBox.textContent = 'Looking up address...';
      await Admin.busy(button, async () => {
        try {
          const result = await Admin.api(`/api/maps/geocode?query=${encodeURIComponent(address)}`);
          resultBox.textContent = result.candidates.length ? 'Review the match and coordinates before selecting:' : 'No matches. Try a more precise address or enter coordinates manually.';
          result.candidates.forEach((candidate) => {
            const choice = document.createElement('button');
            choice.className = 'geocode-choice';
            choice.textContent = `${candidate.label} / ${candidate.lat}, ${candidate.lng} / confidence: ${candidate.confidence}`;
            choice.addEventListener('click', () => {
              quest.missions[mi][`${endpoint}_lat`] = candidate.lat;
              quest.missions[mi][`${endpoint}_lng`] = candidate.lng;
              markChanged(); render(); map.fit();
              Admin.notify('Location selected. Verify its pin on the map before publishing.');
            });
            resultBox.append(choice);
          });
        } catch (error) { resultBox.textContent = error.message; throw error; }
      });
      return;
    }
    if (actionName === 'delete-mission' || actionName === 'delete-quest') {
      if (!await Admin.confirmAction('Remove from this draft?', 'This affects the draft only. Published stories and existing players stay unchanged.', 'Remove')) return;
      if (actionName === 'delete-quest') {
        draft.document.quests.splice(selectedQuest, 1);
        selectedQuest = Math.max(0, selectedQuest - 1);
      } else quest.missions.splice(mi, 1);
      selectedMission = null;
    } else if (actionName === 'duplicate-quest') {
      const copy = structuredClone(quest);
      copy.id = Math.max(0, ...draft.document.quests.map((q) => q.id)) + 1;
      copy.name += ' (copy)';
      draft.document.quests.push(copy);
      selectedQuest = draft.document.quests.length - 1;
    } else if (actionName === 'duplicate-mission') {
      const copy = structuredClone(quest.missions[mi]);
      copy.id = `mission-${crypto.randomUUID()}`;
      quest.missions.splice(mi + 1, 0, copy);
    } else if (actionName === 'up' || actionName === 'down') {
      const to = mi + (actionName === 'up' ? -1 : 1);
      [quest.missions[mi], quest.missions[to]] = [quest.missions[to], quest.missions[mi]];
      selectedMission = to;
    } else if (actionName === 'add-move' || actionName === 'add-question') {
      const type = actionName === 'add-move' ? 'move' : 'question';
      quest.missions.push({ id: `mission-${crypto.randomUUID()}`, type, arrival_prompt: '', complete_prompt: '',
        ...(type === 'move' ? { start_address: '', end_address: '' } : { mission: '', valid_answers: [] }) });
    } else return;
    markChanged(); render();
  } catch (error) { Admin.notify(error.message, true); }
});

document.getElementById('add-quest').addEventListener('click', () => {
  const id = Math.max(0, ...draft.document.quests.map((q) => q.id)) + 1;
  draft.document.quests.push({ id, name: 'New quest', begin: { prompt: '', flavor: '' }, missions: [], end: { prompt: '' } });
  selectedQuest = draft.document.quests.length - 1;
  selectedMission = null; markChanged(); render();
});
document.getElementById('save-draft').addEventListener('click', () => action(async () => {
  const result = await Admin.api(`${apiRoot}/draft`, { method: 'PUT', body: JSON.stringify({ revision: draft.revision, document: draft.document }) });
  acceptDraft(result); Admin.notify('Draft saved. Live players are unchanged.');
}));
document.getElementById('publish-draft').addEventListener('click', () => action(async () => {
  if (unsaved()) throw new Error('Save your draft first.');
  const check = await Admin.api(`${apiRoot}/validate`, { method: 'POST', body: JSON.stringify({ document: draft.document, publish: true }) });
  feedback(check.errors, check.warnings);
  if (check.errors.length) throw new Error('Correct the validation errors before publishing.');
  if (!await Admin.confirmAction('Publish this story?', `New players will receive version ${draft.published_version + 1}. Existing players keep their assigned version.${check.warnings.length ? ` ${check.warnings.length} map endpoints have no coordinates.` : ''}`, 'Publish version')) return;
  acceptDraft(await Admin.api(`${apiRoot}/publish`, { method: 'POST', body: JSON.stringify({ revision: draft.revision }) }));
  Admin.notify(`Version ${draft.published_version} published for new players.`);
}));
document.getElementById('reload-draft').addEventListener('click', () => action(async () => {
  if (unsaved() && !await Admin.confirmAction('Discard unsaved edits?', 'Export your JSON first if you want to keep these changes.', 'Discard and reload')) return;
  acceptDraft(await Admin.api(`${apiRoot}/draft`));
}));
document.getElementById('import-json').addEventListener('click', () => document.getElementById('json-file').click());
document.getElementById('json-file').addEventListener('change', (event) => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  action(async () => {
    if (file.size > 128000) throw new Error('This file is too large for a game document. Split it into separate games.');
    await previewImport(JSON.parse(await file.text()), file.name);
  });
});
document.getElementById('apply-json').addEventListener('click', () => action(async () => {
  await previewImport(JSON.parse(document.getElementById('raw-quests').value), 'Raw JSON');
}));
document.getElementById('import-seed').addEventListener('click', () => action(async () => {
  if (!await Admin.confirmAction('Replace draft with seed quests?', 'This replaces the saved draft and any unsaved edits. Published games do not change.', 'Import seed')) return;
  acceptDraft(await Admin.api(`${apiRoot}/quests/import-seed`, { method: 'POST', body: JSON.stringify({ revision: draft.revision }) }));
}));
document.getElementById('export-json').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(draft.document, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = `${document.body.dataset.slug}-draft.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.querySelectorAll('button[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
document.getElementById('story-preview').addEventListener('change', (event) => {
  studio.classList.toggle('preview-mode', event.target.checked);
  if (draft) render();
  requestAnimationFrame(() => map.resize());
});
document.getElementById('map-quest-filter').addEventListener('change', (event) => { mapFilter = event.target.value; syncMap(true); });
document.getElementById('fit-map').addEventListener('click', () => map.fit());
document.getElementById('fullscreen-map').addEventListener('click', (event) => Admin.busy(event.currentTarget, () => map.fullscreen(document.getElementById('editor-map-panel'))));
document.addEventListener('fullscreenchange', () => map.resize());
window.addEventListener('beforeunload', (event) => { if (unsaved()) { event.preventDefault(); event.returnValue = ''; } });
Admin.api(`${apiRoot}/draft`).then(acceptDraft).catch((error) => {
  document.getElementById('draft-title').textContent = 'Draft unavailable';
  document.getElementById('story-pane').textContent = `${error.message} Reload the page to retry.`;
  Admin.notify(error.message, true);
});
