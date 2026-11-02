/** Pilot metros (PLAN.md §5); mirrors backend/app/pilots.py. `county` is the one selected
 * when the chip is clicked; `center` is [lng, lat] for the office pin. */
export type Metro = { key: string; label: string; county: string; center: [number, number] }

export const METROS: Metro[] = [
  { key: 'atlanta', label: 'Atlanta', county: '13121', center: [-84.39, 33.75] },
  { key: 'charlotte', label: 'Charlotte', county: '37119', center: [-80.84, 35.23] },
  { key: 'dallas', label: 'Dallas', county: '48113', center: [-96.8, 32.78] },
  { key: 'houston', label: 'Houston', county: '48201', center: [-95.37, 29.76] },
  { key: 'denver', label: 'Denver', county: '08031', center: [-104.99, 39.74] },
  { key: 'tampa', label: 'Tampa', county: '12057', center: [-82.46, 27.95] },
  { key: 'dc', label: 'Washington DC', county: '11001', center: [-77.04, 38.91] },
  { key: 'tuscaloosa', label: 'Tuscaloosa', county: '01125', center: [-87.57, 33.21] },
]
