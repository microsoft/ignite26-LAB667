const gameApi = `/api/games/${encodeURIComponent(document.body.dataset.slug)}`;
const escapeHtml = Admin.escapeHtml;
let activity = null;
let refreshing = false;
let firstLoad = true;
const map = new GameMap.Controller({ onSelect: (point) => { if (point.playerId) showPlayer(point.playerId); } });

function selectedPlayers() {
  return activity.players.filter((player) => Number(player.game_version) === Number(activity.published_version));
}

function showPlayer(id) {
  const player = activity.players.find((p) => p.player_id === id);
  if (!player) return;
  document.getElementById('player-detail-title').textContent = player.name;
  const score = activity.game.competitive_mode
    ? `<dt>Score</dt><dd>${escapeHtml(player.score ?? 'Not completed')}</dd>`
    : '';
  document.getElementById('player-detail').innerHTML = `<dl class="player-facts">
    <dt>Player ID</dt><dd>${escapeHtml(player.player_id)}</dd>
    <dt>Story</dt><dd>Version ${escapeHtml(player.game_version)} / ${escapeHtml(player.quest_name)}</dd>
    <dt>Status</dt><dd>${escapeHtml(player.status)}</dd>
    <dt>Mission</dt><dd>${escapeHtml(player.current_mission_id || 'Finished')} (${Math.min(player.current_mission_index + 1, player.mission_count)} / ${player.mission_count})</dd>
    <dt>Attempts</dt><dd>${escapeHtml(player.answer_attempts)}</dd>
    <dt>Recorded location</dt><dd>${escapeHtml(player.location?.address || 'No recorded coordinates')}<small>Story position, not live GPS</small></dd>
    ${score}
  </dl>`;
  document.getElementById('player-dialog').showModal();
}

function renderActivity(fit = false) {
  const players = selectedPlayers();
  const competitive = Boolean(activity.game.competitive_mode);
  document.getElementById('dashboard-version').textContent = `Live · Version ${activity.published_version}`;
  const counts = {
    player: players.length, registered: 0, active: 0, completed: 0, abandoned: 0,
  };
  players.forEach((player) => {
    const key = { registered: 'registered', mission: 'active', complete: 'completed', abandoned: 'abandoned' }[player.status];
    if (key) counts[key]++;
  });
  Object.entries(counts).forEach(([key, value]) => { document.getElementById(`${key}-count`).textContent = value; });
  const rows = players.map((player) => `<tr>
    <td><button class="player-link" data-player="${escapeHtml(player.player_id)}">${escapeHtml(player.name)}</button><small class="table-subtitle">${escapeHtml(player.player_id)}</small></td>
    <td>${escapeHtml(player.quest_name)}<small class="table-subtitle">Version ${escapeHtml(player.game_version)}</small></td>
    <td><span class="player-status">${escapeHtml(player.status)}</span></td>
    <td><progress max="${Math.max(1, player.mission_count)}" value="${player.status === 'complete' ? player.mission_count : player.current_mission_index}"></progress>
      <small class="table-subtitle">${player.status === 'complete' ? player.mission_count : Math.min(player.current_mission_index + 1, player.mission_count)} / ${player.mission_count} missions</small></td>
    <td>${escapeHtml(player.answer_attempts)}</td>${competitive ? `<td class="score">${escapeHtml(player.score ?? '-')}</td>` : ''}
    <td><button class="button button-quiet" data-reset="${escapeHtml(player.player_id)}" aria-label="Reset player ${escapeHtml(player.name)}">Reset</button></td>
  </tr>`).join('');
  document.getElementById('players').innerHTML = `<table><thead><tr><th>Player</th><th>Quest / version</th><th>Status</th><th>Progress</th><th>Attempts</th>${competitive ? '<th>Score</th>' : ''}<th>Actions</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="${competitive ? 7 : 6}" class="table-empty">No players in this view. Share the MCP endpoint after publishing a story.</td></tr>`}</tbody></table>`;
  document.getElementById('leaderboard-panel').hidden = !competitive;
  const top = players.filter((p) => p.status === 'complete' && p.score != null)
    .sort((a, b) => b.score - a.score || (a.time_taken_minutes || 0) - (b.time_taken_minutes || 0)).slice(0, 10);
  document.getElementById('leaderboard').innerHTML = `<table><thead><tr><th>Rank</th><th>Player</th><th>Story</th><th>Score</th><th>Minutes</th></tr></thead><tbody>
    ${top.map((p, index) => `<tr><td class="rank">${index + 1}</td><td>${escapeHtml(p.name)}</td><td>${escapeHtml(p.quest_name)} / v${p.game_version}</td><td class="score">${p.score}</td><td>${escapeHtml(p.time_taken_minutes)}</td></tr>`).join('') || '<tr><td colspan="5" class="table-empty">The finish line is waiting.</td></tr>'}</tbody></table>`;
  const questDocument = activity.documents[String(activity.published_version)];
  const quests = (questDocument?.quests || []).map((quest) => ({
    ...quest,
    name: `${quest.name} / v${activity.published_version}`,
  }));
  map.update({ quests }, { players, fit });
}

async function refreshActivity() {
  if (refreshing) return;
  refreshing = true;
  const status = document.getElementById('players-status');
  try {
    activity = await Admin.api(`${gameApi}/activity`);
    renderActivity(firstLoad);
    firstLoad = false;
    status.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
    status.classList.remove('form-error');
  } catch (error) {
    status.textContent = `Refresh failed: ${error.message} Displayed data may be out of date.`;
    status.classList.add('form-error');
  } finally { refreshing = false; }
}

document.getElementById('players').addEventListener('click', async (event) => {
  const detail = event.target.closest('[data-player]');
  if (detail) { showPlayer(detail.dataset.player); return; }
  const button = event.target.closest('[data-reset]');
  if (!button) return;
  if (!await Admin.confirmAction('Reset this player?', 'This removes their run. On re-registration they receive the latest published story.', 'Reset player')) return;
  await Admin.busy(button, async () => {
    await Admin.api(`${gameApi}/players/${encodeURIComponent(button.dataset.reset)}`, { method: 'DELETE' });
    Admin.notify('Player reset.'); await refreshActivity();
  });
});
document.getElementById('reset-all').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  if (!await Admin.confirmAction('Reset all players?', 'This deletes every player and their progress across all versions of this game. This cannot be undone.', 'Reset all players')) return;
  await Admin.busy(button, async () => {
    await Admin.api(`${gameApi}/players`, { method: 'DELETE' });
    Admin.notify('All players reset.'); await refreshActivity();
  });
});
document.getElementById('refresh-players').addEventListener('click', (event) => Admin.busy(event.currentTarget, refreshActivity));
document.getElementById('fit-map').addEventListener('click', () => map.fit());
document.getElementById('fullscreen-map').addEventListener('click', (event) => Admin.busy(event.currentTarget, () => map.fullscreen(document.getElementById('dashboard-map-panel'))));
document.addEventListener('fullscreenchange', () => map.resize());
refreshActivity();
setInterval(() => { if (!document.hidden) refreshActivity(); }, 10000);
