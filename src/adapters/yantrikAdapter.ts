/**
 * Optional YantrikDB cluster health for state-aware routing (TypeScript reference).
 * The WisePick API runtime uses `app/adapters/yantrik_adapter.py`; keep logic aligned.
 */

export const REPLICATION_LAG_PENALTY_THRESHOLD = 500;
export const HEALTH_PENALTY_MULTIPLIER = 0.5;

export interface YantrikClusterHealth {
  replication_lag_log_entries: number | null;
  raw: Record<string, unknown> | null;
}

function parseLag(body: Record<string, unknown>): number | null {
  const v = body["replication_lag_log_entries"];
  if (v === undefined || v === null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

/**
 * GET `${baseUrl}/v1/health`, parse replication_lag_log_entries.
 * Returns null on failure (caller skips penalty).
 */
export async function getClusterHealth(
  baseUrl: string,
  apiKey: string = ""
): Promise<YantrikClusterHealth | null> {
  const base = baseUrl.trim();
  if (!base) return null;

  const url = `${base.replace(/\/+$/, "")}/v1/health`;
  const headers: Record<string, string> = {};
  if (apiKey.trim()) {
    headers["Authorization"] = `Bearer ${apiKey.trim()}`;
  }

  try {
    const res = await fetch(url, { method: "GET", headers, signal: AbortSignal.timeout(5000) });
    if (!res.ok) return null;
    const data = (await res.json()) as unknown;
    if (data === null || typeof data !== "object" || Array.isArray(data)) return null;
    const raw = data as Record<string, unknown>;
    return {
      replication_lag_log_entries: parseLag(raw),
      raw,
    };
  } catch {
    return null;
  }
}

export function healthScoreMultiplier(health: YantrikClusterHealth | null): number {
  if (!health) return 1;
  const lag = health.replication_lag_log_entries;
  if (lag !== null && lag > REPLICATION_LAG_PENALTY_THRESHOLD) {
    return HEALTH_PENALTY_MULTIPLIER;
  }
  return 1;
}
