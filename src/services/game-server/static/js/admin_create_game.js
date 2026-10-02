document.getElementById('new-game-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  if (button.disabled) return;
  Admin.busy(button, async () => {
    const status = document.getElementById('add-status');
    status.hidden = true;
    status.textContent = '';
    try {
      const slug = document.getElementById('new-slug').value.trim();
      const display_name = document.getElementById('new-name').value.trim();
      const data = await Admin.api('/api/games', {
        method: 'POST', body: JSON.stringify({ slug, display_name }),
      });
      location.assign(`/games/${encodeURIComponent(data.game.slug)}/edit`);
    } catch (error) {
      status.textContent = error.message;
      status.hidden = false;
    }
  });
});
