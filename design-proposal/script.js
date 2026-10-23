const tabs = [...document.querySelectorAll('[role="tab"]')];
const panels = [...document.querySelectorAll('[role="tabpanel"]')];

function showPanel(name) {
  tabs.forEach(tab => {
    const active = tab.dataset.panel === name;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  panels.forEach(panel => {
    const active = panel.id === `panel-${name}`;
    panel.classList.toggle('is-active', active);
    panel.hidden = !active;
  });
}

const initialPanel = location.hash.slice(1);
showPanel(tabs.some(tab => tab.dataset.panel === initialPanel) ? initialPanel : 'discover');

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => showPanel(tab.dataset.panel));
  tab.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[target].focus();
    showPanel(tabs[target].dataset.panel);
  });
});

document.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => showPanel(button.dataset.go)));

// Deterministic stars keep the visual stable between screenshots.
let seed = 17;
function random() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
document.querySelectorAll('.starfield').forEach(surface => {
  const stars = document.createElement('div');
  stars.className = 'stars';
  stars.setAttribute('aria-hidden', 'true');
  for (let i = 0; i < 145; i++) {
    const star = document.createElement('i');
    const size = random() > .93 ? 2.5 : random() > .6 ? 1.5 : 1;
    star.style.cssText = `left:${(random() * 100).toFixed(2)}%;top:${(random() * 100).toFixed(2)}%;width:${size}px;height:${size}px;opacity:${(.22 + random() * .65).toFixed(2)}`;
    stars.append(star);
  }
  surface.prepend(stars);
});
