/** Thin fetch helpers. The API is on the same origin the shell loaded from. */
import type {
  AgentSnapshot,
  CapabilityReport,
  DoctorReport,
  DomainHealth,
  Incident,
} from "../types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    // FastAPI puts the human-readable reason in `detail`; surfacing it verbatim
    // is better than a status code the user cannot act on.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* body was not JSON; the status line is all we have */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  state: () => json<AgentSnapshot>("/api/state"),
  domains: () => json<DomainHealth[]>("/api/domains"),
  actions: () => json<CapabilityReport>("/api/actions"),
  doctor: () => json<DoctorReport>("/api/doctor"),
  approve: (id: string) => json<Incident>(`/api/incidents/${id}/approve`, { method: "POST" }),
  decline: (id: string) => json<Incident>(`/api/incidents/${id}/decline`, { method: "POST" }),
  dropWifi: () => json<{ detail: string }>("/api/demo/wifi-drop", { method: "POST" }),
  loadCpu: (seconds: number) =>
    json<{ detail: string }>(`/api/demo/cpu-load?seconds=${seconds}`, { method: "POST" }),
  stopLoad: () => json<{ detail: string }>("/api/demo/stop-load", { method: "POST" }),
};

export function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/events`;
}
