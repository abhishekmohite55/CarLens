// The Lens: the one shape that never leaves the screen (docs/frontend/13-storyboard.md, Part 2).
// Its size comes from `className` and its content; when either changes, the same shape springs to the new size
// while the content swaps with a short blur. Every Lens shares one layoutId, so when a page change replaces one Lens
// with another, the shape morphs from the old place and size to the new one instead of being cut.
// Rubber band (F10): a second, slower copy of the shape ("trail") sits behind it in the same grid cell, so the
// leading edge moves first and the trailing edge follows a moment later.
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { springs, swap, type SpringName } from "./motion";

export type LensTone = "ink" | "track" | "danger";

const tones: Record<LensTone, string> = {
  ink: "bg-ink text-canvas",
  track: "bg-deep text-ink",
  danger: "bg-danger text-on-status",
};
const surfaces: Record<LensTone, string> = { ink: "bg-ink", track: "bg-deep", danger: "bg-danger" };
const TRAIL = { type: "spring", duration: 0.75, bounce: 0.12 } as const;

export function Lens({ scene, radius, tone = "ink", spring = "morph", className = "", children }: {
  /** Names the current content; a new name swaps the content. */
  scene: string;
  /** Corner radius in px (half the height for a pill, 32 for an open card). */
  radius: number;
  tone?: LensTone;
  spring?: SpringName;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`relative inline-grid ${className}`}>
      <motion.div layoutId="lens-trail" layout transition={TRAIL} style={{ borderRadius: radius }} aria-hidden
        className={`shadow-lens transition-colors duration-300 [grid-area:1/1] ${surfaces[tone]}`} />
      <motion.div layoutId="lens" layout transition={springs[spring]} style={{ borderRadius: radius }}
        className={`relative overflow-hidden transition-colors duration-300 [grid-area:1/1] ${tones[tone]}`}>
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.div key={scene} layout="position" {...swap} transition={{ duration: 0.2, layout: springs[spring] }} className="h-full">
            {children}
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
