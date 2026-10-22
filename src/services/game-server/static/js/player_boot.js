// Runs in <head> before the page is drawn. If this browser already has a player
// key, show the lesson layout straight away instead of flashing the sign-in screen.
// player.js confirms the key and removes the class again if it is no longer valid.
(() => {
  const slug = document.currentScript?.dataset.gameSlug;
  try {
    if (slug && localStorage.getItem(`lost-in-the-city:${slug}:api-key`)) {
      document.documentElement.classList.add('player-returning');
    }
  } catch {
    // Storage can be blocked; the page then simply starts on the sign-in screen.
  }
})();
