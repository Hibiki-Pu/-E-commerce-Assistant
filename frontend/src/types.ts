export type MetricKey = 'sales_cents' | 'refund_cents' | 'cost_cents' | 'contribution_cents'
export interface Summary {
  sales_cents: number; refund_cents: number; cost_cents: number | null;
  contribution_cents: number | null; known_cost_cents: number;
  missing_cost_lines: number; paid_lines: number; quantity: number;
  cross_period_refund_cents: number;
}
export interface Daily extends Summary { date: string }
export interface Product extends Summary { product_id: string; name: string; category: string }
export interface Change { percent: string | null; reason: string | null }
export interface Dashboard {
  is_simulated: boolean; currency: string; summary: Summary; daily: Daily[]; products: Product[];
  period: { start: string; end: string; days: number };
  comparison: { start: string; end: string; available: boolean; label: string; summary: Summary | null };
  changes: Record<MetricKey, Change>;
}
export interface Meta {
  start_date: string; end_date: string; seed: number;
  products: { id: string; name: string; category: string }[];
  counts: { products: number; order_lines: number; refunds: number; product_costs: number };
  missing_cost_lines: number; validation_status: string;
  scenarios: { id: number; start_date: string; end_date: string; title: string; description: string }[];
}
