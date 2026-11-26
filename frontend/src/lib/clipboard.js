// Copy text to the clipboard. navigator.clipboard only exists on secure origins (HTTPS or localhost),
// so on a plain-http LAN address such as http://nas:8000 fall back to a hidden textarea + execCommand.
// Returns true if the text was copied.
export async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch {
            // fall through to the legacy path
        }
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
        ok = document.execCommand('copy');
    } catch {
        ok = false;
    }
    document.body.removeChild(ta);
    return ok;
}
