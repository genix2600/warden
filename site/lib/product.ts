/**
 * The facts the site is allowed to state, in one place.
 *
 * Every number here is real and comes from the application: the domains from
 * `warden/domains.py`, the action counts from the playbook registry, the
 * latency from `docs/calibration.md`. Keeping them in one module rather than
 * inline in the copy means a claim cannot quietly drift out of step with the
 * product on one page while staying correct on another -- which, for a product
 * whose entire argument is that it does not overstate, would be the worst
 * possible bug to ship.
 */

export const REPO = "https://github.com/genix2600/warden";
export const VERSION = "1.0.0";

/** GitHub Releases, because the installer is far past the 100 MB file limit
 *  that GitHub and Vercel both enforce. `/latest/` means the site never needs
 *  editing when a new version ships. */
export const DOWNLOAD_URL = `${REPO}/releases/latest/download/Warden-Setup-${VERSION}.exe`;
export const ZIP_URL = `${REPO}/releases/latest/download/Warden-${VERSION}.zip`;

/** The edition that carries the model weights, for machines that will never
 *  have a usable connection -- built by `build-installer.ps1 -Offline`.
 *
 *  Not published yet, and the site must not link to it until it is: an asset
 *  that does not exist on the release 404s silently rather than erroring, so a
 *  dead download button looks like a broken product rather than a missing
 *  file. Set this to true in the same commit that uploads the asset. */
export const OFFLINE_AVAILABLE = false;
export const OFFLINE_URL = `${REPO}/releases/latest/download/Warden-Setup-${VERSION}-offline.exe`;

export const INSTALLER_SIZE = "45 MB";
export const OFFLINE_SIZE = "967 MB";
export const MODEL_SIZE = "1 GB";

export const STATS = [
  { value: 13, label: "areas watched", suffix: "" },
  { value: 17, label: "actions it can take", suffix: "" },
  { value: 7, label: "problems it refuses to fix", suffix: "" },
  { value: 0, label: "data sent anywhere", suffix: " bytes" },
] as const;

export interface Domain {
  label: string;
  blurb: string;
}

/** The 13 user-facing domains, matching `DOMAINS` in warden/domains.py. */
export const DOMAINS: Domain[] = [
  { label: "Internet & Wi-Fi", blurb: "Whether you are connected, and whether anything loads." },
  { label: "Sharing & Discovery", blurb: "Whether you can see shared printers and other computers." },
  { label: "Printing", blurb: "Whether print jobs can reach a printer at all." },
  { label: "Sound", blurb: "Whether anything can play audio." },
  { label: "Camera & Microphone", blurb: "Whether apps are allowed to see and hear you." },
  { label: "Bluetooth", blurb: "Whether headphones, mice and keyboards can connect." },
  { label: "Windows Update", blurb: "Whether security updates are still arriving." },
  { label: "Search", blurb: "Whether Start and File Explorer can find your files." },
  { label: "Battery", blurb: "How much of its original capacity the battery still holds." },
  { label: "Storage", blurb: "Drive health, and whether there is room left to work in." },
  { label: "Speed & Temperature", blurb: "Whether the processor is being held back by heat." },
  { label: "Devices & Drivers", blurb: "Hardware Windows has flagged as not working." },
  { label: "Clock", blurb: "Whether the time is right, which secure websites depend on." },
];

/** The seven symptoms mapped to an empty candidate tuple in
 *  `warden/playbooks/__init__.py`. The most persuasive list on the site. */
export const REFUSALS = [
  {
    code: "POWER.BATTERY_WORN",
    plain: "A worn-out battery",
    why: "No command restores a battery's chemistry. Warden measures the wear and tells you what to say to a repair shop.",
  },
  {
    code: "STORAGE.DISK_UNHEALTHY",
    plain: "A failing drive",
    why: "SMART says the drive is dying. Software cannot un-fail it, and pretending otherwise costs you the window to back up.",
  },
  {
    code: "THERMAL.SUSTAINED_THROTTLE",
    plain: "Overheating under load",
    why: "Dust, thermal paste and airflow are physical. A setting change would hide the reading, not fix the machine.",
  },
  {
    code: "THERMAL.HIGH_TEMPERATURE",
    plain: "Running too hot",
    why: "Same cause, same answer. Warden shows the temperatures and where they came from.",
  },
  {
    code: "NET.WIFI.RADIO_OFF",
    plain: "Wireless switched off in hardware",
    why: "There is a physical switch or an Fn key. Warden tells you which, instead of restarting drivers pointlessly.",
  },
  {
    code: "NET.WIFI.NO_ADAPTER",
    plain: "No wireless adapter present",
    why: "The hardware is absent or has no driver. That is a different problem, and it says so.",
  },
  {
    code: "NET.INTERNET.UNREACHABLE",
    plain: "The internet itself is down",
    why: "Your machine is fine and the fault is upstream. Warden checks before blaming your computer.",
  },
];

/** The nine standing checks in `warden/audit/`, in the order they are declared.
 *
 *  `acts` is not a marketing distinction, it is the contract. A check may only
 *  carry a fix button if the change can be undone and the quantity can be read
 *  again afterwards. Two of the nine clear that bar. The other seven are still
 *  reported, because a reading you can act on yourself beats silence, and
 *  because the alternative is a button that cannot honour its own promise. */
export const AUDIT_CHECKS = [
  {
    title: "Processor speed limit",
    reads: "The ceiling your power plan puts on the processor, as a percentage.",
    acts: "Raises it to 100 and can put your number back.",
  },
  {
    title: "Automatic cleanup",
    reads: "Whether Storage Sense is switched on.",
    acts: "Turns it on, and off again if you change your mind.",
  },
  {
    title: "Driver age",
    reads: "How old your graphics, network, sound and Bluetooth drivers are.",
    acts: null,
  },
  {
    title: "Space that can be handed back",
    reads: "Megabytes sitting in temporary folders and the update cache.",
    acts: null,
  },
  {
    title: "Power plan",
    reads: "Which plan is active, and what each of the alternatives would cost you.",
    acts: null,
  },
  {
    title: "Programs that start with Windows",
    reads: "How many there are, and which ones.",
    acts: null,
  },
  {
    title: "Wi-Fi adapter power saving",
    reads: "Whether Windows is allowed to switch the radio off to save power.",
    acts: null,
  },
  {
    title: "Scheduled drive optimisation",
    reads: "Whether an SSD is on a defragmentation schedule meant for a spinning disk.",
    acts: null,
  },
  {
    title: "Update waiting to finish",
    reads: "How long a restart has been outstanding.",
    acts: null,
  },
];

export const ACTION_TIERS = [
  {
    tier: "Looks, changes nothing",
    count: 2,
    blurb: "Gathers more information. Cannot alter the machine even if it wanted to.",
    examples: ["netsh wlan show networks", "measure reclaimable temporary files"],
  },
  {
    tier: "Changes something, easily undone",
    count: 9,
    blurb:
      "Reconnects, clears a cache, corrects a setting, turns on automatic cleanup. "
      + "Every one of these can be put back.",
    examples: ["ipconfig /flushdns", "ipconfig /renew", "w32tm /resync"],
  },
  {
    tier: "Disruptive while it runs",
    count: 6,
    blurb: "Restarts a device or service, or changes a startup setting. You will notice these.",
    examples: ["Restart-NetAdapter", "pnputil /restart-device", "Set-NetConnectionProfile"],
  },
];
