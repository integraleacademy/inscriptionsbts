document.querySelectorAll('.sw-card-face-switch').forEach((switcher) => {
  const buttons = switcher.querySelectorAll('[data-card-face-button]');
  const faces = switcher.closest('.sw-school-document').querySelectorAll('[data-card-face]');
  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      buttons.forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
      faces.forEach((face) => {
        face.hidden = face.dataset.cardFace !== button.dataset.cardFaceButton;
      });
    });
  });
});

document.querySelectorAll('[data-student-card-image]').forEach((image) => {
  const showError = () => {
    image.closest('a').hidden = true;
    image.closest('figure').querySelector('[data-card-image-error]').hidden = false;
  };
  image.addEventListener('error', showError);
  if (image.complete && !image.naturalWidth) showError();
});
