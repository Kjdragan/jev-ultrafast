(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  // ---- estate patch (JEV_LABELS=1), 2026-09-23 ---------------------------------------
  // A checkbox or radio styled as `opacity: 0` over or under its own visible <label> fails
  // `visible` (checkOpacity), so stock never offers it: Wikipedia's Main menu, Tools and
  // language toggles and its appearance radios, TodoMVC's "Mark all as complete" (measured
  // by a click probe on 39 pages: 9 of the 12 real misses). Such an input is offered when a
  // label of its own is rendered; the label names it already. `shown` replaces `visible`
  // only where a control is offered or guarded. The LABEL need only be rendered, not
  // exposed: Wikipedia marks its dropdown labels `aria-hidden` because the transparent input
  // on top (`role="button"`, `aria-label`) is the accessible control. The INPUT keeps the
  // aria-hidden/inert check. A label that is not rendered leaves the input unoffered, as does
  // an input hidden by CSS visibility or display.
  const __lb = "__JEV_LABELS_MODE__" === "1";
  const labelledBy = e => __lb && e.tagName==='INPUT' && ['checkbox','radio'].includes(e.type) &&
    !e.closest('[aria-hidden="true"],[inert]') && e.checkVisibility({checkVisibilityCSS:true}) ?
    [...(e.labels||[])].filter(l=>l.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) : [];
  const shown = e => visible(e) || labelledBy(e).length>0;
  const hitAt = el => { const b=el.getBoundingClientRect();
    return [b,...el.getClientRects()].some(q => { const fx=q.x+q.width/2, fy=q.y+q.height/2;
      return q.width>0 && q.height>0 && fx>=0 && fy>=0 && fx<innerWidth && fy<innerHeight &&
        el.contains(document.elementFromPoint(fx,fy)); }); };
  // ---- end estate patch --------------------------------------------------------------
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !shown(e)) return null;  // estate patch (JEV_LABELS): shown
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  // ---- estate patch (JEV_LISTENERS=1), 2026-09-23 --------------------------------------
  // A control whose ONLY clickability is a listener attached by script leaves no trace in
  // the DOM: jQuery tablesorter binds `.click()` on a bare `<th class="header">`, and the
  // selector above never matches it (the-internet /tables, measured: Jev blocked at 0
  // actions every trial). The one instrument that sees such a listener is the inspector's,
  // so browser.py evaluates this file with `includeCommandLineAPI` on the observe path and
  // the DevTools `getEventListeners(el)` is in scope here -- the same backend as CDP
  // `DOMDebugger.getEventListeners`, in one round trip instead of one per node.
  // Every OTHER evaluation of this file (the freshness marker, the readiness gate, and the
  // instruments that read it off disk) runs without that API, so it reuses the set the last
  // observe found; a set that changed between two reads of one page would make every
  // decision stale. The mode is an ALLOW-LIST like the viewport's: unsubstituted is stock.
  // What is offered: a visible, labelled element outside every indexed control, with a
  // click/mouse/pointer listener ON ITSELF, not larger than a quarter of the viewport, and
  // containing no indexed control (a card or row whose link is already offered is a
  // wrapper, not a second control). When a hit contains another hit, the inner one stays.
  // Delegated listeners (React's root, jQuery `.on(sel, fn)`) sit on an ancestor and are
  // NOT seen -- this reads where a listener is attached, not what it handles.
  const __ls = "__JEV_LISTENERS_MODE__", __lvp = "__JEV_VIEWPORT_MODE__";
  let listened = __ls === "1" ? (cache.listen || []) : [];
  if (__ls === "1" && typeof getEventListeners === 'function') {
    const kinds=['click','mousedown','mouseup','pointerdown','pointerup'], found=[];
    const quarter=innerWidth*innerHeight/4;
    for (const e of document.body.querySelectorAll('*')) {
      if (found.length>=60) break;
      if (['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','IFRAME','BR'].includes(e.tagName) ||
          (e instanceof SVGElement && e.tagName.toLowerCase()!=='svg')) continue;
      const r=e.getBoundingClientRect();
      if (r.width<=0 || r.height<=0 || r.width*r.height>quarter) continue;
      const cx=r.x+r.width/2, cy=r.y+r.height/2;
      if ((cx<0 || cy<0 || cx>=innerWidth || cy>=innerHeight) &&
          !(__lvp === "index" || __lvp === "scroll")) continue;
      const l=getEventListeners(e);
      if (!kinds.some(k=>l[k] && l[k].length)) continue;
      if (e.closest(selector) || e.querySelector(selector) || !visible(e) || !name(e)) continue;
      found.push(e);
    }
    listened=cache.listen=found.filter(e=>!found.some(o=>o!==e && e.contains(o)));
  }
  listened=listened.filter(e=>e.isConnected);
  const __listenedSet=new Set(listened);
  const candidates=[...document.querySelectorAll(selector)];
  if (listened.length) {
    candidates.push(...listened);
    candidates.sort((a,b)=>a===b ? 0 : a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
  }
  // ---- end estate patch --------------------------------------------------------------
  const actions=[];
  for (const e of candidates) {
    if (!safe(e) || !shown(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2,
      rname=role(e) || (__listenedSet.has(e) ? 'button' : null);
    if (!rname || r.width<=0 || r.height<=0) continue;
    // ---- estate patch (JEV_VIEWPORT), 2026-09-21 -------------------------------------
    // Stock drops every control whose CENTRE is outside the viewport, which on a real
    // console is about half of them (83 of 116 on one board). `__JEV_VIEWPORT_MODE__` is
    // substituted by browser.py from the env at import; empty means stock, so an unset
    // checkout indexes exactly what it always did. `offscreen` rides on the action either
    // way, because a caller has to be able to tell a control it can reach from one it
    // cannot -- the ACT GUARD applies this same test again, so indexing alone changes
    // nothing on its own.
    // The mode is an ALLOW-LIST, so an UNSUBSTITUTED file is stock. This file is read
    // straight off disk by five instruments here (`jev_batch`, `jev_sweep`'s presettle,
    // `jev_snapshot`, `jev_blindspots`, `jev_extractor_delta`) which never run browser.py's
    // substitution -- and the first version tested `=== ""`, so for them the sentinel was
    // "not empty" and every one silently began indexing offscreen controls. Measured
    // immediately: `rig/prerendered.html` went from 27 controls to 60 with the mode unset.
    const __vp = "__JEV_VIEWPORT_MODE__";
    const __offscreen = x<0 || y<0 || x>=innerWidth || y>=innerHeight;
    if (__offscreen && !(__vp === "index" || __vp === "scroll")) continue;
    // ---- end estate patch --------------------------------------------------------------
    // ---- estate patch (JEV_HITTEST=1), 2026-09-23 --------------------------------------
    // Offer an in-viewport control only if the act guard in browser.py would accept it:
    // the same test, `e.contains(document.elementFromPoint(centre))`. Without it the
    // indexer offers what the guard then refuses ("Target changed or is covered"), and Jev,
    // choosing correctly, picks it again after every re-observe. Measured on
    // platform.claude.com /docs/en/models/overview: a sidebar "Pricing" link whose centre is
    // in the viewport but clipped by the sidebar's scroll container, chosen 118 times in a
    // row until the 120-call budget. Also dropped, measured on 25 pages: controls under a
    // consent iframe (BBC, all 33), cookie banners, and nav overflow laid out behind content
    // (Amazon), none of which a person can see or the guard would click. An offscreen control (viewport mode) is not tested
    // here: `scroll` brings it into view before the guard resolves its point. Allow-list
    // mode like the others: unsubstituted is stock.
    // A link that wraps onto two lines has its box centre on the text between its
    // fragments, so the centre fails; the centre of a visible fragment is tried next, and
    // browser.py's act guard uses the same fallback, so what is offered is what can be hit.
    // A covered control is flagged here and dropped from the offer AFTER the marker is built
    // (below): occlusion is geometry, and the marker compares meaning and identity only.
    // Dropping it here let a control that became covered after an observation make the page
    // read as changed -- the vendor's own check_guards.py failed its moving-target check
    // (2026-09-23, fixed the same day; upstream PR #137 carries the same shape).
    const __covered = !__offscreen && "__JEV_HITTEST_MODE__" === "1" && !e.contains(document.elementFromPoint(x,y)) &&
        ![...e.getClientRects()].some(q => { const fx=q.x+q.width/2, fy=q.y+q.height/2;
          return q.width>0 && q.height>0 && fx>=0 && fy>=0 && fx<innerWidth && fy<innerHeight &&
            e.contains(document.elementFromPoint(fx,fy)); }) &&
        !labelledBy(e).some(hitAt);  // estate patch (JEV_LABELS): a hittable label is a way in
    // ---- end estate patch --------------------------------------------------------------
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,offscreen:__offscreen,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    if (__listenedSet.has(e)) base.listener=true;  // estate patch (JEV_LISTENERS): records only
    if (__covered) base.covered=true;  // estate patch (JEV_HITTEST): dropped after the marker
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,covered,...action})=>action);
  actions.splice(0,actions.length,...actions.filter(a=>!a.covered));  // estate patch (JEV_HITTEST)
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
})()
