"use client";

/**
 * The animated pieces, in the style of react-bits.dev but written here.
 *
 * React Bits' effects are the right *idea* for a landing page -- text that
 * settles in word by word, numbers that count up, cards that light where the
 * cursor is. Reimplementing the three that are actually used, in about a
 * hundred lines of CSS transitions and one IntersectionObserver, avoids pulling
 * GSAP, Framer Motion and OGL into a site whose entire job is to load fast and
 * say what the product does. It also keeps the licence surface at zero.
 *
 * All three honour `prefers-reduced-motion`: they render their final state
 * immediately rather than animating to it, so the page is never less readable
 * for someone who asked their system for less movement.
 */

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia(QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Read the preference as what it is: external state, subscribed to.
 *
 * Doing this with useState and an effect works, but it renders once with the
 * wrong answer and then corrects itself -- which for a motion preference means
 * a flash of the animation the reader explicitly asked not to see. */
function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false, // Server render: assume motion is fine, then correct on hydrate.
  );
}

/** Fires once when the element first scrolls into view. */
function useInView<T extends HTMLElement>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || seen) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [seen]);

  return [ref, seen];
}

/** Headline text that settles in a word at a time. */
export function SplitText({
  text,
  className = "",
  delay = 0,
}: {
  text: string;
  className?: string;
  delay?: number;
}) {
  const reduced = usePrefersReducedMotion();
  const [ref, seen] = useInView<HTMLSpanElement>();
  const words = text.split(" ");

  return (
    <span ref={ref} className={className}>
      {words.map((word, index) => (
        <span key={index} className="inline-block overflow-hidden align-bottom">
          <span
            className="inline-block will-change-transform"
            style={
              reduced
                ? undefined
                : {
                    transform: seen ? "none" : "translateY(0.9em)",
                    opacity: seen ? 1 : 0,
                    transition: `transform 0.7s cubic-bezier(0.16,1,0.3,1) ${
                      delay + index * 55
                    }ms, opacity 0.7s ease ${delay + index * 55}ms`,
                  }
            }
          >
            {word}
          </span>
          {index < words.length - 1 && <span>&nbsp;</span>}
        </span>
      ))}
    </span>
  );
}

/** A number that counts up once, when it comes into view. */
export function CountUp({
  to,
  suffix = "",
  duration = 1100,
  className = "",
}: {
  to: number;
  suffix?: string;
  duration?: number;
  className?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const [ref, seen] = useInView<HTMLSpanElement>();
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!seen || reduced) return;
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      // Ease out, so it decelerates into the final number rather than stopping.
      setValue(Math.round(to * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [seen, to, duration, reduced]);

  // Derived rather than written into state, so the reduced-motion path needs no
  // effect at all -- it simply renders the final number.
  const shown = reduced ? to : value;

  return (
    <span ref={ref} className={className}>
      {shown}
      {suffix}
    </span>
  );
}

/** A card that lights faintly where the cursor is. Pointer-driven only, so it
 *  costs nothing on touch devices, where it also does not apply. */
export function SpotlightCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [spot, setSpot] = useState<{ x: number; y: number } | null>(null);

  return (
    <div
      ref={ref}
      onPointerMove={(event) => {
        if (event.pointerType !== "mouse") return;
        const box = event.currentTarget.getBoundingClientRect();
        setSpot({ x: event.clientX - box.left, y: event.clientY - box.top });
      }}
      onPointerLeave={() => setSpot(null)}
      className={`relative overflow-hidden rounded-xl border border-hairline bg-surface ${className}`}
    >
      {spot && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 transition-opacity duration-300"
          style={{
            background: `radial-gradient(320px circle at ${spot.x}px ${spot.y}px, rgba(57,135,229,0.10), transparent 65%)`,
          }}
        />
      )}
      <div className="relative">{children}</div>
    </div>
  );
}

/** Content that rises into place when scrolled to. */
export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const [ref, seen] = useInView<HTMLDivElement>();

  return (
    <div
      ref={ref}
      className={className}
      style={
        reduced
          ? undefined
          : {
              opacity: seen ? 1 : 0,
              transform: seen ? "none" : "translateY(16px)",
              transition: `opacity 0.6s ease ${delay}ms, transform 0.6s cubic-bezier(0.16,1,0.3,1) ${delay}ms`,
            }
      }
    >
      {children}
    </div>
  );
}
