"""Real-browser checks for checkboxes and radios hidden by opacity behind their own labels.

Run with JEV_LABELS=1 (the estate patch); stock fails the first check. Local fixture only; no
model calls or external websites.
"""

from urllib.parse import quote

from jev_ultrafast.browser import Browser

# Three shapes measured on real pages, plus the ones that must stay unoffered:
#  - "Main menu": an opacity:0 `role="button"` checkbox laid exactly over its aria-hidden label
#    (Wikipedia's Vector skin: the input is the accessible control, the label only draws it).
#  - "Mark all as complete": an opacity:0 checkbox UNDER its label (TodoMVC, Svelte build).
#  - "Toggle all": a 1x1 opacity:0 checkbox away from its label (TodoMVC, jQuery build).
#  - "Small"/"Large": opacity:0 radios beside their labels (Wikipedia's text-size setting).
#  - "Ghost": opacity:0 checkbox whose only label is display:none -> not offered.
#  - "Gone": display:none checkbox with a visible label -> not offered.
#  - "Plain": an ordinary visible checkbox, unchanged.
HTML = """<!doctype html><title>Label checks</title>
<style>
body{margin:20px;font:16px sans-serif} .row{position:relative;height:44px;margin:8px 0}
.hide{opacity:0} label{display:inline-block;padding:10px;background:#eee}
#menu{position:absolute;left:0;top:0;width:120px;height:40px;margin:0}
#menu + label{width:100px}
#all{position:absolute;left:4px;top:4px;width:30px;height:30px;margin:0}
#all + label{position:relative;z-index:1;width:40px;height:40px;padding:0;background:#ddd}
#tog{position:absolute;left:300px;top:0;width:1px;height:1px;margin:0}
.radio input{position:absolute;left:0;opacity:0} .radio label{margin-left:0}
</style>
<div class="row"><input type="checkbox" id="menu" class="hide" role="button" aria-haspopup="true"
  aria-label="Main menu"><label for="menu" aria-hidden="true">Menu</label></div>
<div class="row"><input type="checkbox" id="all" class="hide">
  <label for="all" aria-label="Mark all as complete"></label></div>
<div class="row"><input type="checkbox" id="tog" class="hide"><label for="tog">Toggle all</label></div>
<div class="row radio"><input type="radio" name="size" id="s" value="s"><label for="s">Small</label>
  <input type="radio" name="size" id="l" value="l" checked style="left:120px"><label for="l">Large</label></div>
<div class="row"><input type="checkbox" id="ghost" class="hide">
  <label for="ghost" style="display:none">Ghost</label></div>
<div class="row"><input type="checkbox" id="gone" style="display:none"><label for="gone">Gone</label></div>
<div class="row"><label><input type="checkbox" id="plain">Plain</label></div>
"""


def main():
    browser = Browser("data:text/html," + quote(HTML))
    passed = []
    try:
        page = browser.observe(screenshot=False)
        offered = {a["label"]: a for a in page["actions"]
                   if a.get("role") in ("checkbox", "radio", "button")}
        for label in ("Main menu", "Mark all as complete", "Toggle all", "Small", "Plain"):
            assert label in offered, f"{label!r} must be offered; offered: {sorted(offered)}"
        assert offered["Small"]["role"] == "radio" and offered["Main menu"]["role"] == "button"
        passed.append("opacity-hidden checkboxes and radios offered under their label, with state")
        assert "Ghost" not in offered and "Gone" not in offered, sorted(offered)
        passed.append("hidden label or display:none input not offered")
        assert browser.fresh(page), "The freshness marker must agree with the observe read"
        passed.append("freshness marker agrees")

        for label, element in (("Main menu", "menu"), ("Mark all as complete", "all"),
                               ("Toggle all", "tog"), ("Small", "s"), ("Plain", "plain")):
            page = browser.observe(screenshot=False)
            action = next(a for a in page["actions"] if a["label"] == label and a["kind"] == "click")
            browser.act(action, page)
            assert browser.evaluate(f"document.getElementById('{element}').checked") is True, label
            passed.append(f"{label!r} toggled by a real click")
        page = browser.observe(screenshot=False)
        small = next(a for a in page["actions"] if a["label"] == "Small")
        assert small["checked"] == "true"
        assert browser.evaluate("document.getElementById('l').checked") is False
        passed.append("the observation reports the new state")
    finally:
        browser.close()
    for item in passed:
        print("PASS:", item)


if __name__ == "__main__":
    main()
