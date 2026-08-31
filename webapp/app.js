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

/* Suit un traitement de fond jusqu'à son terme. */
function followJob(progressBox, errorBox, onDone) {
  const fill = progressBox.querySelector('.bar span');
  const label = progressBox.querySelector('.label');
  progressBox.hidden = false;
  showError(errorBox, '');

  const timer = setInterval(async () => {
    const job = await api('/api/job');
    fill.style.width = `${job.progress || 0}%`;
    // Le temps écoulé rassure quand une étape longue reste à 0 %
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
  $('transcribe-warning').hidden = !event.target.checked;
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
    if (result.speech) {
      pieces.push(`${result.speech} répliques transcrites` + (result.speech_reused ? ' (réutilisées)' : ''));
    }
    $('cut-summary').textContent = pieces.join(' · ') + '.';

    $('step-cut').hidden = false;
    $('step-images').hidden = false;
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
for (const id of ['opt-from', 'opt-to']) {
  $(id).oninput = scheduleSegment;
}

async function segment() {
  if (!state.analysed) return;
  const data = await api('/api/segment', {
    target: Number($('opt-target').value),
    tolerance: Number($('opt-tol').value),
    boundary_weight: Number($('opt-weight').value),
    trim_start: $('opt-from').value,
    trim_end: $('opt-to').value,
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

  // Les chapitres ont changé : les propositions d'images ne valent plus rien
  $('galleries').innerHTML = '';

  const warn = $('cut-warn');
  if (data.weak > 0) {
    warn.textContent = `${data.weak} coupe${data.weak > 1 ? 's' : ''} ne tombe`
      + `${data.weak > 1 ? 'nt' : ''} pas sur un silence franc. Essayez d'assouplir `
      + `la régularité, ou relancez l'analyse avec un seuil de silence plus `
      + `tolérant, c'est-à-dire moins négatif (vers −25 ou −20 dB).`;
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }
}

/* ---------- Étape 3 : choix des images ---------- */

$('build-btn').onclick = async () => {
  const started = await api('/api/generate', {
    title: $('opt-title').value,
    age: $('opt-age').value,
    category: $('opt-category').value,
    images: $('opt-images').checked,
    pack: $('opt-pack').checked,
    install: $('opt-install').checked && !$('install-row').hidden,
  });
  if (!started.ok) return showError($('build-error'), started.error);

  $('build-btn').disabled = true;
  $('result').hidden = true;
  followJob($('build-progress'), $('build-error'), (result) => {
    $('build-btn').disabled = false;
    $('result').hidden = false;
    $('result-path').textContent = result.pack
      ? (result.pack.installed || result.pack.pack_dir)
      : result.workdir;

    const notes = [];
    if (result.images && result.images.mismatch) notes.push(result.images.mismatch);
    for (const warning of (result.images?.warnings || [])) notes.push(warning);
    if (result.pack && result.pack.missing_images.length) {
      notes.push('Images manquantes pour les chapitres '
        + result.pack.missing_images.join(', ') + '.');
    }
    if (result.pack && result.pack.install_error) {
      notes.push(result.pack.install_error);
    }
    if (result.pack && result.pack.installed) {
      notes.push('Installé dans Telmi Sync : relancez-le pour voir '
        + "l'histoire apparaître.");
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


/* ---------- Étape 3 : choix des images ---------- */

$('opt-percha').oninput = (event) => {
  $('out-percha').textContent = event.target.value;
};

$('candidates-btn').onclick = async () => {
  const started = await api('/api/candidates', {
    per_chapter: Number($('opt-percha').value),
  });
  if (!started.ok) return showError($('candidates-error'), started.error);

  $('candidates-btn').disabled = true;
  followJob($('candidates-progress'), $('candidates-error'), (result) => {
    $('candidates-btn').disabled = false;
    drawGalleries(result.chapters);
  });
};

function drawGalleries(chapters) {
  const container = $('galleries');
  container.innerHTML = '';

  for (const chapter of chapters) {
    const bloc = document.createElement('div');
    bloc.className = 'gallery';

    const titre = document.createElement('h3');
    titre.textContent = `Chapitre ${chapter.index + 1}`;
    const detail = document.createElement('span');
    detail.textContent = `${chapter.start_label} · ${chapter.duration_label}`;
    titre.appendChild(detail);
    bloc.appendChild(titre);

    const bande = document.createElement('div');
    bande.className = 'strip';
    for (const shot of chapter.candidates) {
      bande.appendChild(makeShot(chapter, shot, bande));
    }
    bloc.appendChild(bande);
    container.appendChild(bloc);
  }
}

function makeShot(chapter, shot, bande) {
  const bouton = document.createElement('button');
  bouton.className = 'shot';
  bouton.type = 'button';
  // aria-pressed porte la sélection : lisible par le lecteur d'écran
  // autant que par la feuille de style
  bouton.setAttribute('aria-pressed', String(shot.time === chapter.chosen_time));

  const img = document.createElement('img');
  img.src = `/api/thumb?name=${encodeURIComponent(shot.file)}`;
  img.alt = `Image à ${shot.label}`;
  img.loading = 'lazy';

  const legende = document.createElement('figcaption');
  legende.textContent = shot.label;
  bouton.append(img, legende);

  bouton.onclick = async () => {
    for (const autre of bande.querySelectorAll('.shot')) {
      autre.setAttribute('aria-pressed', 'false');
    }
    bouton.setAttribute('aria-pressed', 'true');
    await api('/api/choose', { index: chapter.index, time: shot.time });
  };
  return bouton;
}


/* ---------- Étape 4 : couverture et annonce du titre ---------- */

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
      return false;
    }
    return true;
  } catch (error) {
    setStatus(statusElement, `Envoi impossible : ${error}`, true);
    return false;
  }
}

$('opt-cover').onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const ok = await sendFile('/api/cover', file, $('cover-status'), 'Conversion…');
  if (!ok) return;
  setStatus($('cover-status'), 'Couverture prête (640x480).', false);
  const preview = $('cover-preview');
  preview.src = URL.createObjectURL(file);
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
   considéré comme une origine sûre au même titre que https. */
let recorder = null;
let recordedChunks = [];
let recordTimer = null;

$('rec-btn').onclick = async () => {
  if (recorder && recorder.state === 'recording') {
    recorder.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return setStatus($('title-audio-status'),
      "Ce navigateur ne permet pas l'enregistrement. Choisissez un fichier audio.", true);
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    return setStatus($('title-audio-status'),
      `Micro indisponible : ${error.name === 'NotAllowedError'
        ? "l'accès a été refusé" : error.message}`, true);
  }

  recordedChunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (event) => {
    if (event.data.size) recordedChunks.push(event.data);
  };
  recorder.onstop = async () => {
    clearInterval(recordTimer);
    stream.getTracks().forEach((track) => track.stop());
    $('rec-btn').textContent = '🎙 Enregistrer';
    $('rec-btn').classList.remove('recording');
    $('rec-time').hidden = true;
    const blob = new Blob(recordedChunks, { type: recorder.mimeType });
    await useTitleAudio(blob, "Conversion de l'enregistrement…");
  };

  recorder.start();
  const startedAt = Date.now();
  $('rec-btn').textContent = '⏹ Arrêter';
  $('rec-btn').classList.add('recording');
  $('rec-time').hidden = false;
  recordTimer = setInterval(() => {
    $('rec-time').textContent = `${Math.round((Date.now() - startedAt) / 1000)} s`;
  }, 250);
  setStatus($('title-audio-status'), '', false);
};


/* Telmi Sync range ses histoires dans un dossier de travail : si on le
   trouve, on propose d'y déposer le pack directement. */
(async () => {
  const telmi = await api('/api/telmi');
  if (!telmi.found) return;
  $('install-path').textContent = telmi.path;
  $('install-row').hidden = false;
})();
