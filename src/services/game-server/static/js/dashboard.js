// Dashboard live updater. Reads the game slug from <body data-slug="...">.

const SLUG = document.body.dataset.slug;
const AZURE_MAPS_KEY = document.body.dataset.azureMapsKey || '';
const BOARD_ROTATION_MS = 10000;
const BOARD_PAGE_SIZE = 50;
const WELCOME_DURATION_MS = 4000;
const board = document.getElementById('players');
const boardCount = document.getElementById('player-board-count');
const boardPause = document.getElementById('player-board-pause');
let boardPage = 0;
let boardPaused = false;
let boardMarkup = null;
let dashboardData = null;
let knownPlayerIds = null;
let welcomeTimer = null;
const welcomeQueue = [];

const STATUS_STYLES = {
  registered: 'border-gold/80 text-gold',
  mission: 'border-sea/80 text-sea',
  complete: 'border-coral/80 text-coral',
  abandoned: 'border-paper/25 text-paper/50',
};

function fmt(value) {
  return value == null || value === '' ? '-' : value;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  }[char]));
}

function statusLabel(status) {
  if (status === 'registered') return 'Ready';
  if (status === 'complete') return 'Done';
  if (status === 'abandoned') return 'Out';
  return 'Active';
}

const ACTIVE_STATUSES = new Set(['mission']);

function shortenName(name) {
  const value = String(name || '').trim();
  if (value.length <= 14) return value;
  const parts = value.split(/\s+/);
  if (parts.length > 1) {
    const short = `${parts[0]} ${parts[parts.length - 1][0]}.`;
    return short.length <= 14 ? short : `${short.slice(0, 13)}\u2026`;
  }
  return `${value.slice(0, 13)}\u2026`;
}

function trophyForRank(rank) {
  if (rank === 1) return '\uD83E\uDD47'; // 🥇
  if (rank === 2) return '\uD83E\uDD48'; // 🥈
  if (rank === 3) return '\uD83E\uDD49'; // 🥉
  if (rank <= 10) return '\uD83C\uDFC6'; // 🏆
  return '';
}

function renderPlayerBoard(advance = false) {
  if (!dashboardData) return;
  const { players, leaderboard, game } = dashboardData;
  const pageCount = Math.max(1, Math.ceil(players.length / BOARD_PAGE_SIZE));
  boardPage = advance ? (boardPage + 1) % pageCount : Math.min(boardPage, pageCount - 1);
  const start = boardPage * BOARD_PAGE_SIZE;
  const visible = players.slice(start, start + BOARD_PAGE_SIZE);
  boardCount.textContent = players.length
    ? `Showing ${start + 1}\u2013${start + visible.length} of ${players.length}`
    : 'Waiting for attendees';
  boardPause.disabled = pageCount === 1;
  const lbByPlayer = new Map((leaderboard || []).map((entry, index) => [entry.player_id, { rank: index + 1, score: entry.score }]));
  const markup = visible.map((player, index) => {
    const style = STATUS_STYLES[player.status] || 'border-paper/40 text-paper/70';
    const lb = game?.competitive_mode ? lbByPlayer.get(player.player_id) : null;
    const trophy = lb ? trophyForRank(lb.rank) : '';
    const isActive = ACTIVE_STATUSES.has(player.status);
    let meta;
    if (lb && lb.score != null) {
      meta = String(lb.score);
    } else if (isActive && player.mission_count) {
      meta = `${(player.current_mission_index || 0) + 1}/${player.mission_count}`;
    } else {
      meta = statusLabel(player.status);
    }
    const trophyHtml = trophy
      ? `<div class="shrink-0 text-sm leading-none" title="Leaderboard #${lb.rank}">${trophy}</div>`
      : '';
    const questName = player.quest_name ? escapeHtml(shortenName(player.quest_name)) : '';
    return `<div class="departure-tile flex min-w-0 items-center gap-1 border-l-4 ${style} px-1.5" style="--tile-index:${index}" title="${escapeHtml(player.name)}">
      <div class="shrink-0 text-right text-xs font-black text-paper/55">${start + index + 1}</div>
      <div class="min-w-0 flex-1">
        <div class="truncate text-[clamp(0.7rem,1.1vw,1rem)] font-extrabold leading-tight">${escapeHtml(player.name)}</div>
        ${questName ? `<div class="departure-tile-quest truncate text-[0.6rem] font-semibold uppercase tracking-[0.08em] text-paper/40">${questName}</div>` : ''}
      </div>
      ${trophyHtml}
      <div class="shrink-0 text-[0.6rem] font-black uppercase tracking-[0.08em] text-paper/55">${escapeHtml(meta)}</div>
    </div>`;
  }).join('');
  if (markup !== boardMarkup) {
    board.classList.toggle('is-flipping', advance);
    board.innerHTML = markup;
    boardMarkup = markup;
  }
}

function showNextWelcome() {
  const overlay = document.getElementById('player-welcome-overlay');
  const name = document.getElementById('player-welcome-name');
  if (welcomeTimer || !welcomeQueue.length || !overlay || !name) return;
  name.textContent = welcomeQueue.shift();
  overlay.hidden = false;
  overlay.classList.remove('is-visible');
  requestAnimationFrame(() => overlay.classList.add('is-visible'));
  welcomeTimer = setTimeout(() => {
    overlay.hidden = true;
    overlay.classList.remove('is-visible');
    welcomeTimer = null;
    showNextWelcome();
  }, WELCOME_DURATION_MS);
}

function welcomeNewPlayers(players) {
  if (knownPlayerIds === null) {
    knownPlayerIds = new Set(players.map((player) => player.player_id));
    return;
  }
  players.forEach((player) => {
    if (!knownPlayerIds.has(player.player_id)) {
      knownPlayerIds.add(player.player_id);
      welcomeQueue.push(player.name || 'Player');
    }
  });
  showNextWelcome();
}

async function refreshDashboard() {
  try {
    const response = await fetch(`/${SLUG}/dashboard/data`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Attendee data unavailable (HTTP ${response.status})`);
    const data = await response.json();
    dashboardData = data;
    renderPlayerBoard();
    welcomeNewPlayers(data.players);
    syncPlayerAnimations(data.players);
    if (mapRef && JSON.stringify(data.quest_versions || []) !== questMapVersions) {
      await loadQuestLocations(mapRef);
    }
  } catch (error) {
    console.warn('[dashboard] Refresh failed; will retry', error);
    if (!dashboardData) boardCount.textContent = 'Could not load attendees; retrying';
  }
}

// --- Azure Map ---------------------------------------------------------------

function setMapStatus(text) {
  const el = document.getElementById('map-status');
  if (!el) return;
  if (text) {
    el.textContent = text;
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}

function pinHtml(kind, label) {
  return `<div class="map-pin map-pin--${kind}" title="${escapeHtml(label)}">${label.charAt(0).toUpperCase()}</div>`;
}

let questMapVersions = null;
let questMarkers = [];
let loadingQuestLocations = false;

async function loadQuestLocations(map) {
  if (loadingQuestLocations) return;
  loadingQuestLocations = true;
  let payload;
  try {
    const response = await fetch(`/${SLUG}/dashboard/quests`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Quest locations unavailable');
    payload = await response.json();
  } catch (error) {
    setMapStatus('Failed to load quests');
    return;
  } finally {
    loadingQuestLocations = false;
  }
  const initial = questMapVersions === null;
  questMarkers.forEach(({ marker, popup, onClick }) => {
    popup.close();
    map.events.remove('click', marker, onClick);
    map.markers.remove(marker);
  });
  questMarkers = [];
  const positions = [];
  (payload.quests || []).forEach((quest) => {
    (quest.points || []).forEach((point) => {
      const position = [point.lng, point.lat];
      positions.push(position);
      const marker = new atlas.HtmlMarker({
        position,
        htmlContent: pinHtml(point.kind, point.label),
      });
      map.markers.add(marker);
      const popup = new atlas.Popup({
        content: `<div style="padding:8px 10px;font-family:Inter,system-ui,sans-serif;max-width:240px">
          <div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:#0e6f73">${escapeHtml(quest.name || '')}</div>
          <div style="font-size:14px;font-weight:800;margin-top:2px">${escapeHtml(point.label)}</div>
          <div style="font-size:12px;color:#555;margin-top:4px">${escapeHtml(point.address || '')}</div>
        </div>`,
        pixelOffset: [0, -18],
      });
      const onClick = () => {
        popup.setOptions({ position });
        popup.open(map);
      };
      map.events.add('click', marker, onClick);
      questMarkers.push({ marker, popup, onClick });
    });
  });
  if (positions.length) {
    setMapStatus(null);
    if (initial) {
      const bbox = atlas.data.BoundingBox.fromPositions(positions);
      map.setCamera({ bounds: bbox, padding: 60, maxZoom: 15 });
    }
  } else {
    setMapStatus('No quest locations yet');
  }
  questMapVersions = JSON.stringify(payload.versions || []);
}

function initMap() {
  const container = document.getElementById('map');
  if (!container) return;
  if (typeof atlas === 'undefined') {
    setMapStatus('Azure Maps SDK failed to load');
    return;
  }
  if (!AZURE_MAPS_KEY) {
    setMapStatus('Set AZURE_MAPS_KEY to enable the map');
    return;
  }
  const map = new atlas.Map('map', {
    center: [-122.4194, 37.7749],
    zoom: 12,
    style: 'road',
    view: 'Auto',
    authOptions: { authType: 'subscriptionKey', subscriptionKey: AZURE_MAPS_KEY },
  });
  map.events.add('ready', () => {
    mapRef = map;
    loadQuestLocations(map);
  });
  map.events.add('error', () => setMapStatus('Map error \u2014 check AZURE_MAPS_KEY'));
}

// --- Player animation along move routes -------------------------------------

let mapRef = null;
const playerMarkers = new Map(); // player_id -> atlas.HtmlMarker
const animatedCodes = new Set(); // `${player_id}:${code}`
const pendingCodes = new Set();  // player/route pairs currently being fetched
const REPLAY_WINDOW_MS = 60 * 1000;
let initialAnimationSync = true;
let animationIssueCount = 0;

function reportAnimationIssue(reason, details) {
  animationIssueCount += 1;
  if (animationIssueCount > 20) return;
  const payload = { reason, ...details };
  if (typeof window !== 'undefined') window.__dashboardLastAnimationIssue = payload;
  if (typeof console !== 'undefined' && console.warn) {
    console.warn('[dashboard-animation]', payload);
  }
}

function playerPinHtml(slot, player) {
  const status = Object.hasOwn(STATUS_STYLES, player.status) ? player.status : 'mission';
  return `<div class="player-pin player-pin--${status}" title="${escapeHtml(player.name)}">${slot}</div>`;
}

function parseTimestamp(value) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

async function fetchRoute(code) {
  try {
    const res = await fetch(`/${SLUG}/dashboard/routes/${code}`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    return null;
  }
}

function extractPolyline(routeJson) {
  const legs = (((routeJson || {}).raw_route || {}).routes || [{}])[0].legs || [];
  const points = [];
  legs.forEach((leg) => {
    (leg.points || []).forEach((pt) => {
      if (typeof pt.latitude === 'number' && typeof pt.longitude === 'number') {
        points.push([pt.longitude, pt.latitude]);
      }
    });
  });
  return points;
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function animateMarker(marker, polyline, totalMs = 8000, meta = {}) {
  if (polyline.length < 2) {
    if (polyline.length === 1) marker.setOptions({ position: polyline[0] });
    return;
  }
  const safeTotalMs = Number.isFinite(totalMs) && totalMs > 0 ? totalMs : 8000;
  const start = performance.now();
  const segmentMs = safeTotalMs / (polyline.length - 1);

  function frame(now) {
    const ts = Number.isFinite(now) ? now : performance.now();
    const elapsed = ts - start;
    if (!Number.isFinite(elapsed) || !Number.isFinite(segmentMs) || segmentMs <= 0) {
      reportAnimationIssue('invalid-timing', {
        playerId: meta.playerId,
        routeRef: meta.routeRef,
        now,
        ts,
        start,
        elapsed,
        segmentMs,
        polylineLength: polyline.length,
      });
      marker.setOptions({ position: polyline[polyline.length - 1] });
      return;
    }
    if (elapsed >= safeTotalMs) {
      marker.setOptions({ position: polyline[polyline.length - 1] });
      return;
    }
    const progress = elapsed / segmentMs;
    const segIndex = Math.max(0, Math.min(Math.floor(progress), polyline.length - 2));
    const t = progress - segIndex;
    const from = polyline[segIndex];
    const to = polyline[segIndex + 1];
    if (!Array.isArray(from) || !Array.isArray(to) || from.length < 2 || to.length < 2) {
      reportAnimationIssue('invalid-segment-points', {
        playerId: meta.playerId,
        routeRef: meta.routeRef,
        segIndex,
        progress,
        polylineLength: polyline.length,
      });
      marker.setOptions({ position: polyline[polyline.length - 1] });
      return;
    }
    const nextLng = lerp(from[0], to[0], t);
    const nextLat = lerp(from[1], to[1], t);
    if (!Number.isFinite(nextLng) || !Number.isFinite(nextLat)) {
      reportAnimationIssue('invalid-interpolation', {
        playerId: meta.playerId,
        routeRef: meta.routeRef,
        segIndex,
        t,
        from,
        to,
      });
      marker.setOptions({ position: polyline[polyline.length - 1] });
      return;
    }
    marker.setOptions({ position: [nextLng, nextLat] });
    requestAnimationFrame(frame);
  }

  marker.setOptions({ position: polyline[0] });
  requestAnimationFrame(frame);
}

async function animatePlayerAlongRoute(player, slot, code) {
  const route = await fetchRoute(code);
  const polyline = extractPolyline(route);
  if (polyline.length < 1) return false;
  let marker = playerMarkers.get(player.player_id);
  if (!marker) {
    marker = new atlas.HtmlMarker({
      position: polyline[0],
      htmlContent: playerPinHtml(slot, player),
    });
    mapRef.markers.add(marker);
    playerMarkers.set(player.player_id, marker);
  } else {
    marker.setOptions({ htmlContent: playerPinHtml(slot, player) });
  }
  animateMarker(marker, polyline, 8000, {
    playerId: player.player_id,
    routeRef: code,
  });
  return true;
}

function syncPlayerAnimations(players) {
  if (!mapRef) return;
  const replayCutoff = Date.now() - REPLAY_WINDOW_MS;
  const pendingAnimations = [];
  players.forEach((player, index) => {
    const slot = index + 1;
    // Refresh marker styling (status may have changed) without resetting position.
    const marker = playerMarkers.get(player.player_id);
    if (marker) marker.setOptions({ htmlContent: playerPinHtml(slot, player) });
    (player.mission_results || []).forEach((result) => {
      const code = String(result.route_ref || '').trim();
      if (!code) return;
      const key = `${player.player_id}:${code}`;
      if (animatedCodes.has(key) || pendingCodes.has(key)) return;
      if (initialAnimationSync) {
        const completedAt = parseTimestamp(result.completed_at);
        if (completedAt != null && completedAt < replayCutoff) {
          animatedCodes.add(key);
          return;
        }
      }
      pendingCodes.add(key);
      pendingAnimations.push({ key, player, slot, code });
    });
  });
  pendingAnimations.forEach(({ key, player, slot, code }) => {
    animatePlayerAlongRoute(player, slot, code).then((started) => {
      if (started) animatedCodes.add(key);
    }).catch((error) => reportAnimationIssue('route-animation-failed', { routeRef: code, error }))
      .finally(() => pendingCodes.delete(key));
  });
  initialAnimationSync = false;
}

initMap();
refreshDashboard();
setInterval(refreshDashboard, 5000);
setInterval(() => {
  if (!boardPaused && !boardPause.disabled) renderPlayerBoard(true);
}, BOARD_ROTATION_MS);
boardPause.addEventListener('click', () => {
  boardPaused = !boardPaused;
  boardPause.textContent = boardPaused ? 'Resume rotation' : 'Pause rotation';
});
