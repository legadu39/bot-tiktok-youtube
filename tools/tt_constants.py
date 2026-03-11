#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Constantes pour TikTok Uploader.
Contient tous les snippets de code JavaScript (JS_*)
et les indicateurs de fonctionnalités (flags).
"""

# --- Constantes (PATCH) ---
NEUTRALIZE_FILENAME_FOR_PREFILL = True  # évite le préremplissage caption
TT_TMP_DIRNAME = ".tt_tmp"

# -------------------------
# JS probes/actions
# -------------------------

JS_FIND_INPUTS = r"""(() => {
  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 &&
           rect.height > 0 &&
           style.display !== 'none' &&
           style.visibility !== 'hidden' &&
           style.opacity !== '0' &&
           !el.disabled;
  }
  function scan(doc) {
    let inputs = [];
    let visible = 0;
    try {
      inputs = Array.from(doc.querySelectorAll('input[type="file"]'));
      for (const el of inputs) {
        if (isVisible(el)) visible++;
      }
    } catch (e) {
      // ignore errors on this document
    }
    let iframes = [];
    try {
      iframes = Array.from(doc.querySelectorAll('iframe'));
    } catch (e) {
      // ignore
    }
    for (const f of iframes) {
      try {
        const sub = f.contentDocument;
        if (sub) {
          const r = scan(sub);
          inputs = inputs.concat(r.inputs);
          visible += r.visible;
        }
      } catch (e) {
        // cross-origin or inaccessible frame, ignore
      }
    }
    return { inputs, visible };
  }
  try {
    const r = scan(document);
    return { count: r.inputs.length, visible: r.visible };
  } catch (e) {
    return { count: 0, visible: 0, error: String(e) };
  }
})()"""

JS_PAGE_UPLOAD_READY = r"""
(() => {
  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 &&
           rect.height > 0 &&
           style.display !== 'none' &&
           style.visibility !== 'hidden' &&
           el.offsetParent !== null;
  }
  const state = {
    has_file_inputs: false,
    visible_file_inputs: 0,
    has_drop_zone: false,
  };
  try {
    const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
    state.has_file_inputs = inputs.length > 0;
    state.visible_file_inputs = inputs.filter(isVisible).length;
  } catch (e) {
    // ignore
  }
  try {
    const dropCandidate = document.querySelector(
      '[data-intelligent-dropzone], [data-e2e="drag-upload"], [data-e2e="upload-zone"]'
    );
    state.has_drop_zone = !!(dropCandidate && isVisible(dropCandidate));
  } catch (e) {
    // ignore
  }
  const ready = state.visible_file_inputs > 0 || state.has_drop_zone;
  return { ready, state, href: location.href };
})()
"""

# --- PATCH CRITIQUE V3: IGNORER LA SIDEBAR ET DÉTECTER L'ÉDITION ---
JS_DETECT_CTA = r"""
(() => {
  // 1. SAFETY CHECK: Si on est déjà en mode édition, on coupe court.
  // On cherche les marqueurs de la page "Détails" (Description, Cover, etc.)
  const editMarkers = [
    'div[contenteditable="true"]',
    'textarea',
    'input[type="text"]',
    '.notranslate', // Classe souvent utilisée pour le caption
    '[data-e2e="caption-input"]'
  ];
  
  if (editMarkers.some(sel => document.querySelector(sel))) {
      // On retourne false pour dire "Pas de bouton upload ici, on est déjà plus loin"
      return {cta: false, count: 0, reason: "already_in_edit_mode"};
  }

  function text(n){return (n&&(n.innerText||n.textContent)||'').trim().toLowerCase();}
  
  function vis(n){ 
      if(!n) return false; 
      const s=getComputedStyle(n); 
      return s.display!=='none' && s.visibility!=='hidden' && n.offsetParent!==null;
  }
  
  const terms=/(select\s*video|drag.*drop|choose\s*file|upload|importer|téléverser|télécharger|choisir\s*un\s*fichier)/i;
  
  // 2. SMART FILTERING: On exclut explicitement la barre latérale (nav, sidebar)
  const cands=[...document.querySelectorAll('button,div[role=button],label,a')]
    .filter(n => {
        // Doit être visible et contenir les mots clés
        if (!vis(n) || !terms.test(text(n))) return false;
        
        // CRITIQUE: Ne doit PAS être dans la barre de navigation latérale
        if (n.closest('nav') || n.closest('[class*="SideNav"]') || n.closest('[class*="sidebar"]')) return false;
        
        return true;
    });

  const dz=document.querySelector('[data-e2e*="upload"],[data-e2e*="dropzone"],.upload-dropzone');
  
  return {cta: cands.length>0 || !!dz, count: cands.length + (dz?1:0)};
})()
"""

JS_EXIT_MODAL_DISMISS = r"""
(() => {
  function text(n){return (n&&(n.innerText||n.textContent)||'').trim();}
  function v(n){if(!n)return false; const s=getComputedStyle(n); return s.display!=='none'&&s.visibility!=='hidden'&&n.offsetParent!==null;}
  const ds=[...document.querySelectorAll('[role="dialog"],.modal,.Modal,.tiktok-modal')];
  for(const d of ds){ if(!v(d)) continue; const t=(d.innerText||'').toLowerCase(); if(/(exit|leave|quitter|are you sure|êtes[- ]vous sûr)/i.test(t)){ const btn=[...d.querySelectorAll('button')]; const c=btn.find(b=>/(cancel|stay|rester|annuler)/i.test(text(b))); if(c){c.click(); return {dismissed:true};}}}
  return {dismissed:false};
})()
"""

JS_UPLOAD_SIGNS = r"""
(() => {
  function text(n){return (n&&(n.innerText||n.textContent)||'').trim();}
  const replace=[...document.querySelectorAll('button')].find(b=>/replace|remplacer/i.test(text(b)));
  const uploaded=[...document.querySelectorAll('*')].find(n=>/uploaded|tél[ée]vers[ée]e|charg[ée]e/i.test(text(n)));
  const bars=[...document.querySelectorAll('progress,[role=progressbar]')];
  let full=false; for(const p of bars){ try{ if(p.hasAttribute('max')){ if(Number(p.value||0)>=Number(p.max||100)){ full=true; break; } } }catch(e){} }
  return {replace:!!replace, uploaded:!!uploaded||full};
})()
"""

JS_SNAPSHOT_POST = r"""
(() => {
  function text(n){try{return (n&&(n.innerText||n.textContent)||'').trim();}catch(e){return ''}}
  function vis(n){ if(!n) return false; const s=getComputedStyle(n); return s.display!=='none'&&s.visibility!=='hidden'&&n.offsetParent!==null;}
  const btns=[...document.querySelectorAll('button')];
  let cand=btns.find(b=>/^(post|publier)$/i.test(text(b)));
  if(!cand){ cand=btns.find(b=> (b.dataset && b.dataset.e2e && /post/i.test(b.dataset.e2e))); }
  if(!cand){
    cand=btns.find(b=>{const s=getComputedStyle(b); return /rgb\(/i.test(s.backgroundColor)&&s.backgroundColor.includes('255')&&(s.backgroundColor.includes('59')||s.backgroundColor.includes('43')||s.backgroundColor.includes('84'));});
  }
  if(!cand) return {present:false,visible:false,disabled:true,classes:'',color:'',text:''};
  const s=getComputedStyle(cand);
  const dis=!!(cand.disabled || cand.getAttribute('aria-disabled')==='true' || (cand.className||'').toLowerCase().includes('disabled'));
  return {present:true,visible:vis(cand),disabled:dis,classes:(cand.className||''),color:(s.backgroundColor||''),text:text(cand)};
})()
"""

JS_CLICK_POST = r"""
(() => {
  function text(n){return (n&&(n.innerText||n.textContent)||'').trim();}
  const btns=[...document.querySelectorAll('button')];
  let cand=btns.find(b=>/^(post|publier)$/i.test(text(b)));
  if(!cand){ cand=btns.find(b=> (b.dataset && b.dataset.e2e && /post/i.test(b.dataset.e2e))); }
  if(!cand){
    cand=btns.find(b=>{const s=getComputedStyle(b); return /rgb\(/i.test(s.backgroundColor)&&s.backgroundColor.includes('255')&&(s.backgroundColor.includes('59')||s.backgroundColor.includes('43')||s.backgroundColor.includes('84'));});
  }
  if(cand){ cand.click(); return {clicked:true,text:text(cand)}; }
  return {clicked:false};
})()
"""

JS_CLICK_TRIGGER = r"""
(() => {
  function text(n){return (n&&(n.innerText||n.textContent)||'').trim().toLowerCase();}
  function vis(n){ if(!n) return false; const s=getComputedStyle(n); return s.display!=='none'&&s.visibility!=='hidden'&&n.offsetParent!==null;}
  const terms=/(select files|select\s*video|upload|choose file|drag.*drop|importer|téléverser|télécharger|choisir un fichier)/i;
  const cands=[...document.querySelectorAll('button,div[role=button],label,a')].filter(n=>vis(n)&&terms.test(text(n)));
  if(cands.length){ cands[0].click(); return {clicked:true, label:text(cands[0])}; }
  return {clicked:false};
})()
"""

JS_DISPATCH_FILE_CHANGE_ROBUST = r"""(() => {
  let fired = 0;
  try {
    const ins = Array.from(document.querySelectorAll('input[type="file"]'));
    for (const input of ins) {
      try {
        const evInput = new Event('input', { bubbles: true });
        const evChange = new Event('change', { bubbles: true });
        input.dispatchEvent(evInput);
        input.dispatchEvent(evChange);
        fired++;
      } catch (e) {
        // ignore per-input errors
      }
    }
    return { fired, inputs_found: ins.length };
  } catch (e) {
    return { fired, inputs_found: 0, error: String(e) };
  }
})()"""

JS_CLICK_CONFIRM_POST = r"""(() => {
  function text(n) {
    return (n && (n.innerText || n.textContent) || '').trim();
  }

  function textLower(n) {
    return text(n).toLowerCase();
  }

  function vis(n) {
    if (!n) return false;
    const s = getComputedStyle(n);
    return s.display !== 'none' &&
           s.visibility !== 'hidden' &&
           n.offsetParent !== null;
  }

  // Heuristiques de mots-clés pour le dialog et les boutons
  const dialogRe = /(post video|publish|publier|continue to post|continue\s+posting)/i;
  const looseDialogRe = /(continue|post|publish|publier)/i;
  const buttonRe = /(post|publish|publier|continue to post|continue)/i;

  const dialogs = Array.from(
    document.querySelectorAll(
      '[role="dialog"], .modal, .Modal, .tiktok-modal, [data-e2e*="modal"]'
    )
  );

  let anyVisible = false;

  for (const d of dialogs) {
    if (!vis(d)) continue;
    anyVisible = true;

    const t = textLower(d);
    if (!t) continue;

    // 1) Filtre strict : wording explicite connu (inclut "continue to post")
    let matchesDialog = dialogRe.test(t);

    // 2) Filtre plus permissif : dialog qui contient à la fois "continue"
    //    et un indice de post / publish / publier
    if (!matchesDialog && looseDialogRe.test(t)) {
      if (t.includes('continue') && (t.includes('post') || t.includes('publish') || t.includes('publier'))) {
        matchesDialog = true;
      }
    }

    if (!matchesDialog) {
      continue;
    }

    // Chercher les boutons dans ce dialog
    const buttons = Array.from(
      d.querySelectorAll('button, .button, [role="button"]')
    );

    if (!buttons.length) {
      // On a bien un dialog de confirmation, mais aucun bouton cliquable trouvé
      return {
        clicked: false,
        modal_found: true,
        reason: 'no_buttons_in_dialog'
      };
    }

    // Scorer les boutons pour choisir le plus probable
    function scoreButton(b) {
      const lbl = textLower(b);
      let score = 0;

      if (!lbl) return 0;

      if (buttonRe.test(lbl)) score += 5;
      if (lbl.includes('continue to post')) score += 5;
      if (lbl === 'post' || lbl === 'publier') score += 3;

      const cls = (b.className || '').toLowerCase();
      if (/primary|confirm|publish|post/.test(cls)) score += 2;

      const d2 = b.dataset || {};
      const e2e = (d2.e2e || d2.e2E || '').toLowerCase();
      if (e2e && /post|confirm|publish/.test(e2e)) score += 2;

      return score;
    }

    let best = null;
    let bestScore = 0;
    for (const b of buttons) {
      const s = scoreButton(b);
      if (s > bestScore) {
        bestScore = s;
        best = b;
      }
    }

    if (best && bestScore > 0) {
      try {
        best.click();
        return {
          clicked: true,
          modal_found: true,
          label: text(best),
          score: bestScore
        };
      } catch (e) {
        return {
          clicked: false,
          modal_found: true,
          reason: 'click_error:' + String(e)
        };
      }
    }

    // Dialog identifié, mais aucun bouton ne matche vraiment
    return {
      clicked: false,
      modal_found: true,
      reason: 'no_matching_button'
    };
  }

  // Aucun dialog visible ou pertinent trouvé
  return {
    clicked: false,
    modal_found: false,
    anyVisible: anyVisible,
    dialogsCount: dialogs.length
  };

})()"""