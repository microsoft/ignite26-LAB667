/* Shared authenticated requests and accessible feedback for the admin only. */
window.Admin = (() => {
  let noticeTimeout;

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
    }[char]));
  }

  function notify(message, error = false) {
    const notice = document.getElementById('notice');
    clearTimeout(noticeTimeout);
    notice.textContent = message;
    notice.dataset.error = String(error);
    notice.hidden = false;
    noticeTimeout = setTimeout(() => { notice.hidden = true; }, error ? 12000 : 5000);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers);
    if (options.body) headers.set('Content-Type', 'application/json');
    if (options.method && options.method !== 'GET') {
      headers.set('X-CSRF-Token', document.querySelector('meta[name="csrf-token"]').content);
    }
    const response = await fetch(url, { ...options, headers, credentials: 'same-origin' });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(`The server returned an unexpected response (${response.status}). Please try again.`);
    }
    if (!response.ok || data.ok === false) {
      if (response.status === 401 && !url.startsWith('/api/auth/')) {
        location.assign('/login');
      }
      if (response.status === 403 && data.detail === 'Password change required') {
        location.assign('/password');
      }
      const detail = typeof data.detail === 'string' ? data.detail : data.error;
      throw new Error(detail || `Request failed (${response.status}). Please try again.`);
    }
    return data;
  }

  async function busy(button, action) {
    button.disabled = true;
    try {
      await action();
    } catch (error) {
      notify(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  function confirmAction(title, description, label) {
    const dialog = document.getElementById('confirm-dialog');
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-description').textContent = description;
    document.getElementById('confirm-action').textContent = label;
    dialog.returnValue = '';
    return new Promise((resolve) => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
      dialog.showModal();
    });
  }

  document.getElementById('logout')?.addEventListener('click', (event) => {
    busy(event.currentTarget, async () => {
      await api('/api/auth/logout', { method: 'POST' });
      location.assign('/login');
    });
  });

  return { api, escapeHtml, notify, busy, confirmAction };
})();
