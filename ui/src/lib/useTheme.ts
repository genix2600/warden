import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type Theme = "dark" | "light";

const STORAGE_KEY = "warden.theme";

/**
 * The chosen theme, applied to the document and remembered.
 *
 * Two stores, deliberately. The backend owns the setting -- it survives a
 * reinstall and lives beside the recorded sessions -- but reading it costs a
 * round trip, and applying the theme one paint after the window opens is a
 * white flash on a dark interface. So the last choice is mirrored into
 * localStorage and applied synchronously on load, with the backend's answer
 * taking over a moment later if they disagree.
 */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(read);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  // The stored preference is authoritative; the local mirror is only a guess
  // at what it will say, kept so the first paint is not the wrong colour.
  useEffect(() => {
    let alive = true;
    api
      .settings()
      .then((settings) => {
        if (alive && (settings.theme === "dark" || settings.theme === "light")) {
          setTheme(settings.theme);
        }
      })
      .catch(() => {
        /* offline or still starting; the mirrored value is fine */
      });
    return () => {
      alive = false;
    };
  }, []);

  return [theme, useCallback((next: Theme) => setTheme(next), [])];
}

function read(): Theme {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "light" ? "light" : "dark";
}
