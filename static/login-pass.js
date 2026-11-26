/* The switch opens the form. Authentication remains in app.js. */
(() => {
  function init() {
    const auth = document.getElementById('auth');
    const form = auth?.querySelector('.auth-form');
    if (!form) return;

    const scene = document.createElement('div');
    scene.className = 'neon-login-entry';
    const label = document.createElement('label');
    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.className = 'neon-login-switch';
    toggle.setAttribute('role', 'switch');
    toggle.setAttribute('aria-controls', 'login-form');
    const prompt = document.createElement('span');
    prompt.textContent = '开启登录';
    label.append(toggle, prompt);
    scene.append(label);
    auth.prepend(scene);

    function addFeishuShortcut() {
      const feishu = document.getElementById('feishu-login');
      if (!feishu) return;
      const shortcut = document.createElement('button');
      shortcut.type = 'button';
      shortcut.textContent = '飞书登录';
      shortcut.className = 'neon-login-link';
      shortcut.onclick = () => feishu.click();
      scene.append(shortcut);
    }
    if (document.readyState === 'complete') addFeishuShortcut();
    else window.addEventListener('load', addFeishuShortcut, {once:true});

    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let opening = 0;
    function showForm() {
      if (auth.hidden || !toggle.checked) return;
      const error = document.getElementById('auth-error');
      if (error?.textContent === 'SESSION_CHANGED') error.textContent = '';
      auth.classList.add('neon-login-open');
      form.inert = false;
      form.querySelector('input')?.focus();
    }
    toggle.addEventListener('change', () => {
      if (!toggle.checked) return;
      toggle.disabled = true;
      if (motion.matches) showForm();
      else opening = window.setTimeout(showForm, 480);
    });
    function sync() {
      window.clearTimeout(opening);
      toggle.checked = false;
      toggle.disabled = false;
      form.inert = !auth.hidden;
      auth.classList.remove('neon-login-open', 'neon-login-success');
    }
    window.hubLoginPass = {
      async complete() {
        if (auth.hidden || motion.matches) return;
        auth.classList.add('neon-login-success');
        await new Promise(resolve => window.setTimeout(resolve, 240));
      },
    };
    auth.classList.replace('pass-login', 'neon-login');
    auth.classList.add('neon-login');
    new MutationObserver(sync).observe(auth, {attributes:true, attributeFilter:['hidden']});
    sync();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
