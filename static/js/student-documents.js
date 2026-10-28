document.querySelectorAll('[data-student-card-image]').forEach((image) => {
  const showError = () => {
    image.closest('a').hidden = true;
    image.closest('figure').querySelector('[data-card-image-error]').hidden = false;
  };
  image.addEventListener('error', showError);
  if (image.complete && !image.naturalWidth) showError();
});
