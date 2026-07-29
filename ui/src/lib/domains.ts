/**
 * Labels and icons for the 13 user-facing domains, for surfaces that receive a
 * bare domain id.
 *
 * The Health page gets these from `/api/domains` because it renders live state.
 * The audit only carries the id on each finding, and refetching every domain to
 * label one card would be a request the page has no other use for. Kept in step
 * with `warden/domains.py` by `tests/test_domains.py`, which asserts the two
 * lists agree -- so a domain added on the backend cannot silently render here as
 * a raw id.
 */
export interface DomainLabel {
  label: string;
  icon: string;
}

export const BY_DOMAIN: Record<string, DomainLabel> = {
  network: { label: "Internet & Wi-Fi", icon: "wifi" },
  sharing: { label: "Sharing & Discovery", icon: "share" },
  printing: { label: "Printing", icon: "printer" },
  sound: { label: "Sound", icon: "speaker" },
  camera: { label: "Camera & Microphone", icon: "camera" },
  bluetooth: { label: "Bluetooth", icon: "bluetooth" },
  updates: { label: "Windows Update", icon: "download" },
  search: { label: "Search", icon: "search" },
  battery: { label: "Battery", icon: "battery" },
  storage: { label: "Storage", icon: "drive" },
  performance: { label: "Speed & Temperature", icon: "gauge" },
  devices: { label: "Devices & Drivers", icon: "chip" },
  clock: { label: "Clock", icon: "clock" },
};
