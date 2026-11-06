const CANDIDATES = window.DUPLICATE_SWEEP_TOP50 || [];

const STORAGE_KEY = 'crate-review-decisions-v3-post-2026-11-06';
const THEME_KEY = 'crate-review-theme-v2';
const THEME_MODES = ['system', 'light', 'dark'];
const THEME_ICONS = { system: '◐', light: '☀', dark: '☾' };
const systemLight = matchMedia('(prefers-color-scheme: light)');
let decisions = readStored();
let activeFilter = 'all';
let toastTimer;
let activeAudio = null;

function readStored() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
  catch { return {}; }
}
function saveStored() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions));
  document.querySelector('#save-status').textContent = 'Saved in this browser';
  updateSummary();
}

function middleTrim(path, max = 48) {
  if (path.length <= max) return path;
  const keep = Math.floor((max - 1) / 2);
  return `${path.slice(0, keep)}…${path.slice(-(max - keep - 1))}`;
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function localAudioUrl(path) {
  return `file://${path.split('/').map(encodeURIComponent).join('/')}`;
}
function manualPlaylistCount(track) {
  if (Array.isArray(track.manualPlaylists)) return track.manualPlaylists.length;
  return Number((track.playlists || '').match(/(\d+) manual/)?.[1] || 0);
}
function cueScore(track) {
  const match = (track.cues || '').match(/H(\d+)\s+M(\d+)\s+L(\d+)/i);
  return match ? Number(match[1]) + Number(match[2]) + Number(match[3]) : 0;
}
function compareScore(a, b) {
  const fields = [
    [Number.parseInt(a.quality, 10) || 0, Number.parseInt(b.quality, 10) || 0],
    [cueScore(a), cueScore(b)]
  ];
  let wins = 0, losses = 0;
  for (const [left, right] of fields) {
    if (left > right) wins++;
    else if (left < right) losses++;
  }
  return { wins, losses };
}
function recommendedChoice(candidate) {
  if (candidate.sweepEvidence && ['a', 'b'].includes(candidate.recommended)) return candidate.recommended;
  const [a, b] = candidate.tracks;
  const aManual = manualPlaylistCount(a), bManual = manualPlaylistCount(b);
  const score = compareScore(a, b);
  if (candidate.matchType === 'exact') {
    if (aManual && bManual) return 'both';
    if (aManual) return 'a';
    if (bManual) return 'b';
    if (score.wins > 0 && score.losses === 0) return 'a';
    if (score.losses > 0 && score.wins === 0) return 'b';
    return candidate.recommended || 'a';
  }
  if (score.wins > 0 && score.losses === 0 && !bManual) return 'a';
  if (score.losses > 0 && score.wins === 0 && !aManual) return 'b';
  return candidate.recommended || 'both';
}
function getDecision(id) {
  const candidate = CANDIDATES.find(c => c.id === id);
  return decisions[id] || { choice: recommendedChoice(candidate), confirmed: false };
}

function keepState(choice) {
  return choice === 'both' ? [true, true] : choice === 'a' ? [true, false] : choice === 'b' ? [false, true] : [false, false];
}

function choiceFromKeeps(keep) {
  return keep[0] && keep[1] ? 'both' : keep[0] ? 'a' : keep[1] ? 'b' : 'skip';
}

function cueDescription(cue) {
  const time = `${Math.floor(cue.start / 60)}:${String(Math.floor(cue.start % 60)).padStart(2, '0')}.${String(Math.round((cue.start % 1) * 10))}`;
  if (cue.kind === 'hot') return `Hot cue ${cue.slot} · ${time}`;
  if (cue.kind === 'memory') return `${cue.name || 'Memory cue'} · ${time}`;
  const end = cue.end == null ? '' : `–${Math.floor(cue.end / 60)}:${String(Math.floor(cue.end % 60)).padStart(2, '0')}`;
  return `Loop · ${time}${end}`;
}

function formatStamp(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

function waveformSvg(track, candidate, index) {
  const visual = window.TRACK_VISUALS?.[track.path];
  if (!visual) return '<div class="waveform-missing">No waveform data</div>';
  const width = 600, height = 42, duration = visual.duration || track.seconds || 1;
  const bars = visual.peaks ? Array.from(visual.peaks, (digit, i) => {
    const amplitude = parseInt(digit, 36) / 35;
    const barHeight = 2 + amplitude * 31;
    const step = width / visual.peaks.length;
    return `<rect class="wave-bar" x="${(i * step).toFixed(2)}" y="${((height - barHeight) / 2).toFixed(2)}" width="${Math.max(.65, step * .72).toFixed(2)}" height="${barHeight.toFixed(2)}" rx=".4"/>`;
  }).join('') : '';
  const cueMarks = (visual.cues || []).map((cue, cueIndex) => {
    const x = Math.min(width, Math.max(0, cue.start / duration * width));
    const title = esc(cueDescription(cue));
    if (cue.kind === 'loop') {
      const endX = cue.end == null ? x + 4 : Math.min(width, cue.end / duration * width);
      return `<g class="cue-loop"><title>${title}</title><rect x="${x.toFixed(2)}" y="2" width="${Math.max(1, endX - x).toFixed(2)}" height="38"/><line x1="${x.toFixed(2)}" y1="2" x2="${x.toFixed(2)}" y2="40"/><line x1="${endX.toFixed(2)}" y1="2" x2="${endX.toFixed(2)}" y2="40"/></g>`;
    }
    const kindClass = cue.kind === 'hot' ? 'cue-hot' : 'cue-memory';
    const label = cue.kind === 'hot' ? cue.slot : 'M';
    const shape = cue.kind === 'hot'
      ? `<path d="M${x.toFixed(2)} 1 l6 7 h-12 z"/>`
      : `<path d="M${x.toFixed(2)} 0 l5 5 -5 5 -5 -5 z"/>`;
    return `<g class="${kindClass}"><title>${title}</title>${shape}<line x1="${x.toFixed(2)}" y1="2" x2="${x.toFixed(2)}" y2="40"/><text x="${x.toFixed(2)}" y="15" text-anchor="middle">${label}</text></g>`;
  }).join('');
  const missing = !visual.peaks;
  return `<svg class="waveform ${missing ? 'no-audio' : ''}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(candidate.artist)} ${esc(candidate.title)} waveform and Rekordbox cue positions, track ${index + 1}"><title>Audio-derived waveform · Rekordbox cue positions</title><line class="wave-center" x1="0" y1="21" x2="600" y2="21"/>${bars}${cueMarks}${missing ? '<text class="wave-missing-text" x="300" y="26" text-anchor="middle">Audio file unavailable</text>' : ''}</svg><div class="wave-time"><span>0:00</span><span>${formatStamp(duration)}</span></div>`;
}

function displayValue(track, field) {
  const visual = window.TRACK_VISUALS?.[track.path];
  if (field === 'quality') return track.quality || '—';
  if (field === 'length') {
    const seconds = Number(visual?.duration || track.seconds || 0);
    return seconds ? formatStamp(seconds) : '—';
  }
  if (field === 'key') return track.key || '—';
  if (field === 'bpm') return track.bpm ? `${Number(track.bpm).toFixed(2)} BPM` : '—';
  if (field === 'cues') return track.cues || `${(visual?.cues || []).length} marks`;
  if (field === 'playlists') {
    const match = (track.playlists || '').match(/(\d+) manual \/ (\d+) smart/);
    return match ? `${match[1]}M · ${match[2]}S` : track.playlists || '—';
  }
  return '—';
}

function valuesDiffer(candidate, field) {
  const [a, b] = candidate.tracks;
  if (field === 'cues') {
    const cues = track => (window.TRACK_VISUALS?.[track.path]?.cues || []).map(c => `${c.kind}:${c.slot}:${c.start.toFixed(2)}:${c.end?.toFixed(2) || ''}`).sort().join('|');
    return cues(a) !== cues(b);
  }
  if (field === 'playlists') {
    return a.playlists !== b.playlists || JSON.stringify(a.manualPlaylists || []) !== JSON.stringify(b.manualPlaylists || []);
  }
  return displayValue(a, field) !== displayValue(b, field);
}

function renderValues(candidate, index) {
  const track = candidate.tracks[index];
  const other = candidate.tracks[1 - index];
  const fields = [
    ['quality', 'quality'], ['length', 'length'], ['key', 'key'],
    ['bpm', 'bpm'], ['cues', 'cues'], ['playlists', 'playlists']
  ];
  return fields.map(([field, label]) => {
    const value = displayValue(track, field);
    const different = valuesDiffer(candidate, field);
    const warning = field === 'quality' && Number.parseInt(track.quality, 10) < 256;
    let preference = '';
    if (different && field === 'quality') {
      const quality = Number.parseInt(track.quality, 10) || 0;
      const otherQuality = Number.parseInt(other.quality, 10) || 0;
      preference = quality > otherQuality ? 'is-better' : quality < otherQuality ? 'is-worse' : '';
    }
    const full = field === 'playlists' ? `${track.manualPlaylists?.length || 0} manual: ${(track.manualPlaylists || []).join(', ') || 'none'}; ${track.smartPlaylists || 0} smart` : value;
    const abbreviations = { quality: 'Q', length: 'LEN', key: 'KEY', bpm: 'BPM', cues: 'CUE', playlists: 'LIST' };
    return `<span class="track-value ${different ? 'is-delta' : 'is-shared'} ${preference} ${warning ? 'is-warning' : ''}" title="${esc(label)}: ${esc(full)}"><small>${abbreviations[field]}</small><strong>${esc(value)}</strong></span>`;
  }).join('');
}

function hasSharedProperties(candidate) {
  return ['quality', 'length', 'key', 'bpm', 'cues', 'playlists'].some(field => !valuesDiffer(candidate, field));
}

function renderCard(candidate) {
  const state = getDecision(candidate.id);
  const locked = state.confirmed;
  const keep = keepState(state.choice);
  const suggestion = candidate.options.find(option => option.id === recommendedChoice(candidate))?.label || 'Review';
  const trackHTML = candidate.tracks.map((track, index) => `
    <div class="track-row ${!keep[index] && locked ? 'is-deleting' : ''}">
      <div class="track-identity">
        <div class="track-file ${!keep[index] && locked ? 'is-deleting-title' : ''}" title="${esc(track.path)}">${esc(track.name)}</div>
        <div class="track-source">
          ${track.path.includes('/Media.localized/Music/') ? '<span class="apple-music-icon" title="Apple Music library">♫</span>' : ''}
          <span class="track-label">${esc(track.album)}</span>
          ${track.path.includes('/Media.localized/Music/') ? '' : `<span class="track-path" title="${esc(track.path)}">${esc(middleTrim(track.path))}</span>`}
        </div>
      </div>
      <div class="waveform-wrap">
        <button class="audio-play" type="button" aria-label="Play ${esc(track.name)}" title="Play track"><span aria-hidden="true">▶</span></button>
        <div class="waveform-player">
          <div class="waveform-stage">
            ${waveformSvg(track, candidate, index)}
            <input class="wave-seek" type="range" min="0" max="${Number(track.seconds || 1)}" step="0.05" value="0" aria-label="Seek ${esc(track.name)}" aria-valuetext="0:00">
          </div>
          <audio class="track-audio" preload="none" src="${esc(localAudioUrl(track.path))}"></audio>
        </div>
      </div>
      <div class="track-values" aria-label="Track values in order: quality, length, key, BPM, cues, playlists; highlighted values differ">
        ${hasSharedProperties(candidate) ? '<button class="property-toggle" type="button" aria-label="Show matching properties" aria-expanded="false" title="Show matching properties"><span aria-hidden="true">‹</span></button>' : ''}
        ${renderValues(candidate, index)}
      </div>
      <button class="decision-switch ${keep[index] ? 'is-keep' : 'is-delete'}" type="button" role="switch" aria-checked="${keep[index]}" aria-label="${keep[index] ? 'Keep' : 'Delete'} ${esc(track.name)}" title="${keep[index] ? 'Keep this file' : 'Delete this file when processing approved choices'}" data-track-index="${index}" ${locked ? 'disabled' : ''}><span class="switch-thumb" aria-hidden="true">${keep[index] ? '<svg viewBox="0 0 16 16"><path d="m3.2 8.2 3.1 3.1 6.5-6.7"/></svg>' : '<svg viewBox="0 0 16 16"><path d="M3 4.5h10M6 4.5V3h4v1.5m2 0-.6 8H4.6L4 4.5m2.2 2v4.2m3.6-4.2v4.2"/></svg>'}</span></button>
    </div>`).join('');
  return `<article class="candidate-card" data-id="${candidate.id}">
    <div class="candidate-head">
      <div class="title-side"><span class="number">${candidate.id}</span><div class="title-copy"><h2>${esc(candidate.artist)} — ${esc(candidate.title)}</h2></div></div>
      <div class="card-controls"><div class="badges"><span class="badge ${candidate.matchType === 'exact' ? 'match-exact' : 'match-unknown'}">${candidate.match}</span><span class="badge suggestion-badge">Suggest · ${esc(suggestion)}</span>${(candidate.patternGroups || []).map(group => `<span class="badge pattern-badge" title="${esc(candidate.pattern || '')}">${esc(group)}</span>`).join('')}</div><label class="confirm-label" title="${locked ? 'Unlock this choice' : 'Lock this choice'}"><input class="confirm-checkbox" type="checkbox" aria-label="${locked ? 'Unlock choice' : 'Lock choice'}" ${locked ? 'checked' : ''}><span aria-hidden="true">${locked ? '🔒' : '🔓'}</span></label></div>
    </div>
    <div class="tracks">${trackHTML}</div>
  </article>`;
}

function render() {
  const list = document.querySelector('#candidate-list');
  const filtered = CANDIDATES.filter(candidate => activeFilter === 'all' || (activeFilter === 'approved' ? getDecision(candidate.id).confirmed : !getDecision(candidate.id).confirmed));
  list.innerHTML = filtered.length ? filtered.map(renderCard).join('') : `<div class="empty-state"><strong>${activeFilter === 'approved' ? 'No confirmed choices yet' : CANDIDATES.length ? 'All candidates are confirmed' : 'No candidate data loaded'}</strong>${activeFilter === 'approved' ? 'Confirm a selection to see it here.' : CANDIDATES.length ? 'Use the filters above to review your decisions.' : 'Generate a local review from a Rekordbox XML export.'}</div>`;
  list.querySelectorAll('.property-toggle').forEach(button => button.addEventListener('click', event => {
    const card = event.currentTarget.closest('.candidate-card');
    const expanded = card.classList.toggle('show-shared');
    card.querySelectorAll('.property-toggle').forEach(toggle => {
      toggle.setAttribute('aria-expanded', String(expanded));
      toggle.setAttribute('aria-label', expanded ? 'Hide matching properties' : 'Show matching properties');
      toggle.title = expanded ? 'Hide matching properties' : 'Show matching properties';
      toggle.querySelector('span').textContent = expanded ? '›' : '‹';
    });
  }));
  list.querySelectorAll('.track-row').forEach(row => {
    const audio = row.querySelector('.track-audio');
    const play = row.querySelector('.audio-play');
    const seek = row.querySelector('.wave-seek');
    const sync = () => {
      const duration = Number.isFinite(audio.duration) ? audio.duration : Number(seek.max);
      const current = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
      if (Number.isFinite(audio.duration) && audio.duration > 0) seek.max = String(audio.duration);
      seek.value = String(Math.min(current, duration || current));
      seek.setAttribute('aria-valuetext', `${formatStamp(current)} of ${formatStamp(duration || 0)}`);
      play.querySelector('span').textContent = audio.paused ? '▶' : 'Ⅱ';
      play.classList.toggle('is-playing', !audio.paused);
      play.setAttribute('aria-label', `${audio.paused ? 'Play' : 'Pause'} ${row.querySelector('.track-file').textContent}`);
      play.title = audio.paused ? 'Play track' : 'Pause track';
    };
    play.addEventListener('click', () => {
      if (!audio.paused) { audio.pause(); return; }
      const previous = activeAudio;
      activeAudio = audio;
      if (previous && previous !== audio) previous.pause();
      audio.play().catch(() => {
        if (activeAudio === audio) activeAudio = null;
        showToast('Could not play this audio file');
        sync();
      });
    });
    audio.addEventListener('play', sync);
    audio.addEventListener('pause', () => {
      if (activeAudio === audio) activeAudio = null;
      sync();
    });
    audio.addEventListener('timeupdate', sync);
    audio.addEventListener('loadedmetadata', sync);
    audio.addEventListener('durationchange', sync);
    audio.addEventListener('ended', sync);
    seek.addEventListener('input', () => {
      audio.currentTime = Number(seek.value);
      sync();
    });
  });
  list.querySelectorAll('.decision-switch').forEach(button => button.addEventListener('click', event => {
    const id = Number(event.currentTarget.closest('.candidate-card').dataset.id);
    const keep = keepState(getDecision(id).choice);
    keep[Number(event.currentTarget.dataset.trackIndex)] = !keep[Number(event.currentTarget.dataset.trackIndex)];
    decisions[id] = { choice: choiceFromKeeps(keep), confirmed: false };
    saveStored(); render();
  }));
  list.querySelectorAll('.confirm-checkbox').forEach(input => input.addEventListener('change', event => {
    const id = Number(event.target.closest('.candidate-card').dataset.id);
    const state = getDecision(id);
    if (event.target.checked && state.choice === 'skip') {
      showToast('Keep at least one track before locking this pair');
      render();
      return;
    }
    decisions[id] = { ...state, confirmed: event.target.checked };
    saveStored(); render();
    if (event.target.checked) showToast(`Choice ${id} confirmed and locked`);
  }));
  updateSummary();
}

function updateSummary() {
  const confirmed = CANDIDATES.filter(c => getDecision(c.id).confirmed).length;
  const total = CANDIDATES.length;
  document.querySelector('#progress-count').textContent = `${confirmed} of ${total}`;
  document.querySelector('#pending-count').textContent = String(total - confirmed);
  document.querySelector('#approved-count').textContent = String(confirmed);
  document.querySelector('#progress-bar').style.width = `${total ? confirmed / total * 100 : 0}%`;
  document.querySelector('#all-count').textContent = String(total);
  document.querySelector('#pending-filter-count').textContent = String(total - confirmed);
  document.querySelector('#approved-filter-count').textContent = String(confirmed);
  document.querySelector('#export-button').disabled = confirmed === 0;
}

function exportApproved() {
  const approved = CANDIDATES.filter(c => getDecision(c.id).confirmed && getDecision(c.id).choice !== 'skip').map(c => ({
    number: c.id,
    candidate: `${c.artist} — ${c.title}`,
    patternGroups: c.patternGroups || [],
    selectedOption: c.options.find(o => o.id === getDecision(c.id).choice)?.label || getDecision(c.id).choice,
    selectedOptionId: getDecision(c.id).choice,
    audioMatch: c.match,
    tracks: c.tracks.map((t, index) => {
      const keep = keepState(getDecision(c.id).choice)[index];
      return {
        decision: keep ? 'keep' : 'delete', path: t.path, trackId: t.trackId || null,
        quality: t.quality, rekordboxCues: t.cues, playlists: t.playlists,
        ...(keep ? {} : { processing: [
          { target: 'rekordbox', action: 'remove-from-collection' },
          { target: 'apple-music', action: 'remove-from-library-keep-file' },
          { target: 'file', action: 'move-to-trash' }
        ] })
      };
    })
  }));
  const payload = { format: 'crate-review-approvals', version: 2, createdAt: new Date().toISOString(), note: 'Approved decisions and requested processing steps. Exporting does not execute changes; process only when explicitly requested.', approved };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'crate-review-approved.json'; a.click();
  URL.revokeObjectURL(url);
  showToast(`${approved.length} approved ${approved.length === 1 ? 'choice' : 'choices'} downloaded`);
}

function importDecisions(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      if (data.format !== 'crate-review-approvals' || ![1, 2].includes(data.version) || !Array.isArray(data.approved)) throw new Error('not a Crate Review approval file');
      for (const record of data.approved) {
        if (!CANDIDATES.some(c => c.id === Number(record.number))) continue;
        const candidate = CANDIDATES.find(c => c.id === Number(record.number));
        if (!Array.isArray(record.tracks) || record.tracks.length !== candidate.tracks.length ||
            !record.tracks.every((track, index) => track.path === candidate.tracks[index].path)) continue;
        if (!candidate.options.some(o => o.id === record.selectedOptionId)) continue;
        decisions[candidate.id] = { choice: record.selectedOptionId, confirmed: true };
      }
      saveStored(); render(); showToast('Approved choices imported');
    } catch { showToast('Could not read that approval file'); }
  };
  reader.readAsText(file);
}

function showToast(message) {
  const toast = document.querySelector('#toast'); toast.textContent = message; toast.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('show'), 2400);
}

document.querySelectorAll('.filter-button').forEach(button => button.addEventListener('click', () => {
  activeFilter = button.dataset.filter;
  document.querySelectorAll('.filter-button').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); });
  render();
}));
document.querySelector('#export-button').addEventListener('click', exportApproved);
document.querySelector('#import-button').addEventListener('click', () => document.querySelector('#import-file').click());
document.querySelector('#import-file').addEventListener('change', event => { if (event.target.files[0]) importDecisions(event.target.files[0]); event.target.value = ''; });
function setTheme(mode, persist = true) {
  document.documentElement.dataset.theme = mode;
  if (persist) localStorage.setItem(THEME_KEY, mode);
  const next = THEME_MODES[(THEME_MODES.indexOf(mode) + 1) % THEME_MODES.length];
  const button = document.querySelector('#theme-toggle');
  button.querySelector('span').textContent = THEME_ICONS[mode];
  button.setAttribute('aria-label', `Theme: ${mode}. Switch to ${next}`);
  button.title = `Theme: ${mode} · click for ${next}`;
  document.querySelector('meta[name="theme-color"]').content =
    mode === 'light' || (mode === 'system' && systemLight.matches) ? '#f3f4ef' : '#111511';
}
document.querySelector('#theme-toggle').addEventListener('click', () => {
  const current = document.documentElement.dataset.theme;
  setTheme(THEME_MODES[(THEME_MODES.indexOf(current) + 1) % THEME_MODES.length]);
});
systemLight.addEventListener('change', () => {
  if (document.documentElement.dataset.theme === 'system') setTheme('system', false);
});
const storedTheme = localStorage.getItem(THEME_KEY);
setTheme(THEME_MODES.includes(storedTheme) ? storedTheme : 'system', false);
render();
