// The synthetic data has no coordinates, so the map places things from this small lookup.
// Warehouses are the real cities they are named after; supplier origins are demo placements.
import routes from "./routes.json";

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
  "Apex Electricals": [23.0225, 72.5714], // Ahmedabad
  "Southern Packaging": [11.0168, 76.9558], // Coimbatore
  "Northline Metals": [30.901, 75.8573], // Ludhiana
};

/** A point `t` of the way from `a` to `b` (0 to 1), for where the late shipment is on its route. */
export function along(a: LatLng, b: LatLng, t: number): LatLng {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

export type Route = { km: number; hours: number; points: LatLng[] };

// Driving routes between every supplier and hub, fetched once from OpenStreetMap routing data (OSRM) and saved,
// so the map needs no routing service at run time. The shipment's real carrier route is not in the data.
const ROUTES = routes as unknown as Record<string, { km: number; hours: number; points: number[][] }>;

/** The road route from a supplier to a hub, or null for a pair we have no route for (the map then draws a straight line). */
export function roadRoute(supplier: string, warehouse: string): Route | null {
  const r = ROUTES[`${supplier}|${warehouse}`];
  return r ? { km: r.km, hours: r.hours, points: r.points as LatLng[] } : null;
}

/** The point `t` (0 to 1) of the way along a path, measured by distance, so the late shipment sits on the road. */
export function alongPath(points: LatLng[], t: number): LatLng {
  const cos = Math.cos((points[0][0] * Math.PI) / 180); // shrink longitude so distances are roughly even
  const len = (a: LatLng, b: LatLng) => Math.hypot(b[0] - a[0], (b[1] - a[1]) * cos);
  let total = 0;
  for (let i = 1; i < points.length; i++) total += len(points[i - 1], points[i]);
  let left = total * t;
  for (let i = 1; i < points.length; i++) {
    const seg = len(points[i - 1], points[i]);
    if (left <= seg && seg > 0) return along(points[i - 1], points[i], left / seg);
    left -= seg;
  }
  return points[points.length - 1];
}
