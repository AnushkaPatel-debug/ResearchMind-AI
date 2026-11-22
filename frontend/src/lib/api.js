const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export async function api(path, options={}) {
  let response;
  try { response = await fetch(`${BASE}/api${path}`, options); }
  catch { throw new Error('Cannot reach the backend. Start FastAPI on port 8000.'); }
  const data = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
