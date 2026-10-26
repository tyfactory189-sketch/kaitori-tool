/* サイト全体のパスワード保護。
 * データ（data.enc.json・budgets.enc.json）はパスワードで暗号化されて公開されている。
 * ここでパスワードを入れて復号する（パスワードはこのブラウザにだけ記憶）。
 * data.enc.json が無い（暗号化していない）ときは従来どおり data.json を読む。
 */
window.KTS_CRYPT = (() => {
  const KEY = 'kts_site_pass';
  const b64d = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const getPass = () => { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } };
  const setPass = p => { try { p ? localStorage.setItem(KEY, p) : localStorage.removeItem(KEY); } catch (e) { /* noop */ } };
  async function decrypt(enc, pass) {
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt: b64d(enc.salt), iterations: 200000, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64d(enc.iv) }, key, b64d(enc.ct));
    return JSON.parse(new TextDecoder().decode(pt));
  }
  async function tryDecrypt(enc, pass) { try { return await decrypt(enc, pass); } catch (e) { return null; } }

  // ログイン画面（全画面）を出して、正しいパスワードが入るまで待つ
  function askLogin(enc, msg) {
    return new Promise(resolve => {
      const d = document.createElement('div');
      d.id = 'ktsLogin';
      d.innerHTML = `<style>#ktsLogin{position:fixed;inset:0;z-index:9999;background:var(--bg,#f6f7f9);display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif}
        #ktsLogin form{background:var(--panel,#fff);color:var(--ink,#222);border:1px solid var(--line,#ddd);border-radius:12px;padding:28px 26px;width:min(340px,90vw);box-shadow:0 6px 24px rgba(0,0,0,.08)}
        #ktsLogin h1{font-size:18px;margin:0 0 6px}#ktsLogin p{font-size:13px;color:var(--sub,#666);margin:0 0 14px}
        #ktsLogin input{width:100%;box-sizing:border-box;font:inherit;padding:9px 10px;border:1px solid var(--line,#ccc);border-radius:8px;margin-bottom:10px}
        #ktsLogin button{width:100%;font:inherit;padding:9px;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer}
        #ktsLogin .e{color:#d33;font-size:13px;min-height:1.2em;margin-top:8px}</style>
        <form><h1>🔒 ログイン</h1><p>${msg || '買取差益チェッカーのパスワードを入力してください'}</p>
        <input type="password" autocomplete="current-password" placeholder="パスワード" required>
        <button>ログイン</button><div class="e"></div></form>`;
      document.body.appendChild(d);
      const f = d.querySelector('form'), inp = d.querySelector('input'), err = d.querySelector('.e');
      inp.focus();
      f.onsubmit = async ev => {
        ev.preventDefault();
        err.textContent = '確認中…';
        const data = await tryDecrypt(enc, inp.value);
        if (!data) { err.textContent = 'パスワードが違います'; inp.select(); return; }
        setPass(inp.value); d.remove(); resolve(data);
      };
    });
  }

  // データを読む：暗号化版があればパスワードで復号、無ければ平文
  async function loadData(base = '') {
    const r = await fetch(base + 'data.enc.json', { cache: 'no-store' }).catch(() => null);
    if (!r || !r.ok) return fetch(base + 'data.json', { cache: 'no-store' }).then(x => x.json());
    const enc = await r.json();
    const saved = getPass();
    if (saved) { const d = await tryDecrypt(enc, saved); if (d) return d; }
    return askLogin(enc, saved ? 'パスワードが変更されました。新しいパスワードを入力してください' : '');
  }
  function logout() { setPass(''); location.reload(); }
  return { loadData, decrypt, tryDecrypt, getPass, setPass, logout };
})();
