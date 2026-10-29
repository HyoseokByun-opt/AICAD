/* Line icons (24 x 24, two-tone: strokes use currentColor, fills use --ic).
   Inline SVG only: the program must work on an isolated network. */
(function () {
  "use strict";
  const S = 'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"';
  const F = 'fill="var(--ic, #cfe2ff)" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"';
  const P = {
    // the AICAD mark: an isometric solid with a section cut and the AI spark
    logo: `<path d="M12 1.6 21.2 6.9v10.4L12 22.6 2.8 17.3V6.9z" fill="#0b62c4"/><path d="M12 1.6 21.2 6.9 12 12.2 2.8 6.9z" fill="#5fa2ea"/><path d="M12 12.2 21.2 6.9v10.4L12 22.6z" fill="#084c98"/><path d="M7.4 9.55 12 12.2v5.3l-4.6-2.65z" fill="#ffffff" opacity=".92"/><path d="M17.6 1.4l.75 1.85 1.85.75-1.85.75-.75 1.85-.75-1.85L15 4l1.85-.75z" fill="#8250df" stroke="#fff" stroke-width=".6"/>`,
    new: `<path ${F} d="M6 3h8l4 4v14H6z"/><path ${S} d="M14 3v4h4M12 11v6M9 14h6"/>`,
    open: `<path ${F} d="M3 7h6l2 2h10v10H3z"/><path ${S} d="M3 11h18"/>`,
    examples: `<rect ${F} x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect ${S} x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect ${S} x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect ${F} x="13.5" y="13.5" width="7" height="7" rx="1.5"/>`,
    import: `<path ${F} d="M5 3h9l5 5v13H5z"/><path ${S} d="M14 3v5h5M12 10v7M9 14l3 3 3-3"/>`,
    sheet: `<rect ${F} x="3" y="4" width="18" height="16" rx="1.5"/><path ${S} d="M6 8h6v5H6zM14 8h4M14 11h4M6 16h12M15 14v4"/>`,
    describe: `<path ${F} d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z"/><path ${S} d="M8 8h8M8 11.5h5"/>`,
    generate: `<path ${F} d="M11 5 18 9v8l-7 4-7-4V9z"/><path ${S} d="M4 9l7 4 7-4M11 13v8"/><path d="M19 1.5l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z" fill="#8250df"/>`,
    read: `<path ${F} d="M5 3h9l5 5v13H5z"/><path ${S} d="M14 3v5h5"/><circle ${S} cx="11" cy="14" r="3.2"/><path ${S} d="M13.4 16.4 16 19"/>`,
    values: `<rect ${F} x="3.5" y="4.5" width="17" height="15" rx="2"/><path ${S} d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10"/>`,
    play: `<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>`,
    stop: `<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor"/>`,
    spark: `<path d="M12 2.5l2.2 5.3 5.3 2.2-5.3 2.2L12 17.5l-2.2-5.3L4.5 10l5.3-2.2z" fill="currentColor"/>`,
    cube: `<path ${F} d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path ${S} d="M4 7.5 12 12l8-4.5M12 12v9"/>`,
    compare: `<rect ${F} x="3" y="5" width="7.5" height="14" rx="1.5"/><rect ${S} x="13.5" y="5" width="7.5" height="14" rx="1.5"/><path ${S} d="M5.5 9h2.5M5.5 12h2.5M16 9h2.5M16 12h2.5"/>`,
    code: `<rect ${F} x="3" y="4" width="18" height="16" rx="2"/><path ${S} d="M9 9.5 6.5 12 9 14.5M15 9.5l2.5 2.5-2.5 2.5M13 8.5l-2 7"/>`,
    rebuild: `<path ${S} d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path ${S} d="M19.5 4v4.5H15"/><path ${F} d="M12 8.5 15 10v3.5L12 15l-3-1.5V10z"/>`,
    params: `<path ${S} d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle ${F} cx="15" cy="6" r="2"/><circle ${F} cx="9" cy="12" r="2"/><circle ${F} cx="17" cy="18" r="2"/>`,
    history: `<circle ${F} cx="12" cy="12" r="8.5"/><path ${S} d="M12 7.5V12l3 2"/>`,
    prev: `<path ${S} d="M14.5 6 8.5 12l6 6"/>`,
    next: `<path ${S} d="M9.5 6l6 6-6 6"/>`,
    refine: `<path ${F} d="M4 4h7v7H4z"/><path ${S} d="M13 13h7v7h-7z"/><path ${S} d="M14 6.5h4.5V11M10 17.5H5.5V13"/><path ${S} d="M16.5 4.5l2 2-2 2M7.5 19.5l-2-2 2-2"/>`,
    edit: `<path ${F} d="M4 20l1-4.5L15.5 5l3.5 3.5L8.5 19z"/><path ${S} d="M13.5 7l3.5 3.5"/><path d="M19.5 14l.7 1.7 1.7.7-1.7.7-.7 1.7-.7-1.7-1.7-.7 1.7-.7z" fill="#8250df"/>`,
    chip: `<rect ${F} x="6" y="6" width="12" height="12" rx="2"/><path ${S} d="M9 2.5v3.5M12 2.5v3.5M15 2.5v3.5M9 18v3.5M12 18v3.5M15 18v3.5M2.5 9H6M2.5 12H6M2.5 15H6M18 9h3.5M18 12h3.5M18 15h3.5"/><path ${S} d="M9.5 14.5l1.5-5h2l1.5 5M10.2 12.8h3.6"/>`,
    power: `<path ${S} d="M12 3.5v8"/><path ${S} d="M7.2 6.5a7.5 7.5 0 1 0 9.6 0"/>`,
    gear: `<circle ${S} cx="12" cy="12" r="3"/><path ${F} fill-opacity=".45" d="M12 2.8l1.6 2.3 2.7-.7.6 2.7 2.6 1-1 2.6 1.8 2.1-2.1 1.8 1 2.6-2.6 1-.6 2.7-2.7-.7L12 21.2l-1.6-2.3-2.7.7-.6-2.7-2.6-1 1-2.6-1.8-2.1 2.1-1.8-1-2.6 2.6-1 .6-2.7 2.7.7z"/><circle ${S} cx="12" cy="12" r="3"/>`,
    step: `<path ${F} d="M5 3h9l5 5v13H5z"/><path ${S} d="M14 3v5h5"/><path ${S} d="M12 10.5l3.5 2v4L12 18.5l-3.5-2v-4z"/>`,
    stl: `<path ${F} d="M12 3.5 20 18H4z"/><path ${S} d="M12 3.5 9 18M12 3.5 15 18M6.5 13.5h11"/>`,
    glb: `<circle ${F} cx="12" cy="12" r="8.5"/><ellipse ${S} cx="12" cy="12" rx="3.6" ry="8.5"/><path ${S} d="M3.5 12h17"/>`,
    dxf: `<rect ${F} x="3" y="4" width="18" height="16" rx="1.5"/><path ${S} d="M6 15V8h5v7zM13 8h5M13 11h5M6 18h12" /><path ${S} stroke-dasharray="1.6 1.4" d="M8.5 8v7"/>`,
    brep: `<path ${F} d="M4 8l8-4.5L20 8v8l-8 4.5L4 16z"/><path ${S} d="M8 10.2v5.6l4 2.2 4-2.2v-5.6L12 8z"/>`,
    zip: `<path ${F} d="M6 3h12v18H6z"/><path ${S} d="M12 3v2M12 7v2M12 11v2M10.5 14h3v4h-3z"/>`,
    python: `<path ${F} d="M12 3c-3.5 0-4.5 1.3-4.5 3v2.5h4.5v1H6c-2 0-3 1.4-3 3.5s1 3.5 3 3.5h1.5v-2.5c0-1.6 1.2-3 3-3h4.5c1.4 0 2.5-1 2.5-2.5V6c0-1.7-1.5-3-6-3z"/><path ${S} d="M12 21c3.5 0 4.5-1.3 4.5-3v-2.5H12v-1h6c2 0 3-1.4 3-3.5s-1-3.5-3-3.5h-1.5"/><circle cx="10" cy="5.6" r=".9" fill="currentColor"/>`,
    camera: `<path ${F} d="M4 8h3l1.8-2.5h6.4L17 8h3v11H4z"/><circle ${S} cx="12" cy="13.3" r="3.3"/>`,
    fit: `<path ${S} d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>`,
    ruler: `<path ${F} d="M3 16.5 16.5 3 21 7.5 7.5 21z"/><path ${S} d="M7 12.5l1.8 1.8M9.8 9.7l1.3 1.3M12.6 6.9l1.8 1.8M15.4 4.1l1.3 1.3"/>`,
    target: `<circle ${F} cx="12" cy="12" r="7.5"/><circle ${S} cx="12" cy="12" r="3.2"/><path ${S} d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/>`,
    views: `<rect ${F} x="3.5" y="3.5" width="7.5" height="7.5" rx="1"/><rect ${S} x="13" y="3.5" width="7.5" height="7.5" rx="1"/><rect ${S} x="3.5" y="13" width="7.5" height="7.5" rx="1"/>`,
    section: `<path ${F} d="M12 3 20 7.5v9L12 21l-8-4.5v-9z" fill-opacity=".5"/><path ${S} d="M2.5 13.5 21.5 9.5M4 7.5 12 12l8-4.5"/>`,
    layers: `<path ${F} d="M12 4 21 8.5 12 13 3 8.5z"/><path ${S} d="M3 12.5l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>`,
    info: `<circle ${F} cx="12" cy="12" r="8.5"/><path ${S} d="M12 11v5.5M12 7.6v.1"/>`,
    warn: `<path ${F} d="M12 3.5 21 19.5H3z"/><path ${S} d="M12 9.5v4.5M12 16.8v.1"/>`,
    ok: `<circle ${F} cx="12" cy="12" r="8.5"/><path ${S} d="M8 12.3l2.6 2.6L16 9.5"/>`,
    error: `<circle ${F} cx="12" cy="12" r="8.5"/><path ${S} d="M9 9l6 6M15 9l-6 6"/>`,
    delete: `<path ${S} d="M4 7h16M9 7V4h6v3"/><path ${F} d="M6 7l1 13h10l1-13"/><path ${S} d="M10 11v6M14 11v6"/>`,
    chevron: `<path ${S} d="M9 6l6 6-6 6"/>`,
    plus: `<path ${S} d="M12 5v14M5 12h14"/>`,
    download: `<path ${S} d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/>`,
    collapse: `<path ${S} d="M6 9l6 6 6-6"/>`,
    folder: `<path ${F} d="M3 6h6l2 2h10v11H3z"/>`,
    eye: `<path ${F} d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle ${S} cx="12" cy="12" r="3"/>`,
    gpu: `<rect ${F} x="2.5" y="6" width="19" height="11" rx="1.5"/><circle ${S} cx="9" cy="11.5" r="3"/><path ${S} d="M15 9.5h4M15 12.5h4M5 17v2.5M8 17v2.5M11 17v2.5"/>`,
  };
  window.ICON = function (name, cls) {
    const body = P[name] || P.info;
    return `<svg class="ico${cls ? " " + cls : ""}" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
  };
  window.ICON_NAMES = Object.keys(P);
})();
