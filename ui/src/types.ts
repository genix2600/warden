/**
 * Named aliases over the generated schema.
 *
 * `generated/api.ts` is produced from the backend's OpenAPI document by
 * `npm run gen:types` and is gitignored -- nothing here is written by hand. If a
 * Pydantic contract changes and this interface has not caught up, the build
 * fails at compile time rather than at a demonstration.
 */
import type { components } from "./generated/api";

type S = components["schemas"];

export type AgentSnapshot = S["AgentSnapshot"];
export type Observation = S["Observation"];
export type Symptom = S["Symptom"];
export type Incident = S["Incident"];
export type IncidentState = S["IncidentState"];
export type Diagnosis = S["Diagnosis"];
export type Hypothesis = S["Hypothesis"];
export type ActionProposal = S["ActionProposal"];
export type ActionSpec = S["ActionSpec"];
export type ServiceAdvice = S["ServiceAdvice"];
export type ExecutionRecord = S["ExecutionRecord"];
export type VerificationResult = S["VerificationResult"];
export type CollectorHealth = S["CollectorHealth"];
export type DomainHealth = S["DomainHealth"];
export type ReasonerHealth = S["ReasonerHealth"];
export type DoctorReport = S["DoctorReport"];
export type CapabilityReport = S["CapabilityReport"];
export type Severity = S["Severity"];

export type TelemetryEvent = S["TelemetryEvent"];
export type AgentLogEvent = S["AgentLogEvent"];
export type AgentStatusEvent = S["AgentStatusEvent"];
export type SymptomRaisedEvent = S["SymptomRaisedEvent"];
export type SymptomClearedEvent = S["SymptomClearedEvent"];
export type IncidentOpenedEvent = S["IncidentOpenedEvent"];
export type IncidentStateEvent = S["IncidentStateEvent"];
export type DiagnosisReadyEvent = S["DiagnosisReadyEvent"];
export type ProposalPendingEvent = S["ProposalPendingEvent"];
export type DecisionEvent = S["DecisionEvent"];
export type ExecutionStartedEvent = S["ExecutionStartedEvent"];
export type ExecutionOutputEvent = S["ExecutionOutputEvent"];
export type ExecutionFinishedEvent = S["ExecutionFinishedEvent"];
export type VerificationEvent = S["VerificationEvent"];
export type IncidentClosedEvent = S["IncidentClosedEvent"];

/** The discriminated union carried by the WebSocket, keyed on `type`. */
export type AgentEvent =
  | TelemetryEvent
  | AgentLogEvent
  | AgentStatusEvent
  | SymptomRaisedEvent
  | SymptomClearedEvent
  | IncidentOpenedEvent
  | IncidentStateEvent
  | DiagnosisReadyEvent
  | ProposalPendingEvent
  | DecisionEvent
  | ExecutionStartedEvent
  | ExecutionOutputEvent
  | ExecutionFinishedEvent
  | VerificationEvent
  | IncidentClosedEvent;

/** A line of process output, kept per incident so reruns do not interleave. */
export interface OutputLine {
  stream: "stdout" | "stderr";
  text: string;
  seq: number;
}

export type StatusTone = "good" | "warning" | "serious" | "critical" | "idle";

/** The pages in the desktop shell. A plain union rather than a router: this is
 *  a fixed-size desktop window with no deep links and no browser history. */
export type PageId =
  | "overview"
  | "health"
  | "history"
  | "capabilities"
  | "evidence"
  | "readiness";
