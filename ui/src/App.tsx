import { useCallback, useMemo, useState } from "react";
import { api } from "./lib/api";
import { isTerminal, useWarden } from "./lib/useWarden";
import type { Observation, PageId } from "./types";
import { DemoBar } from "./components/DemoBar";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { Capabilities } from "./pages/Capabilities";
import { Evidence } from "./pages/Evidence";
import { Health } from "./pages/Health";
import { History } from "./pages/History";
import { Overview } from "./pages/Overview";
import { Readiness } from "./pages/Readiness";

export default function App() {
  const { state, incidents, focus, refresh } = useWarden();
  const [page, setPage] = useState<PageId>("overview");
  const [inspecting, setInspecting] = useState<Observation | null>(null);
  const [busy, setBusy] = useState(false);

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
          {page === "overview" && (
            <Overview
              state={state}
              focus={focus}
              log={state.log}
              onInspect={setInspecting}
              onApprove={(id) => decide(id, "approve")}
              onDecline={(id) => decide(id, "decline")}
              onSeeHealth={() => setPage("health")}
              busy={busy}
            />
          )}
          {page === "health" && (
            <Health onInspect={setInspecting} tick={state.snapshot?.tick ?? 0} />
          )}
          {page === "history" && <History incidents={incidents} />}
          {page === "capabilities" && <Capabilities />}
          {page === "evidence" && (
            <Evidence telemetry={state.telemetry} onInspect={setInspecting} />
          )}
          {page === "readiness" && <Readiness snapshot={state.snapshot} />}
        </main>

        <DemoBar />
      </div>

      <EvidenceDrawer observation={inspecting} onClose={() => setInspecting(null)} />
    </div>
  );
}
