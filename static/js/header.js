import { el } from './dom.js';

// DEMO ONLY: the chosen role is remembered in the browser. It changes what
// each page shows but is not real security.
const STORAGE_KEY = 'uat-role';

export function getRole() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'manager' ? 'manager' : 'tester';
  } catch {
    return 'tester';
  }
}

export function setRole(role) {
  try {
    localStorage.setItem(STORAGE_KEY, role);
  } catch {
    // Storage can be blocked; the switch then simply won't be remembered.
  }
}

function goHome(role) {
  window.location.href = role === 'manager' ? '/static/manager.html' : '/';
}

export function initHeader() {
  const host = document.getElementById('site-header');
  if (!host) return;

  const current = getRole();

  const button = (role, label) =>
    el('button', {
      type: 'button',
      'aria-pressed': String(current === role),
      onclick: () => {
        if (role === current) return;
        setRole(role);
        goHome(role);
      },
    }, label);

  host.replaceChildren(
    el('div', { class: 'site-header__inner' },
      el('a', { class: 'brand', href: '/' }, 'UAT, Untangled'),
      el('div', { class: 'role-switch' },
        el('span', { id: 'role-label' }, 'Viewing as'),
        el('div', { class: 'role-switch__group', role: 'group', 'aria-labelledby': 'role-label' },
          button('tester', 'Tester'),
          button('manager', 'Manager'),
        ),
      ),
    ),
  );
}
