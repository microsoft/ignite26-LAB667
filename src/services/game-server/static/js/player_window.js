(() => {
  const countdown = document.getElementById('player-window-countdown');
  if (!countdown) return;

  const initialSeconds = Number(countdown.dataset.secondsUntilStart);
  if (!Number.isFinite(initialSeconds) || initialSeconds < 0) return;
  const opensAt = performance.now() + initialSeconds * 1000;

  function render() {
    const remaining = Math.max(0, Math.ceil((opensAt - performance.now()) / 1000));
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.floor((remaining % 3600) / 60);
    const seconds = remaining % 60;
    countdown.textContent = [hours, minutes, seconds]
      .map((value) => String(value).padStart(2, '0'))
      .join(':');
    if (remaining === 0) {
      countdown.textContent = 'Opening now...';
      window.setTimeout(() => window.location.reload(), 1000);
      return;
    }
    window.setTimeout(render, 250);
  }

  render();
})();
