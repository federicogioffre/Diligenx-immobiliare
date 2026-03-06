const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const api = {
  deals: {
    list: () => request<Deal[]>("/deals/"),
    get: (id: number) => request<Deal>(`/deals/${id}`),
    create: (data: DealCreate) =>
      request<Deal>("/deals/", { method: "POST", body: JSON.stringify(data) }),
  },
  agents: {
    analyze: (deal_id: number) =>
      request("/agents/analyze", { method: "POST", body: JSON.stringify({ deal_id }) }),
  },
};

export interface Deal {
  id: number;
  title: string;
  description?: string;
  value?: number;
  status: string;
  ai_summary?: string;
  ai_score?: number;
  created_at: string;
}

export interface DealCreate {
  title: string;
  description?: string;
  value?: number;
}
