// The car: a generic hatchback as 3D line segments (docs/frontend/13-storyboard.md §1.5). No brand.
// Units are metres. x points forward, y to the car's left, z up; the ground is z = 0.
// The model is swappable (owner, 13 Nov): a new model replaces CAR and SPOTS only; Car3D.tsx draws whatever is here.
// Assumed: a car of normal size (about 4 m long) centred on the origin.

export type Point = [number, number, number];
export type Edge = [Point, Point];

const WHEEL_X = 1.22;
const WHEEL_Z = 0.32; // wheel centre height = wheel radius
const ARCH = 0.4;
const SIDE = 0.82; // half-width of the lower body

// Side outline over the top, front to rear: [x, z, half-width at that point].
const TOP: [number, number, number][] = [
  [1.93, 0.3, 0.78], [2.0, 0.48, 0.8], [1.96, 0.7, 0.8], [1.05, 0.88, 0.82],
  [0.4, 1.36, 0.66], [-1.0, 1.4, 0.66], [-1.55, 1.28, 0.7], [-1.88, 0.94, 0.8],
  [-2.0, 0.74, 0.82], [-2.0, 0.46, 0.8], [-1.92, 0.3, 0.78],
];
const GLASS: [number, number, number][] = [
  [0.98, 0.92, 0.8], [0.42, 1.31, 0.67], [-0.98, 1.35, 0.67], [-1.5, 1.24, 0.7], [-1.72, 0.98, 0.79],
];

function line(points: Point[], closed = false): Edge[] {
  const edges: Edge[] = [];
  for (let i = 1; i < points.length; i++) edges.push([points[i - 1], points[i]]);
  if (closed) edges.push([points[points.length - 1], points[0]]);
  return edges;
}

/** Part of a circle in the car's side plane, centre (cx, y, cz), from angle `from` to `to` (radians). */
function arc(cx: number, y: number, cz: number, r: number, from: number, to: number, steps: number): Point[] {
  const points: Point[] = [];
  for (let i = 0; i <= steps; i++) {
    const a = from + ((to - from) * i) / steps;
    points.push([cx + r * Math.cos(a), y, cz + r * Math.sin(a)]);
  }
  return points;
}

function build(): Edge[] {
  const arches: Edge[] = [], roofline: Edge[] = [], rest: Edge[] = [], wheels: Edge[] = [];
  for (const s of [1, -1]) {
    const at = ([x, z, half]: [number, number, number]): Point => [x, s * half, z];
    for (const wx of [WHEEL_X, -WHEEL_X]) {
      arches.push(...line(arc(wx, s * SIDE, WHEEL_Z, ARCH, 0, Math.PI, 10)));
      wheels.push(...line(arc(wx, s * 0.86, WHEEL_Z, WHEEL_Z, 0, 2 * Math.PI, 22)));
      wheels.push(...line(arc(wx, s * 0.86, WHEEL_Z, 0.15, 0, 2 * Math.PI, 10)));
      wheels.push(...line(arc(wx, s * 0.64, WHEEL_Z, WHEEL_Z, 0, 2 * Math.PI, 22)));
    }
    roofline.push(...line(TOP.map(at)));
    // Underside: rear end → rear arch, sill between the arches, front arch → front end.
    rest.push([at(TOP[10]), [-WHEEL_X - ARCH, s * SIDE, WHEEL_Z]]);
    rest.push([[-WHEEL_X + ARCH, s * SIDE, WHEEL_Z], [WHEEL_X - ARCH, s * SIDE, WHEEL_Z]]);
    rest.push([[WHEEL_X + ARCH, s * SIDE, WHEEL_Z], at(TOP[0])]);
    rest.push(...line(GLASS.map(at), true));
    rest.push([[-0.25, s * 0.8, 0.94], [-0.25, s * 0.67, 1.33]]); // pillar between the doors
    rest.push([[-0.25, s * 0.83, 0.94], [-0.25, s * SIDE, WHEEL_Z]]); // door seams
    rest.push([[0.78, s * 0.82, 0.91], [0.78, s * SIDE, WHEEL_Z]]);
    rest.push([[1.985, s * 0.78, 0.62], [1.985, s * 0.42, 0.62]]); // headlight
    rest.push([[-1.995, s * 0.8, 0.8], [-1.995, s * 0.5, 0.8]]); // tail light
  }
  for (const [x, z, half] of TOP) rest.push([[x, half, z], [x, -half, z]]); // left ↔ right
  rest.push(...line([[-2.0, 0.26, 0.52], [-2.0, 0.26, 0.64], [-2.0, -0.26, 0.64], [-2.0, -0.26, 0.52]], true)); // rear plate
  // Drawing order (Scene 1): wheel arches first, then the roofline, then the rest.
  return [...arches, ...roofline, ...rest, ...wheels];
}

export const CAR: Edge[] = build();

/** Named places on the car where pins sit (Scenes 1 and 5): one per thing the pipeline looks for. */
export const SPOTS = {
  plate: [-2.0, 0, 0.58],
  badge: [-1.98, -0.4, 0.86],
  dashboard: [0.55, 0.3, 1.0],
  tyre_front_left: [WHEEL_X, 0.86, WHEEL_Z],
  tyre_front_right: [WHEEL_X, -0.86, WHEEL_Z],
  tyre_rear_left: [-WHEEL_X, 0.86, WHEEL_Z],
  tyre_rear_right: [-WHEEL_X, -0.86, WHEEL_Z],
  door_left_rear: [-0.75, 0.83, 0.62],
  door_left_front: [0.3, 0.83, 0.62],
  door_right_front: [0.3, -0.83, 0.62],
} satisfies Record<string, Point>;

export type Spot = keyof typeof SPOTS;

/** Turns that show one part of the car to the viewer (radians, as used by `project`). */
export const VIEWS = {
  front: 0.6, // front three-quarter, the resting view
  rear: Math.PI - 0.55, // rear three-quarter: plate and badge
  left: -1.15, // left side
} as const;

const PITCH = 0.3; // the viewer looks down on the car by about 17°
const CAMERA = 9; // viewer distance in metres: a mild perspective
const CENTRE_Z = 0.7;
export const FLOOR_UP = -CENTRE_Z * Math.cos(PITCH); // where the ground under the car's centre lands ("up" below)
export const FLOOR_SQUASH = Math.sin(PITCH); // a circle on the ground is seen as an ellipse this flat

/** Where a point lands on screen after the car has turned by `angle` radians: [right, up, depth], in metres. */
export function project([x, y, z]: Point, angle: number): [number, number, number] {
  const cos = Math.cos(angle), sin = Math.sin(angle);
  const right = x * sin + y * cos;
  const toward = x * cos - y * sin;
  const height = z - CENTRE_Z;
  const up = height * Math.cos(PITCH) - toward * Math.sin(PITCH);
  const depth = toward * Math.cos(PITCH) + height * Math.sin(PITCH);
  const zoom = CAMERA / (CAMERA - depth);
  return [right * zoom, up * zoom, depth];
}
