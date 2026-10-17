/**
 * REST client. Sends the crew PIN (when signed in) on every request.
 */
const API = {
  pin: sessionStorage.getItem('crewPin') || '',

  setPin(pin) {
    this.pin = pin || '';
    if (this.pin) sessionStorage.setItem('crewPin', this.pin);
    else sessionStorage.removeItem('crewPin');
  },

  async request(method, path, body) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (this.pin) headers['X-Crew-Pin'] = this.pin;
    let res;
    try {
      const go = () => fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
      try { res = await go(); }
      catch (first) {
        if (method !== 'GET') throw first;      // never auto-retry writes
        await new Promise((r) => setTimeout(r, 400));
        res = await go();
      }
    } catch (e) {
      const err = new Error('Cannot reach the server. Check your connection and try again.');
      err.network = true;
      throw err;
    }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && this.pin && path !== '/api/crew/login') {
      this.setPin('');
      if (window.App) window.App.onAuthLost();
    }
    return { status: res.status, ok: res.ok, data };
  },

  getStats: () => API.request('GET', '/api/stats'),
  getSectors: () => API.request('GET', '/api/sectors'),
  getHazards: () => API.request('GET', '/api/hazards'),
  getHazard: (id) => API.request('GET', `/api/hazards/${id}`),
  submitHazard: (data) => API.request('POST', '/api/hazards', data),
  upvoteHazard: (id) => API.request('POST', `/api/hazards/${id}/upvote`, {}),
  crewLogin: () => API.request('POST', '/api/crew/login', {}),
  acknowledge: (id, data) => API.request('POST', `/api/hazards/${id}/acknowledge`, data),
  dispatchCrew: (id, data) => API.request('POST', `/api/hazards/${id}/dispatch`, data),
  verifyOnSite: (id, data) => API.request('POST', `/api/hazards/${id}/verify`, data),
  resolveHazard: (id, data) => API.request('POST', `/api/hazards/${id}/resolve`, data)
};
