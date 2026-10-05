const apiRoot = `/api/games/${encodeURIComponent(document.body.dataset.slug)}`;
const esc = Admin.escapeHtml;
const studio = document.getElementById('story-studio');
let draft = null;
let saved = '';
let selectedQuest = 0;
let selectedMission = null;
let busy = false;
let versionState = null;
const editorDialog = document.getElementById('scene-dialog');
const editorDialogBody = document.getElementById('scene-dialog-body');

function updateVersionDelete() {
  const select = document.getElementById('version-management');
  const button = document.getElementById('delete-version');
  const status = document.getElementById('version-delete-status');
  const selected = versionState?.versions.find((item) => String(item.version) === select.value);
  if (!selected) {
    button.disabled = true;
    status.textContent = versionState?.versions.length ? 'Select a published version.' : 'No published versions yet.';
  } else if (selected.version === versionState.published_version) {
    button.disabled = true;
    status.textContent = 'Current version; new players receive this story.';
  } else if (selected.player_count) {
    button.disabled = true;
    status.textContent = `${selected.player_count} ${selected.player_count === 1 ? 'player is' : 'players are'} assigned. Reset them before deleting.`;
  } else {
    button.disabled = false;
    status.textContent = `Version ${selected.version} can be deleted.`;
  }
}

async function refreshVersions(preserveSelection = false) {
  const select = document.getElementById('version-management');
  const previous = select.value;
  versionState = await Admin.api(`${apiRoot}/versions`);
  select.innerHTML = versionState.versions.map((item) =>
    `<option value="${item.version}">Version ${item.version}${item.version === versionState.published_version ? ' (current)' : ''}</option>`).join('');
  const available = versionState.versions.some((item) => String(item.version) === previous);
  select.value = preserveSelection && available ? previous : String(versionState.published_version || '');
  select.disabled = !versionState.versions.length;
  updateVersionDelete();
}

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
  draft = result;
  saved = JSON.stringify(draft.document);
  selectedQuest = Math.max(0, Math.min(selectedQuest, draft.document.quests.length - 1));
  document.getElementById('raw-quests').value = JSON.stringify(draft.document, null, 2);
  studio.setAttribute('aria-busy', 'false');
  feedback(result.errors, result.warnings);
  render();
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

function field(label, path, value, { multiline = false, type = 'text', hint = '' } = {}) {
  const id = `field-${path.replaceAll('.', '-')}`;
  const input = multiline
    ? `<textarea id="${id}" data-field="${path}" rows="4">${esc(value ?? '')}</textarea>`
    : `<input id="${id}" data-field="${path}" type="${type}" ${type === 'number' ? 'step="any"' : ''} value="${esc(value ?? '')}" />`;
  return `<div class="field"><label for="${id}">${esc(label)}</label>${input}${hint ? `<small>${esc(hint)}</small>` : ''}</div>`;
}

function openEditor(label, title, content) {
  document.getElementById('scene-dialog-label').textContent = label;
  document.getElementById('scene-dialog-title').textContent = title;
  editorDialogBody.innerHTML = content;
  editorDialog.showModal();
}

function sceneCard(section, title, content) {
  const label = section === 'begin' ? 'START' : 'FINISH';
  return `<article class="story-card story-bookend ${section === 'begin' ? 'story-start' : 'story-finish'}">
    <div class="scene-card-header"><div><span class="timeline-label">${label}</span><span class="eyebrow">${esc(title)}</span></div>
      <button type="button" class="button button-quiet card-actions" data-action="edit-scene" data-section="${section}">Edit</button></div>
    <p class="story-prose">${esc(content.prompt || 'No scene written yet.')}</p>
    ${content.flavor ? `<p class="story-flavor">${esc(content.flavor)}</p>` : ''}</article>`;
}

function endpointFields(mission, mi, endpoint) {
  const path = `quests.${selectedQuest}.missions.${mi}.${endpoint}`;
  const available = GameMap.valid(mission[`${endpoint}_lat`], mission[`${endpoint}_lng`]);
  return `<fieldset class="location-fields"><legend>${endpoint === 'start' ? 'Origin' : 'Destination'} ${available ? '' : '<span class="coordinate-warning">Needs a map pin</span>'}</legend>
    ${field('Address', `${path}_address`, mission[`${endpoint}_address`])}
    <div class="coordinate-fields">${field('Latitude', `${path}_lat`, mission[`${endpoint}_lat`], { type: 'number' })}${field('Longitude', `${path}_lng`, mission[`${endpoint}_lng`], { type: 'number' })}</div>
    <div class="actions"><button class="button button-quiet" data-action="geocode" data-mi="${mi}" data-endpoint="${endpoint}">Look up address</button></div>
    <div id="candidates-${mi}-${endpoint}" class="geocode-candidates" role="status"></div>
  </fieldset>`;
}

function routePreview(mission) {
  const start = mission.start_address || 'Choose an origin';
  const end = mission.end_address || 'Choose a destination';
  const mapped = GameMap.valid(mission.start_lat, mission.start_lng) && GameMap.valid(mission.end_lat, mission.end_lng);
  return `<div class="route-map-preview ${mapped ? 'is-mapped' : 'needs-pins'}" aria-label="Azure Maps preview from ${esc(start)} to ${esc(end)}"
      ${mapped ? `data-start-lat="${mission.start_lat}" data-start-lng="${mission.start_lng}" data-end-lat="${mission.end_lat}" data-end-lng="${mission.end_lng}"` : ''}>
      <div class="route-map-grid" data-route-map aria-hidden="true"></div>
      <span class="route-map-state">${mapped ? 'Loading Azure Maps...' : 'Map pins needed'}</span>
    </div>
    <div class="route-timeline">
      <div class="route-stop"><span class="route-stop-dot"></span><div><small>START</small><strong>${esc(start)}</strong></div></div>
      <span class="route-arrow" aria-hidden="true">→</span>
      <div class="route-stop route-stop-end"><span class="route-stop-dot"></span><div><small>END</small><strong>${esc(end)}</strong></div></div>
    </div>`;
}

function answerPreview(mission, moving = false) {
  const answers = mission.valid_answers?.length ? mission.valid_answers : moving ? ['car', 'walking', 'bike'] : [];
  return `<div class="answer-panel" aria-label="Accepted answers"><span class="answer-label">${moving ? 'Accepted travel answers' : `Accepted ${answers.length === 1 ? 'answer' : 'answers'}`}</span>
    <div class="answer-chips">${answers.length
    ? answers.map((answer) => `<span>${esc(answer)}</span>`).join('')
    : '<span class="answer-empty">No accepted answers yet</span>'}</div></div>`;
}

function missionActions(mi, count) {
  return `<details class="action-menu card-actions"><summary aria-label="Actions for mission ${mi + 1}">Actions</summary>
    <div class="action-menu-panel">
      <button type="button" data-action="edit-mission" data-mi="${mi}">Edit</button>
      <button type="button" data-action="up" data-mi="${mi}" ${mi === 0 ? 'disabled' : ''}>Move up</button>
      <button type="button" data-action="down" data-mi="${mi}" ${mi === count - 1 ? 'disabled' : ''}>Move down</button>
      <button type="button" data-action="duplicate-mission" data-mi="${mi}">Duplicate</button>
      <button type="button" class="danger-action" data-action="delete-mission" data-mi="${mi}">Remove</button>
    </div></details>`;
}

function missionEditor(mission, mi) {
  const path = `quests.${selectedQuest}.missions.${mi}`;
  const moving = mission.type === 'move';
  return `${field('Mission ID', `${path}.id`, mission.id)}
    ${!moving ? field('Question', `${path}.mission`, mission.mission, { multiline: true }) : ''}
    ${field('Arrival scene', `${path}.arrival_prompt`, mission.arrival_prompt, { multiline: true })}
    ${field('Completion scene', `${path}.complete_prompt`, mission.complete_prompt, { multiline: true })}
    ${moving ? endpointFields(mission, mi, 'start') + endpointFields(mission, mi, 'end') : ''}
    ${field(moving ? 'Accepted transport choices (optional)' : 'Accepted answers — operator only', `${path}.valid_answers`, (mission.valid_answers || []).join('\n'), { multiline: true, hint: moving ? 'One per line. Leave empty for car, walking, and bike.' : 'One accepted answer per line. Hidden in story preview.' })}`;
}

function missionCard(mission, mi, count) {
  const moving = mission.type === 'move';
  const title = moving ? 'Travel to the next scene' : mission.mission || 'Write your question';
  return `<article id="mission-${mi}" class="story-card mission-card ${moving ? 'travel-card' : 'question-card'} ${selectedMission === mi ? 'is-selected' : ''}" data-mi="${mi}">
    <div class="scene-heading"><span class="mission-number">${String(mi + 1).padStart(2, '0')}</span>
      <div class="scene-title"><span class="eyebrow">${moving ? 'TRAVEL' : 'QUESTION'} / ${esc(mission.id)}</span><h3>${esc(title)}</h3></div>
      ${missionActions(mi, count)}</div>
    <div class="mission-progress" aria-label="Mission flow"><span>Start</span><b aria-hidden="true">→</b><span>Answer</span><b aria-hidden="true">→</b><span>Complete</span></div>
    <div class="mission-flow">
      <section class="mission-phase phase-start"><span class="phase-label">START</span>
        <div class="phase-content"><p class="story-prose">${esc(mission.arrival_prompt || 'No start scene written yet.')}</p></div></section>
      <section class="mission-phase phase-answer"><span class="phase-label">ANSWER</span>
        <div class="phase-content">${moving ? routePreview(mission) + answerPreview(mission, true) : answerPreview(mission)}</div></section>
      <section class="mission-phase phase-complete"><span class="phase-label">COMPLETE</span>
        <div class="phase-content"><p class="story-prose">${esc(mission.complete_prompt || 'No completion scene written yet.')}</p></div></section>
    </div>
  </article>`;
}

function render() {
  const quests = draft.document.quests;
  document.getElementById('quest-list').innerHTML = quests.map((quest, qi) =>
    `<button class="quest-link ${qi === selectedQuest ? 'selected' : ''}" data-quest="${qi}" ${qi === selectedQuest ? 'aria-current="true"' : ''}>
      <span>${String(qi + 1).padStart(2, '0')}</span><span>${esc(quest.name || 'Untitled quest')}<small>${quest.missions.length} missions</small></span></button>`).join('');
  const quest = quests[selectedQuest];
  document.getElementById('story-pane').innerHTML = !quest
    ? '<div class="empty-state"><h2>Your next story starts here.</h2><p>Add a quest or import a JSON file. Nothing goes live until you publish.</p></div>'
    : `<div class="quest-heading"><div><span class="eyebrow">QUEST ${esc(quest.id)}</span><h2>${esc(quest.name || 'Untitled quest')}</h2></div>
      <details class="action-menu quest-action-menu card-actions"><summary aria-label="Quest actions">Actions</summary><div class="action-menu-panel">
        <button type="button" data-action="edit-quest">Edit</button><button type="button" data-action="duplicate-quest">Duplicate</button>
        <button type="button" class="danger-action" data-action="delete-quest">Remove</button></div></details></div>
      <div class="story-timeline">${sceneCard('begin', 'OPENING SCENE', quest.begin || {})}
      ${quest.missions.map((m, mi) => missionCard(m, mi, quest.missions.length)).join('')}
      <div class="add-mission-actions"><button class="button button-quiet" data-action="add-move">+ Travel mission</button><button class="button button-quiet" data-action="add-question">+ Question mission</button></div>
      ${sceneCard('end', 'ENDING SCENE', quest.end || {})}</div>`;
  GameMap.renderRoutePreviews(document.getElementById('story-pane'));
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
  markChanged();
  feedback([], result.warnings);
  render();
  Admin.notify('Imported into the editor. Save draft, then publish when ready.');
}

function updateField(event) {
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
}
document.getElementById('story-pane').addEventListener('input', updateField);
editorDialog.addEventListener('input', updateField);

document.getElementById('quest-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-quest]');
  if (!button || busy) return;
  selectedQuest = Number(button.dataset.quest);
  selectedMission = null;
  render();
});

async function handleStoryAction(event) {
  const button = event.target.closest('[data-action]');
  if (!button || busy) return;
  const quest = draft.document.quests[selectedQuest];
  const mi = Number(button.dataset.mi);
  const endpoint = button.dataset.endpoint;
  const actionName = button.dataset.action;
  try {
    if (actionName === 'edit-quest') {
      openEditor('QUEST SETTINGS', quest.name || 'Untitled quest',
        field('Quest name', `quests.${selectedQuest}.name`, quest.name));
      return;
    }
    if (actionName === 'edit-scene') {
      const section = button.dataset.section;
      const content = quest[section] || {};
      const prefix = `quests.${selectedQuest}.${section}`;
      openEditor(section === 'begin' ? 'OPENING SCENE' : 'ENDING SCENE', section === 'begin' ? 'Edit the opening' : 'Edit the ending',
        `${field('Scene text', `${prefix}.prompt`, content.prompt, { multiline: true })}
        ${field('Atmosphere / flavor', `${prefix}.flavor`, content.flavor, { multiline: true })}`);
      return;
    }
    if (actionName === 'edit-mission') {
      const mission = quest.missions[mi];
      openEditor(`${mission.type === 'move' ? 'TRAVEL' : 'QUESTION'} / MISSION ${mi + 1}`,
        mission.type === 'move' ? 'Edit travel mission' : 'Edit question mission', missionEditor(mission, mi));
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
              markChanged();
              if (editorDialog.open) editorDialog.close();
              render();
              Admin.notify('Location selected. Verify the route preview before publishing.');
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
}
document.getElementById('story-pane').addEventListener('click', handleStoryAction);
editorDialog.addEventListener('click', handleStoryAction);
document.getElementById('close-scene-editor').addEventListener('click', () => editorDialog.close());
document.getElementById('close-scene-editor-top').addEventListener('click', () => editorDialog.close());
editorDialog.addEventListener('close', () => {
  editorDialogBody.replaceChildren();
  if (draft) render();
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
  await refreshVersions();
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
document.getElementById('story-preview').addEventListener('change', (event) => {
  studio.classList.toggle('preview-mode', event.target.checked);
  if (draft) render();
});
document.getElementById('version-management').addEventListener('change', updateVersionDelete);
document.getElementById('delete-version').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const version = Number(document.getElementById('version-management').value);
  if (!await Admin.confirmAction(`Delete version ${version}?`, 'This permanently removes the published story version. This cannot be undone.', 'Delete version')) return;
  await Admin.busy(button, async () => {
    await Admin.api(`${apiRoot}/versions/${version}`, { method: 'DELETE' });
    Admin.notify(`Version ${version} deleted.`);
    await refreshVersions();
  });
});
window.addEventListener('beforeunload', (event) => { if (unsaved()) { event.preventDefault(); event.returnValue = ''; } });
refreshVersions().catch((error) => {
  document.getElementById('version-delete-status').textContent = `Versions unavailable: ${error.message}`;
});
Admin.api(`${apiRoot}/draft`).then(acceptDraft).catch((error) => {
  document.getElementById('draft-title').textContent = 'Draft unavailable';
  document.getElementById('story-pane').textContent = `${error.message} Reload the page to retry.`;
  Admin.notify(error.message, true);
});
