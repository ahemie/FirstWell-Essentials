// FirstWell Essentials Staff UI. Flask protects all routes; this only displays login state.
(async function () {
  try {
    const res = await fetch('/api/auth/session', {credentials:'same-origin'});
    if (!res.ok) { location.href = '/login'; return; }
    const session = await res.json();
    const box = document.createElement('div');
    box.style.cssText = 'position:fixed;bottom:15px;right:15px;background:white;border:1px solid #dde1dc;border-radius:10px;padding:8px 12px;z-index:99999;font:13px system-ui;box-shadow:0 3px 10px #0002';
    const label = document.createElement('span');
    label.textContent = session.email + '  ';
    const btn = document.createElement('button');
    btn.textContent = 'Sign out';
    btn.style.cssText='cursor:pointer;padding:6px;border-radius:6px';
    btn.onclick = async () => { await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':session.csrf_token}});location.href='/login'; };
    box.append(label,btn);
    document.body.appendChild(box);
  } catch (_) { location.href = '/login'; }
})();
