// The car on its turntable: a 3D wireframe projected to a 2D canvas each frame (no 3D engine).
// Line colour = the canvas's CSS `color`; turntable --c-deep; pins --c-ink. All follow the theme.
// The car's shape comes from car.ts (swappable model); this file only draws it.
import { useEffect, useRef } from "react";
import { CAR, FLOOR_SQUASH, FLOOR_UP, project, SPOTS, type Spot } from "./car";

const DRAW_IN_MS = 1200;
const FIRST_ANGLE = 0.6;
const TURNTABLE = 2.35; // radius in metres
const PIN_DROP_MS = 450;
const TURN_EASE = 3.2; // how quickly the car turns to a requested view (higher = faster)

/** solid = confirmed; faded = rejected (drawn small and quiet). */
export type CarPin = { spot: Spot; solid?: boolean; faded?: boolean };

type Props = {
  /** Seconds per full turn while no view is requested. */
  secondsPerTurn?: number;
  /** Turn to this angle and hold (see VIEWS in car.ts); undefined = keep turning. */
  view?: number;
  pins?: CarPin[];
  /** A ring pulses around this pin (the loupe resting on it). */
  checking?: Spot;
  className?: string;
};

export function Car3D({ secondsPerTurn = 24, view, pins = [], checking, className = "" }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const props = useRef({ view, pins, checking });
  props.current = { view, pins, checking };

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let width = 0, height = 0, line = "", floor = "", ink = "", paper = "", visible = true, frame = 0;
    const started = performance.now();
    let angle = FIRST_ANGLE, last = started;
    const pinSince = new Map<Spot, number>(); // when each pin first appeared, for its drop

    const render = (now: number) => {
      if (!width || !height) return;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const { view: target, pins: shownPins, checking: checked } = props.current;
      if (target !== undefined) {
        const diff = Math.atan2(Math.sin(target - angle), Math.cos(target - angle)); // shortest way round
        angle = still ? target : angle + diff * (1 - Math.exp(-dt * TURN_EASE));
      } else if (!still) {
        angle += (dt / secondsPerTurn) * 2 * Math.PI;
      }
      const elapsed = now - started;
      const shown = still ? CAR.length : Math.min(CAR.length, (elapsed / DRAW_IN_MS) * CAR.length);
      const scale = Math.min(width / 5.4, height / 3.1); // px per metre
      const cx = width / 2, cy = height / 2;
      const fade = (depth: number) => Math.max(0.3, Math.min(1, 0.3 + (0.7 * (depth + 2.2)) / 4.4)); // far = fainter

      ctx.clearRect(0, 0, width, height);
      ctx.globalAlpha = 1;
      ctx.fillStyle = floor;
      ctx.beginPath();
      ctx.ellipse(cx, cy - FLOOR_UP * scale, TURNTABLE * scale, TURNTABLE * scale * FLOOR_SQUASH, 0, 0, 2 * Math.PI);
      ctx.fill();

      ctx.strokeStyle = line;
      ctx.lineWidth = 1.5;
      ctx.lineCap = "round";
      for (let i = 0; i < shown; i++) {
        const [a, b] = CAR[i];
        const [ax, ay, ad] = project(a, angle);
        const [bx, by, bd] = project(b, angle);
        const part = Math.min(1, shown - i); // the edge being drawn right now is only partly there
        ctx.globalAlpha = fade((ad + bd) / 2);
        ctx.beginPath();
        ctx.moveTo(cx + ax * scale, cy - ay * scale);
        ctx.lineTo(cx + (ax + (bx - ax) * part) * scale, cy - (ay + (by - ay) * part) * scale);
        ctx.stroke();
      }

      for (const spot of pinSince.keys()) if (!shownPins.some((p) => p.spot === spot)) pinSince.delete(spot);
      for (const pin of shownPins) {
        if (!pinSince.has(pin.spot)) pinSince.set(pin.spot, now);
        const t = still ? 1 : Math.min(1, (now - pinSince.get(pin.spot)!) / PIN_DROP_MS);
        const drop = (1 - t) ** 3 * 0.5; // falls the last half metre, slowing as it lands
        const [px, py, pd] = project(SPOTS[pin.spot], angle);
        const x = cx + px * scale, y = cy - (py + drop) * scale;
        ctx.globalAlpha = t * fade(pd);
        if (pin.spot === checked && !still) {
          const pulse = (now % 1400) / 1400;
          ctx.globalAlpha = t * (1 - pulse);
          ctx.strokeStyle = ink;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(x, y, 8 + pulse * 18, 0, 2 * Math.PI);
          ctx.stroke();
          ctx.globalAlpha = t * fade(pd);
        }
        ctx.fillStyle = pin.solid ? ink : paper;
        ctx.strokeStyle = pin.faded ? line : ink;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, pin.faded ? 3.5 : 6, 0, 2 * Math.PI);
        ctx.fill();
        ctx.stroke();
      }
    };

    const readColours = () => {
      const style = getComputedStyle(canvas);
      line = style.color;
      floor = style.getPropertyValue("--c-deep");
      ink = style.getPropertyValue("--c-ink");
      paper = style.getPropertyValue("--c-canvas");
      if (still) render(performance.now());
    };
    const fit = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      if (still) render(performance.now());
    };
    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      if (visible) render(now); // nothing is drawn while the car is scrolled out of view
      else last = now;
    };

    const themeWatch = new MutationObserver(readColours);
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const sizeWatch = new ResizeObserver(fit);
    sizeWatch.observe(canvas);
    const viewWatch = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; });
    viewWatch.observe(canvas);
    readColours();
    fit();
    frame = requestAnimationFrame(loop); // with reduced motion the loop still places pins and views, without movement

    return () => {
      cancelAnimationFrame(frame);
      themeWatch.disconnect();
      sizeWatch.disconnect();
      viewWatch.disconnect();
    };
  }, [secondsPerTurn]);

  return <canvas ref={ref} role="img" aria-label="Line drawing of a car" className={`block text-line-strong ${className}`} />;
}
