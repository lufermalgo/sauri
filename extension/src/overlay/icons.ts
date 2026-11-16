import { createElement, type IconNode } from 'lucide';
import { ICON_SIZE, ICON_STROKE_WIDTH } from '../core/design/iconDefaults';

/** Builds a decorative Lucide SVG for the Shadow DOM bar (no React in the content script). */
export function icon(node: IconNode, size = ICON_SIZE, className?: string): SVGElement {
  return createElement(node, {
    ...(className ? { class: className } : {}),
    width: size,
    height: size,
    'stroke-width': ICON_STROKE_WIDTH,
    'aria-hidden': 'true',
    focusable: 'false',
  });
}

/** Same icon as markup, for the innerHTML templates that build each bar. */
export function iconHtml(node: IconNode, size = ICON_SIZE, className?: string): string {
  return icon(node, size, className).outerHTML;
}
