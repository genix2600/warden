import type { PageId } from "../types";
import { Icon } from "./Icon";

interface Props {
  page: PageId;
  onNavigate: (page: PageId) => void;
  /** Count of things genuinely needing a decision. Nothing else gets a badge. */
  needsAttention: number;
  openIncidents: number;
}

// "What it can do" sits third on purpose. That page carries the list of
// problems Warden has decided it cannot fix -- enforced by an empty candidate
// tuple, not by good intentions -- and it is the most persuasive screen here.
// Burying it below History meant nobody reached it.
const NAV: { id: PageId; label: string; icon: string; hint: string }[] = [
  { id: "overview", label: "Now", icon: "home", hint: "What is happening right now" },
  { id: "ask", label: "Describe a problem", icon: "search", hint: "Tell Warden in your own words" },
  { id: "health", label: "Health", icon: "heart", hint: "Every part of the machine" },
  { id: "tuneup", label: "Tune-up", icon: "gauge", hint: "Settings that are worth changing" },
  { id: "history", label: "History", icon: "history", hint: "What Warden has done" },
  { id: "evidence", label: "Readings", icon: "list", hint: "Everything Warden has read" },
  { id: "model", label: "Model", icon: "chip", hint: "Which brain answers, and what it costs" },
  { id: "settings", label: "Settings", icon: "sliders", hint: "Appearance and behaviour" },
  { id: "readiness", label: "Readiness", icon: "check", hint: "Is Warden set up properly" },
];

export function Sidebar({ page, onNavigate, needsAttention, openIncidents }: Props) {
  return (
    <nav className="flex w-[188px] shrink-0 flex-col border-r border-hairline bg-surface">
      <div className="px-4 pt-4 pb-3">
        <div className="text-[15px] font-bold tracking-tight text-ink">Warden</div>
        <div className="text-[10px] uppercase tracking-wider text-muted">
          system diagnostician
        </div>
      </div>

      <ul className="flex-1 space-y-0.5 px-2">
        {NAV.map((item) => {
          const active = page === item.id;
          const badge =
            item.id === "overview" ? needsAttention : item.id === "history" ? openIncidents : 0;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onNavigate(item.id)}
                title={item.hint}
                aria-current={active ? "page" : undefined}
                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors ${
                  active
                    ? "bg-raised font-medium text-ink"
                    : "text-ink-2 hover:bg-raised/60 hover:text-ink"
                }`}
              >
                <Icon name={item.icon} size={17} className={active ? "text-series-1" : ""} />
                <span className="flex-1 truncate">{item.label}</span>
                {badge > 0 && (
                  <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-warning text-[10px] font-bold text-plane">
                    {badge}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      <p className="px-4 pb-3 text-[10px] leading-relaxed text-muted">
        Warden never runs anything without asking you first.
      </p>
    </nav>
  );
}
