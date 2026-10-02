const loginForm = document.getElementById('login-form');
const passwordForm = document.getElementById('password-form');

async function submitAuth(event, url, payload) {
  event.preventDefault();
  const status = document.getElementById('auth-status');
  const button = event.currentTarget.querySelector('button[type="submit"]');
  status.hidden = true;
  button.disabled = true;
  try {
    const result = await Admin.api(url, { method: 'POST', body: JSON.stringify(payload) });
    location.assign(result.redirect);
  } catch (error) {
    status.textContent = error.message;
    status.hidden = false;
  } finally {
    button.disabled = false;
  }
}

loginForm?.addEventListener('submit', (event) => {
  submitAuth(event, '/api/auth/login', {
    username: document.getElementById('username').value.trim(),
    password: document.getElementById('password').value,
  });
});

passwordForm?.addEventListener('submit', (event) => {
  const password = document.getElementById('new-password').value;
  const confirmation = document.getElementById('confirm-password');
  confirmation.setCustomValidity(password === confirmation.value ? '' : 'The new passwords must match.');
  if (!confirmation.reportValidity()) {
    event.preventDefault();
    return;
  }
  submitAuth(event, '/api/auth/password', {
    current_password: document.getElementById('current-password').value,
    new_password: password,
  });
});
document.getElementById('confirm-password')?.addEventListener('input', (event) => event.target.setCustomValidity(''));
document.getElementById('new-password')?.addEventListener('input', () => document.getElementById('confirm-password').setCustomValidity(''));
