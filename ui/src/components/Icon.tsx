/**
 * Inline SVG icons, drawn on a 24-unit grid with a 1.75 stroke.
 *
 * Hand-rolled rather than pulled from a library because the set is small and a
 * whole icon package is a lot of bytes for fourteen glyphs -- and because these
 * ship inside a desktop bundle that should stay small.
 *
 * Every icon in this file is decorative. The interface never uses one to carry
 * meaning on its own: a status is always a glyph plus a colour plus a word.
 */

type IconName =
  | "wifi"
  | "share"
  | "printer"
  | "speaker"
  | "camera"
  | "bluetooth"
  | "download"
  | "search"
  | "battery"
  | "drive"
  | "gauge"
  | "chip"
  | "clock"
  | "home"
  | "heart"
  | "history"
  | "shield"
  | "list"
  | "check"
  | "beaker";

const PATHS: Record<IconName, React.ReactNode> = {
  wifi: (
    <>
      <path d="M2 8.5a16 16 0 0 1 20 0" />
      <path d="M5 12a11 11 0 0 1 14 0" />
      <path d="M8.5 15.5a6 6 0 0 1 7 0" />
      <circle cx="12" cy="19" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  share: (
    <>
      <circle cx="18" cy="5" r="2.5" />
      <circle cx="6" cy="12" r="2.5" />
      <circle cx="18" cy="19" r="2.5" />
      <path d="m8.3 10.8 7.4-4.3M8.3 13.2l7.4 4.3" />
    </>
  ),
  printer: (
    <>
      <path d="M7 9V3h10v6" />
      <path d="M5 9h14a2 2 0 0 1 2 2v6h-4" />
      <path d="M6 17H3v-6" />
      <rect x="7" y="14" width="10" height="7" rx="1" />
    </>
  ),
  speaker: (
    <>
      <path d="M11 5 6 9H3v6h3l5 4z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9 9 0 0 1 0 13" />
    </>
  ),
  camera: (
    <>
      <rect x="2" y="6" width="14" height="12" rx="2" />
      <path d="m16 11 6-3.5v9L16 13z" />
    </>
  ),
  bluetooth: <path d="m7 7 10 10-5 4V3l5 4L7 17" />,
  download: (
    <>
      <path d="M12 3v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M4 20h16" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4.3-4.3" />
    </>
  ),
  battery: (
    <>
      <rect x="2" y="7" width="17" height="10" rx="2" />
      <path d="M22 11v2" />
      <path d="M5.5 10.5h5v3h-5z" fill="currentColor" stroke="none" />
    </>
  ),
  drive: (
    <>
      <rect x="2" y="4" width="20" height="7" rx="2" />
      <rect x="2" y="13" width="20" height="7" rx="2" />
      <path d="M6 7.5h.01M6 16.5h.01" />
    </>
  ),
  gauge: (
    <>
      <path d="M3.5 17a9 9 0 1 1 17 0" />
      <path d="m12 13 4-4" />
      <circle cx="12" cy="14" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  chip: (
    <>
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
      <path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.5l3.5 2" />
    </>
  ),
  home: (
    <>
      <path d="m3 10.5 9-7 9 7" />
      <path d="M5.5 9.5V20h13V9.5" />
      <path d="M10 20v-5.5h4V20" />
    </>
  ),
  heart: (
    <path d="M12 20s-7.5-4.7-7.5-9.7A4.3 4.3 0 0 1 12 7.6a4.3 4.3 0 0 1 7.5 2.7C19.5 15.3 12 20 12 20z" />
  ),
  history: (
    <>
      <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" />
      <path d="M3 4v4h4" />
      <path d="M12 8v4.5l3 1.8" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6z" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </>
  ),
  list: <path d="M4 6.5h16M4 12h16M4 17.5h10" />,
  check: <path d="m4.5 12.5 5 5 10-11" />,
  beaker: (
    <>
      <path d="M9.5 3v6.5L4.6 18a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3l-4.9-8.5V3" />
      <path d="M8 3h8" />
      <path d="M6.8 14.5h10.4" />
    </>
  ),
};

export function Icon({
  name,
  size = 18,
  className = "",
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const path = PATHS[name as IconName];
  if (!path) return null;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
      focusable="false"
    >
      {path}
    </svg>
  );
}
