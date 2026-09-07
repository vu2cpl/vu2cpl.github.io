(function() {
  const lb       = document.getElementById('lightbox');
  if (!lb) return;
  const lbImg    = lb.querySelector('img');
  const lbCap    = lb.querySelector('.lightbox-caption');
  const lbClose  = lb.querySelector('.lightbox-close');

  function open(href, caption, alt) {
    lbImg.src = href;
    lbImg.alt = alt || '';
    lbCap.textContent = caption || '';
    lb.classList.add('open');
    lb.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    lb.classList.remove('open');
    lb.setAttribute('aria-hidden', 'true');
    lbImg.src = '';
    document.body.style.overflow = '';
  }

  document.querySelectorAll('a.shack-zoom').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      const img = a.querySelector('img');
      open(a.getAttribute('href'), a.dataset.caption || '', img ? img.alt : '');
    });
  });
  lbClose.addEventListener('click', close);
  lb.addEventListener('click', e => { if (e.target === lb) close(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && lb.classList.contains('open')) close();
  });
})();
