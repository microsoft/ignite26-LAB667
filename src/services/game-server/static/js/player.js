(() => {
  const slug = document.body.dataset.gameSlug;
  const storageKey = `lost-in-the-city:${slug}:api-key`;
  const session = document.getElementById('player-session');
  const registration = document.getElementById('player-registration');
  const form = document.getElementById('player-registration-form');
  const error = document.getElementById('player-registration-error');
  const headerIdentity = document.getElementById('player-header-identity');
  const keyDialog = document.getElementById('player-key-dialog');
  const progress = document.getElementById('player-progress');
  const content = document.getElementById('player-content');
  const timeline = document.getElementById('player-timeline');
  const timelineShell = document.getElementById('player-timeline-shell');
  const timelinePrevious = document.getElementById('player-timeline-previous');
  const timelineNext = document.getElementById('player-timeline-next');
  const agent42Dialog = document.getElementById('player-agent42-dialog');
  const agent42Content = document.getElementById('player-agent42-content');
  const agent42Status = document.getElementById('player-agent42-status');
  const agent42Map = document.getElementById('player-agent42-map');
  const agent42MapPanel = document.getElementById('player-agent42-map-panel');
  const agent42MapStatus = document.getElementById('player-agent42-map-status');
  const agent42Layout = document.querySelector('.player-agent42-layout');
  let apiKey = localStorage.getItem(storageKey) || '';
  let pollTimer;
  let agent42MapUrl = '';

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));

  function updateTimelineControls() {
    const maxScroll = Math.max(0, timeline.scrollWidth - timeline.clientWidth);
    timelineShell.classList.toggle('player-timeline-scrollable', maxScroll > 1);
    timelinePrevious.hidden = maxScroll <= 1;
    timelineNext.hidden = maxScroll <= 1;
    timelinePrevious.disabled = timeline.scrollLeft <= 1;
    timelineNext.disabled = timeline.scrollLeft >= maxScroll - 1;
  }

  function scrollTimeline(direction) {
    const milestone = timeline.querySelector('.player-timeline-event');
    const distance = milestone ? milestone.getBoundingClientRect().width : timeline.clientWidth;
    timeline.scrollLeft += direction * distance;
    updateTimelineControls();
  }

  function showRegistration(message = '') {
    clearTimeout(pollTimer);
    session.hidden = false;
    registration.hidden = false;
    headerIdentity.hidden = true;
    progress.hidden = true;
    content.hidden = true;
    if (keyDialog.open) keyDialog.close();
    error.textContent = message;
    error.hidden = !message;
  }

  function renderPlayer(player) {
    session.hidden = true;
    registration.hidden = true;
    headerIdentity.hidden = false;
    progress.hidden = false;
    content.hidden = false;
    document.getElementById('player-progress-status').hidden = true;
    document.getElementById('player-name').textContent = player.name;
    document.getElementById('player-api-key').textContent = apiKey;
    document.querySelectorAll('[data-player-quest-name]').forEach((element) => {
      element.textContent = player.quest_name
        ? `${player.quest_name} with Foundry IQ`
        : 'Solve Your City Guide Question with Foundry IQ';
    });
    document.querySelectorAll('[data-player-quest-question]').forEach((element) => {
      element.textContent = player.quest_question || '';
      element.hidden = !player.quest_question;
    });
    const events = player.timeline || [];
    const completedMissions = new Set(events
      .filter((event) => event.type === 'mission_complete')
      .map((event) => event.mission_index));
    const pendingMissions = Array.from(
      { length: player.mission_count },
      (_, index) => index,
    ).filter((index) => !completedMissions.has(index)).map((index) => ({
      type: 'pending',
      title: `Mission ${index + 1}`,
      detail: 'Not completed yet.',
      occurred_at: '',
    }));
    timeline.innerHTML = [...events, ...pendingMissions].map((event) => `
      <li class="player-timeline-event player-timeline-${escapeHtml(event.type)}">
        <span class="player-timeline-marker" aria-hidden="true"></span>
        <div>
          ${event.type === 'agent42' && event.has_details
            ? `<button class="player-timeline-detail" type="button" data-agent42-event="${event.event_index}">
                <span class="player-timeline-meta"><strong>${escapeHtml(event.title)}</strong></span>
                ${event.detail ? `<span class="player-timeline-detail-summary">${escapeHtml(event.detail)}</span>` : ''}
                <span class="player-timeline-detail-cta">View route details &rarr;</span>
              </button>`
            : `<div class="player-timeline-meta">
                <strong>${escapeHtml(event.title)}</strong>
              </div>
              ${event.transport
                ? `<span class="player-timeline-transport">Transport: ${escapeHtml(event.transport)}</span>`
                : ''}
              ${event.detail ? `<p>${escapeHtml(event.detail)}</p>` : ''}`}
        </div>
      </li>
    `).join('');
    requestAnimationFrame(updateTimelineControls);
  }

  function releaseAgent42Map() {
    if (agent42MapUrl) URL.revokeObjectURL(agent42MapUrl);
    agent42MapUrl = '';
    agent42Map.removeAttribute('src');
    agent42Map.alt = '';
  }

  function renderAgent42Route(route) {
    const values = [
      ['From', route?.origin || 'Not available'],
      ['To', route?.destination || 'Not available'],
      ['Mode', route?.mode || 'Not available'],
      ['Distance', route?.distance_km == null ? 'Not available' : `${route.distance_km} km`],
      ['Travel time', route?.travel_time_minutes == null ? 'Not available' : `${route.travel_time_minutes} minutes`],
      ['Traffic delay', route?.traffic_delay_minutes == null ? 'Not available' : `${route.traffic_delay_minutes} minutes`],
    ];
    document.getElementById('player-agent42-route').innerHTML = values
      .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
      .join('');
  }

  async function openAgent42Details(eventIndex) {
    releaseAgent42Map();
    agent42Content.hidden = true;
    agent42Status.hidden = false;
    agent42Status.textContent = 'Loading route details...';
    agent42Layout.hidden = false;
    agent42MapPanel.hidden = false;
    agent42MapStatus.textContent = 'Loading route map...';
    agent42Dialog.showModal();
    try {
      const baseUrl = `/api/games/${encodeURIComponent(slug)}/player/timeline/${eventIndex}/agent42`;
      const response = await fetch(baseUrl, {
        headers: { Authorization: 'Bearer ' + apiKey },
        cache: 'no-store',
      });
      const details = await response.json();
      if (!response.ok) throw new Error(details.error || 'Could not load Agent42 details.');
      document.getElementById('player-agent42-title').textContent = details.title;
      document.getElementById('player-agent42-weather').textContent = details.weather || 'Weather was not included in this advice.';
      document.getElementById('player-agent42-recommendation').textContent = details.recommendation
        ? `Recommended: ${details.recommendation}`
        : 'No recommendation recorded';
      document.getElementById('player-agent42-advice').textContent = details.advice || 'No advice was recorded.';
      renderAgent42Route(details.route);
      agent42Content.hidden = false;
      agent42Status.hidden = true;
      if (!details.route) {
        agent42Layout.hidden = true;
        return;
      }
      if (!details.map_available) {
        agent42MapPanel.hidden = false;
        agent42MapStatus.textContent = 'A route map is not available for this advice.';
        return;
      }
      const mapResponse = await fetch(`${baseUrl}/map`, {
        headers: { Authorization: 'Bearer ' + apiKey },
        cache: 'no-store',
      });
      if (!mapResponse.ok) throw new Error(`Could not load the route map (${mapResponse.status}).`);
      agent42MapUrl = URL.createObjectURL(await mapResponse.blob());
      agent42Map.src = agent42MapUrl;
      agent42Map.alt = details.route
        ? `Agent42 route from ${details.route.origin} to ${details.route.destination}`
        : 'Agent42 recommended route';
      agent42MapStatus.textContent = 'Recommended route map';
    } catch (detailsError) {
      agent42Status.textContent = detailsError.message;
      agent42Status.hidden = false;
    }
  }

  async function loadState() {
    if (!apiKey) {
      showRegistration();
      return;
    }
    const response = await fetch(`/api/games/${encodeURIComponent(slug)}/player`, {
      headers: { Authorization: 'Bearer ' + apiKey },
      cache: 'no-store',
    });
    if (response.status === 401) {
      localStorage.removeItem(storageKey);
      apiKey = '';
      showRegistration('That saved key is no longer valid. Start a new game.');
      return;
    }
    if (!response.ok) {
      throw new Error(`Could not load player progress (${response.status}).`);
    }
    renderPlayer((await response.json()).player);
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => loadState().catch(showLoadError), 4000);
  }

  function showLoadError(loadError) {
    const status = document.getElementById('player-progress-status');
    status.textContent = loadError.message;
    status.hidden = false;
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => loadState().catch(showLoadError), 8000);
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    error.hidden = true;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const response = await fetch(`/api/games/${encodeURIComponent(slug)}/players`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname: form.elements.nickname.value }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not start the game.');
      apiKey = payload.api_key;
      localStorage.setItem(storageKey, apiKey);
      renderPlayer(payload.player);
      pollTimer = setTimeout(() => loadState().catch(showLoadError), 4000);
    } catch (registrationError) {
      error.textContent = registrationError.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById('open-player-key').addEventListener('click', () => {
    document.getElementById('copy-player-key-status').textContent = '';
    keyDialog.showModal();
  });

  document.getElementById('close-player-key').addEventListener('click', () => {
    keyDialog.close();
  });

  document.getElementById('close-player-agent42').addEventListener('click', () => {
    agent42Dialog.close();
  });

  document.getElementById('copy-player-key').addEventListener('click', async () => {
    const status = document.getElementById('copy-player-key-status');
    try {
      await navigator.clipboard.writeText(apiKey);
      status.textContent = 'API key copied.';
    } catch {
      status.textContent = 'Copy failed. Select the key and copy it manually.';
    }
  });

  document.getElementById('forget-player-key').addEventListener('click', () => {
    localStorage.removeItem(storageKey);
    apiKey = '';
    form.reset();
    showRegistration();
  });

  timelinePrevious.addEventListener('click', () => scrollTimeline(-1));
  timelineNext.addEventListener('click', () => scrollTimeline(1));
  timeline.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-agent42-event]');
    if (trigger) openAgent42Details(trigger.dataset.agent42Event);
  });
  timeline.addEventListener('scroll', updateTimelineControls, { passive: true });
  window.addEventListener('resize', updateTimelineControls);
  agent42Dialog.addEventListener('close', releaseAgent42Map);

  loadState().catch((loadError) => {
    if (apiKey) {
      showLoadError(loadError);
    } else {
      showRegistration();
    }
  });
})();
