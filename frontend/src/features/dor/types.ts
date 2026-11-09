export interface EquipmentLine {
  asset_code: string;
  rate_id: string | null;
  operating: string;
  standby: string;
  breakdown: string;
  rig: string;
  remark?: string | null;
}

export interface CrewLine {
  employee_code: string;
  rate_id: string | null;
  hours: string;
  overtime_hours: string;
}

export interface ConsumableLine {
  item_code: string;
  rate_id: string | null;
  qty: string;
}

/** The DOR as edited on the device and sent to `/operations/dors/sync`. */
export interface DorData {
  report_date: string;
  wbs_code: string;
  site_warehouse: string | null;
  activities: string;
  npt_hours: string;
  npt_reason: string;
  technical: Record<string, string>;
  hse: Record<string, string>;
  equipment: EquipmentLine[];
  crew: CrewLine[];
  consumables: ConsumableLine[];
}

export interface Rate {
  id: string;
  kind: 'equipment' | 'personnel' | 'consumable';
  description: string;
  unit: string;
  rate: string;
  standby_rate: string | null;
  breakdown_rate: string | null;
  unit_cost: string | null;
  markup_pct: string | null;
  internal_cost: string | null;
}

export interface FormOptions {
  project: {
    id: string;
    number: string;
    name: string;
    service_line: string;
    service_type: string | null;
    contract_number: string | null;
  };
  template: {
    label: string;
    fields: { key: string; label: string; unit: string; type?: string }[];
  } | null;
  wbs: { code: string; name: string }[];
  sites: { code: string; name: string; project_code: string | null }[];
  default_site: string | null;
  rates: Rate[];
  assets: {
    code: string;
    name: string;
    internal_day_rate: string;
    blocked: string | null;
    warning: string | null;
  }[];
  crew: {
    code: string;
    full_name: string;
    position: string;
    blocked: string | null;
    warning: string | null;
  }[];
  stock: {
    warehouse_code: string;
    item_code: string;
    name: string;
    uom: string;
    qty: string;
    avg_cost: string;
  }[];
}

export interface DorDetail {
  id: string;
  client_id: string;
  version: number;
  number: string;
  status: 'draft' | 'submitted' | 'approved' | 'returned';
  status_label: string;
  project_id: string;
  project_number: string;
  project_name: string;
  report_date: string;
  wbs_code: string;
  site_warehouse: string | null;
  activities: string | null;
  npt_hours: string;
  npt_reason: string | null;
  technical: Record<string, string>;
  hse: Record<string, string>;
  revenue: string;
  internal_cost: string;
  late: boolean;
  submitted_at: string | null;
  approved_at: string | null;
  deadline: string;
  return_reason: string | null;
  request_id: string | null;
  created_by_name: string | null;
  can_edit: boolean;
  can_submit: boolean;
  equipment: (EquipmentLine & { revenue: string; internal_cost: string })[];
  crew: (CrewLine & { revenue: string; internal_cost: string })[];
  consumables: (ConsumableLine & { revenue: string; internal_cost: string })[];
}

export interface DorRow {
  id: string;
  number: string;
  status: DorDetail['status'];
  status_label: string;
  project_number: string;
  report_date: string;
  revenue: string;
  internal_cost: string;
  late: boolean;
}
