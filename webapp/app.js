'use strict';

const $ = (id) => document.getElementById(id);
const state = { film: null, analysed: false };

/* ---------- Utilitaires ---------- */

async function api(route, body) {
  const options = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) }
    : {};
  const response = await fetch(route, options);
  return response.json();
}

function minutesLabel(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s} s`;
  return s === 0 ? `${m} min` : `${m} min ${s}`;
}

function sizeLabel(bytes) {
  const giga = bytes / 1e9;
  return giga >= 1 ? `${giga.toFixed(1)} Go` : `${Math.round(bytes / 1e6)} Mo`;
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

/* Suit un traitement de fond jusqu'à son terme. */
function followJob(progressBox, errorBox, onDone) {
  const fill = progressBox.querySelector('.bar span');
  const label = progressBox.querySelector('.label');
  progressBox.hidden = false;
  showError(errorBox, '');

  const timer = setInterval(async () => {
    const job = await api('/api/job');
    fill.style.width = `${job.progress || 0}%`;
    label.textContent = job.label || '';
    if (job.state === 'done') {
      clearInterval(timer);
      progressBox.hidden = true;
      onDone(job.result);
    } else if (job.state === 'error') {
      clearInterval(timer);
      progressBox.hidden = true;
      showError(errorBox, job.error || 'Une erreur est survenue.');
    }
  }, 400);
}

/* ---------- Étape 1 : choix du film ---------- */

const browser = $('browser');

async function openBrowser(path) {
  const data = await api('/api/browse' + (path ? `?path=${encodeURIComponent(path)}` : ''));
  const list = $('browser-list');
  $('browser-path').textContent = data.path || '';
  list.innerHTML = '';

  // Un film indique directement par son chemin : on le prend sans naviguer
  if (data.file) {
    chooseFilm(data.file);
    return;
  }
  showError($('browser-error'), data.error || '');
  if (data.error && !data.drives?.length) {
    browser.hidden = false;
    return;
  }

  // Sous Windows, les autres lecteurs (D:, cle USB...) sont hors de
  // l'arborescence du disque systeme : il faut les proposer explicitement
  for (const drive of (data.drives || [])) {
    const item = row('💾', drive.name, () => openBrowser(drive.path));
    item.className = 'drive';
    list.appendChild(item);
  }
  if (data.error) { browser.hidden = false; return; }
  if (data.parent) {
    list.appendChild(row('📁', '..', () => openBrowser(data.parent)));
  }
  for (const dir of data.dirs) {
    list.appendChild(row('📁', dir.name, () => openBrowser(dir.path)));
  }
  for (const file of data.files) {
    list.appendChild(row('🎬', file.name, () => chooseFilm(file), sizeLabel(file.size)));
  }
  if (!data.dirs.length && !data.files.length) {
    list.appendChild(Object.assign(document.createElement('li'),
      { className: 'empty', textContent: 'Ce dossier ne contient aucun film.' }));
  }
  browser.hidden = false;
}

function row(icon, name, onClick, extra) {
  const item = document.createElement('li');
  const button = document.createElement('button');
  button.innerHTML = `<span>${icon}</span><span></span>`;
  button.children[1].textContent = name;
  if (extra) {
    const size = document.createElement('span');
    size.className = 'size';
    size.textContent = extra;
    button.appendChild(size);
  }
  button.onclick = onClick;
  item.appendChild(button);
  return item;
}

function chooseFilm(file) {
  state.film = file.path;
  browser.hidden = true;
  const chosen = $('chosen');
  chosen.textContent = file.name;
  chosen.classList.add('set');
  $('analyze-btn').disabled = false;
  if (!$('opt-title').value) $('opt-title').value = file.name.replace(/\.[^.]+$/, '');
}

function gotoTypedPath() {
  const value = $('browser-goto').value.trim();
  if (value) openBrowser(value);
}
$('browser-go').onclick = gotoTypedPath;
$('browser-goto').onkeydown = (event) => {
  if (event.key === 'Enter') gotoTypedPath();
};

$('pick-btn').onclick = () => openBrowser(null);
$('browser-close').onclick = () => { browser.hidden = true; };
browser.onclick = (event) => { if (event.target === browser) browser.hidden = true; };

/* ---------- Étape 1 : analyse ---------- */

$('opt-transcribe').onchange = (event) => {
  $('model-row').hidden = !event.target.checked;
};
$('opt-noise').oninput = (e) => { $('out-noise').textContent = `${e.target.value} dB`; };
$('opt-minsil').oninput = (e) => {
  $('out-minsil').textContent = `${Number(e.target.value).toFixed(1).replace('.', ',')} s`;
};

$('analyze-btn').onclick = async () => {
  const started = await api('/api/analyze', {
    video: state.film,
    transcribe: $('opt-transcribe').checked,
    model: $('opt-model').value,
    noise: Number($('opt-noise').value),
    min_silence: Number($('opt-minsil').value),
  });
  if (!started.ok) return showError($('analyze-error'), started.error);

  $('analyze-btn').disabled = true;
  followJob($('analyze-progress'), $('analyze-error'), (result) => {
    $('analyze-btn').disabled = false;
    state.analysed = true;

    const pieces = [
      `Film de ${result.duration_label}`,
      `${result.silences} silences repérés`,
    ];
    if (result.speech) pieces.push(`${result.speech} répliques transcrites`);
    $('cut-summary').textContent = pieces.join(' · ') + '.';

    $('step-cut').hidden = false;
    $('step-build').hidden = false;
    // Une durée de chapitre plus longue que le film n'a pas de sens
    const slider = $('opt-target');
    slider.max = Math.max(60, Math.floor(result.duration / 2 / 30) * 30);
    if (Number(slider.value) > Number(slider.max)) slider.value = slider.max;
    refreshLabels();
    segment();
    $('step-cut').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
};

/* ---------- Étape 2 : découpage en direct ---------- */

function toleranceLabel(value) {
  if (value <= 0.3) return 'stricte';
  if (value <= 0.6) return 'souple';
  return 'très libre';
}
function weightLabel(value) {
  if (value <= 0.1) return 'faible';
  if (value <= 0.4) return 'moyenne';
  return 'forte';
}
function refreshLabels() {
  $('out-target').textContent = minutesLabel(Number($('opt-target').value));
  $('out-tol').textContent = toleranceLabel(Number($('opt-tol').value));
  $('out-weight').textContent = weightLabel(Number($('opt-weight').value));
}

let debounce = null;
function scheduleSegment() {
  refreshLabels();
  clearTimeout(debounce);
  debounce = setTimeout(segment, 180);
}
for (const id of ['opt-target', 'opt-tol', 'opt-weight']) {
  $(id).oninput = scheduleSegment;
}

async function segment() {
  if (!state.analysed) return;
  const data = await api('/api/segment', {
    target: Number($('opt-target').value),
    tolerance: Number($('opt-tol').value),
    boundary_weight: Number($('opt-weight').value),
  });
  const body = $('cut-table').querySelector('tbody');

  if (data.error) {
    body.innerHTML = '';
    $('cut-warn').hidden = true;
    return showError($('cut-error'), data.error);
  }
  showError($('cut-error'), '');

  body.innerHTML = '';
  for (const chapter of data.chapters) {
    const tr = document.createElement('tr');
    const cells = [
      chapter.index + 1, chapter.start_label,
      chapter.end_label, chapter.duration_label,
    ];
    for (const value of cells) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    }
    const tag = document.createElement('td');
    const span = document.createElement('span');
    span.className = 'tag ' + (
      chapter.cut_quality >= 0.6 ? 'franche'
        : chapter.cut_quality > 0 ? 'correcte'
        : chapter.cut_quality === 0 ? 'arbitraire' : 'replique');
    span.textContent = chapter.cut_label;
    tag.appendChild(span);
    tr.appendChild(tag);
    body.appendChild(tr);
  }

  const warn = $('cut-warn');
  if (data.weak > 0) {
    warn.textContent = `${data.weak} coupe${data.weak > 1 ? 's' : ''} ne tombe`
      + `${data.weak > 1 ? 'nt' : ''} pas sur un silence franc. Essayez d'assouplir `
      + `la régularité, ou relancez l'analyse avec un seuil de silence plus bas.`;
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }
}

/* ---------- Étape 3 : génération ---------- */

$('build-btn').onclick = async () => {
  const started = await api('/api/generate', {
    title: $('opt-title').value,
    age: $('opt-age').value,
    images: $('opt-images').checked,
    pack: $('opt-pack').checked,
  });
  if (!started.ok) return showError($('build-error'), started.error);

  $('build-btn').disabled = true;
  $('result').hidden = true;
  followJob($('build-progress'), $('build-error'), (result) => {
    $('build-btn').disabled = false;
    $('result').hidden = false;
    $('result-path').textContent = result.pack
      ? result.pack.pack_dir
      : result.workdir;

    const notes = [];
    if (result.images && result.images.mismatch) notes.push(result.images.mismatch);
    for (const warning of (result.images?.warnings || [])) notes.push(warning);
    if (result.pack && result.pack.missing_images.length) {
      notes.push('Images manquantes pour les chapitres '
        + result.pack.missing_images.join(', ') + '.');
    }
    if (result.pack && result.pack.silent_title) {
      notes.push("title.mp3 est un silence d'une seconde : remplacez-le par un "
        + 'enregistrement du titre si vous le souhaitez.');
    }
    const warn = $('result-warn');
    warn.textContent = notes.join(' ');
    warn.hidden = notes.length === 0;

    const thumbs = $('thumbs');
    thumbs.innerHTML = '';
    for (const detail of (result.images?.details || [])) {
      const figure = document.createElement('figure');
      const img = document.createElement('img');
      img.src = `/api/thumb?name=${encodeURIComponent(detail.name)}&t=${Date.now()}`;
      img.alt = `Chapitre ${detail.index + 1}`;
      const caption = document.createElement('figcaption');
      caption.textContent = `Chapitre ${detail.index + 1}`;
      figure.append(img, caption);
      thumbs.appendChild(figure);
    }
    $('result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
};

refreshLabels();
