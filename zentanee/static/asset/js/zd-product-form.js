/* Dashboard product form behaviors (extracted from inline template scripts). */
document.addEventListener('DOMContentLoaded', function () {
  /* Collapsed editor: the full form starts hidden behind "Edit details" /
     "Fill in manually" so the AI intake is the whole screen on phones. */
  document.querySelectorAll('[data-zd-editor-reveal]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const editor = document.querySelector('[data-zd-editor]');
      const body = document.querySelector('[data-zd-editor-body]');
      if (editor) editor.hidden = false;
      if (body) body.hidden = false;
      document.querySelectorAll('[data-zd-editor-reveal]').forEach(function (b) {
        const holder = b.closest('.zd-manual-reveal');
        (holder || b).remove();
      });
      if (editor) editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  /* Drive the draft while Gemini works: the process endpoint is idempotent
     and (on serverless) runs the enrichment inside the request, so watching
     this page is enough to make it finish — no waiting for the cron sweeper. */
  const progressPanel = document.querySelector('[data-ai-draft-progress]');
  if (progressPanel) {
    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    let inFlight = false;
    const timer = setInterval(async function () {
      if (inFlight) return;
      inFlight = true;
      try {
        const processUrl = progressPanel.dataset.processUrl;
        const res = processUrl && csrfInput
          ? await fetch(processUrl, { method: 'POST', headers: { 'Accept': 'application/json', 'X-CSRFToken': csrfInput.value } })
          : await fetch(progressPanel.dataset.statusUrl, { headers: { 'Accept': 'application/json' } });
        const body = await res.json();
        const state = body.pipeline_state || '';
        if (state === 'ready' || state === 'manual_review' || (body.draft && body.draft.status === 'succeeded')) {
          clearInterval(timer);
          window.location.reload();
        } else {
          const badge = progressPanel.querySelector('[data-ai-draft-progress-badge]');
          if (badge && body.queue_label) badge.textContent = body.queue_label;
        }
      } catch (e) { /* transient — try again next tick */ }
      finally { inFlight = false; }
    }, 4000);
  }

  /* Live thumbnail previews for the bulk gallery picker. */
  const input = document.querySelector('[data-bulk-gallery]');
  const preview = document.querySelector('[data-bulk-gallery-preview]');
  if (!input || !preview) return;

  input.addEventListener('change', function () {
    preview.innerHTML = '';
    const files = Array.from(input.files || []);
    preview.classList.toggle('is-visible', files.length > 0);
    if (!files.length) return;
    files.forEach(function (file) {
      if (!file.type || !file.type.startsWith('image/')) return;
      const img = document.createElement('img');
      img.alt = file.name;
      img.onload = function () { URL.revokeObjectURL(img.src); };
      img.src = URL.createObjectURL(file);
      preview.appendChild(img);
    });
    const count = document.createElement('span');
    count.className = 'zd-bulk-gallery-preview__count';
    count.textContent = files.length + ' image' + (files.length === 1 ? '' : 's') + ' ready to upload';
    preview.appendChild(count);
  });
});
