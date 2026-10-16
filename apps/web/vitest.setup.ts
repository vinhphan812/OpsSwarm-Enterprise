// Mock HTMLCanvasElement.getContext for jsdom (which lacks native canvas).
// jsdom auto-discovers the 'canvas' package if installed; this supplements
// it with a basic 2D fallback for procedural texture creation in R3F scenes.
if (typeof HTMLCanvasElement !== "undefined" && !HTMLCanvasElement.prototype.getContext) {
  HTMLCanvasElement.prototype.getContext = function (contextType: string) {
    return { ...createCanvasMock() } as ReturnType<HTMLCanvasElement["getContext"]>;
  };
}

function createCanvasMock() {
  const ctx: Record<string, unknown> = {};
  const methods = [
    "fillRect", "clearRect", "getImageData", "putImageData", "createImageData",
    "setTransform", "resetTransform", "drawImage", "save", "restore",
    "beginPath", "moveTo", "lineTo", "closePath", "stroke", "fill", "clip",
    "rect", "arc", "measureText", "createLinearGradient", "createRadialGradient",
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
