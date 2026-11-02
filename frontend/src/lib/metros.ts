/** Pilot metros (PLAN.md §5). Coordinates are [lng, lat] for map fly-to. */
export type Metro = { key: string; label: string; center: [number, number]; office: boolean }

export const METROS: Metro[] = [
  { key: 'atlanta', label: 'Atlanta', center: [-84.39, 33.75], office: true },
  { key: 'charlotte', label: 'Charlotte', center: [-80.84, 35.23], office: true },
  { key: 'dallas', label: 'Dallas', center: [-96.8, 32.78], office: true },
  { key: 'houston', label: 'Houston', center: [-95.37, 29.76], office: true },
  { key: 'denver', label: 'Denver', center: [-104.99, 39.74], office: true },
  { key: 'tampa', label: 'Tampa', center: [-82.46, 27.95], office: true },
  { key: 'dc', label: 'Washington DC', center: [-77.04, 38.91], office: true },
  { key: 'tuscaloosa', label: 'Tuscaloosa', center: [-87.57, 33.21], office: false },
]
