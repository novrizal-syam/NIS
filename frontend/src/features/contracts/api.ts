import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type RateKind = 'service' | 'equipment' | 'personnel' | 'consumable' | 'mobilisation';
export const RATE_KINDS: RateKind[] = [
  'service',
  'equipment',
  'personnel',
  'consumable',
  'mobilisation',
];

export interface ContractRow {
  id: string;
  number: string;
  title: string;
  company_name: string;
  status: 'active' | 'completed' | 'terminated';
  value: string;
  used_value: string;
  usage_pct: string | null;
  po_number: string | null;
  start_date: string | null;
  end_date: string | null;
  payment_term_days: number;
  owner_name: string | null;
  project_id: string | null;
  project_number: string | null;
}

export interface ContractRate {
  id?: string;
  kind: RateKind;
  price_item_code: string | null;
  cost_element_code: string | null;
  description: string;
  unit: string;
  rate: string | null;
  standby_rate: string | null;
  breakdown_rate: string | null;
  unit_cost: string | null;
  markup_pct: string | null;
  quoted_qty: string | null;
}

export interface ContractDetail extends ContractRow {
  opportunity_id: string;
  opportunity_number: string | null;
  quotation_id: string | null;
  quotation_label: string | null;
  can_edit: boolean;
  rates: ContractRate[];
}

type Params = Record<string, string | number | undefined>;
const qs = (p: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') q.set(k, String(v));
  return q.toString();
};
export const contractExportPath = (p: Params) => `/contracts/export?${qs(p)}`;

export function useContracts(params: Params) {
  return useQuery({
    queryKey: ['contracts', 'list', params],
    queryFn: () =>
      api<{ items: ContractRow[]; total: number; total_value: string }>(`/contracts?${qs(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useContract(id: string) {
  return useQuery({
    queryKey: ['contracts', 'detail', id],
    queryFn: () => api<ContractDetail>(`/contracts/${id}`),
  });
}

function useContractMutation<V>(fn: (v: V) => Promise<ContractDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['contracts'] }),
  });
}

export const useSaveContractHeader = (id: string) =>
  useContractMutation((body: Record<string, unknown>) =>
    api<ContractDetail>(`/contracts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  );

export const useSaveRates = (id: string) =>
  useContractMutation((rates: Record<string, unknown>[]) =>
    api<ContractDetail>(`/contracts/${id}/rates`, {
      method: 'PUT',
      body: JSON.stringify({ rates }),
    }),
  );
