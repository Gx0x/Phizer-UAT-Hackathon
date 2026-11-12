import { el } from './dom.js';

// DEMO ONLY: browser roles change the view, not real access permissions.
const STORAGE_KEY = 'uat-role';
const ROLES = ['tester', 'manager', 'developer'];

export function getRole() {
  try {
    const role = localStorage.getItem(STORAGE_KEY);
    return ROLES.includes(role) ? role : 'tester';
  } catch {
    return 'tester';
  }
}

export function setRole(role) {
  try {
    localStorage.setItem(STORAGE_KEY, role);
  } catch {
    // The role switch still works when browser storage is available again.
  }
}

function goHome(role) {
  const pages = { tester: '/', manager: '/static/manager.html', developer: '/static/developer.html' };
  window.location.href = pages[role] ?? '/';
}

export function initHeader() {
  const host = document.getElementById('site-header');
  if (!host) return;
  const current = getRole();
  const button = (role, label) => el('button', {
    type: 'button', 'aria-pressed': String(current === role),
    onclick: () => {
      if (role === current) return;
      setRole(role);
      goHome(role);
    },
  }, label);
  host.replaceChildren(
    el('div', { class: 'site-header__inner' },
      el('a', { class: 'brand', href: '/' }, 'UAT Clarif-AI'),
      el('div', { class: 'role-switch' },
        el('span', { id: 'role-label' }, 'Viewing as'),
        el('div', { class: 'role-switch__group', role: 'group', 'aria-labelledby': 'role-label' },
          button('tester', 'Tester'), button('manager', 'Manager'), button('developer', 'Developer'),
        ),
      ),
    ),
  );
}
