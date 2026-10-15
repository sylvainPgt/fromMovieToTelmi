'use strict';

const $ = (id) => document.getElementById(id);
const state = { book: null, analysed: false, hasChapters: false, browsing: null };

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

function elapsedLabel(seconds) {
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m} min ${String(s).padStart(2, '0')} s` : `${s} s`;
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function thumbUrl(name) {
  return `/api/thumb?name=${encodeURIComponent(name)}&t=${Date.now()}`;
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
    const parts = [job.label || ''];
    if (job.elapsed >= 5) parts.push(elapsedLabel(job.elapsed));
    label.textContent = parts.filter(Boolean).join(' · ');
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

/* ---------- Étape 1 : choix du livre ---------- */

const browser = $('browser');

async function openBrowser(path) {
  const data = await api('/api/browse' + (path ? `?path=${encodeURIComponent(path)}` : ''));
  const list = $('browser-list');
  $('browser-path').textContent = data.path || '';
  list.innerHTML = '';

  // Un fichier indiqué directement par son chemin : on le prend sans naviguer
  if (data.pick) {
    chooseBook(data.pick);
    return;
  }
  showError($('browser-error'), data.error || '');

  // Le dossier ouvert contient lui-même un livre : on propose de le prendre
  state.browsing = data.book ? { name: data.path.split(/[\\/]/).pop(), path: data.path } : null;
  $('browser-here').hidden = !state.browsing;

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
    // Un dossier de livre se prend d'un clic : c'est le cas de chaque
    // dossier « Titre [ASIN] » de Libation
    list.appendChild(dir.book
      ? row('📚', dir.name, () => chooseBook(dir), 'livre')
      : row('📁', dir.name, () => openBrowser(dir.path)));
  }
  for (const file of data.files) {
    list.appendChild(file.protected
      ? row('🔒', file.name, () => showError($('browser-error'),
          'Fichier encore protégé : libérez-le dans Libation, puis choisissez '
          + 'le dossier qu\'il produit.'), 'protégé')
      : row('🎧', file.name, () => chooseBook(file), sizeLabel(file.size)));
  }
  if (!data.dirs.length && !data.files.length) {
    list.appendChild(Object.assign(document.createElement('li'),
      { className: 'empty', textContent: 'Ce dossier ne contient aucun livre.' }));
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

function chooseBook(entry) {
  state.book = entry.path;
  browser.hidden = true;
  const chosen = $('chosen');
  chosen.textContent = entry.name;
  chosen.classList.add('set');
  $('analyze-btn').disabled = false;
}

function gotoTypedPath() {
  const value = $('browser-goto').value.trim();
  if (value) openBrowser(value);
}
$('browser-go').onclick = gotoTypedPath;
$('browser-goto').onkeydown = (event) => {
  if (event.key === 'Enter') gotoTypedPath();
};
$('browser-here').onclick = () => { if (state.browsing) chooseBook(state.browsing); };

$('pick-btn').onclick = () => openBrowser(null);
$('browser-close').onclick = () => { browser.hidden = true; };
browser.onclick = (event) => { if (event.target === browser) browser.hidden = true; };

$('opt-noise').oninput = (e) => { $('out-noise').textContent = `${e.target.value} dB`; };

/* ---------- Étape 1 : lecture du livre ---------- */

$('analyze-btn').onclick = async () => {
  const started = await api('/api/analyze', {
    book: state.book,
    silences: $('opt-silences').checked,
    noise: Number($('opt-noise').value),
  });
  if (!started.ok) return showError($('analyze-error'), started.error);

  $('analyze-btn').disabled = true;
  followJob($('analyze-progress'), $('analyze-error'), (result) => {
    $('analyze-btn').disabled = false;
    state.analysed = true;
    state.hasChapters = result.chapters.length > 0;

    const pieces = [result.title];
    if (result.author) pieces.push(result.author);
    pieces.push(result.duration_label);
    pieces.push(result.source_kind);
    if (result.silences) pieces.push(`${result.silences} silences repérés`);
    $('book-summary').textContent = pieces.join(' · ') + '.';

    const cover = $('book-cover');
    cover.hidden = !result.cover;
    if (result.cover) cover.src = thumbUrl(result.cover);
    $('cover-preview').hidden = true;
    setStatus($('cover-status'), '', false);

    const body = $('book-table').querySelector('tbody');
    body.innerHTML = '';
    result.chapters.forEach((chapter, index) => {
      const tr = document.createElement('tr');
      for (const value of [index + 1, chapter.start_label, chapter.duration_label, chapter.title]) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.appendChild(td);
      }
      body.appendChild(tr);
    });
    $('book-chapters-summary').textContent = `${result.chapters.length} chapitres dans le livre`;
    $('book-info').hidden = false;

    // Sans chapitres, seul le mode « durée » a un sens
    $('mode-livre').disabled = !state.hasChapters;
    if (!state.hasChapters) $('mode-duree').checked = true;
    $('opt-title').value = result.title;
    $('opt-from').value = '';
    $('opt-to').value = '';

    const slider = $('opt-target');
    slider.max = Math.max(180, Math.min(1800, Math.floor(result.duration / 2 / 60) * 60));
    if (Number(slider.value) > Number(slider.max)) slider.value = slider.max;

    $('step-cut').hidden = false;
    $('step-build').hidden = false;
    refreshMode();
    segment();
    $('step-cut').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
};

/* ---------- Étape 2 : découpage en direct ---------- */

function currentMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}
function toleranceLabel(value) {
  if (value <= 0.3) return 'stricte';
  if (value <= 0.6) return 'souple';
  return 'très libre';
}
function weightLabel(value) {
  if (value <= 0.15) return 'faible';
  if (value <= 0.5) return 'moyenne';
  return 'forte';
}
function refreshLabels() {
  $('out-target').textContent = minutesLabel(Number($('opt-target').value));
  $('out-tol').textContent = toleranceLabel(Number($('opt-tol').value));
  $('out-weight').textContent = weightLabel(Number($('opt-weight').value));
}
function refreshMode() {
  $('duration-sliders').hidden = currentMode() !== 'duree';
}

let debounce = null;
function scheduleSegment() {
  refreshLabels();
  refreshMode();
  clearTimeout(debounce);
  debounce = setTimeout(segment, 180);
}
for (const id of ['opt-target', 'opt-tol', 'opt-weight', 'opt-from', 'opt-to']) {
  $(id).oninput = scheduleSegment;
}
for (const radio of document.querySelectorAll('input[name="mode"]')) {
  radio.onchange = scheduleSegment;
}

async function segment() {
  if (!state.analysed) return;
  const data = await api('/api/segment', {
    mode: currentMode(),
    target: Number($('opt-target').value),
    tolerance: Number($('opt-tol').value),
    boundary_weight: Number($('opt-weight').value),
    trim_start: $('opt-from').value,
    trim_end: $('opt-to').value,
  });
  const body = $('cut-table').querySelector('tbody');
  body.innerHTML = '';

  if (data.error) {
    $('cut-warn').hidden = true;
    return showError($('cut-error'), data.error);
  }
  showError($('cut-error'), '');

  for (const chapter of data.chapters) {
    const tr = document.createElement('tr');
    for (const value of [chapter.index + 1, chapter.start_label, chapter.duration_label]) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    }
    const tag = document.createElement('td');
    const span = document.createElement('span');
    span.className = 'tag ' + (
      chapter.cut_quality >= 1 ? 'franche'
        : chapter.cut_quality > 0 ? 'correcte' : 'arbitraire');
    span.textContent = chapter.cut_label;
    tag.appendChild(span);
    tr.appendChild(tag);
    const content = document.createElement('td');
    content.textContent = chapter.title;
    tr.appendChild(content);
    body.appendChild(tr);
  }

  drawChapterAudios(data.chapters);

  const warn = $('cut-warn');
  const short = data.chapters.filter((c) => c.duration < 60).length;
  const notes = [];
  if (data.weak > 0) {
    notes.push(`${data.weak} coupe${data.weak > 1 ? 's tombent' : ' tombe'} hors de tout `
      + 'silence. Cochez « Repérer aussi les silences » à l\'étape 1 et relisez le livre.');
  }
  if (short > 0 && currentMode() === 'livre') {
    notes.push(`${short} chapitre${short > 1 ? 's durent' : ' dure'} moins d'une minute `
      + '(jingle, crédits ?) : écartez-les avec le début et la fin de l\'histoire, '
      + 'ou passez en mode durée pour les regrouper.');
  }
  warn.textContent = notes.join(' ');
  warn.hidden = notes.length === 0;
}

/* ---------- Étape 3 : génération ---------- */

$('build-btn').onclick = async () => {
  const started = await api('/api/generate', {
    title: $('opt-title').value,
    age: $('opt-age').value,
    category: $('opt-category').value,
    numbered: $('opt-numbered').checked,
    install: $('opt-install').checked && !$('install-row').hidden,
    show_image: $('opt-showimage').checked,
  });
  if (!started.ok) return showError($('build-error'), started.error);

  $('build-btn').disabled = true;
  $('result').hidden = true;
  followJob($('build-progress'), $('build-error'), (result) => {
    $('build-btn').disabled = false;
    $('result').hidden = false;
    $('result-path').textContent = result.pack.installed || result.pack.pack_dir;

    const notes = [];
    if (result.pack.install_error) notes.push(result.pack.install_error);
    if (result.pack.installed) {
      notes.push("Installé dans Telmi Sync : relancez-le pour voir l'histoire apparaître.");
    }
    if (result.pack.silent_title) {
      notes.push("title.mp3 est un silence d'une seconde : enregistrez l'annonce du "
        + 'titre si vous le souhaitez.');
    }
    const warn = $('result-warn');
    warn.textContent = notes.join(' ');
    warn.hidden = notes.length === 0;

    const thumbs = $('thumbs');
    thumbs.innerHTML = '';
    for (const detail of result.images) {
      const figure = document.createElement('figure');
      const img = document.createElement('img');
      img.src = thumbUrl(detail.name);
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

/* ---------- Couverture et annonce du titre ---------- */

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function setStatus(element, message, failed) {
  element.textContent = message;
  element.classList.toggle('ko', Boolean(failed));
  element.hidden = !message;
}

async function sendFile(route, blob, statusElement, working) {
  setStatus(statusElement, working, false);
  try {
    const answer = await api(route, { data: await readAsDataUrl(blob) });
    if (answer.error) {
      setStatus(statusElement, answer.error, true);
      return null;
    }
    return answer;
  } catch (error) {
    setStatus(statusElement, `Envoi impossible : ${error}`, true);
    return null;
  }
}

$('opt-cover').onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const answer = await sendFile('/api/cover', file, $('cover-status'), 'Conversion…');
  if (!answer) return;
  setStatus($('cover-status'), 'Couverture prête : voici son rendu sur la Telmi.', false);
  const preview = $('cover-preview');
  preview.src = thumbUrl(answer.name);
  preview.hidden = false;
};

$('opt-title-audio').onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  await useTitleAudio(file, 'Conversion du fichier…');
};

async function useTitleAudio(blob, working) {
  const ok = await sendFile('/api/title-audio', blob, $('title-audio-status'), working);
  if (!ok) return;
  setStatus($('title-audio-status'), 'Annonce prête (MP3 44100 Hz).', false);
  const preview = $('title-audio-preview');
  preview.src = URL.createObjectURL(blob);
  preview.hidden = false;
}

/* Enregistrement au micro. Le navigateur autorise le micro sur 127.0.0.1,
   considéré comme une origine sûre au même titre que https.
   Un seul enregistrement à la fois, quel que soit le bouton. */
let activeRecorder = null;

function attachRecorder({ button, timeEl, statusEl, onBlob }) {
  let recorder = null;
  let chunks = [];
  let timer = null;

  button.onclick = async () => {
    if (recorder && recorder.state === 'recording') {
      recorder.stop();
      return;
    }
    if (activeRecorder) {
      return setStatus(statusEl, 'Un autre enregistrement est en cours.', true);
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      return setStatus(statusEl,
        "Ce navigateur ne permet pas l'enregistrement. Choisissez un fichier audio.", true);
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      return setStatus(statusEl,
        `Micro indisponible : ${error.name === 'NotAllowedError'
          ? "l'accès a été refusé" : error.message}`, true);
    }

    chunks = [];
    recorder = new MediaRecorder(stream);
    activeRecorder = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    recorder.onstop = async () => {
      clearInterval(timer);
      stream.getTracks().forEach((track) => track.stop());
      activeRecorder = null;
      button.textContent = '🎙 Enregistrer';
      button.classList.remove('recording');
      timeEl.hidden = true;
      await onBlob(new Blob(chunks, { type: recorder.mimeType }));
    };

    recorder.start();
    const startedAt = Date.now();
    button.textContent = '⏹ Arrêter';
    button.classList.add('recording');
    timeEl.hidden = false;
    timer = setInterval(() => {
      timeEl.textContent = `${Math.round((Date.now() - startedAt) / 1000)} s`;
    }, 250);
    setStatus(statusEl, '', false);
  };
}

attachRecorder({
  button: $('rec-btn'), timeEl: $('rec-time'), statusEl: $('title-audio-status'),
  onBlob: (blob) => useTitleAudio(blob, "Conversion de l'enregistrement…"),
});

/* ---------- Annonces des chapitres dans le menu ---------- */

function drawChapterAudios(chapters) {
  const container = $('chapter-audios');
  container.innerHTML = '';
  for (const chapter of chapters) {
    const line = document.createElement('div');
    line.className = 'chapter-row';

    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = `${chapter.index + 1} · ${chapter.title}`;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn';
    button.textContent = '🎙 Enregistrer';

    const timeEl = document.createElement('span');
    timeEl.className = 'rec-time';
    timeEl.hidden = true;
    const statusEl = document.createElement('p');
    statusEl.className = 'status';
    statusEl.hidden = true;
    const preview = document.createElement('audio');
    preview.controls = true;
    preview.hidden = true;

    line.append(who, button, timeEl, statusEl, preview);
    container.appendChild(line);

    attachRecorder({
      button, timeEl, statusEl,
      onBlob: async (blob) => {
        setStatus(statusEl, 'Conversion…', false);
        const answer = await api('/api/chapter-audio',
          { index: chapter.index, data: await readAsDataUrl(blob) });
        if (answer.error) return setStatus(statusEl, answer.error, true);
        setStatus(statusEl, 'Annonce enregistrée.', false);
        preview.src = URL.createObjectURL(blob);
        preview.hidden = false;
      },
    });
  }
}

/* Telmi Sync range ses histoires dans un dossier de travail : si on le
   trouve, on propose d'y déposer le pack directement. */
(async () => {
  const telmi = await api('/api/telmi');
  if (!telmi.found) return;
  $('install-path').textContent = telmi.path;
  $('install-row').hidden = false;
})();
