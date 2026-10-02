const usersTable = document.getElementById('users');
const usersStatus = document.getElementById('users-status');
const editDialog = document.getElementById('edit-user-dialog');
const createForm = document.getElementById('create-user-form');
const editForm = document.getElementById('edit-user-form');
const esc = Admin.escapeHtml;
let users = [];
let editing = null;
let saving = false;

function formError(id, message = '') {
  const box = document.getElementById(id);
  box.textContent = message;
  box.hidden = !message;
}

async function loadUsers() {
  usersTable.setAttribute('aria-busy', 'true');
  try {
    users = (await Admin.api('/api/users')).users;
    usersTable.innerHTML = `<table><thead><tr><th>Username</th><th>Role</th><th>Access</th><th>Password</th><th>Actions</th></tr></thead><tbody>
      ${users.map((user) => `<tr>
        <td>${esc(user.username)}${user.username === document.body.dataset.username ? '<small class="table-subtitle">You</small>' : ''}</td>
        <td>${user.role === 'admin' ? 'Administrator' : 'Editor'}</td>
        <td><span class="player-status">${user.enabled ? 'Enabled' : 'Disabled'}</span></td>
        <td>${user.must_change_password ? 'Change required' : 'Set'}</td>
        <td>${user.username === document.body.dataset.username ? '<a href="/password" class="button button-quiet">Change my password</a>'
          : `<button class="button button-quiet" data-manage="${esc(user.username)}" aria-label="Manage ${esc(user.username)}">Manage</button>`}</td>
      </tr>`).join('')}</tbody></table>`;
    usersStatus.textContent = `${users.length} operator account${users.length === 1 ? '' : 's'}`;
    usersStatus.classList.remove('form-error');
  } catch (error) {
    usersStatus.textContent = `Could not refresh users: ${error.message} Any displayed data may be out of date.`;
    usersStatus.classList.add('form-error');
    throw error;
  } finally {
    usersTable.setAttribute('aria-busy', 'false');
  }
}

createForm.addEventListener('submit', (event) => {
  event.preventDefault();
  formError('create-user-error');
  const password = document.getElementById('user-password').value;
  if (password !== document.getElementById('user-password-confirm').value) {
    formError('create-user-error', 'Temporary passwords do not match.');
    return;
  }
  Admin.busy(createForm.querySelector('[type="submit"]'), async () => {
    try {
      const username = document.getElementById('user-name').value.trim();
      await Admin.api('/api/users', { method: 'POST', body: JSON.stringify({
        username, role: document.getElementById('user-role').value, temporary_password: password,
      }) });
      createForm.reset();
      Admin.notify(`Created ${username}. Share the temporary password privately.`);
      await loadUsers();
    } catch (error) {
      formError('create-user-error', error.message);
    }
  });
});

usersTable.addEventListener('click', (event) => {
  const button = event.target.closest('[data-manage]');
  if (!button) return;
  editing = users.find((user) => user.username === button.dataset.manage);
  editForm.reset();
  formError('edit-user-error');
  document.getElementById('edit-user-title').textContent = `Manage ${editing.username}`;
  const role = document.getElementById('edit-user-role');
  const enabled = document.getElementById('edit-user-enabled');
  role.value = editing.role;
  enabled.checked = editing.enabled;
  role.disabled = enabled.disabled = editing.username === 'admin';
  document.getElementById('protected-user-note').hidden = editing.username !== 'admin';
  editDialog.showModal();
});

editForm.addEventListener('submit', (event) => {
  event.preventDefault();
  formError('edit-user-error');
  const password = document.getElementById('edit-user-password').value;
  if (password !== document.getElementById('edit-user-password-confirm').value) {
    formError('edit-user-error', 'Temporary passwords do not match.');
    return;
  }
  const payload = {
    revision: editing.revision, role: document.getElementById('edit-user-role').value,
    enabled: document.getElementById('edit-user-enabled').checked,
    ...(password ? { temporary_password: password } : {}),
  };
  const username = editing.username;
  const changed = payload.role !== editing.role || payload.enabled !== editing.enabled || Boolean(password);
  if (!changed) {
    editDialog.close();
    return;
  }
  Admin.busy(editForm.querySelector('[type="submit"]'), async () => {
    saving = true;
    document.getElementById('cancel-edit-user').disabled = true;
    try {
      const confirmed = await Admin.confirmAction(
        `Update ${username}?`,
        `Role: ${payload.role === 'admin' ? 'Administrator' : 'Editor'}. Access: ${payload.enabled ? 'enabled' : 'disabled'}.${password ? ' Password will be reset.' : ''} Existing sessions will be signed out.`,
        'Confirm account changes',
      );
      if (!confirmed) return;
      await Admin.api(`/api/users/${encodeURIComponent(username)}`, { method: 'PATCH', body: JSON.stringify(payload) });
      editDialog.close();
      Admin.notify('Account updated.');
    } catch (error) {
      formError('edit-user-error', error.message);
      return;
    } finally {
      saving = false;
      document.getElementById('cancel-edit-user').disabled = false;
    }
    await loadUsers();
  });
});
document.getElementById('cancel-edit-user').addEventListener('click', () => editDialog.close());
editDialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
editDialog.addEventListener('close', () => { editForm.reset(); editing = null; });
document.getElementById('refresh-users').addEventListener('click', (event) => Admin.busy(event.currentTarget, loadUsers));
loadUsers().catch((error) => Admin.notify(error.message, true));
