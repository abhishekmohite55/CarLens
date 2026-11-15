// A number that arrives on rolling drums, like an odometer (Scene 14): each digit column spins and stops, right to left.
import { motion } from "motion/react";
import { springs } from "./motion";

const DIGITS = "0123456789";

export function RollingNumber({ text, className = "" }: { text: string; className?: string }) {
  const chars = [...text];
  return (
    <span className={`inline-flex flex-wrap tabular-nums ${className}`} aria-label={text}>
      {chars.map((char, i) => {
        const digit = DIGITS.indexOf(char);
        if (digit < 0) return <span key={i} aria-hidden className="whitespace-pre">{char}</span>;
        return (
          <span key={i} aria-hidden className="inline-block h-[1em] overflow-hidden leading-none">
            <motion.span className="flex flex-col" initial={{ y: 0 }} animate={{ y: `-${digit}em` }}
              transition={{ ...springs.settle, delay: (chars.length - i) * 0.05 }}>
              {[...DIGITS].map((d) => <span key={d} className="h-[1em]">{d}</span>)}
            </motion.span>
          </span>
        );
      })}
    </span>
  );
}
