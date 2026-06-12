// Admin API config. Both values MUST match what's in /app/backend/.env.
// Backend URL is the deployed KevinAI Pro backend.
export const BACKEND_URL = "https://cryptostock-pro.preview.emergentagent.com";
export const ADMIN_TOKEN = "kevin-admin-2026-do-not-share-xyz789";

export interface LoggedUser {
  email: string;
  unlocked_at: string;
  last_seen: string;
  login_count: number;
}

export async function fetchLoggedUsers(): Promise<LoggedUser[]> {
  const res = await fetch(`${BACKEND_URL}/api/admin/users`, {
    headers: { "X-Admin-Token": ADMIN_TOKEN },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = (await res.json()) as { total: number; users: LoggedUser[] };
  return data.users;
}
