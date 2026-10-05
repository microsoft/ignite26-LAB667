window.GameMap = (() => {
  const colors = ['#b7f779', '#77d9ed', '#d7a6ff', '#ffc078', '#ff9fb9', '#9faeff'];
  const valid = (lat, lng) => typeof lat === 'number' && typeof lng === 'number'
    && Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;

  function pointsFor(document, filter = 'all') {
    const points = new Map();
    const lines = [];
    const missing = [];
    const legend = [];
    (document.quests || []).forEach((quest, qi) => {
      if (filter !== 'all' && String(qi) !== String(filter)) return;
      const color = colors[qi % colors.length];
      legend.push({ name: quest.name || `Quest ${qi + 1}`, color });
      (quest.missions || []).forEach((mission, mi) => {
        const pair = [];
        ['start', 'end'].forEach((endpoint) => {
          const lat = mission[`${endpoint}_lat`], lng = mission[`${endpoint}_lng`];
          const address = mission[`${endpoint}_address`] || '';
          if (!valid(lat, lng)) {
            if (address || mission.type === 'move') missing.push({ questIndex: qi, missionIndex: mi, endpoint });
            return;
          }
          const key = `${lat.toFixed(6)},${lng.toFixed(6)}`;
          if (!points.has(key)) points.set(key, { position: [lng, lat], members: [], color, number: points.size + 1 });
          points.get(key).members.push({ questIndex: qi, missionIndex: mi, endpoint, address, questName: quest.name, missionId: mission.id });
          pair.push([lng, lat]);
        });
        if (pair.length === 2) lines.push({ positions: pair, color });
      });
    });
    return { points: [...points.values()], lines, missing, legend };
  }

  let sdkPromise;
  let configPromise;
  function mapConfig() {
    if (!configPromise) {
      configPromise = Admin.api('/api/maps/config').catch((error) => {
        configPromise = null;
        throw error;
      });
    }
    return configPromise;
  }

  function loadSDK() {
    if (window.atlas) return Promise.resolve();
    if (!sdkPromise) {
      sdkPromise = new Promise((resolve, reject) => {
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = 'https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css';
        document.head.append(css);
        const script = document.createElement('script');
        script.src = 'https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js';
        const timeout = setTimeout(() => reject(new Error('Map library timed out. Reload to retry.')), 20000);
        script.onload = () => { clearTimeout(timeout); resolve(); };
        script.onerror = () => { clearTimeout(timeout); reject(new Error('Map library could not load. Story editing is still available.')); };
        document.head.append(script);
      });
    }
    return sdkPromise;
  }

  let routeMaps = [];
  let routeGeneration = 0;

  async function renderRoutePreviews(root) {
    const generation = ++routeGeneration;
    routeMaps.forEach((routeMap) => routeMap.dispose());
    routeMaps = [];
    const previews = [...root.querySelectorAll('.route-map-preview')];
    const mapped = previews.filter((preview) => {
      const { startLat, startLng, endLat, endLng } = preview.dataset;
      return valid(Number(startLat), Number(startLng)) && valid(Number(endLat), Number(endLng));
    });
    if (!mapped.length) return;

    let key;
    try {
      ({ key } = await mapConfig());
      await loadSDK();
    } catch (error) {
      if (generation !== routeGeneration) return;
      mapped.forEach((preview) => {
        preview.classList.add('map-unavailable');
        preview.querySelector('.route-map-state').textContent = error.message;
      });
      return;
    }
    if (generation !== routeGeneration) return;

    mapped.forEach((preview) => {
      const start = [Number(preview.dataset.startLng), Number(preview.dataset.startLat)];
      const end = [Number(preview.dataset.endLng), Number(preview.dataset.endLat)];
      const canvas = preview.querySelector('[data-route-map]');
      const status = preview.querySelector('.route-map-state');
      const routeMap = new atlas.Map(canvas, {
        center: [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2],
        zoom: 12,
        style: 'road',
        interactive: false,
        authOptions: { authType: 'subscriptionKey', subscriptionKey: key },
      });
      routeMaps.push(routeMap);
      routeMap.events.add('error', () => {
        status.textContent = 'Azure Maps could not render this route.';
        preview.classList.add('map-unavailable');
      });
      routeMap.events.add('ready', () => {
        if (generation !== routeGeneration) {
          routeMap.dispose();
          return;
        }
        const source = new atlas.source.DataSource();
        routeMap.sources.add(source);
        source.add(new atlas.data.Feature(new atlas.data.LineString([start, end])));
        routeMap.layers.add(new atlas.layer.LineLayer(source, undefined, {
          strokeColor: '#28665f',
          strokeWidth: 4,
          strokeDashArray: [2, 2],
        }));
        [
          { position: start, label: 'S', className: 'mini-route-marker mini-route-start', title: 'Start' },
          { position: end, label: 'E', className: 'mini-route-marker mini-route-end', title: 'End' },
        ].forEach((point) => {
          const marker = document.createElement('span');
          marker.className = point.className;
          marker.textContent = point.label;
          marker.title = point.title;
          routeMap.markers.add(new atlas.HtmlMarker({ position: point.position, htmlContent: marker }));
        });
        requestAnimationFrame(() => {
          routeMap.resize();
          routeMap.setCamera({
            bounds: atlas.data.BoundingBox.fromPositions([start, end]),
            padding: 34,
            maxZoom: 15,
          });
        });
        preview.classList.add('is-ready');
        status.textContent = 'Azure Maps';
      });
    });
  }

  class Controller {
    constructor({ onSelect = () => {}, onPick = () => {} } = {}) {
      this.onSelect = onSelect;
      this.onPick = onPick;
      this.document = { quests: [] };
      this.filter = 'all';
      this.players = [];
      this.pending = null;
      this.graph = pointsFor(this.document);
      this.status = document.getElementById('map-status');
      this.map = null;
      this.ready = false;
      this.init();
    }

    async init() {
      try {
        const { key } = await mapConfig();
        await loadSDK();
        this.map = new atlas.Map('game-map', {
          center: [-122.4194, 37.7749], zoom: 11, style: 'road',
          authOptions: { authType: 'subscriptionKey', subscriptionKey: key },
        });
        this.map.events.add('error', () => { this.status.textContent = 'Map service error. Check Maps configuration or reload. Story editing is still available.'; });
        this.map.events.add('ready', () => {
          this.source = new atlas.source.DataSource();
          this.map.sources.add(this.source);
          this.map.layers.add(new atlas.layer.LineLayer(this.source, undefined, {
            strokeColor: ['get', 'color'], strokeWidth: 3, strokeDashArray: [3, 3],
          }));
          this.ready = true;
          this.draw();
          this.fit();
        });
        this.map.events.add('click', (event) => {
          if (this.pending && event.position) {
            const target = this.pending;
            this.pending = null;
            this.onPick(target, { lng: event.position[0], lat: event.position[1] });
          }
        });
      } catch (error) {
        this.status.textContent = error.message;
        this.status.classList.add('map-unavailable');
      }
    }

    update(document, { filter = 'all', players = [], selected = null, fit = false } = {}) {
      this.document = document;
      this.filter = filter;
      this.players = players;
      this.selected = selected;
      this.graph = pointsFor(document, filter);
      const legend = window.document.getElementById('map-legend');
      legend.replaceChildren();
      this.graph.legend.forEach((item) => {
        const label = window.document.createElement('span');
        const swatch = window.document.createElement('i');
        swatch.style.background = item.color;
        label.append(swatch, window.document.createTextNode(item.name));
        legend.append(label);
      });
      if (this.ready) {
        this.draw();
        if (fit) this.fit();
      }
    }

    draw() {
      if (!this.ready) return;
      this.popup?.close();
      this.map.markers.clear();
      this.source.clear();
      this.source.add(this.graph.lines.map((line) => new atlas.data.Feature(
        new atlas.data.LineString(line.positions), { color: line.color },
      )));
      this.graph.points.forEach((point) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'story-map-pin';
        button.style.borderColor = point.color;
        const selected = this.selected && point.members.some((member) => member.questIndex === this.selected.questIndex && member.missionIndex === this.selected.missionIndex);
        button.classList.toggle('selected', Boolean(selected));
        button.textContent = String(point.number);
        button.title = [...new Set(point.members.map((member) => member.address || member.questName))].join(' / ');
        button.setAttribute('aria-label', `Point ${point.number}: ${button.title}`);
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          const content = document.createElement('div');
          content.className = 'map-popup';
          const heading = document.createElement('strong');
          heading.textContent = `Point ${point.number}`;
          content.append(heading);
          point.members.forEach((member) => {
            const link = document.createElement('button');
            link.type = 'button';
            link.textContent = `${member.questName} / ${member.missionIndex + 1} ${member.endpoint}: ${member.address || 'Coordinates only'}`;
            link.addEventListener('click', () => { this.popup.close(); this.onSelect(member); });
            content.append(link);
          });
          const coords = document.createElement('small');
          coords.textContent = `${point.position[1].toFixed(6)}, ${point.position[0].toFixed(6)}`;
          content.append(coords);
          this.popup?.close();
          this.popup = new atlas.Popup({ content, position: point.position, pixelOffset: [0, -18] });
          this.popup.open(this.map);
          if (point.members.length === 1) this.onSelect(point.members[0]);
        });
        this.map.markers.add(new atlas.HtmlMarker({ position: point.position, htmlContent: button }));
      });
      this.players.forEach((player) => {
        if (!player.location || !valid(player.location.lat, player.location.lng)) return;
        const pin = document.createElement('button');
        pin.type = 'button';
        pin.className = 'story-player-pin';
        pin.textContent = (player.name || '?').slice(0, 2).toUpperCase();
        pin.title = `${player.name} / v${player.game_version} / ${player.status} (story position, not GPS)`;
        pin.setAttribute('aria-label', pin.title);
        pin.addEventListener('click', (event) => { event.stopPropagation(); this.onSelect({ playerId: player.player_id }); });
        this.map.markers.add(new atlas.HtmlMarker({ position: [player.location.lng, player.location.lat], htmlContent: pin }));
      });
      this.status.textContent = this.pending ? 'Click the map to place the selected endpoint. This changes the editor draft only.'
        : `${this.graph.points.length} unique locations${this.graph.missing.length ? ` / ${this.graph.missing.length} endpoints missing coordinates` : ''}.`;
    }

    pick(target) {
      if (!this.ready) throw new Error('The map is unavailable. Enter coordinates manually or use address lookup.');
      this.pending = target;
      this.status.textContent = 'Click the map to place this endpoint. Choose Story to cancel.';
    }

    fit() {
      if (!this.ready) return;
      const positions = this.graph.points.map((point) => point.position);
      this.players.forEach((p) => { if (p.location && valid(p.location.lat, p.location.lng)) positions.push([p.location.lng, p.location.lat]); });
      if (!positions.length) return;
      this.map.setCamera(positions.length === 1 ? { center: positions[0], zoom: 14 }
        : { bounds: atlas.data.BoundingBox.fromPositions(positions), padding: 65, maxZoom: 15 });
    }

    resize() { if (this.ready) this.map.resize(); }

    async fullscreen(panel) {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (panel.requestFullscreen) await panel.requestFullscreen();
      else throw new Error('Fullscreen is not supported by this browser. Use Full map view instead.');
      this.resize();
    }
  }

  return { Controller, pointsFor, valid, renderRoutePreviews };
})();
