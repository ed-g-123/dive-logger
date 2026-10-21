const state = { dives: [], filtered: [], selected: null, trip: 'all', trips: [], numbered: new Map(),
                divers: [], diver: 'all', groups: new Map() };

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
const SRC = { padi: 'PADI', oceanic: 'Oceanic+', shearwater: 'Shearwater' };
const srcLabel = d => d.sources.length > 1 ? 'merged' : (SRC[d.sources[0]] || d.sources[0]);
const diverOf = id => state.divers.find(x => x.id === id) || { id, label: id, colour: '#0e7c7b' };
const colourOf = d => diverOf(d.diver).colour;
const mates = d => d.group ? state.dives.filter(x => x.group === d.group && x.id !== d.id) : [];
const timeLabel = d => d.time ? d.time + (d.time_basis === 'utc' ? ' UTC' : '') : '';
const byTime = (a, b) => (a.date || '').localeCompare(b.date || '')
  || (a.time || '').localeCompare(b.time || '')
  || String(a.id).localeCompare(String(b.id));

async function init() {
  const res = await fetch('data/merged_log.json');
  const data = await res.json();
  const asc = data.dives.slice().sort(byTime);
  state.divers = data.divers || [];
  const seen = {};
  for (const d of asc) if (counted(d)) state.numbered.set(d.id, seen[d.diver] = (seen[d.diver] || 0) + 1);   // numbers run per diver
  state.dives = asc.reverse();                                          // newest first
  state.trips = data.trips || [];
  buildDiverSwitch();

  const years = [...new Set(state.dives.map(d => d.date.slice(0, 4)))].sort().reverse();
  for (const y of years) {
    const o = document.createElement('option'); o.value = y; o.textContent = y;
    document.getElementById('f-year').appendChild(o);
  }
  buildTripChips();
  ['f-mode', 'f-year', 'f-site'].forEach(id => document.getElementById(id).addEventListener('input', applyFilters));
  applyFilters();
}

function buildDiverSwitch() {
  const el = document.getElementById('divers');
  if (state.divers.length < 2) { el.hidden = true; return; }       // one diver: no switch needed
  const opts = [{ id: 'all', label: 'All divers', colour: '#0b2545' }].concat(state.divers);
  el.replaceChildren(...opts.map(v => {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = v.id === 'all' ? esc(v.label) : `<i style="background:${esc(v.colour)}"></i>${esc(v.label)}`;
    b.setAttribute('aria-pressed', String(v.id === state.diver));
    b.addEventListener('click', () => {
      state.diver = v.id;
      [...el.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      buildTripChips();
      applyFilters();
    });
    return b;
  }));
}

const inDiver = d => state.diver === 'all' || d.diver === state.diver;

function buildTripChips() {
  const el = document.getElementById('trips');
  const mine = state.dives.filter(inDiver);
  const trips = state.trips.filter(t => mine.some(d => d.trip === t.id));
  if (state.trip !== 'all' && !trips.some(t => t.id === state.trip)) state.trip = 'all';
  const list = [{ id: 'all', label: 'All trips', n: mine.filter(counted).length }]
    .concat(trips.slice().reverse().map(t => ({ ...t, n: mine.filter(d => d.trip === t.id && counted(d)).length })));
  el.replaceChildren(...list.map(t => {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = `${esc(t.label)}<small>${t.n}</small>`;
    if (t.start) b.title = t.start === t.end ? fmt.date(t.start) : `${fmt.date(t.start)} – ${fmt.date(t.end)}`;
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
    if (!inDiver(d)) return false;
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
  const split = state.diver === 'all' && state.divers.length > 1
    ? state.divers.map(v => `${v.label} ${ds.filter(d => d.diver === v.id).length}`).join(' · ') : '';
  const together = new Set(ds.filter(d => d.group).map(d => d.group)).size;
  const cards = [
    [ds.length, 'scuba dives', [split, together && state.diver === 'all' ? `${together} together` : '',
                                free ? `plus ${free} freedive${free === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ')],
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
      <td>${fmt.date(d.date)}${d.time ? ' ' + esc(timeLabel(d)) : ''}</td>
      <td>${state.diver === 'all' && state.divers.length > 1 ? `<span class="diver-chip" style="background:${esc(colourOf(d))}">${esc(diverOf(d.diver).label)}</span> ` : ''} ${d.group ? `<span class="badge together" title="Dived together with ${esc(mates(d).map(m => diverOf(m.diver).label).join(', '))}">🤗</span> ` : ''} ${esc(d.site) || '—'} ${d.suspect ? ' <span class="badge warn">flagged</span>' : ''}</td>
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
  else {
    selectDive(id, { pan: true });
    // on a phone the details sit below the list, so bring them into view
    if (window.matchMedia('(max-width: 980px)').matches)
      document.getElementById('right').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// ------------------------------------------------------------------ map ----
let map, clusterLayer, pulseLayer;

// Diver-down flag: red with a white diagonal stripe (amber for freedive-only spots), on a pole.
// Count badge shows when a spot has more than one dive.
// A small round button beside the pole shows who dived: one diver's colour, or equal slices (half and half
// for two divers) when more than one diver is involved. Nothing is drawn when the log has one diver.
function diverButton(cols) {
  if (!cols.length) return '';
  const cx = 12, cy = 28.5, r = 5.2;
  const ring = `stroke="#fff" stroke-width="1.4"`;
  if (cols.length === 1) return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${cols[0]}" ${ring}/>`;
  const pt = a => `${(cx + r * Math.sin(a)).toFixed(2)} ${(cy - r * Math.cos(a)).toFixed(2)}`;
  const slices = cols.map((c, i) => {
    const a0 = (2 * Math.PI * i) / cols.length + Math.PI;   // first slice is the left half
    const a1 = (2 * Math.PI * (i + 1)) / cols.length + Math.PI;
    return `<path d="M${cx} ${cy} L${pt(a0)} A${r} ${r} 0 0 1 ${pt(a1)} Z" fill="${c}"/>`;
  }).join('');
  return slices + `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" ${ring}/>`;
}

const colsFor = ids => state.divers.length > 1
  ? state.divers.filter(v => ids.includes(v.id)).map(v => v.colour) : [];

function flagSvg(n, scuba, k = 1, cols = []) {
  const field = scuba ? '#d62828' : '#b45f17';
  const badge = n > 1
    ? `<circle cx="29" cy="7" r="7" fill="#0b2545" stroke="#fff" stroke-width="1.2"/>` +
      `<text x="29" y="10.2" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="system-ui,sans-serif">${n}</text>`
    : '';
  return `<svg viewBox="0 0 36 38" width="${36 * k}" height="${38 * k}" aria-hidden="true">` +
    `<line x1="4" y1="2" x2="4" y2="38" stroke="#0b2545" stroke-width="2.5" stroke-linecap="round"/>` +
    `<rect x="5" y="3" width="22" height="16" rx="1.5" fill="${field}" stroke="#fff" stroke-width="1.2"/>` +
    `<polygon points="5,3 8.5,3 27,16.45 27,19 23.5,19 5,5.55" fill="#fff"/>` +
    badge + diverButton(cols) + `</svg>`;
}


// A shared dive is two records; it is drawn once on the map (the first one in the current list).
function mapDives() {
  const done = new Set();
  return state.filtered.filter(d => {
    if (!hasPos(d) || d.suspect) return false;
    if (!d.group) return true;
    if (done.has(d.group)) return false;
    done.add(d.group);
    return true;
  });
}

function sitePoints() {
  const bySite = {};
  for (const d of mapDives()) {
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
    // worldCopyJump: when you pan across the date line the view jumps back to the main copy of the world,
    // so the flags are always visible instead of being left behind on the first copy.
    map = L.map('map', { scrollWheelZoom: true, worldCopyJump: true });
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
            html: flagSvg(c.getChildCount(), c.getAllChildMarkers().some(m => m.options.scuba), 1,
                          colsFor([...new Set(c.getAllChildMarkers().flatMap(m => m.options.divers || []))])),
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

  for (const d of mapDives()) {
    const who = [d, ...mates(d)].filter(inDiver).map(x => x.diver);   // everyone on this flag, within the diver filter
    const k = 0.75;                                          // single-dive flags are a little smaller than cluster flags
    const icon = L.divIcon({
      className: 'site-dot',
      html: flagSvg(1, isScuba(d), k, colsFor(who)),
      iconSize: [36 * k, 38 * k],
      iconAnchor: [4 * k, 38 * k],                             // pole foot sits on the dive position
      popupAnchor: [10 * k, -34 * k],
    });
    L.marker([d.lat, d.lon], { icon, keyboard: false, scuba: isScuba(d), site: d.site, area: d.area, divers: who })
      .bindPopup(`<b>${esc(d.site) || 'Unnamed site'}</b><br>${fmt.date(d.date)} · ${fmt.n(d.max_depth_m, ' m')} · ${fmt.time(d.duration_min)}` +
        (state.divers.length > 1 ? `<br>${[d, ...mates(d).filter(inDiver)].map(x => esc(diverOf(x.diver).label)).join(' + ')}` : ''))
      .addTo(clusterLayer)
      .on('click', () => selectDive(d.id, { pan: false }));
  }
  fitMap();

  const missing = state.filtered.filter(d => !hasPos(d) && !d.suspect && !mates(d).some(m => hasPos(m)));
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
  const label = (state.divers.length > 1 ? diverOf(d.diver).label + ' ' : '') + (num ? `dive #${num}` : 'dive');
  const trace = (x, name) => {
    const lm = (x.duration_min || Infinity) * 60 + 60;
    const q = (x.profile || []).filter(p => p[0] <= lm);
    return q.length > 2 ? { x: q.map(p => p[0] / 60), y: q.map(p => p[1]), mode: 'lines', name,
                           line: { color: colourOf(x), width: 2 } } : null;
  };
  const traces = [trace(d, diverOf(d.diver).label)].concat(mates(d).map(m => trace(m, diverOf(m.diver).label))).filter(Boolean);
  if (traces.length) traces[0].fill = 'tozeroy';
  if (typeof Plotly !== 'undefined') Plotly.purge(prof);
  if (pts.length > 2 && typeof Plotly !== 'undefined') {
    prof.innerHTML = '';
    Plotly.newPlot(prof, traces, {
      margin: { t: 30, r: 16, b: 36, l: 44 },
      xaxis: { title: 'time (min)' },
      yaxis: { title: 'depth (m)', autorange: 'reversed' },
      title: { text: `${label} profile${traces.length > 1 ? ' (shared dive)' : ''}`, font: { size: 14 } },
      showlegend: traces.length > 1, legend: { orientation: 'h', y: 1.12, x: 1, xanchor: 'right' },
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
    ['Diver', state.divers.length > 1 ? esc(diverOf(d.diver).label) : ''],
    ['Together', mates(d).map(m => esc(diverOf(m.diver).label)).join(', ')],
    ['Site', esc(d.site)],
    ['Date', fmt.date(d.date) + (d.time ? ' · ' + esc(timeLabel(d)) : '')],
    ['Max depth', fmt.n(d.max_depth_m, ' m')], ['Duration', fmt.time(d.duration_min)],
    ['Water temp', d.water_temp_c != null ? fmt.n(d.water_temp_c, ' °C') : ''],
    ['Gas', isScuba(d) ? gas : ''],
    ['Mode', isScuba(d) ? 'Scuba (open circuit)' : 'Snorkel / freedive'],
    ['Rating', d.rating ? '★'.repeat(d.rating) : ''],
    ['Title', esc(d.title)], ['Dive type', esc(d.dive_type)], ['Buddies', esc(d.buddies)],
    ['Dive center', esc(d.dive_center)], ['Visibility', esc(d.visibility)],
    ['Weight', d.weight != null ? fmt.n(d.weight, ' kg') : ''], ['Suit', esc(d.suit)],
    ['Position', hasPos(d) ? `${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}` : 'not on the map'],
    ['Sources', d.sources.map(s => SRC[s] || s).join(' + ')],
    ['Flag', d.suspect ? 'Under 5 minutes, left out of totals' : ''],
    ['Notes', esc(d.notes)],
  ].filter(([k, v]) => v != null && v !== '');

  document.getElementById('detail').innerHTML =
    `<h3>${label[0].toUpperCase() + label.slice(1)}${d.title ? ' — ' + esc(d.title) : ''}</h3><dl>` +
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
