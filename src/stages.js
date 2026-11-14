// The stages of a scene load, shared by the load worker (which reports them) and the page
// (which shows them). Pure.

// Stages in order, with the share of the whole load at which each one starts. The load
// worker reports { stage, within } (within = fraction of that stage done); the page turns
// that into a progress bar and a status line.
export const STAGES = {
  download: 0,
  parse: 0.45,
  normals: 0.65,
  lighting: 0.8,
  pack: 0.9,
  upload: 0.98,
};

// Overall fraction (0–1) for a stage and the fraction of that stage done.
export function overallProgress(stage, within = 0) {
  const names = Object.keys(STAGES);
  const k = names.indexOf(stage);
  const start = STAGES[stage] ?? 0;
  const end = k >= 0 && k + 1 < names.length ? STAGES[names[k + 1]] : 1;
  return start + (end - start) * Math.max(0, Math.min(1, within));
}
