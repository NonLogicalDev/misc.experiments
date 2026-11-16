// Try the synchronous selection path during the click gesture, including on HTTP.
export async function copyText(text, doc=globalThis.document, clipboard=globalThis.navigator?.clipboard) {
  let field;
  const previousFocus=doc.activeElement;
  try {
    field=doc.createElement('textarea');
    field.value=text;
    field.setAttribute('readonly','');
    Object.assign(field.style,{position:'fixed',left:'-9999px',top:'0',fontSize:'16px'});
    doc.body.appendChild(field);
    field.focus({preventScroll:true});
    field.select();
    field.setSelectionRange(0,text.length);
    if(doc.execCommand('copy')) return true;
  } catch {} finally {
    field?.remove();
    if(previousFocus?.isConnected) previousFocus.focus({preventScroll:true});
  }
  try { if(clipboard?.writeText) { await clipboard.writeText(text); return true; } } catch {}
  return false;
}
