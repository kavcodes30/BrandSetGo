/* Shared shell state and a tiny hash router. Views import this, never app.js. */

export const state = { me: null, brands: [], path: "" };

export let render = () => {};
export let reloadShell = () => {};

export function setRenderers(renderFn, shellFn) {
  render = renderFn;
  reloadShell = shellFn;
}

export function navigate(path) {
  if (location.hash === `#${path}`) render();
  else location.hash = path;
}

export function refresh() {
  render();
}

export function brandById(id) {
  return state.brands.find((b) => b.id === id) || null;
}
