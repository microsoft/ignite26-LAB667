function scheduleValues(form) {
  return {
    ...(form.elements.event_name
      ? { event_name: form.elements.event_name.value.trim() }
      : {}),
    ...(form.elements.display_name
      ? { display_name: form.elements.display_name.value.trim() }
      : {}),
    starts_at: form.elements.starts_at.value || null,
    ends_at: form.elements.ends_at.value || null,
    timezone: form.elements.timezone.value.trim(),
    player_mode: form.elements.player_mode?.value || 'guided',
  };
}

document.getElementById('schedule-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  Admin.busy(form.querySelector('button[type="submit"]'), async () => {
    const error = document.getElementById('schedule-error');
    error.hidden = true;
    try {
      const data = await Admin.api(`/api/games/${encodeURIComponent(document.body.dataset.slug)}/schedule`, {
        method: 'PUT',
        body: JSON.stringify({ ...scheduleValues(form), revision: Number(form.dataset.revision) }),
      });
      form.dataset.revision = data.game.schedule_revision;
      document.getElementById('game-availability').textContent = data.availability.message;
      const mode = data.game.player_mode === 'challenge' ? 'Challenge' : 'Guided';
      document.querySelectorAll('[data-player-mode]').forEach((pill) => { pill.textContent = `${mode} mode`; });
      const heading = document.querySelector('.game-heading h1');
      if (heading) heading.textContent = data.game.display_name;
      Admin.notify('Game settings saved.');
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    }
  });
});
