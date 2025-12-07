import axios from "axios";

const apiBase = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const client = axios.create({
  baseURL: apiBase,
  timeout: 10000,
});

export async function fetchStats(params) {
  const { data } = await client.get("/api/stats", { params });
  return data;
}

export async function fetchDecisions(params) {
  const { data } = await client.get("/api/decisions", { params });
  return data;
}

export async function fetchDecisionDetail(id) {
  const { data } = await client.get(`/api/decisions/${id}`);
  return data;
}

export async function fetchEventEnum() {
  const { data } = await client.get("/api/enums/system-events");
  return data.event_types || [];
}

export async function fetchEvents(params) {
  const { data } = await client.get("/api/system-events", { params });
  return data;
}

export async function fetchTrades(params) {
  const { data } = await client.get("/api/trades", { params });
  return data;
}

export async function fetchSignals(params) {
  const { data } = await client.get("/api/signals", { params });
  return data;
}
