// The Lens: the one shape that never leaves the screen (docs/frontend/13-storyboard.md, Part 2).
// Its size comes from `className` and its content; when either changes, the same element springs to the new size
// while the content swaps with a short blur.
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { springs, swap, type SpringName } from "./motion";

export type LensTone = "ink" | "track" | "danger";

const tones: Record<LensTone, string> = {
  ink: "bg-ink text-canvas",
  track: "bg-deep text-ink",
  danger: "bg-danger text-on-status",
};

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
    <motion.div layout transition={springs[spring]} style={{ borderRadius: radius }}
      className={`relative overflow-hidden shadow-lens transition-colors duration-300 ${tones[tone]} ${className}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div key={scene} layout="position" {...swap} transition={{ duration: 0.2, layout: springs[spring] }} className="h-full">
          {children}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  );
}
