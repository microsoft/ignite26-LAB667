const DASHBOARD_URL = document.body.dataset.dashboardUrl.replace(/\/$/, '');
const gamesContainer = document.getElementById('games');
const escapeHtml = Admin.escapeHtml;

async function loadGames() {
  gamesContainer.setAttribute('aria-busy', 'true');
  try {
    const data = await Admin.api('/api/games');
    document.getElementById('game-count').textContent = String(data.games.length).padStart(2, '0');
    gamesContainer.innerHTML = data.games.map((game) => {
      const slug = encodeURIComponent(game.slug);
      const dashUrl = `${DASHBOARD_URL}/${slug}/dashboard`;
      const playerUrl = `${DASHBOARD_URL}/${slug}/player`;
      const mode = game.player_mode === 'challenge' ? 'Challenge mode' : 'Guided mode';
      return `<article class="game-card">
        <div class="game-card-heading">
          <div><h3>${escapeHtml(game.display_name)}</h3><span class="slug">/${escapeHtml(game.slug)}</span></div>
          <span class="mode-pill badge">${mode}</span>
        </div>
        <div class="actions">
          <a class="button button-primary" href="/games/${slug}">Manage <span aria-hidden="true">&rarr;</span></a>
          <a class="button button-quiet" href="${escapeHtml(playerUrl)}" target="_blank" rel="noopener">Player &nearr;</a>
          <a class="button button-quiet" href="${escapeHtml(dashUrl)}" target="_blank" rel="noopener">Dashboard &nearr;</a>
        </div>
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

document.getElementById('refresh-games').addEventListener('click', (event) => Admin.busy(event.currentTarget, loadGames));
loadGames().catch((error) => Admin.notify(error.message, true));
