// Mock HTMLCanvasElement.getContext for jsdom (which lacks native canvas).
// jsdom defines getContext but throws when called; unconditionally replace it
// with a working mock to ensure R3F scene tests can create procedural textures.
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = function (contextType: string) {
    // Return mock for any context type (2d, webgl, webgl2) to support both
    // Canvas 2D texture creation and R3F WebGL renderer initialization.
    return { ...createCanvasMock() } as ReturnType<HTMLCanvasElement["getContext"]>;
  };
}

function createCanvasMock() {
  const ctx: Record<string, unknown> = {};
  const methods = [
    "fillRect", "clearRect", "getImageData", "putImageData", "createImageData",
    "setTransform", "resetTransform", "drawImage", "save", "restore",
    "beginPath", "moveTo", "lineTo", "closePath", "stroke", "fill", "clip",
    "rect", "arc", "ellipse", "measureText", "createLinearGradient", "createRadialGradient",
    "createPattern", "translate", "scale", "rotate", "transform", "font",
    "textAlign", "textBaseline", "fillText", "strokeText",
    "drawFocusFromIfNeeded", "scrollPathIntoView", "getBoxObjectFor",
    "canvas", "acquireImage", "checkImgSrcChanged",
    "setLineDash", "lineDashOffset",
  ];
  methods.forEach((m) => { ctx[m] = () => {}; });
  ctx.createLinearGradient = () =>
    ({ addColorStop: () => {}, getColorStop: () => ({ offset: 0, color: "" }) });
  ctx.createRadialGradient = () => ctx.createLinearGradient(null);
  ctx.measureText = () => ({
    width: 0, actualBoundingBoxLeft: 0, actualBoundingBoxRight: 0,
    actualBoundingBoxAscent: 0, actualBoundingBoxDescent: 0,
    fontBoundingBoxAscent: 0, fontBoundingBoxDescent: 0,
    alphabeticBaseline: 0, hangingBaseline: 0, ideographicBaseline: 0,
  });
  return ctx;
}

import "./src/i18n";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Mock localStorage for zustand persist middleware
const store: Record<string, string> = {};
(globalThis as unknown as { localStorage: Storage }).localStorage = {
  getItem: (key: string) => (key in store ? store[key] : null),
  setItem: (key: string, value: string) => { store[key] = value; },
  removeItem: (key: string) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  key: (i: number) => Object.keys(store)[i] || null,
  get length() { return Object.keys(store).length; },
} as Storage;
