/**
 * Live pricing preview on the device (also offline), mirroring the backend
 * (`operations/dor_service.py`); the server recalculates on save and is authoritative.
 */
import type { DorData, FormOptions } from './types';

const num = (v: string | null | undefined) => Number((v ?? '0').replace(',', '.')) || 0;
const round = (v: number) => Math.round(v);

export interface Pricing {
  equipment: { revenue: number; cost: number; hours: number }[];
  crew: { revenue: number; cost: number }[];
  consumables: { revenue: number; cost: number; available: number }[];
  revenue: number;
  cost: number;
}

export function price(d: DorData, o: FormOptions): Pricing {
  const rate = (id: string | null) => o.rates.find((r) => r.id === id);
  const equipment = d.equipment.map((x) => {
    const r = rate(x.rate_id);
    const op = num(x.operating);
    const sb = num(x.standby);
    const bd = num(x.breakdown);
    const rig = num(x.rig);
    const revenue = r
      ? round(
          (op * num(r.rate) +
            sb * num(r.standby_rate) +
            bd * num(r.breakdown_rate) +
            rig * num(r.rate)) /
            24,
        )
      : 0;
    const asset = o.assets.find((a) => a.code === x.asset_code);
    return { revenue, cost: num(asset?.internal_day_rate), hours: op + sb + bd + rig };
  });
  const crew = d.crew.map((c) => {
    const r = rate(c.rate_id);
    return { revenue: r ? num(r.rate) : 0, cost: r ? num(r.internal_cost) : 0 };
  });
  const consumables = d.consumables.map((k) => {
    const r = rate(k.rate_id);
    const qty = num(k.qty);
    const s = o.stock.find(
      (x) => x.item_code === k.item_code && x.warehouse_code === d.site_warehouse,
    );
    return {
      revenue: r ? round(qty * num(r.unit_cost) * (1 + num(r.markup_pct) / 100)) : 0,
      cost: round(qty * num(s?.avg_cost)),
      available: num(s?.qty),
    };
  });
  const all = [...equipment, ...crew, ...consumables];
  return {
    equipment,
    crew,
    consumables,
    revenue: all.reduce((a, x) => a + x.revenue, 0),
    cost: all.reduce((a, x) => a + x.cost, 0),
  };
}

/** Client-side checks shown while typing (the server repeats them on submit). */
export function checks(d: DorData, o: FormOptions, p: Pricing): string[] {
  const out: string[] = [];
  d.equipment.forEach((x, i) => {
    if (p.equipment[i]!.hours !== 24)
      out.push(`${x.asset_code}: total jam ${p.equipment[i]!.hours}, harus 24.`);
  });
  const need = new Map<string, number>();
  d.consumables.forEach((k) => need.set(k.item_code, (need.get(k.item_code) ?? 0) + num(k.qty)));
  need.forEach((qty, code) => {
    const s = o.stock.find((x) => x.item_code === code && x.warehouse_code === d.site_warehouse);
    if (qty > num(s?.qty)) out.push(`${code}: ${qty} melebihi stok site (${num(s?.qty)}).`);
  });
  if (!d.activities.trim()) out.push('Isi ringkasan aktivitas.');
  return out;
}
