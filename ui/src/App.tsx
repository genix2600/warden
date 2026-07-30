import { useCallback, useMemo, useState } from "react";
import { api } from "./lib/api";
import { isTerminal, useWarden } from "./lib/useWarden";
import { useTheme } from "./lib/useTheme";
import { useZoom } from "./lib/useZoom";
import type { Observation, PageId } from "./types";
import { DemoBar } from "./components/DemoBar";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { Warming } from "./components/Warming";
import { Capabilities } from "./pages/Capabilities";
import { Evidence } from "./pages/Evidence";
import { Health } from "./pages/Health";
import { History } from "./pages/History";
import { Overview } from "./pages/Overview";
import { Readiness } from "./pages/Readiness";
import { Settings } from "./pages/Settings";
import { TuneUp } from "./pages/TuneUp";

export default function App() {
  const { state, incidents, focus, refresh } = useWarden();
  // Ctrl +/- , for showing this on a projector. Return value unused: the hook
  // sets the root font size, and every size in the interface is relative to it.
  useZoom();
  const [theme, setTheme] = useTheme();
  const [page, setPage] = useState<PageId>("overview");
  const [inspecting, setInspecting] = useState<Observation | null>(null);
  const [busy, setBusy] = useState(false);

  // Warming is not the same as paused: both mean no readings yet, but only one
  // of them means Warden is doing something about it.
  const warming = state.snapshot?.warming ?? false;

  const decide = useCallback(async (id: string, choice: "approve" | "decline") => {
    setBusy(true);
    try {
      await (choice === "approve" ? api.approve(id) : api.decline(id));
    } finally {
      setBusy(false);
    }
  }, []);

  // Only things genuinely awaiting a human decision earn a badge. A count of
  // "open incidents" would include everything Warden is quietly working
  // through, which trains people to ignore the number.
  const awaitingApproval = useMemo(
    () => incidents.filter((i) => i.state === "awaiting_approval").length,
    [incidents],
  );
  const open = useMemo(() => incidents.filter((i) => !isTerminal(i.state)).length, [incidents]);

  return (
    <div className="flex h-full bg-plane">
      <Sidebar
        page={page}
        onNavigate={setPage}
        needsAttention={awaitingApproval}
        openIncidents={open}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          snapshot={state.snapshot}
          connected={state.connected}
          desynced={state.desynced}
          onResync={() => void refresh()}
          onOpenDoctor={() => setPage("readiness")}
        />

        <main className="min-h-0 flex-1">
          {/* Startup used to happen before the window could exist, so the whole
              wait was spent looking at nothing. The window now opens at once
              and this stands in until the first readings land. */}
          {warming && <Warming log={state.log} />}
          {!warming && page === "overview" && (
            <Overview
              state={state}
              focus={focus}
              log={state.log}
              onInspect={setInspecting}
              onApprove={(id) => decide(id, "approve")}
              onDecline={(id) => decide(id, "decline")}
              onSeeHealth={() => setPage("health")}
              busy={busy}
              elevated={state.snapshot?.elevated ?? false}
            />
          )}
          {!warming && page === "health" && (
            <Health
              onInspect={setInspecting}
              tick={state.snapshot?.tick ?? 0}
              // A check that found something opens an incident, which lives on
              // Now -- so go there rather than leaving the user on a page that
              // has just stopped being where the action is.
              onChecked={() => setPage("overview")}
            />
          )}
          {!warming && page === "tuneup" && <TuneUp />}
          {!warming && page === "history" && <History incidents={incidents} />}
          {!warming && page === "capabilities" && <Capabilities />}
          {!warming && page === "evidence" && (
            <Evidence telemetry={state.telemetry} onInspect={setInspecting} />
          )}
          {!warming && page === "settings" && (
            <Settings theme={theme} onThemeChange={setTheme} />
          )}
          {!warming && page === "readiness" && <Readiness snapshot={state.snapshot} />}
        </main>

        <DemoBar />
      </div>

      <EvidenceDrawer observation={inspecting} onClose={() => setInspecting(null)} />
    </div>
  );
}
