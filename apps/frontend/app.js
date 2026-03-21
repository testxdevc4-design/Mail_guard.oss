/**
 * MailGuard OSS — Dashboard JS
 *
 * Communicates directly with the MailGuard FastAPI backend using Bearer-token
 * auth.  No framework or build step required — plain ES2020 modules.
 *
 * State is stored in sessionStorage so it survives page refresh but is cleared
 * when the tab closes (no long-lived token persistence in localStorage).
 */

'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const apiUrlInput     = $('api-url');
const apiKeyInput     = $('api-key');
const connectBtn      = $('connect-btn');
const connStatus      = $('conn-status');

const otpCard         = $('otp-card');
const otpEmailInput   = $('otp-email');
const otpProjectInput = $('otp-project');
const otpSendBtn      = $('otp-send-btn');
const otpSendResult   = $('otp-send-result');

const otpVerifyEmail   = $('otp-verify-email');
const otpCode          = $('otp-code');
const otpVerifyProject = $('otp-verify-project');
const otpVerifyBtn     = $('otp-verify-btn');
const otpVerifyResult  = $('otp-verify-result');

const magicCard          = $('magic-card');
const magicEmailInput    = $('magic-email');
const magicProjectInput  = $('magic-project');
const magicRedirectInput = $('magic-redirect');
const magicSendBtn       = $('magic-send-btn');
const magicSendResult    = $('magic-send-result');

const healthCard   = $('health-card');
const healthBtn    = $('health-btn');
const healthResult = $('health-result');

// ── State ─────────────────────────────────────────────────────────────────────
let apiBase = '';
let apiKey  = '';

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Normalise a base URL: strip trailing slash.
 * @param {string} url
 * @returns {string}
 */
function normaliseBase(url) {
  return url.replace(/\/+$/, '');
}

/**
 * Make an authenticated request to the MailGuard API.
 *
 * @param {string} path   - e.g. '/otp/send'
 * @param {Object} [body] - JSON-serialisable body; omit for GET
 * @returns {Promise<{ok: boolean, status: number, data: unknown}>}
 */
async function apiFetch(path, body) {
  const url = `${apiBase}${path}`;
  const headers = {
    'Authorization': `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  };
  const init = body !== undefined
    ? { method: 'POST', headers, body: JSON.stringify(body) }
    : { method: 'GET',  headers };

  const res = await fetch(url, init);
  let data;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
}

/**
 * Display a JSON response in a <pre> element.
 *
 * @param {HTMLElement} el
 * @param {{ ok: boolean, status: number, data: unknown }} result
 */
function showResult(el, result) {
  el.classList.remove('hidden', 'ok', 'err');
  el.classList.add(result.ok ? 'ok' : 'err');
  el.textContent = JSON.stringify(result.data, null, 2);
}

/**
 * Set loading state on a button.
 *
 * @param {HTMLButtonElement} btn
 * @param {boolean} loading
 */
function setLoading(btn, loading) {
  btn.disabled = loading;
  btn.textContent = loading ? 'Loading…' : btn.dataset.label;
}

/** Reveal the post-connect panels. */
function showPanels() {
  otpCard.classList.remove('hidden');
  magicCard.classList.remove('hidden');
  healthCard.classList.remove('hidden');
}

/** Persist connection details in sessionStorage. */
function saveSession() {
  sessionStorage.setItem('mg_api_base', apiBase);
  sessionStorage.setItem('mg_api_key', apiKey);
}

/** Restore connection details from sessionStorage. */
function restoreSession() {
  const base = sessionStorage.getItem('mg_api_base');
  const key  = sessionStorage.getItem('mg_api_key');
  if (base && key) {
    apiBase = base;
    apiKey  = key;
    apiUrlInput.value = base;
    apiKeyInput.value = key;
    connStatus.textContent = '✓ Restored from session';
    connStatus.className = 'status ok';
    showPanels();
  }
}

// ── Initialise button labels ──────────────────────────────────────────────────
[connectBtn, otpSendBtn, otpVerifyBtn, magicSendBtn, healthBtn].forEach((btn) => {
  btn.dataset.label = btn.textContent;
});

// ── Connect ───────────────────────────────────────────────────────────────────
connectBtn.addEventListener('click', async () => {
  const rawBase = apiUrlInput.value.trim();
  const rawKey  = apiKeyInput.value.trim();

  if (!rawBase) {
    connStatus.textContent = '✗ API Base URL is required';
    connStatus.className = 'status err';
    return;
  }
  if (!rawKey) {
    connStatus.textContent = '✗ API Key is required';
    connStatus.className = 'status err';
    return;
  }

  apiBase = normaliseBase(rawBase);
  apiKey  = rawKey;

  connStatus.textContent = 'Connecting…';
  connStatus.className = 'status loading';
  setLoading(connectBtn, true);

  try {
    const res = await apiFetch('/health');
    if (res.ok) {
      connStatus.textContent = '✓ Connected';
      connStatus.className = 'status ok';
      saveSession();
      showPanels();
    } else {
      connStatus.textContent = `✗ API returned ${res.status}`;
      connStatus.className = 'status err';
    }
  } catch (err) {
    connStatus.textContent = `✗ ${err.message}`;
    connStatus.className = 'status err';
  } finally {
    setLoading(connectBtn, false);
  }
});

// ── OTP: Send ─────────────────────────────────────────────────────────────────
otpSendBtn.addEventListener('click', async () => {
  const email   = otpEmailInput.value.trim();
  const project = otpProjectInput.value.trim();
  if (!email || !project) {
    otpSendResult.classList.remove('hidden', 'ok');
    otpSendResult.classList.add('err');
    otpSendResult.textContent = 'Email and Project ID are required.';
    return;
  }

  setLoading(otpSendBtn, true);
  try {
    const res = await apiFetch('/otp/send', { email, project_id: project });
    showResult(otpSendResult, res);
  } catch (err) {
    otpSendResult.classList.remove('hidden', 'ok');
    otpSendResult.classList.add('err');
    otpSendResult.textContent = `Network error: ${err.message}`;
  } finally {
    setLoading(otpSendBtn, false);
  }
});

// ── OTP: Verify ───────────────────────────────────────────────────────────────
otpVerifyBtn.addEventListener('click', async () => {
  const email   = otpVerifyEmail.value.trim();
  const code    = otpCode.value.trim();
  const project = otpVerifyProject.value.trim();
  if (!email || !code || !project) {
    otpVerifyResult.classList.remove('hidden', 'ok');
    otpVerifyResult.classList.add('err');
    otpVerifyResult.textContent = 'Email, code, and Project ID are required.';
    return;
  }

  setLoading(otpVerifyBtn, true);
  try {
    const res = await apiFetch('/otp/verify', { email, code, project_id: project });
    showResult(otpVerifyResult, res);
  } catch (err) {
    otpVerifyResult.classList.remove('hidden', 'ok');
    otpVerifyResult.classList.add('err');
    otpVerifyResult.textContent = `Network error: ${err.message}`;
  } finally {
    setLoading(otpVerifyBtn, false);
  }
});

// ── Magic Links: Send ─────────────────────────────────────────────────────────
magicSendBtn.addEventListener('click', async () => {
  const email    = magicEmailInput.value.trim();
  const project  = magicProjectInput.value.trim();
  const redirect = magicRedirectInput.value.trim();

  if (!email || !project) {
    magicSendResult.classList.remove('hidden', 'ok');
    magicSendResult.classList.add('err');
    magicSendResult.textContent = 'Email and Project ID are required.';
    return;
  }

  const body = { email, project_id: project };
  if (redirect) body.redirect_url = redirect;

  setLoading(magicSendBtn, true);
  try {
    const res = await apiFetch('/magic/send', body);
    showResult(magicSendResult, res);
  } catch (err) {
    magicSendResult.classList.remove('hidden', 'ok');
    magicSendResult.classList.add('err');
    magicSendResult.textContent = `Network error: ${err.message}`;
  } finally {
    setLoading(magicSendBtn, false);
  }
});

// ── Health ────────────────────────────────────────────────────────────────────
healthBtn.addEventListener('click', async () => {
  setLoading(healthBtn, true);
  try {
    const res = await apiFetch('/health');
    showResult(healthResult, res);
  } catch (err) {
    healthResult.classList.remove('hidden', 'ok');
    healthResult.classList.add('err');
    healthResult.textContent = `Network error: ${err.message}`;
  } finally {
    setLoading(healthBtn, false);
  }
});

// ── Restore session on load ───────────────────────────────────────────────────
restoreSession();
