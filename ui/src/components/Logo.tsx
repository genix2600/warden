/**
 * The Warden mark.
 *
 * Served from `public/` rather than inlined: the file is a couple of hundred
 * kilobytes at 256px, which is fine as a cached request and wasteful as base64
 * in the JavaScript bundle every page load has to parse.
 *
 * Regenerate with `scripts/make-icons.py` after changing `assets/wardenlogo.png`
 * -- that script is also what produces the `.ico` Windows uses for the taskbar,
 * so the two cannot drift apart.
 */
export function Logo({ size = 20, className = "" }: { size?: number; className?: string }) {
  return (
    <img
      src="/warden.png"
      width={size}
      height={size}
      alt=""
      aria-hidden
      className={className}
      style={{ width: size, height: size }}
    />
  );
}
