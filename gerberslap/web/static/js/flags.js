// Languages offered by the interface, each with an inline SVG flag (emoji flags are not drawn on every platform, Windows for one).
// Adding a language means adding a catalogue in i18n.js and one entry here.
const svg = (viewBox, body) => `<svg viewBox="${viewBox}" width="24" height="16" aria-hidden="true" focusable="false">${body}</svg>`;

export const LANGS = [
  { id: 'it', name: 'Italiano',
    flag: svg('0 0 3 2', '<rect width="1" height="2" fill="#009246"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#ce2b37"/>') },
  { id: 'en', name: 'English',
    flag: svg('0 0 60 40', '<rect width="60" height="40" fill="#012169"/><path d="M0 0L60 40M60 0L0 40" stroke="#fff" stroke-width="8"/><path d="M0 0L60 40M60 0L0 40" stroke="#c8102e" stroke-width="3"/>'
      + '<path d="M30 0V40M0 20H60" stroke="#fff" stroke-width="12"/><path d="M30 0V40M0 20H60" stroke="#c8102e" stroke-width="7"/>') },
];
