import { useEffect, useState } from "react";

/**
 * Ctrl +/- to scale the whole interface.
 *
 * This exists for one situation: Warden shown on a projector to a room. The
 * type here is 10-15px because it is an instrument panel read at arm's length,
 * and that is right for the person whose machine it is and unreadable from five
 * metres. The string that matters most is the argv on the approval card --
 * "the command, exactly as it will run" is the entire argument, and it is set
 * in 13px monospace.
 *
 * Implemented with CSS `zoom` rather than a root font size, because every size
 * in this interface is a literal pixel value -- `text-[13px]`, not `rem` -- so
 * scaling the root font would have changed nothing at all. `zoom` also beats a
 * transform: it reflows rather than magnifying, so panels re-wrap and the
 * responsive breakpoints still fire, and a zoomed window behaves like a smaller
 * one instead of a blurry larger one. It is Chromium-specific, which is exactly
 * what WebView2 is.
 */
const STEP = 0.1;
const MIN = 0.8;
const MAX = 1.8;

export function useZoom(): number {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    document.documentElement.style.zoom = String(scale);
  }, [scale]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      // The main keyboard's "+" arrives as "=" without shift; the numeric
      // keypad sends "Add". Accepting all three is the difference between a
      // shortcut that works on the presenter's laptop and one that does not.
      const zoomIn = event.key === "+" || event.key === "=" || event.key === "Add";
      const zoomOut = event.key === "-" || event.key === "_" || event.key === "Subtract";
      const reset = event.key === "0";
      if (!zoomIn && !zoomOut && !reset) return;

      event.preventDefault();
      setScale((current) => {
        if (reset) return 1;
        const next = current + (zoomIn ? STEP : -STEP);
        return Math.min(MAX, Math.max(MIN, Math.round(next * 100) / 100));
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return scale;
}
