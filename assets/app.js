const state = { dives: [], filtered: [], selected: null, trip: 'all', trips: [], numbered: new Map() };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const fmt = {
  n: (v, u = '') => v == null ? '—' : `${v}${u}`,
  time: mins => { if (mins == null) return '—'; const h = Math.floor(mins / 60), m = Math.round(mins % 60);
                  return h ? `${h}h ${m}m` : `${m} min`; },
  date: d => d ? new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—',
};

const isScuba = d => d.dive_mode === 'opencircuit';
const counted = d => isScuba(d) && !d.suspect;           // dives that feed the totals
const isNitrox = d => !!(d.gas && d.gas.o2 > 0.21);
const hasPos = d => d.lat != null && d.lon != null;
const srcLabel = d => d.sources.length > 1 ? 'merged' : d.sources[0] === 'padi' ? 'PADI' : 'Oceanic+';
const byTime = (a, b) => (a.date || '').localeCompare(b.date || '')
  || (a.time || '').localeCompare(b.time || '')
  || String(a.id).localeCompare(String(b.id));

async function init() {
  const res = await fetch('data/merged_log.json');
  const data = await res.json();
  const asc = data.dives.slice().sort(byTime);
  let n = 0;
  for (const d of asc) if (counted(d)) state.numbered.set(d.id, ++n);   // dive numbers: valid scuba only
  state.dives = asc.reverse();                                          // newest first
  state.trips = data.trips || [];

  const years = [...new Set(state.dives.map(d => d.date.slice(0, 4)))].sort().reverse();
  for (const y of years) {
    const o = document.createElement('option'); o.value = y; o.textContent = y;
    document.getElementById('f-year').appendChild(o);
  }
  buildTripChips();
  ['f-mode', 'f-year', 'f-site'].forEach(id => document.getElementById(id).addEventListener('input', applyFilters));
  applyFilters();
}

function buildTripChips() {
  const el = document.getElementById('trips');
  const list = [{ id: 'all', label: 'All trips', n: state.dives.filter(counted).length }]
    .concat(state.trips.slice().reverse().map(t => ({ ...t, n: state.dives.filter(d => d.trip === t.id && counted(d)).length })));
  el.replaceChildren(...list.map(t => {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = `${esc(t.label)}<small>${t.n}</small>`;
    b.setAttribute('aria-pressed', String(t.id === state.trip));
    b.addEventListener('click', () => {
      state.trip = t.id;
      [...el.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      applyFilters();
    });
    return b;
  }));
}

function applyFilters() {
  const mode = document.getElementById('f-mode').value;
  const year = document.getElementById('f-year').value;
  const site = document.getElementById('f-site').value.trim().toLowerCase();
  state.filtered = state.dives.filter(d => {
    if (state.trip !== 'all' && d.trip !== state.trip) return false;
    if (mode === 'opencircuit' && !isScuba(d)) return false;
    if (mode === 'other' && isScuba(d)) return false;
    if (year !== 'all' && !d.date.startsWith(year)) return false;
    if (site && !(d.site || '').toLowerCase().includes(site)) return false;
    return true;
  });
  renderStats(); renderTable(); renderMap();
  // keep the current selection if it is still listed, otherwise open on the newest
  // scuba dive that has a depth profile (the most useful thing to look at)
  const keep = state.filtered.find(d => d.id === state.selected);
  const pick = keep || state.filtered.find(d => counted(d) && d.profile) || state.filtered[0];
  if (pick) selectDive(pick.id, { pan: false });
  else clearDetail();
}

function renderStats() {
  const all = state.filtered;
  const ds = all.filter(counted);
  const free = all.filter(d => !isScuba(d)).length;
  const mins = ds.reduce((s, d) => s + (d.duration_min || 0), 0);
  const deepest = ds.reduce((a, d) => d.max_depth_m > (a?.max_depth_m ?? -1) ? d : a, null);
  const depths = ds.filter(d => d.max_depth_m != null).map(d => d.max_depth_m);
  const avg = depths.length ? (depths.reduce((a, b) => a + b, 0) / depths.length).toFixed(1) : null;
  const temps = ds.map(d => d.water_temp_c).filter(t => t != null);
  const nitrox = ds.filter(isNitrox).length;
  const cards = [
    [ds.length, 'scuba dives', free ? `plus ${free} freedive${free === 1 ? '' : 's'}` : ''],
    [fmt.time(Math.round(mins)), 'bottom time', ds.length ? `avg ${Math.round(mins / ds.length)} min a dive` : ''],
    [fmt.n(deepest?.max_depth_m, ' m'), 'deepest', deepest ? `${fmt.date(deepest.date)} · ${deepest.site || ''}` : ''],
    [fmt.n(avg, ' m'), 'average max depth', ''],
    [temps.length ? `${Math.min(...temps)}–${Math.max(...temps)} °C` : '—', 'water temperature', temps.length ? `${temps.length} dives with a reading` : 'none recorded'],
    [ds.length ? `${nitrox} of ${ds.length}` : '—', 'on nitrox', ''],
  ];
  document.getElementById('stat-cards').innerHTML =
    cards.map(([v, l, s]) => `<div class="stat"><div class="v">${esc(v)}</div><div class="l">${l}</div>${s ? `<div class="s">${esc(s)}</div>` : ''}</div>`).join('');
  const flagged = all.filter(d => d.suspect).length;
  document.getElementById('count').textContent =
    `${all.length} record${all.length === 1 ? '' : 's'}${flagged ? ` · ${flagged} flagged and left out of totals` : ''}`;
}

function renderTable() {
  const tb = document.querySelector('#dive-table tbody');
  tb.innerHTML = '';
  for (const d of state.filtered) {                       // already newest first
    const tr = document.createElement('tr');
    tr.dataset.id = d.id;
    tr.tabIndex = 0;
    if (d.suspect) tr.classList.add('flagged');
    if (state.selected === d.id) tr.classList.add('active');
    const num = state.numbered.get(d.id);
    tr.innerHTML = `
      <td>${num ?? '—'}</td>
      <td>${fmt.date(d.date)}${d.time ? ' ' + esc(d.time) : ''}</td>
      <td>${esc(d.site) || '—'} <span class="badge src">${srcLabel(d)}</span>${d.suspect ? ' <span class="badge warn">flagged</span>' : ''}</td>
      <td>${fmt.n(d.max_depth_m, ' m')}</td>
      <td>${fmt.time(d.duration_min)}</td>
      <td>${fmt.n(d.water_temp_c, '°')}</td>
      <td>${isNitrox(d) ? `<span class="nitrox-badge">${Math.round(d.gas.o2 * 100)}</span>` : ''}</td>
      <td>${isScuba(d) ? '' : '<span class="badge src">freedive</span>'}</td>`;
    tr.addEventListener('click', () => onRowActivate(d.id));
    tr.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRowActivate(d.id); }
    });
    tb.appendChild(tr);
  }
}

function onRowActivate(id) {
  if (state.selected === id) fitMap();                    // click the selected row again to zoom back out
  else selectDive(id, { pan: true });
}

// ------------------------------------------------------------------ map ----
let map, clusterLayer, pulseLayer;

// Diver-down flag: red with a white diagonal stripe (amber for freedive-only spots), on a pole.
// Count badge shows when a spot has more than one dive.
function flagSvg(n, scuba, k = 1) {
  const field = scuba ? '#d62828' : '#b45f17';
  const badge = n > 1
    ? `<circle cx="29" cy="7" r="7" fill="#0b2545" stroke="#fff" stroke-width="1.2"/>` +
      `<text x="29" y="10.2" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="system-ui,sans-serif">${n}</text>`
    : '';
  return `<svg viewBox="0 0 36 38" width="${36 * k}" height="${38 * k}" aria-hidden="true">` +
    `<line x1="4" y1="2" x2="4" y2="38" stroke="#0b2545" stroke-width="2.5" stroke-linecap="round"/>` +
    `<rect x="5" y="3" width="22" height="16" rx="1.5" fill="${field}" stroke="#fff" stroke-width="1.2"/>` +
    `<polygon points="5,3 8.5,3 27,16.45 27,19 23.5,19 5,5.55" fill="#fff"/>` +
    badge + `</svg>`;
}


function sitePoints() {
  const bySite = {};
  for (const d of state.filtered) {
    if (!hasPos(d) || d.suspect) continue;
    const k = d.site || `${d.lat},${d.lon}`;
    (bySite[k] ||= { lat: d.lat, lon: d.lon, dives: 0, max: 0, name: d.site || k, scuba: false });
    bySite[k].dives++;
    bySite[k].max = Math.max(bySite[k].max, d.max_depth_m || 0);
    bySite[k].scuba ||= isScuba(d);
  }
  return Object.values(bySite);
}

function fitMap() {
  const pts = sitePoints();
  if (!pts.length) return;
  if (pts.length === 1) map.setView([pts[0].lat, pts[0].lon], 13);
  else map.fitBounds(pts.map(s => [s.lat, s.lon]), { padding: [30, 30], maxZoom: 11 });
}

function renderMap() {
  if (typeof L === 'undefined') {
    document.getElementById('map-note').textContent = 'Map library did not load (offline?).';
    return;
  }
  if (!map) {
    map = L.map('map', { scrollWheelZoom: true });
    const osm = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    // OpenStreetMap needs no key (fair-use policy, fine for a personal log). If you later want
    // CARTO tiles, they now need a free key: https://www.carto.com/basemaps/apikey/
    const base = {
      'Streets (OpenStreetMap)': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: osm, maxZoom: 19 }),
      'Terrain (OpenTopoMap)': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        { attribution: osm + ' &copy; <a href="https://opentopomap.org">OpenTopoMap</a>', subdomains: 'abc', maxZoom: 17 }),
    };
    base['Streets (OpenStreetMap)'].addTo(map);
    const seamarks = L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png',
      { attribution: '&copy; <a href="https://www.openseamap.org">OpenSeaMap</a> contributors', maxZoom: 18 });
    L.control.layers(base, { 'Seamarks (OpenSeaMap)': seamarks }, { collapsed: true }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    // One cluster group: dives that are close together on screen merge into a single flag with a count,
    // and split apart as you zoom in. Falls back to plain markers if the plugin did not load.
    clusterLayer = L.markerClusterGroup
      ? L.markerClusterGroup({
          maxClusterRadius: 60,            // pixels: how close two flags must be to merge
          showCoverageOnHover: false,
          iconCreateFunction: c => L.divIcon({
            className: 'site-dot',
            html: flagSvg(c.getChildCount(), c.getAllChildMarkers().some(m => m.options.scuba)),
            iconSize: [36, 38], iconAnchor: [4, 38],     // pole foot on the cluster centre
          }),
        })
      : L.layerGroup();
    clusterLayer.addTo(map);
    // hovering a cluster lists what is inside it: the area, then each site with its dive count
    clusterLayer.on('clustermouseover', e => {
      const kids = e.layer.getAllChildMarkers();
      const areas = [...new Set(kids.map(m => m.options.area).filter(Boolean))];
      const sites = {};
      kids.forEach(m => { const n = m.options.site || 'Unnamed site'; sites[n] = (sites[n] || 0) + 1; });
      const lines = Object.entries(sites).sort((a, b) => b[1] - a[1]).map(([n, c]) => `${esc(n)} ×${c}`);
      const head = areas.length ? `<b>${esc(areas.join(' · '))}</b><br>` : '';
      e.layer.bindTooltip(`${head}${kids.length} dives<br>${lines.join('<br>')}`,
        { direction: 'top', offset: [10, -30] }).openTooltip();
    });
    pulseLayer = L.layerGroup().addTo(map);
  }

  clusterLayer.clearLayers();

  for (const d of state.filtered) {
    if (!hasPos(d) || d.suspect) continue;
    const k = 0.75;                                          // single-dive flags are a little smaller than cluster flags
    const icon = L.divIcon({
      className: 'site-dot',
      html: flagSvg(1, isScuba(d), k),
      iconSize: [36 * k, 38 * k],
      iconAnchor: [4 * k, 38 * k],                             // pole foot sits on the dive position
      popupAnchor: [10 * k, -34 * k],
    });
    L.marker([d.lat, d.lon], { icon, keyboard: false, scuba: isScuba(d), site: d.site, area: d.area })
      .bindPopup(`<b>${esc(d.site) || 'Unnamed site'}</b><br>${fmt.date(d.date)} · ${fmt.n(d.max_depth_m, ' m')} · ${fmt.time(d.duration_min)}`)
      .addTo(clusterLayer)
      .on('click', () => selectDive(d.id, { pan: false }));
  }
  fitMap();

  const missing = state.filtered.filter(d => !hasPos(d) && !d.suspect);
  const names = [...new Set(missing.map(d => d.site).filter(Boolean))];
  document.getElementById('map-note').textContent = missing.length
    ? `${missing.length} dive${missing.length === 1 ? '' : 's'} not on the map: no position for ${names.join(', ') || 'unnamed site'}. Add it in data/site_coords.json.`
    : '';
}

// --------------------------------------------------------------- detail ----
function clearDetail() {
  state.selected = null;
  document.getElementById('detail').innerHTML = '<h3>No dives match these filters</h3>';
  const prof = document.getElementById('profile');
  if (typeof Plotly !== 'undefined') Plotly.purge(prof);
  prof.innerHTML = '';
}

function selectDive(id, opts = {}) {
  const d = state.dives.find(x => x.id === id);
  if (!d) return;
  state.selected = id;
  document.querySelectorAll('#dive-table tbody tr').forEach(tr => {
    const on = tr.dataset.id === id;
    tr.classList.toggle('active', on);
    tr.setAttribute('aria-selected', String(on));
  });

  // profile
  const prof = document.getElementById('profile');
  const lim = (d.duration_min || Infinity) * 60 + 60;           // Oceanic+ samples run past the end of the dive
  const pts = (d.profile || []).filter(p => p[0] <= lim);
  const num = state.numbered.get(id);
  const label = num ? `Dive #${num}` : 'Dive';
  if (typeof Plotly !== 'undefined') Plotly.purge(prof);
  if (pts.length > 2 && typeof Plotly !== 'undefined') {
    prof.innerHTML = '';
    Plotly.newPlot(prof, [{
      x: pts.map(p => p[0] / 60), y: pts.map(p => p[1]),
      mode: 'lines', line: { color: '#0e7c7b', width: 2 }, fill: 'tozeroy', name: 'depth',
    }], {
      margin: { t: 30, r: 16, b: 36, l: 44 },
      xaxis: { title: 'time (min)' },
      yaxis: { title: 'depth (m)', autorange: 'reversed' },
      title: { text: `${label} profile`, font: { size: 14 } },
    }, { displayModeBar: false, responsive: true });
  } else {
    const why = d.sources[0] === 'padi' && d.sources.length === 1
      ? 'PADI logbook entries have no depth profile.'
      : 'No depth profile recorded for this dive.';
    prof.innerHTML = `<div style="padding:20px;min-height:260px;box-sizing:border-box;opacity:.6;font-size:.9rem">${why}</div>`;
  }

  // details
  const gas = d.gas
    ? (isNitrox(d) ? `Nitrox ${Math.round(d.gas.o2 * 100)}%` : d.gas.assumed ? 'Air (assumed)' : 'Air')
    : '—';
  const rows = [
    ['Site', esc(d.site)],
    ['Date', fmt.date(d.date) + (d.time ? ' · ' + esc(d.time) : '')],
    ['Max depth', fmt.n(d.max_depth_m, ' m')], ['Duration', fmt.time(d.duration_min)],
    ['Water temp', d.water_temp_c != null ? fmt.n(d.water_temp_c, ' °C') : ''],
    ['Gas', isScuba(d) ? gas : ''],
    ['Mode', isScuba(d) ? 'Scuba (open circuit)' : 'Snorkel / freedive'],
    ['Rating', d.rating ? '★'.repeat(d.rating) : ''],
    ['Title', esc(d.title)], ['Dive type', esc(d.dive_type)], ['Buddies', esc(d.buddies)],
    ['Dive center', esc(d.dive_center)], ['Visibility', esc(d.visibility)],
    ['Weight', d.weight != null ? fmt.n(d.weight, ' kg') : ''], ['Suit', esc(d.suit)],
    ['Position', hasPos(d) ? `${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}` : 'not on the map'],
    ['Sources', d.sources.map(s => s === 'padi' ? 'PADI' : 'Oceanic+').join(' + ')],
    ['Flag', d.suspect ? 'Under 5 minutes, left out of totals' : ''],
    ['Notes', esc(d.notes)],
  ].filter(([k, v]) => v != null && v !== '');

  document.getElementById('detail').innerHTML =
    `<h3>${label}${d.title ? ' — ' + esc(d.title) : ''}</h3><dl>` +
    rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('') + '</dl>';

  if (map && pulseLayer) {                                  // a pulsing ring marks the selected dive
    pulseLayer.clearLayers();
    if (hasPos(d)) {
      L.marker([d.lat, d.lon], {
        icon: L.divIcon({ className: 'pulse', html: '<i></i>', iconSize: [44, 44] }),
        interactive: false, keyboard: false, zIndexOffset: -100,
      }).addTo(pulseLayer);
    }
  }
  if (opts.pan && map && hasPos(d)) map.flyTo([d.lat, d.lon], Math.max(map.getZoom(), 13), { duration: 1.2 });
}

init().catch(e => document.body.innerHTML = `<pre style="padding:24px">Failed to load data/merged_log.json\n${esc(e)}</pre>`);
