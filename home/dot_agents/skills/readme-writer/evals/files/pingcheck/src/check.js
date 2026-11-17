// URL にリクエストして、ステータスと所要時間(ミリ秒)を返す。
export async function check(url, { timeoutMs = 5000, fetchImpl = fetch } = {}) {
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, { signal: controller.signal });
    return { url, ok: response.ok, status: response.status, ms: Date.now() - started };
  } catch (error) {
    return { url, ok: false, status: null, ms: Date.now() - started, error: error.name === 'AbortError' ? 'timeout' : String(error.message) };
  } finally {
    clearTimeout(timer);
  }
}
