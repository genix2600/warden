import { useCallback, useState } from "react";
import { api } from "./lib/api";
import { useWarden } from "./lib/useWarden";
import type { Observation } from "./types";
import { AgentLog } from "./components/AgentLog";
import { DemoBar } from "./components/DemoBar";
import { DoctorPanel } from "./components/DoctorPanel";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { Header } from "./components/Header";
import { IncidentStage } from "./components/IncidentStage";
import { TelemetryPanel } from "./components/TelemetryPanel";

export default function App() {
  const { state, focus, refresh } = useWarden();
  const [inspecting, setInspecting] = useState<Observation | null>(null);
  const [doctorOpen, setDoctorOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  // Evidence is cited by id. Most cited readings are still in the live
  // telemetry map; anything older is fetched, since the backend keeps a longer
  // history than the interface does.
  const lookup = useCallback(
    (id: string): Observation | undefined =>
      Object.values(state.telemetry).find((observation) => observation.id === id),
    [state.telemetry],
  );

  const decide = useCallback(
    async (id: string, choice: "approve" | "decline") => {
      setBusy(true);
      try {
        await (choice === "approve" ? api.approve(id) : api.decline(id));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return (
    <div className="flex h-full flex-col bg-plane">
      <Header
        snapshot={state.snapshot}
        connected={state.connected}
        desynced={state.desynced}
        onResync={() => void refresh()}
        onOpenDoctor={() => setDoctorOpen(true)}
      />

      <main className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_290px] gap-4 p-4">
        <TelemetryPanel
          telemetry={state.telemetry}
          series={state.series}
          collectors={state.snapshot?.collectors ?? []}
          onInspect={setInspecting}
        />

        <IncidentStage
          incident={focus}
          monitoring={state.snapshot?.monitoring ?? false}
          output={focus ? (state.output[focus.id] ?? []) : []}
          observationsById={lookup}
          onInspect={setInspecting}
          onApprove={(id) => decide(id, "approve")}
          onDecline={(id) => decide(id, "decline")}
          busy={busy}
        />

        <AgentLog lines={state.log} />
      </main>

      <DemoBar />

      <EvidenceDrawer observation={inspecting} onClose={() => setInspecting(null)} />
      {doctorOpen && <DoctorPanel onClose={() => setDoctorOpen(false)} />}
    </div>
  );
}
