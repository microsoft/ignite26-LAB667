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
  const milestoneDialog = document.getElementById('player-milestone-dialog');
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
  let timelineMarkup = '';

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));

  function showRegistration(message = '') {
    clearTimeout(pollTimer);
    document.documentElement.classList.remove('player-returning');
    document.body.classList.remove('player-active');
    document.querySelectorAll('[data-player-api-key]').forEach((element) => {
      element.textContent = '<copy-from-this-player-page>';
    });
    session.hidden = false;
    registration.hidden = false;
    headerIdentity.hidden = true;
    progress.hidden = true;
    document.getElementById('player-progress-status').hidden = true;
    content.hidden = true;
    if (keyDialog.open) keyDialog.close();
    if (milestoneDialog.open) milestoneDialog.close();
    error.textContent = message;
    error.hidden = !message;
  }

  function renderPlayer(player) {
    document.body.classList.add('player-active');
    session.hidden = true;
    registration.hidden = true;
    headerIdentity.hidden = false;
    progress.hidden = false;
    content.hidden = false;
    document.getElementById('player-progress-status').hidden = true;
    document.getElementById('player-name').textContent = player.name;
    document.querySelectorAll('[data-player-name]').forEach((element) => {
      element.textContent = player.name;
    });
    document.querySelectorAll('[data-player-api-key]').forEach((element) => {
      element.textContent = apiKey;
    });
    document.querySelectorAll('[data-player-quest]').forEach((element) => {
      element.textContent = player.quest_name || 'your quest';
    });
    document.querySelectorAll('[data-player-question]').forEach((element) => {
      element.textContent = player.quest_question || 'the question from your quest';
    });
    document.getElementById('player-api-key').textContent = apiKey;
    const events = player.timeline || [];
    const completedMissions = new Set(events
      .filter((event) => event.type === 'mission_complete')
      .map((event) => event.mission_index));
    const pendingMissions = Array.from(
      { length: player.mission_count },
      (_, index) => index,
    ).filter((index) => !completedMissions.has(index)).map((index) => ({
      type: 'pending',
      title: `Quest step ${index + 1}`,
      detail: 'Not completed yet.',
      occurred_at: '',
    }));
    const milestones = [
      { type: 'start', title: 'Start', detail: 'Your adventure begins here.' },
      ...events.filter((event) => event.type !== 'registered'),
      ...pendingMissions,
      {
        type: player.status === 'complete' ? 'end' : 'pending-end',
        title: 'End',
        detail: player.status === 'complete' ? 'Adventure completed.' : 'Your final destination.',
      },
    ];
    const markup = milestones.map((event) => {
      const hasDetails = event.type === 'agent42' && event.has_details;
      const title = event.type === 'mission_complete'
        ? event.title.replace(/^Mission (\d+) complete$/, 'Quest step $1 complete')
        : event.title;
      const label = [
        title,
        event.transport ? `Transport: ${event.transport}` : '',
        event.detail,
        hasDetails ? 'View route details' : '',
      ].filter(Boolean).join('. ');
      const attributes = `class="player-timeline-dot" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"`;
      const detail = [
        event.transport ? `Transport: ${event.transport}` : '',
        event.detail,
      ].filter(Boolean).join('\n\n') || 'No additional details recorded.';
      const action = hasDetails
        ? `data-agent42-event="${escapeHtml(event.event_index)}"`
        : `data-milestone-title="${escapeHtml(title)}" data-milestone-detail="${escapeHtml(detail)}"`;
      const marker = '<span class="player-timeline-marker" aria-hidden="true"></span>';
      return `
        <li class="player-timeline-event player-timeline-${escapeHtml(event.type)}">
          <svg class="player-timeline-connector" viewBox="0 0 72 64" aria-hidden="true" focusable="false">
            <path d="M24 0 C24 32 48 32 48 64" />
          </svg>
          <button ${attributes} type="button" aria-haspopup="dialog" ${action}>
            ${marker}
            <span class="player-timeline-label" aria-hidden="true">${escapeHtml(title)}</span>
          </button>
        </li>
      `;
    }).join('');
    if (markup !== timelineMarkup) {
      const focusedIndex = [...timeline.children].findIndex((event) => event.contains(document.activeElement));
      timeline.innerHTML = markup;
      timelineMarkup = markup;
      if (focusedIndex >= 0) {
        timeline.children[focusedIndex]?.querySelector('.player-timeline-dot').focus({ preventScroll: true });
      }
    }
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

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.className = 'copy-fallback';
      document.body.append(area);
      area.select();
      let copied = false;
      try { copied = document.execCommand('copy'); } catch { copied = false; }
      area.remove();
      return copied;
    }
  }

  function addCopyButtons() {
    document.querySelectorAll('.lesson-content pre').forEach((pre) => {
      if (pre.parentElement.classList.contains('code-block')) return;
      const code = pre.querySelector('code') || pre;
      const language = ((code.className || '').match(/language-([\w-]+)/) || [])[1] || 'text';
      const readOnly = /-read$/.test(language);
      const wrapper = document.createElement('div');
      wrapper.className = readOnly ? 'code-block code-block-read' : 'code-block';
      const bar = document.createElement('div');
      bar.className = 'code-block-bar';
      const label = document.createElement('span');
      label.className = 'code-block-language';
      label.textContent = language.replace(/-(notype|read)$/, '');
      if (readOnly) {
        if (/^output/.test(language)) {
          wrapper.classList.add('code-block-output');
          code.innerHTML = code.innerHTML.replace(/^(You|Agent):$/gm, '<span class="chat-speaker">$1</span>');
        }
        const note = document.createElement('span');
        note.className = 'code-block-note';
        note.textContent = 'Just read, no need to copy';
        bar.append(label, note);
        pre.replaceWith(wrapper);
        wrapper.append(bar, pre);
        return;
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'code-block-copy';
      button.textContent = 'Copy';
      const status = document.createElement('span');
      status.className = 'sr-only';
      status.setAttribute('role', 'status');
      let resetTimer;
      button.addEventListener('click', async () => {
        const copied = await copyText(code.textContent.replace(/\n$/, ''));
        clearTimeout(resetTimer);
        button.textContent = copied ? 'Copied' : 'Copy failed';
        button.dataset.state = copied ? 'copied' : 'failed';
        status.textContent = copied ? 'Code copied to clipboard.' : 'Copy failed. Select the code and copy it manually.';
        resetTimer = setTimeout(() => {
          button.textContent = 'Copy';
          delete button.dataset.state;
          status.textContent = '';
        }, 2000);
      });
      bar.append(label, button, status);
      pre.replaceWith(wrapper);
      wrapper.append(bar, pre);
    });
  }
  addCopyButtons();

  const workshopHeader = document.querySelector('.workshop-header');
  const syncHeaderHeight = () => {
    const sticky = getComputedStyle(workshopHeader).position === 'sticky';
    document.documentElement.style.setProperty(
      '--player-header-height', sticky ? `${workshopHeader.offsetHeight}px` : '0px',
    );
  };
  if (workshopHeader && 'ResizeObserver' in window) {
    new ResizeObserver(syncHeaderHeight).observe(workshopHeader);
    window.addEventListener('resize', syncHeaderHeight);
  }

  const navToggle = document.getElementById('workshop-nav-toggle');
  const navCollapsedKey = 'lost-in-the-city:nav-collapsed';
  function setNavCollapsed(collapsed) {
    content.classList.toggle('workshop-nav-collapsed', collapsed);
    navToggle.setAttribute('aria-expanded', String(!collapsed));
    document.getElementById('workshop-nav').inert = collapsed;
    const label = collapsed ? 'Show chapters' : 'Hide chapters';
    navToggle.setAttribute('aria-label', label);
    navToggle.title = label;
  }
  setNavCollapsed(localStorage.getItem(navCollapsedKey) !== 'false');
  navToggle.addEventListener('click', () => {
    const collapsed = !content.classList.contains('workshop-nav-collapsed');
    localStorage.setItem(navCollapsedKey, String(collapsed));
    setNavCollapsed(collapsed);
  });

  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href^="#more-"]');
    const dialog = link && document.getElementById(link.getAttribute('href').slice(1));
    if (dialog instanceof HTMLDialogElement) {
      event.preventDefault();
      dialog.showModal();
      return;
    }
    const close = event.target.closest('[data-close-more]');
    if (close) close.closest('dialog').close();
  });
  document.querySelectorAll('.more-info-dialog').forEach((moreDialog) => {
    moreDialog.addEventListener('click', (event) => {
      if (event.target === moreDialog) moreDialog.close();
    });
    moreDialog.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') moreDialog.close();
    });
  });

  timeline.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-agent42-event]');
    if (trigger) {
      openAgent42Details(trigger.dataset.agent42Event);
      return;
    }
    const milestone = event.target.closest('[data-milestone-title]');
    if (milestone) {
      document.getElementById('player-milestone-title').textContent = milestone.dataset.milestoneTitle;
      document.getElementById('player-milestone-detail').textContent = milestone.dataset.milestoneDetail;
      milestoneDialog.showModal();
    }
  });
  document.getElementById('close-player-milestone').addEventListener('click', () => {
    milestoneDialog.close();
  });
  milestoneDialog.addEventListener('click', (event) => {
    if (event.target === milestoneDialog) milestoneDialog.close();
  });
  agent42Dialog.addEventListener('close', releaseAgent42Map);

  loadState().catch((loadError) => {
    if (apiKey) {
      showLoadError(loadError);
    } else {
      showRegistration();
    }
  });
})();
