"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

# Atomically read visible content and controls, preserving actual DOM node identity.
# ---- estate patch (JEV_VIEWPORT), 2026-09-21 -------------------------------------------
# `snapshot.js` runs IN THE PAGE and cannot read the environment, so the mode is substituted
# into its source once, here, at import. Unset -> the empty string -> the file behaves exactly
# as shipped. Two values:
#   index  -- the indexer offers controls whose centre is outside the viewport.
#   scroll -- index, AND the act guard scrolls a target into view before resolving its point.
# `index` alone is deliberately reachable: the viewport test exists TWICE (here and in the act
# guard below), so offering a control the guard will refuse is a measurable state rather than
# an argument, and the arm that proves it is worth being able to run.
JEV_VIEWPORT = os.environ.get("JEV_VIEWPORT", "")
if JEV_VIEWPORT not in ("", "index", "scroll"):
    raise ValueError(f"JEV_VIEWPORT must be '', 'index' or 'scroll'; got {JEV_VIEWPORT!r}")
READ_STATE = (Path(__file__).with_name("snapshot.js").read_text()
              .replace("__JEV_VIEWPORT_MODE__", JEV_VIEWPORT))
# ---- end estate patch ------------------------------------------------------------------
# ---- estate patch (JEV_LISTENERS=1), 2026-09-23 ----------------------------------------
# Index controls whose only clickability is a script-attached listener (snapshot.js has the
# rule and the reason). "1" or unset; the sentinel is substituted here like the viewport's,
# and the substitution is asserted, because one that matches nothing measures stock twice.
JEV_LISTENERS = os.environ.get("JEV_LISTENERS", "")
if JEV_LISTENERS not in ("", "1"):
    raise ValueError(f"JEV_LISTENERS must be '' or '1'; got {JEV_LISTENERS!r}")
if "__JEV_LISTENERS_MODE__" not in READ_STATE:
    raise RuntimeError("snapshot.js carries no __JEV_LISTENERS_MODE__ sentinel")
READ_STATE = READ_STATE.replace("__JEV_LISTENERS_MODE__", JEV_LISTENERS)
# ---- end estate patch ------------------------------------------------------------------
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"

class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Browser:
    def __init__(self, url):
        ensure_daemon()
        self.target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)
        # ---- estate patch (JEV_READY=1), 2026-09-21 ---------------------------------
        self.ready = {"why": "readystate-complete", "gated": False}
        if os.environ.get("JEV_READY") == "1":
            self.ready = self._await_indexer()

    # ---- estate patch (JEV_READY=1), 2026-09-21 -------------------------------------
    # `readyState == "complete"` says the DOCUMENT finished loading. On a client-rendered page
    # the route paints AFTER that, so the constructor above hands the indexer a document with
    # ZERO controls and Jev decides against a blank page. Measured on hPanel (browser_use_lab
    # findings §15j/§15k): the constructor returned at 15.84 s on its own cap with `readyState`
    # still `interactive`, 0 controls, 0 body characters, and `wait` the only action offered --
    # the first indexable control arrived 13.3 s later. It returned 0 controls in all twelve
    # trials across §15k and §15l, foreground and activated included, which is why this fix is
    # independent of the focus half and stands after it.
    #
    # WHAT IT WAITS FOR, and why it is not "at least one control". That naive predicate was
    # built first, inside a harness, and paid for: it returned at 10 of ~18 controls on a real
    # page and Jev answered `done` about a page that was not there yet. A premature `done` is
    # strictly worse than the defect -- it is a wrong answer where a premature `blocked` is at
    # least an honest refusal. So the condition is the indexed count REACHING ONE AND THEN
    # CEASING TO GROW for `quiet` seconds, with a cap so a genuinely empty page still returns.
    #
    # WHAT IT POLLS, measured rather than assumed (browser_use_lab findings §6b). Three cheaper
    # predicates were timed against the real indexer on six pages:
    #   * `document.body.innerText.length` is non-zero from the first paint on any page with a
    #     heading -- 16 chars on a fixture with zero controls -- so it cannot gate.
    #   * a bare `querySelectorAll(<this file's own selector>)` count is ~4x cheaper and tracks
    #     the indexer exactly on ordinary pages, but settles 444 ms EARLY when elements land in
    #     the DOM hidden and are revealed later: the same premature return by another route.
    #   * that count filtered by visibility and `:disabled` fixes the hidden case and still
    #     fails on a real console -- 116 against the indexer's 33, settling 248 ms early,
    #     because `snapshot.js` also rejects anything whose centre is outside the viewport.
    # Only the indexer is the indexer. It costs 8-68 ms per evaluation on the pages measured
    # (68 ms is a 116-control board), which is bounded, paid once per page load, and cheap
    # against a gate that is currently returning blank documents.
    #
    # QUIET WINDOW, 0.6 s. It has to EXCEED the largest gap between two consecutive changes in
    # the indexed count, or the gate returns in the silence between two render bursts. Measured
    # maxima: 240 ms (Mission Control's board), 373 ms (Tome, authenticated), 257 ms (the rig
    # fixture at default spacing), 423 ms (that fixture with its bursts deliberately spread).
    # 0.6 s clears the largest real page by 1.6x. The error is asymmetric -- too short is a
    # wrong answer, too long is a bounded cost on every page -- so it is set generously.
    #
    # CAP, 20 s, and it binds ONLY while the count is still zero. It is longer than the
    # `readyState` wait above so the gate genuinely extends the window, and it covers the
    # activated hPanel range of 7.1-14.5 s. It deliberately does NOT cover that page's
    # UNACTIVATED background target, whose first control arrived at 29.15 s: that is fix (2)'s
    # territory, and a page which never paints reports `capped` rather than pretending.
    _READY_JS = ("(() => { const s=" + READ_STATE + "; if (!s) return null;"
                 " const a=(s.actions||[]).filter(x => x.kind!=='scroll' && x.kind!=='wait');"
                 " return {n: new Set(a.map(x => x.node)).size,"
                 " chars: document.body ? document.body.innerText.length : 0}; })()")

    def _await_indexer(self, quiet=0.6, cap=20.0, poll=0.1):
        """Return once the indexed control count has reached one and stopped growing.

        The return value is the instrument, not logging: `why` separates a page that was
        already fine (`readystate-complete`) from one this gate rescued (`indexer-satisfied`)
        from one that never painted (`capped`). Without it a fixed page and a page that never
        needed fixing are indistinguishable afterwards.
        """
        t0 = last_change = time.monotonic()
        n, chars, polls, peak = 0, 0, 0, 0
        while True:
            try:
                state = self.evaluate(self._READY_JS) or {}
            except StalePage:
                # A navigation landed mid-evaluation. That is a change, not an error.
                state, last_change = {}, time.monotonic()
            polls += 1
            got = int(state.get("n") or 0)
            chars = int(state.get("chars") or 0)
            now = time.monotonic()
            if got != n:
                n, last_change = got, now
                peak = max(peak, got)
            if n >= 1 and now - last_change >= quiet:
                why = "indexer-satisfied"
            elif now - t0 >= cap:
                why = "capped"
            else:
                time.sleep(poll)
                continue
            return {"why": why, "gated": True, "elements_n": n, "peak_elements_n": peak,
                    "chars": chars, "waited_ms": round((now - t0) * 1000), "polls": polls,
                    "quiet_s": quiet, "cap_s": cap}

    def call(self, method, **params):
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    # ---- estate patch (JEV_SETTLE=1), 2026-09-19 -------------------------------------
    # Stock Jev re-observes ~50 ms after an input and treats the page as current. On a page
    # whose handler runs a 3000 ms timer (the-internet's dynamic_controls, measured), that
    # snapshot shows the clicked button DISABLED and a loading indicator VISIBLE, the target
    # of the next step not yet actionable, and Jev chooses BLOCKED at ~4 s — before the
    # page has finished doing what Jev correctly asked it to do. WAIT cannot rescue it: one
    # WAIT sleeps 100 ms, so a 3 s handler is ~30 round trips.
    #
    # This waits, after an input, until the page stops LOOKING busy and then stops CHANGING:
    #   busy   = the acted-on node is now disabled, or aria-busy / a progressbar is set, or
    #            a visible element whose id/class says load/spinner/busy;
    #   settled = the page marker unchanged for `quiet` seconds.
    # Capped at `cap` seconds, then proceeds regardless — so a page that is busy forever
    # degrades to today's behaviour rather than hanging. Pure quiescence is NOT enough on its
    # own: this page is stable for three seconds with a timer pending, and a quiet-window
    # check returns at 0.4 s and misses the change. The busy signals are what carry it.
    _BUSY_JS = """(node => {
      const c = window.__jevFast; const el = c && node != null ? c.nodes.get(node) : null;
      const vis = e => { try { const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(e).display !== 'none'
          && getComputedStyle(e).visibility !== 'hidden'; } catch (_) { return false; } };
      if (el && el.disabled) return 'acted-node-disabled';
      if (document.querySelector('[aria-busy="true"]')) return 'aria-busy';
      for (const e of document.querySelectorAll('progress,[role="progressbar"]')) if (vis(e)) return 'progressbar';
      for (const e of document.querySelectorAll('[id*="load" i],[class*="load" i],[class*="spinner" i],[class*="busy" i]'))
        if (vis(e)) return 'loading-indicator';
      return null;
    })"""

    # Signals in the first set are STRONG: the page itself says it is mid-operation, and they
    # are honoured until they clear. `loading-indicator` is WEAK — an id/class heuristic —
    # and real pages leave such things visible forever (the-internet's dynamic_controls
    # gives two divs the same `id="loading"` and jQuery hides only the first). So it is
    # honoured only until the page has demonstrably moved once since the input; after that
    # a lingering indicator is stale, and trusting it burned the full cap twice per run.
    _STRONG = {"acted-node-disabled", "aria-busy", "progressbar", "stale"}

    def _settle_after_input(self, action, quiet=0.4, cap=8.0):
        node = action.get("node") if isinstance(action.get("node"), int) else None
        pre = getattr(self, "_busy_before_input", None)
        t0 = last_change = time.monotonic()
        marker, changes = None, -1  # first read establishes the baseline, not a change
        while True:
            try:
                busy = self.evaluate(self._BUSY_JS + "(" + json.dumps(node) + ")")
                m = self.evaluate(MARKER)
            except StalePage:
                busy, m = "stale", None
            now = time.monotonic()
            if m != marker:
                marker, last_change, changes = m, now, changes + 1
            if busy and busy not in self._STRONG and (changes > 0 or busy == pre):
                # Weak indicator that was ALREADY showing before this input, or that lingers
                # after the page has moved once: not evidence about this action. Typing, for
                # instance, legitimately changes nothing, so "wait until it moves" would hold
                # a stale indicator for the whole cap.
                busy = None
            if not busy and now - last_change >= quiet:
                return {"waited_ms": round((now - t0) * 1000), "capped": False,
                        "changes": changes}
            if now - t0 >= cap:
                return {"waited_ms": round((now - t0) * 1000), "capped": True,
                        "still": busy, "changes": changes}
            time.sleep(0.1)

    def observe(self, screenshot=True):
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            if os.environ.get("JEV_SETTLE") == "1" and action.get("kind") != "wait":
                self.last_settle = self._settle_after_input(action)
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))(""" + json.dumps(action) + ")",
                    awaitPromise=True,
                    returnByValue=True,
                )
            except RuntimeError:
                pass
        for attempt in range(10):
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        if os.environ.get("JEV_SETTLE") == "1" and action["kind"] != "wait":
            # Baseline for the settle: what already looked busy BEFORE this input.
            node = action.get("node") if isinstance(action.get("node"), int) else None
            try:
                self._busy_before_input = self.evaluate(self._BUSY_JS + "(" + json.dumps(node) + ")")
            except StalePage:
                self._busy_before_input = None
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            # The mode is an ARGUMENT, not a top-level `const`. Every act in a run evaluates
            # this same source in the same context, and a top-level `const`/`let` persists in
            # the global lexical environment -- so a declaration here throws "already been
            # declared" on the SECOND action of every run and nowhere in a single-step test.
            target = evaluate("""((action, VIEWPORT_MODE) => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              let r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
              if (!r.width || !r.height) return null;
              // ---- estate patch (JEV_VIEWPORT=scroll), 2026-09-21 ----------------------
              // The viewport test lives HERE as well as in the indexer, and this is the copy
              // that decides whether an action can be dispatched -- CDP mouse events carry
              // viewport coordinates, so a control below the fold has no point to click.
              // `scroll` brings it into view first, instantly rather than smoothly, because
              // the dispatch that follows is synchronous. Everything after this line is
              // unchanged, including the hit test: a control that is covered once scrolled
              // to is still refused.
              if ((x<0 || y<0 || x>=innerWidth || y>=innerHeight) && VIEWPORT_MODE==='scroll') {
                e.scrollIntoView({block:'center', inline:'center', behavior:'instant'});
                r=e.getBoundingClientRect(); x=r.x+r.width/2; y=r.y+r.height/2;
              }
              // ---- end estate patch ------------------------------------------------------
              if (x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
              if (!e.contains(document.elementFromPoint(x,y))) return null;
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return {x,y};
            })(""" + json.dumps(action) + "," + json.dumps(JEV_VIEWPORT) + ")")
            if target is None:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    if JEV_LISTENERS == "1":
        # ---- estate patch (JEV_LISTENERS=1): the observe read, and only it, gets the
        # DevTools command-line API, so `getEventListeners` exists for snapshot.js. Every
        # other read of READ_STATE reuses the set this one found.
        result = call("Runtime.evaluate", expression=READ_STATE, returnByValue=True,
                      includeCommandLineAPI=True)
        if result.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        info = result.get("result", {}).get("value")
    else:
        info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
