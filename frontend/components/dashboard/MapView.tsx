"use client";

import { useEffect, useRef } from "react";
import "leaflet/dist/leaflet.css";
import { along, SUPPLIER_POS, WAREHOUSE_POS } from "./geo";

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const RED = "#e5384f";
const ORANGE = "#f08a24";

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const label = (text: string) => `<div class="diq-pin-label">${esc(text)}</div>`;

/** A street map of the disruption: the four hubs, the supplier, the route and the late shipment on it. */
export function MapView({ warehouse, supplier, shipment }: { warehouse: string; supplier: string; shipment: string | null }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let dispose = () => {};
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      if (cancelled || !box.current) return;
      const map = L.map(box.current, { zoomControl: false, scrollWheelZoom: false, attributionControl: true, zoomSnap: 0.25 });
      L.control.zoom({ position: "bottomright" }).addTo(map);
      L.tileLayer(TILES, {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);

      const icon = (html: string, size: [number, number]) =>
        L.divIcon({ className: "diq-pin", html, iconSize: size, iconAnchor: [size[0] / 2, size[1] / 2] });
      const bounds: [number, number][] = [];

      for (const [name, pos] of Object.entries(WAREHOUSE_POS)) {
        const hit = name === warehouse;
        L.marker(pos, { icon: icon(`<div class="diq-hub${hit ? " diq-hub-hit" : ""}"><i></i>${esc(name)} Hub</div>`, [96, 26]), zIndexOffset: hit ? 500 : 0 }).addTo(map);
      }

      const wh = WAREHOUSE_POS[warehouse];
      const sup = SUPPLIER_POS[supplier];
      if (wh) bounds.push(wh);
      if (sup) {
        bounds.push(sup);
        L.marker(sup, { icon: icon(`${label(supplier)}<div class="diq-dot" style="background:${ORANGE}"></div>`, [30, 56]), zIndexOffset: 400 }).addTo(map);
      }
      if (sup && wh) {
        L.polyline([sup, wh], { color: RED, weight: 2.5, dashArray: "6 6", opacity: 0.85 }).addTo(map);
        const at = along(sup, wh, 0.6);
        const tag = shipment ? label(shipment) : "";
        L.marker(at, { icon: icon(`${tag}<div class="diq-dot diq-dot-lg" style="background:${RED}"><b></b></div>`, [34, 62]), zIndexOffset: 600 }).addTo(map);
      }

      if (bounds.length > 1) map.fitBounds(bounds, { padding: [60, 60], maxZoom: 8 });
      else map.setView(wh ?? [20.5, 78.9], wh ? 7 : 5);
      dispose = () => map.remove();
    })();
    return () => { cancelled = true; dispose(); };
  }, [warehouse, supplier, shipment]);

  return <div ref={box} className="diq-map h-full min-h-[360px] w-full overflow-hidden rounded-xl bg-brand-wash" role="img" aria-label={`Map: ${supplier} to ${warehouse}`} />;
}
