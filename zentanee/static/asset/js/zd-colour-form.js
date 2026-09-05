/* "Add a colour" page: live preview of the new swatch while staff type and
   pick the cover photo, plus SKU and title suggestions that follow the colour
   name until staff edit those fields themselves. */
document.addEventListener('DOMContentLoaded', function () {
  const form = document.querySelector('[data-colour-form]');
  const colourInput = document.querySelector('input[name="color"]');
  const coverInput = document.querySelector('input[name="product_image"]');
  const skuInput = document.querySelector('input[name="sku"]');
  const titleInput = document.querySelector('input[name="title"]');
  const previewBox = document.querySelector('[data-colour-preview]');
  const previewLabel = document.querySelector('[data-colour-preview-label]');

  const skuBase = form ? (form.dataset.skuBase || '') : '';
  const sourceTitle = form ? (form.dataset.sourceTitle || '') : '';
  const sourceColour = form ? (form.dataset.sourceColour || '') : '';

  function token(value) {
    return value.normalize('NFKD').replace(/[^\w\s-]/g, '').trim().replace(/[\s_-]+/g, '').toUpperCase().slice(0, 24);
  }

  function suggestedSku(colour) {
    const t = token(colour) || 'ALT';
    return skuBase ? skuBase + '-' + t : t;
  }

  function suggestedTitle(colour) {
    if (!sourceColour || !colour) return sourceTitle;
    const pattern = new RegExp('\\b' + sourceColour.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i');
    return pattern.test(sourceTitle) ? sourceTitle.replace(pattern, colour) : sourceTitle;
  }

  /* A field is "auto" until staff type into it; auto fields follow the colour. */
  let skuIsAuto = !!skuInput && skuInput.value === suggestedSku('');
  let titleIsAuto = !!titleInput && titleInput.value === sourceTitle;
  if (skuInput) skuInput.addEventListener('input', function () { skuIsAuto = false; });
  if (titleInput) titleInput.addEventListener('input', function () { titleIsAuto = false; });

  if (colourInput) {
    const sync = function () {
      const value = colourInput.value.trim();
      if (previewLabel) previewLabel.textContent = value || 'New colour';
      if (skuInput && skuIsAuto) skuInput.value = suggestedSku(value);
      if (titleInput && titleIsAuto) titleInput.value = suggestedTitle(value);
    };
    colourInput.addEventListener('input', sync);
    sync();
  }

  if (coverInput && previewBox) {
    coverInput.addEventListener('change', function () {
      const file = coverInput.files && coverInput.files[0];
      previewBox.innerHTML = '';
      previewBox.classList.toggle('zd-colour-swatch-img--empty', !file);
      if (!file || !file.type || !file.type.startsWith('image/')) {
        previewBox.innerHTML = '<span aria-hidden="true">+</span>';
        return;
      }
      const img = document.createElement('img');
      img.alt = '';
      img.onload = function () { URL.revokeObjectURL(img.src); };
      img.src = URL.createObjectURL(file);
      previewBox.appendChild(img);
    });
  }
});
