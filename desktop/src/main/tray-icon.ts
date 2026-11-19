// Menu-bar icon pixels (Requirement 8.2). The Sauri isotype (brand/sauri-isotype-small.svg, the variant for
// sizes of 32 px or less) is drawn in code from its polygons, so there are no image files to package or resolve.
// Template images are monochrome (black + alpha), so the four states are told apart by shape:
//   ready      the isotype alone
//   starting   the isotype outlined (hollow rounded square, diagonal gap and diamond kept)
//   processing the isotype plus a hollow ring badge at the bottom-right corner
//   error      the isotype plus a solid badge with a knocked-out "!" at the bottom-right corner
// The canvas is 18 pt (36 px at 2x), the usual menu-bar icon height; the isotype is 15 pt (30 px) and the
// badge uses the spare corner, so the isotype stays the same size and place in every state.
export type IconState = "starting" | "ready" | "processing" | "error";

export const ICON_SIZE = 36; // 18 pt at 2x
const BOX = 30; // isotype side in px, anchored at the top-left of the canvas
const SCALE = BOX / 100;
const SAMPLES = 4; // 4x4 supersampling per pixel for smooth edges

type Point = [number, number];

// Polygons of brand/sauri-isotype-small.svg (100 x 100 viewBox, clipped to a rounded square of radius 27).
const LIGHT_HALF: Point[] = [[-10, -10], [105.76, -10], [54.88, 40.88], [50, 36], [36, 50], [40.88, 54.88], [-10, 105.76]];
const DARK_HALF: Point[] = [[110, 110], [110, -5.76], [59.12, 45.12], [64, 50], [50, 64], [45.12, 59.12], [-5.76, 110]];
// Monochrome has no colour to separate the diamond from the halves, so it is drawn smaller than in the SVG
// (half-diagonal 12 instead of 14), the notch around it in the halves is widened to 17 and the diagonal gap to
// |x + y - 100| < 5.5.
const DIAMOND_REACH = 12;
const NOTCH_REACH = 17;
const GAP = 5.5;
const RADIUS = 27;

function inPolygon(x: number, y: number, polygon: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Signed distance (positive inside) to the isotype's rounded square, in isotype units. */
function insideDepth(x: number, y: number): number {
  const qx = Math.abs(x - 50) - (50 - RADIUS);
  const qy = Math.abs(y - 50) - (50 - RADIUS);
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - RADIUS;
  return -outside;
}

const STROKE = 9; // outline thickness in isotype units (~2.7 px)

function isotypeCovers(state: IconState, x: number, y: number): boolean {
  const depth = insideDepth(x, y);
  if (depth < 0) return false;
  if (Math.abs(x - 50) + Math.abs(y - 50) <= DIAMOND_REACH) return true;
  if (Math.abs(x + y - 100) < GAP || Math.abs(x - 50) + Math.abs(y - 50) < NOTCH_REACH) return false;
  if (state === "starting") return depth <= STROKE && (inPolygon(x, y, LIGHT_HALF) || inPolygon(x, y, DARK_HALF));
  return inPolygon(x, y, LIGHT_HALF) || inPolygon(x, y, DARK_HALF);
}

// Badge in canvas px.
const BADGE = { x: 28.5, y: 28.5, r: 7 };
const KNOCKOUT = 9.5; // isotype is cleared this far around the badge so it reads as a separate mark

function badgeCovers(state: IconState, px: number, py: number): boolean {
  const d = Math.hypot(px - BADGE.x, py - BADGE.y);
  if (state === "processing") return d <= BADGE.r && d >= BADGE.r - 2.6;
  if (state === "error") {
    if (d > BADGE.r) return false;
    const bar = Math.abs(px - BADGE.x) <= 1.1 && py >= BADGE.y - 4.2 && py <= BADGE.y + 0.8;
    const dot = Math.hypot(px - BADGE.x, py - (BADGE.y + 3.4)) <= 1.3;
    return !(bar || dot);
  }
  return false;
}

/** Black-on-transparent BGRA pixels for the state at 36 x 36 px (alpha carries the shape). */
export function iconPixels(state: IconState): Buffer {
  const pixels = Buffer.alloc(ICON_SIZE * ICON_SIZE * 4);
  const hasBadge = state === "processing" || state === "error";
  for (let y = 0; y < ICON_SIZE; y += 1) {
    for (let x = 0; x < ICON_SIZE; x += 1) {
      let covered = 0;
      for (let sy = 0; sy < SAMPLES; sy += 1) {
        for (let sx = 0; sx < SAMPLES; sx += 1) {
          const px = x + (sx + 0.5) / SAMPLES;
          const py = y + (sy + 0.5) / SAMPLES;
          const nearBadge = hasBadge && Math.hypot(px - BADGE.x, py - BADGE.y) <= KNOCKOUT;
          if (nearBadge ? badgeCovers(state, px, py) : isotypeCovers(state, px / SCALE, py / SCALE)) covered += 1;
        }
      }
      pixels[(y * ICON_SIZE + x) * 4 + 3] = Math.round((covered * 255) / (SAMPLES * SAMPLES));
    }
  }
  return pixels;
}
