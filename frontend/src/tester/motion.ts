// Motion presets (docs/frontend/13-storyboard.md §1.4).

export const springs = {
  /** The Lens changing size and curve: firm, no visible overshoot. */
  morph: { type: "spring", duration: 0.45, bounce: 0 },
  /** Pills stretching sideways: overshoots by a hair, then settles. */
  rubber: { type: "spring", duration: 0.55, bounce: 0.2 },
  /** Large objects coming to rest. */
  settle: { type: "spring", duration: 0.7, bounce: 0 },
} as const;

export type SpringName = keyof typeof springs;

/** Content change inside a shape: the old content blurs out, the new sharpens in. */
export const swap = {
  initial: { opacity: 0, filter: "blur(6px)" },
  animate: { opacity: 1, filter: "blur(0px)" },
  exit: { opacity: 0, filter: "blur(6px)" },
} as const;
