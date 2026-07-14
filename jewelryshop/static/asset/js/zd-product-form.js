/* Dashboard product form behaviors (extracted from inline template scripts). */
document.addEventListener('DOMContentLoaded', function () {
  /* Poll draft status while Gemini works in the background task queue. */
  const progressPanel = document.querySelector('[data-ai-draft-progress]');
  if (progressPanel) {
    const timer = setInterval(async function () {
      try {
        const res = await fetch(progressPanel.dataset.statusUrl, { headers: { 'Accept': 'application/json' } });
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
