import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Settings as SettingsModel } from "../types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";

/**
 * The handful of things a person may change.
 *
 * Deliberately short. Warden's thresholds -- what counts as too hot, too slow,
 * too full -- are not here: they were measured rather than chosen, the runs
 * behind them are in docs/calibration.md, and a settings page that let anyone
 * drag "too hot" upward would turn a measurement into an opinion. What is here
 * are the choices with no correct answer.
 */
export function Settings({
  theme,
  onThemeChange,
}: {
  theme: "dark" | "light";
  onThemeChange: (theme: "dark" | "light") => void;
}) {
  const [settings, setSettings] = useState<SettingsModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .settings()
      .then(setSettings)
      .catch((problem: unknown) =>
        setError(problem instanceof Error ? problem.message : String(problem)),
      );
  }, []);

  const update = useCallback(
    async (change: Partial<SettingsModel>) => {
      if (!settings) return;
      const next = { ...settings, ...change };
      setSettings(next);
      setSaving(true);
      setError(null);
      try {
        setSettings(await api.saveSettings(next));
        if (change.theme) onThemeChange(change.theme);
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : String(problem));
      } finally {
        setSaving(false);
      }
    },
    [settings, onThemeChange],
  );

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Settings"
        subtitle="A short list on purpose. What Warden judges your machine by was measured, not chosen, so it is not adjustable here."
      />

      {error && <p className="mb-4 text-[13px] text-critical">{error}</p>}

      <Group
        title="Appearance"
        blurb="Dark is the default because the interface was designed in it and its contrast was checked there. Light is a full design, not an inversion."
      >
        <div className="flex gap-2">
          <ThemeChoice
            label="Dark"
            icon="moon"
            active={theme === "dark"}
            onSelect={() => void update({ theme: "dark" })}
          />
          <ThemeChoice
            label="Light"
            icon="sun"
            active={theme === "light"}
            onSelect={() => void update({ theme: "light" })}
          />
        </div>
      </Group>

      <Group
        title="When Warden finds something"
        blurb="Warden always watches. This is about whether it interrupts you."
      >
        <Toggle
          label="Look into findings automatically"
          detail={
            settings?.autodiagnose
              ? "Warden reasons about anything it finds and proposes a fix without being asked. It still never runs anything without your approval."
              : "Findings appear on the Health page and wait. Nothing is diagnosed until you press Look into this, so a printer you do not own never interrupts you."
          }
          on={settings?.autodiagnose ?? false}
          busy={saving || settings === null}
          onToggle={() => void update({ autodiagnose: !settings?.autodiagnose })}
        />
      </Group>

      <p className="mt-6 max-w-2xl border-t border-hairline pt-4 text-[12px] leading-relaxed text-muted">
        Settings live in <code className="font-mono">%LOCALAPPDATA%\Warden\settings.json</code>,
        beside your recorded sessions, so an update does not reset them. The file holds a
        theme name and a switch. There is nowhere in it for a password or a key.
      </p>
    </div>
  );
}

function Group({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-6">
      <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
      <p className="mb-3 max-w-2xl text-[12px] leading-relaxed text-muted">{blurb}</p>
      {children}
    </section>
  );
}

function ThemeChoice({
  label,
  icon,
  active,
  onSelect,
}: {
  label: string;
  icon: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-[13px] transition-colors ${
        active
          ? "border-series-1 bg-raised text-ink"
          : "border-hairline text-ink-2 hover:bg-raised hover:text-ink"
      }`}
    >
      <Icon name={icon} size={15} className={active ? "text-series-1" : ""} />
      {label}
      {active && <Icon name="check" size={13} className="text-series-1" />}
    </button>
  );
}

function Toggle({
  label,
  detail,
  on,
  busy,
  onToggle,
}: {
  label: string;
  detail: string;
  on: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex gap-4 rounded-xl border border-hairline bg-surface p-4">
      <div className="min-w-0 flex-1">
        <h3 className="text-[13px] font-medium text-ink">{label}</h3>
        <p className="mt-1 text-[12px] leading-relaxed text-ink-2">{detail}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        disabled={busy}
        onClick={onToggle}
        className={`mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors disabled:opacity-50 ${
          on ? "border-series-1 bg-series-1" : "border-hairline bg-sunken"
        }`}
      >
        <span
          className={`block size-4 rounded-full bg-white transition-transform ${
            on ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}
