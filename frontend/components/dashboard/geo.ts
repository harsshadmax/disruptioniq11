// The synthetic data has no coordinates, so the map places things from this small lookup.
// Warehouses are the real cities they are named after; supplier origins are demo placements.
export type LatLng = [number, number];

export const WAREHOUSE_POS: Record<string, LatLng> = {
  Chennai: [13.0827, 80.2707],
  Bengaluru: [12.9716, 77.5946],
  Mumbai: [19.076, 72.8777],
  Delhi: [28.6139, 77.209],
};

export const SUPPLIER_POS: Record<string, LatLng> = {
  "Coastal Polymers": [17.6868, 83.2185], // Visakhapatnam
  "Metro Components": [18.5204, 73.8567], // Pune
  "Deccan Plastics": [17.385, 78.4867], // Hyderabad
};

/** A point `t` of the way from `a` to `b` (0 to 1), for where the late shipment is on its route. */
export function along(a: LatLng, b: LatLng, t: number): LatLng {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}
