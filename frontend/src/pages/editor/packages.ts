/**
 * The packages each engine writes, named the way it names them.
 *
 * A modeller reads NPF, IC, STO and DIS in a name file and a listing file, and
 * the screen that edits them should use the same words. "Hydraulic properties"
 * is a category; NPF is a file you can open, and it is the one that appears in
 * the error you are chasing.
 *
 * The two engines are genuinely different stacks, not two spellings of one:
 * MODFLOW 6 has NPF and STO and GWT packages, while PHT3D is MODFLOW-2005 plus
 * MT3DMS and has LPF, BTN and GCG. Showing MF6 names on a PHT3D project would
 * be a lie about what gets written.
 */

export type Engine = "mf6rtm" | "pht3d";

export interface PackageTab {
  /** The acronym, which is what the file is called and what errors mention. */
  id: string;
  /** What it is, for anyone who does not already know the acronym. */
  label: string;
  /** One line on what it decides. */
  purpose: string;
}

/** Flow packages: the aquifer itself, before any boundary is added. */
const FLOW_PACKAGES: Record<Engine, PackageTab[]> = {
  mf6rtm: [
    {
      id: "NPF",
      label: "Node property flow",
      purpose: "Hydraulic conductivity and how a cell converts between confined and unconfined.",
    },
    {
      id: "IC",
      label: "Initial conditions",
      purpose: "The head the solver starts from.",
    },
    {
      id: "STO",
      label: "Storage",
      purpose: "Specific storage and yield. Only used where a stress period is transient.",
    },
    {
      id: "IMS",
      label: "Solver",
      purpose: "How hard MODFLOW works to converge, and when it gives up.",
    },
  ],
  pht3d: [
    {
      id: "LPF",
      label: "Layer property flow",
      purpose: "Conductivity and storage. MODFLOW-2005's equivalent of NPF and STO together.",
    },
    {
      id: "BAS",
      label: "Basic",
      purpose: "Starting heads, and which cells are active.",
    },
    {
      id: "PCG",
      label: "Solver",
      purpose: "Preconditioned conjugate gradient: how hard it works to converge.",
    },
  ],
};

/** Boundary packages. Both engines call these the same thing. */
/**
 * Zones are not a MODFLOW package, but they belong beside the property tabs.
 *
 * Every property tab can send a value to a zone, so the place zones are drawn
 * has to be one click away from the place they are used. Giving them their own
 * step would put the outline and the number that fills it on different screens.
 */
export const ZONES_TAB: PackageTab = {
  id: "ZONES",
  label: "Zones",
  purpose: "Named parts of the grid that properties can vary over.",
};

export const BOUNDARY_PACKAGES: PackageTab[] = [
  { id: "WEL", label: "Well", purpose: "Injection or extraction at named cells." },
  {
    id: "CHD",
    label: "Constant head",
    purpose: "Holds a head, supplying or removing whatever it takes.",
  },
  { id: "RCH", label: "Recharge", purpose: "Areal inflow to the top layer." },
  { id: "DRN", label: "Drain", purpose: "Removes water above an elevation. Never adds any." },
  { id: "RIV", label: "River", purpose: "Exchange with a stream through its bed." },
  {
    id: "GHB",
    label: "General head",
    purpose: "A head some distance away, through a conductance.",
  },
];

/** Transport packages: how solute moves, and what happens to it. */
const TRANSPORT_PACKAGES: Record<Engine, PackageTab[]> = {
  mf6rtm: [
    {
      id: "MST",
      label: "Mobile storage",
      purpose: "Porosity, which sets how fast the water moves.",
    },
    { id: "ADV", label: "Advection", purpose: "The scheme that carries solute with the flow." },
    { id: "DSP", label: "Dispersion", purpose: "Spreading on top of advection, and diffusion." },
    {
      id: "SSM",
      label: "Source mixing",
      purpose: "What each flow boundary brings in with its water.",
    },
  ],
  pht3d: [
    {
      id: "BTN",
      label: "Basic transport",
      purpose: "Porosity, starting concentrations and the component list.",
    },
    { id: "ADV", label: "Advection", purpose: "The scheme that carries solute with the flow." },
    { id: "DSP", label: "Dispersion", purpose: "Spreading on top of advection, and diffusion." },
    {
      id: "SSM",
      label: "Source mixing",
      purpose: "What each flow boundary brings in with its water.",
    },
    { id: "GCG", label: "Solver", purpose: "The transport solver's iteration limits." },
  ],
};

export function flowPackages(engine: string): PackageTab[] {
  return FLOW_PACKAGES[engine as Engine] ?? FLOW_PACKAGES.mf6rtm;
}

export function transportPackages(engine: string): PackageTab[] {
  return TRANSPORT_PACKAGES[engine as Engine] ?? TRANSPORT_PACKAGES.mf6rtm;
}

/** The package a boundary of this kind is written into. */
export const PACKAGE_FOR_KIND: Record<string, string> = {
  well: "WEL",
  chd: "CHD",
  recharge: "RCH",
  drn: "DRN",
  riv: "RIV",
  ghb: "GHB",
};
