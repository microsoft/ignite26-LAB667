const GAME_SERVER_URL = document.body.dataset.gameServerUrl.replace(/\/$/, '');
const DASHBOARD_URL = document.body.dataset.dashboardUrl.replace(/\/$/, '');
const gamesContainer = document.getElementById('games');
const escapeHtml = Admin.escapeHtml;

async function loadGames() {
  gamesContainer.setAttribute('aria-busy', 'true');
  try {
    const data = await Admin.api('/api/games');
    document.getElementById('game-count').textContent = String(data.games.length).padStart(2, '0');
    gamesContainer.innerHTML = data.games.map((game, index) => {
      const slug = encodeURIComponent(game.slug);
      const mcpUrl = `${GAME_SERVER_URL}/${slug}/mcp`;
      const dashUrl = `${DASHBOARD_URL}/${slug}/dashboard`;
      const created = game.created_at ? new Date(game.created_at).toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
      }) : 'Date unavailable';
      return `<article class="game-card">
        <div class="card-top"><span class="game-icon" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span><span class="badge">WORKSHOP GAME</span></div>
        <h3>${escapeHtml(game.display_name)}</h3><span class="slug">/${escapeHtml(game.slug)}</span>
        <div class="card-endpoint"><small>MCP ENDPOINT</small><code>${escapeHtml(mcpUrl)}</code></div>
        <div class="card-footer"><div class="actions">
          <a class="button button-primary" href="/games/${slug}">Manage <span aria-hidden="true">&rarr;</span></a>
          <a class="button button-quiet" href="${escapeHtml(dashUrl)}" target="_blank" rel="noopener">Dashboard &nearr;</a>
        </div><button class="button button-danger" data-action="delete-game" data-slug="${escapeHtml(game.slug)}" aria-label="Delete ${escapeHtml(game.display_name)}">Delete</button></div>
        <p class="card-created">Created ${escapeHtml(created)}</p>
      </article>`;
    }).join('') || '<div class="empty-state"><h3>A city full of possibilities.</h3><a class="button button-primary" href="/games/new">Create your first game</a></div>';
  } catch (error) {
    gamesContainer.innerHTML = `<div class="empty-state">${escapeHtml(error.message)} Use Refresh to retry.</div>`;
    document.getElementById('game-count').textContent = '-';
    throw error;
  } finally {
    gamesContainer.setAttribute('aria-busy', 'false');
  }
}

gamesContainer.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action="delete-game"]');
  if (!button) return;
  const slug = button.dataset.slug;
  if (!await Admin.confirmAction('Delete this game?', `Delete "${slug}" and all its quests and players? This cannot be undone.`, 'Delete game')) return;
  await Admin.busy(button, async () => {
    await Admin.api(`/api/games/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    Admin.notify(`Deleted ${slug}.`);
    await loadGames();
  });
});
document.getElementById('refresh-games').addEventListener('click', (event) => Admin.busy(event.currentTarget, loadGames));
loadGames().catch((error) => Admin.notify(error.message, true));
