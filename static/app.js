/* Invoice Processor – Frontend Logic */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let selectedFiles = [];        // DataTransfer-list of File objects
let pendingDuplicates = [];    // Queue of duplicate results waiting for user decision
let currentDupResolve = null;  // Promise resolve for current modal

// ── DOM refs ──────────────────────────────────────────────────────────────────
const dropZone     = document.getElementById('drop-zone');
const fileInput    = document.getElementById('file-input');
const fileList     = document.getElementById('file-list');
const uploadBtn    = document.getElementById('upload-btn');
const clearBtn     = document.getElementById('clear-btn');
const statusBar    = document.getElementById('status-bar');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('results-container');
const catGroup     = document.getElementById('category-group');

// Modal
const modal        = document.getElementById('duplicate-modal');
const overlay      = document.getElementById('modal-overlay');
const dupMsg       = document.getElementById('duplicate-message');
const dupSkip      = document.getElementById('dup-skip');
const dupForce     = document.getElementById('dup-force');

// ── Drop zone events ──────────────────────────────────────────────────────────
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));

dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  addFiles([...e.dataTransfer.files]);
});

fileInput.addEventListener('change', () => {
  addFiles([...fileInput.files]);
  fileInput.value = '';
});

function addFiles(newFiles) {
  const allowed = new Set(['.pdf', '.csv', '.xlsx', '.xls']);
  for (const f of newFiles) {
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
    if (!allowed.has(ext)) {
      showStatus(`Nicht unterstützt: ${f.name} (nur PDF, CSV, XLSX)`, 'error');
      continue;
    }
    if (!selectedFiles.find(x => x.name === f.name && x.size === f.size)) {
      selectedFiles.push(f);
    }
  }
  renderFileList();
  updateUploadBtn();
}

function removeFile(idx) {
  selectedFiles.splice(idx, 1);
  renderFileList();
  updateUploadBtn();
}

function renderFileList() {
  if (!selectedFiles.length) {
    fileList.classList.add('hidden');
    return;
  }
  fileList.classList.remove('hidden');
  fileList.innerHTML = selectedFiles.map((f, i) => `
    <div class="file-item">
      <span class="file-icon">${fileIcon(f.name)}</span>
      <span class="file-name">${escHtml(f.name)}</span>
      <span class="file-size">${formatSize(f.size)}</span>
      <span class="remove-file" onclick="removeFile(${i})" title="Entfernen">✕</span>
    </div>
  `).join('');
}

function fileIcon(name) {
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  return ext === '.pdf' ? '📄' : ext === '.csv' ? '📊' : '📗';
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Category selection ────────────────────────────────────────────────────────
catGroup.addEventListener('change', () => {
  catGroup.classList.remove('error');
  updateUploadBtn();
});

function getCategory() {
  const checked = catGroup.querySelector('input[name="category"]:checked');
  return checked ? checked.value : null;
}

function updateUploadBtn() {
  const ready = selectedFiles.length > 0 && !!getCategory();
  uploadBtn.disabled = !ready;
}

// ── Upload ────────────────────────────────────────────────────────────────────
uploadBtn.addEventListener('click', startUpload);
clearBtn.addEventListener('click', resetAll);

async function startUpload() {
  const category = getCategory();
  if (!category) {
    catGroup.classList.add('error');
    showStatus('Bitte zuerst eine Kategorie wählen.', 'error');
    return;
  }

  if (!selectedFiles.length) return;

  const referenz = document.getElementById('referenz').value.trim();

  uploadBtn.disabled = true;
  uploadBtn.innerHTML = '<span class="spinner"></span> Verarbeite…';
  showStatus('Dateien werden verarbeitet…', 'loading');
  resultsSection.classList.remove('hidden');
  resultsContainer.innerHTML = '';

  // Upload all files in one request
  const formData = new FormData();
  formData.append('category', category);
  formData.append('referenz', referenz);
  for (const f of selectedFiles) formData.append('files[]', f);

  let data;
  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });
    data = await resp.json();
  } catch (err) {
    showStatus('Netzwerkfehler: ' + err.message, 'error');
    resetUploadBtn();
    return;
  }

  // Handle errors list
  for (const e of data.errors || []) {
    appendResult({
      file: e.file,
      status: 'error',
      error: e.error,
    });
  }

  // Handle results – process duplicates interactively
  for (const r of data.results || []) {
    if (r.status === 'duplicate') {
      const decision = await askDuplicate(r);
      if (decision === 'force') {
        // Re-upload with force=true for this single file
        await forceUpload(r.file, category, referenz);
        continue;
      }
      // Skip
      appendResult({ ...r, message: 'Übersprungen (Duplikat).' });
    } else {
      appendResult(r);
    }
  }

  const total   = (data.results || []).filter(r => r.status === 'ok').length;
  const skipped = (data.results || []).filter(r => r.status === 'duplicate').length;
  const errors  = (data.errors || []).length + (data.results || []).filter(r => r.status === 'error').length;

  const parts = [];
  if (total) parts.push(`${total} Rechnung(en) importiert`);
  if (skipped) parts.push(`${skipped} übersprungen`);
  if (errors) parts.push(`${errors} Fehler`);

  showStatus(parts.join(' · ') || 'Fertig.', errors ? 'error' : 'success');

  clearBtn.classList.remove('hidden');
  resetUploadBtn();
}

async function forceUpload(filename, category, referenz) {
  // Find file object
  const fileObj = selectedFiles.find(f => f.name === filename);
  if (!fileObj) return;

  const formData = new FormData();
  formData.append('category', category);
  formData.append('referenz', referenz);
  formData.append('force', 'true');
  formData.append('files[]', fileObj);

  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });
    const data = await resp.json();
    for (const r of data.results || []) appendResult(r);
    for (const e of data.errors || [])  appendResult({ file: e.file, status: 'error', error: e.error });
  } catch (err) {
    appendResult({ file: filename, status: 'error', error: err.message });
  }
}

function resetUploadBtn() {
  uploadBtn.innerHTML = 'Rechnungen verarbeiten →';
  updateUploadBtn();
}

function resetAll() {
  selectedFiles = [];
  renderFileList();
  document.getElementById('referenz').value = '';
  document.querySelectorAll('input[name="category"]').forEach(r => r.checked = false);
  resultsSection.classList.add('hidden');
  resultsContainer.innerHTML = '';
  clearBtn.classList.add('hidden');
  statusBar.classList.add('hidden');
  updateUploadBtn();
}

// ── Duplicate modal ───────────────────────────────────────────────────────────
function askDuplicate(result) {
  return new Promise(resolve => {
    dupMsg.textContent = result.message || `Rechnung ${result.invoice_nr} bereits vorhanden.`;
    modal.classList.remove('hidden');
    overlay.classList.remove('hidden');
    currentDupResolve = resolve;
  });
}

dupSkip.addEventListener('click', () => closeModal('skip'));
dupForce.addEventListener('click', () => closeModal('force'));

function closeModal(decision) {
  modal.classList.add('hidden');
  overlay.classList.add('hidden');
  if (currentDupResolve) {
    currentDupResolve(decision);
    currentDupResolve = null;
  }
}

// ── Results rendering ─────────────────────────────────────────────────────────
function appendResult(r) {
  const status = r.status || 'ok';
  const badgeClass = status === 'ok' ? 'ok' : status === 'duplicate' ? 'duplicate' : 'error';
  const cardClass  = status === 'ok' ? '' : status;

  const metaParts = [];
  if (r.provider)    metaParts.push(`<strong>Anbieter:</strong> ${escHtml(r.provider)}`);
  if (r.invoice_nr)  metaParts.push(`<strong>Rechnung:</strong> ${escHtml(r.invoice_nr)}`);
  if (r.category)    metaParts.push(`<strong>Tab:</strong> ${escHtml(r.category)}`);
  if (r.rows_parsed) metaParts.push(`<strong>Zeilen:</strong> ${r.rows_parsed}`);
  if (r.error)       metaParts.push(`<span style="color:var(--red)">${escHtml(r.error)}</span>`);
  if (r.message)     metaParts.push(escHtml(r.message));

  const labels = {
    'dienstleister':   'Anbieter',
    'rechnungsnr':     'Rechnung-Nr.',
    'rechnungsdatum':  'Datum',
    'referenz':        'Referenz',
    'trackingnummer':  'Tracking',
    'betrag_brutto_eur': 'Betrag EUR',
    'serviceart':      'Service',
  };

  let previewHtml = '';
  if (r.preview && r.preview.length) {
    const keys = Object.keys(labels);
    previewHtml = `
      <table class="preview-table">
        <thead><tr>${keys.map(k => `<th>${labels[k]}</th>`).join('')}</tr></thead>
        <tbody>
          ${r.preview.map(row =>
            `<tr>${keys.map(k => `<td title="${escHtml(String(row[k]||''))}">${escHtml(String(row[k]||''))}</td>`).join('')}</tr>`
          ).join('')}
        </tbody>
      </table>`;
  }

  const div = document.createElement('div');
  div.className = `result-card ${cardClass}`;
  div.innerHTML = `
    <div class="result-header">
      <span class="result-filename">${escHtml(r.file || '')}</span>
      <span class="badge ${badgeClass}">${statusLabel(status)}</span>
    </div>
    <div class="result-meta">${metaParts.join(' &nbsp;·&nbsp; ')}</div>
    ${previewHtml}
  `;
  resultsContainer.appendChild(div);
}

function statusLabel(status) {
  return status === 'ok'        ? '✓ Importiert'
       : status === 'duplicate' ? '⟳ Duplikat'
       : status === 'sheet_error' ? '⚠ Sheet-Fehler'
       : '✗ Fehler';
}

// ── Status bar ────────────────────────────────────────────────────────────────
function showStatus(msg, type = 'loading') {
  statusBar.textContent = msg;
  statusBar.className = `status-bar ${type}`;
  statusBar.classList.remove('hidden');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
