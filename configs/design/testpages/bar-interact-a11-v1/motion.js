// bar-interact-a11-v1 (Design, queue #113): the cards on the second screen rise into view when they
// are scrolled to (a class change on scroll). Their look is in motion.css, inside
// prefers-reduced-motion: no-preference, so under reduce the class changes nothing.
const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }
}, {threshold: 0.15});
document.querySelectorAll('.reveal').forEach((el) => io.observe(el));
