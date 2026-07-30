/**
 * The interface's entire state, derived from one event stream.
 *
 * There is no second source of truth. The snapshot fetched on connect seeds the
 * state; every change after that arrives as an `AgentEvent` and is folded in by
 * the reducer below. Because the recorder writes the same events and the replay
 * reader emits them, a recorded session drives this interface exactly as a live
 * agent does -- which is what makes a recording trustworthy rather than a
 * separate, drifting code path.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { api, socketUrl } from "./api";
import type {
  AgentEvent,
  AgentSnapshot,
  Incident,
  Observation,
  OutputLine,
  Symptom,
} from "../types";

const SPARK_POINTS = 60;
const LOG_LIMIT = 200;

export interface LogLine {
  seq: number;
  ts: string;
  level: "info" | "warn" | "error";
  text: string;
  detail?: string | null;
}

export interface WardenState {
  connected: boolean;
  snapshot: AgentSnapshot | null;
  telemetry: Record<string, Observation>;
  /** Short numeric histories, kept only for the sources the interface plots. */
  series: Record<string, number[]>;
  symptoms: Record<string, Symptom>;
  incidents: Record<string, Incident>;
  order: string[];
  output: Record<string, OutputLine[]>;
  log: LogLine[];
  lastSeq: number;
  /** True once a sequence gap is seen; the header offers a resync. */
  desynced: boolean;
}

const PLOTTED = new Set(["cpu.busy_pct", "cpu.performance_pct", "sys.cpu.percent", "thermal.cpu_c"]);

const initial: WardenState = {
  connected: false,
  snapshot: null,
  telemetry: {},
  series: {},
  symptoms: {},
  incidents: {},
  order: [],
  output: {},
  log: [],
  lastSeq: 0,
  desynced: false,
};

type Action =
  | { kind: "connected"; value: boolean }
  | { kind: "snapshot"; snapshot: AgentSnapshot }
  | { kind: "event"; event: AgentEvent }
  | { kind: "reset" };

function pushSeries(series: Record<string, number[]>, source: string, value: unknown) {
  if (!PLOTTED.has(source) || typeof value !== "number") return series;
  const previous = series[source] ?? [];
  return { ...series, [source]: [...previous, value].slice(-SPARK_POINTS) };
}

function upsert(state: WardenState, incident: Incident): WardenState {
  const known = incident.id in state.incidents;
  return {
    ...state,
    incidents: { ...state.incidents, [incident.id]: incident },
    order: known ? state.order : [incident.id, ...state.order].slice(0, 30),
  };
}

function patch(state: WardenState, id: string, change: Partial<Incident>): WardenState {
  const existing = state.incidents[id];
  if (!existing) return state;
  return { ...state, incidents: { ...state.incidents, [id]: { ...existing, ...change } } };
}

function reduce(state: WardenState, action: Action): WardenState {
  switch (action.kind) {
    case "connected":
      return { ...state, connected: action.value };

    case "reset":
      return { ...initial, connected: state.connected };

    case "snapshot": {
      const snapshot = action.snapshot;
      return {
        ...state,
        snapshot,
        telemetry: { ...state.telemetry, ...snapshot.telemetry },
        symptoms: Object.fromEntries(snapshot.active_symptoms.map((s) => [s.code, s])),
        incidents: Object.fromEntries(snapshot.incidents.map((i) => [i.id, i])),
        order: snapshot.incidents.map((i) => i.id),
      };
    }

    case "event": {
      const event = action.event;
      // Sequence numbers are monotonic. A gap means the socket dropped frames,
      // which the header surfaces rather than papering over.
      const desynced = state.desynced || (state.lastSeq > 0 && event.seq > state.lastSeq + 1);
      let next: WardenState = { ...state, lastSeq: event.seq, desynced };

      switch (event.type) {
        case "telemetry": {
          const telemetry = { ...next.telemetry };
          let series = next.series;
          for (const observation of event.observations) {
            telemetry[observation.source] = observation;
            series = pushSeries(series, observation.source, observation.value);
          }
          return { ...next, telemetry, series };
        }

        case "agent.log": {
          const line: LogLine = {
            seq: event.seq,
            ts: event.ts,
            level: event.level,
            text: event.text,
            detail: event.detail,
          };
          return { ...next, log: [line, ...next.log].slice(0, LOG_LIMIT) };
        }

        // Fold everything the event carries, not a subset.
        //
        // This previously copied `tick` and `monitoring` and silently dropped
        // the rest, which meant `warming` never cleared: the snapshot fetched
        // on connect had it true, nothing ever updated it, and the loading
        // screen stayed up permanently while a perfectly healthy agent ticked
        // away behind it. The reasoner fields had the same problem and it
        // matters more now the model runtime starts in the background -- the
        // header would say "rules engine" for the whole session after the
        // model had arrived.
        //
        // Adding a field to AgentStatusEvent and forgetting it here is silent,
        // so the safe shape is to spread rather than to enumerate.
        case "agent.status": {
          const snapshot = next.snapshot;
          if (!snapshot) return next;
          return {
            ...next,
            snapshot: {
              ...snapshot,
              tick: event.tick,
              monitoring: event.monitoring,
              warming: event.warming,
              // Null until the first snapshot carries one; there is nothing to
              // patch in that case, and inventing a shape here would only hide
              // the fact that the backend has not reported yet.
              reasoner: snapshot.reasoner
                ? {
                    ...snapshot.reasoner,
                    available: event.reasoner_available,
                    model: event.reasoner_model,
                  }
                : snapshot.reasoner,
            },
          };
        }

        case "symptom.raised":
          return { ...next, symptoms: { ...next.symptoms, [event.symptom.code]: event.symptom } };

        case "symptom.cleared": {
          const symptoms = { ...next.symptoms };
          delete symptoms[event.code];
          return { ...next, symptoms };
        }

        case "incident.opened":
        case "incident.closed":
          return upsert(next, event.incident);

        case "incident.state":
          return patch(next, event.incident_id, { state: event.state });

        case "diagnosis.ready":
          return patch(next, event.incident_id, { diagnosis: event.diagnosis });

        case "proposal.decided":
          return patch(next, event.incident_id, { decision: event.decision });

        case "execution.started":
          // A fresh run clears the previous transcript so an escalation's output
          // is not read as a continuation of the attempt that failed.
          return { ...next, output: { ...next.output, [event.incident_id]: [] } };

        case "execution.output": {
          const previous = next.output[event.incident_id] ?? [];
          const line: OutputLine = { stream: event.stream, text: event.text, seq: event.seq };
          return {
            ...next,
            output: { ...next.output, [event.incident_id]: [...previous, line].slice(-120) },
          };
        }

        case "execution.finished":
          return patch(next, event.incident_id, { execution: event.record });

        case "verification.result": {
          const incident = next.incidents[event.incident_id];
          if (!incident?.execution) return next;
          return patch(next, event.incident_id, {
            execution: { ...incident.execution, verification: event.result },
          });
        }

        default:
          return next;
      }
    }
  }
}

export function useWarden() {
  const [state, dispatch] = useReducer(reduce, initial);
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      dispatch({ kind: "snapshot", snapshot: await api.state() });
    } catch {
      /* the socket will resync when the backend comes back */
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;

    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(socketUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        dispatch({ kind: "connected", value: true });
        void refresh();
      };
      socket.onmessage = (message) => {
        try {
          dispatch({ kind: "event", event: JSON.parse(message.data as string) as AgentEvent });
        } catch {
          /* a malformed frame is not worth tearing the socket down for */
        }
      };
      socket.onclose = () => {
        dispatch({ kind: "connected", value: false });
        if (disposed) return;
        // Back off to a ceiling: the backend may be restarting during
        // development, and a tight reconnect loop would bury its logs.
        const delay = Math.min(500 * 2 ** retryRef.current++, 5000);
        timer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket.close();
    };

    connect();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
      socketRef.current?.close();
    };
  }, [refresh]);

  const incidents = useMemo(
    () => state.order.map((id) => state.incidents[id]).filter((i): i is Incident => Boolean(i)),
    [state.order, state.incidents],
  );

  /** The incident the main stage shows: the newest one still needing attention. */
  const focus = useMemo(() => {
    const open = incidents.find((i) => !isTerminal(i.state));
    return open ?? incidents[0] ?? null;
  }, [incidents]);

  return { state, incidents, focus, refresh };
}

export function isTerminal(state: string): boolean {
  return ["resolved", "unresolved", "needs_service", "declined"].includes(state);
}
