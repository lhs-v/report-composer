/* Motion: the few moves the tree makes. transform/opacity only; reduced motion turns them into fades (or nothing). */
window.Motion = (() => {
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ms = name => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
  // FLIP: measure, mutate, invert with transform, then let go next frame so rows glide to their new place.
  function flip(container, mutate) {
    if (reduced() || !ms("--t-move")) { mutate(); return; }
    const first = new Map([...container.querySelectorAll("[data-id]")].map(el => [el.dataset.id, el.getBoundingClientRect()]));
    mutate();
    if (!first.size) return; // a fresh draw (nothing was on screen): no choreography
    const moved = [];
    for (const el of container.querySelectorAll("[data-id]")) {
      const a = first.get(el.dataset.id), b = el.getBoundingClientRect();
      if (!b.height) continue;                       // hidden by a filter: nothing to animate
      el.style.transition = "none";                   // the invert step must be instant, whatever the class transitions say
      if (!a || !a.height) { el.style.opacity = "0"; moved.push(el); continue; }
      const dy = a.top - b.top;
      if (Math.abs(dy) < 1) { el.style.transition = ""; continue; }
      // an "off" row rests at translateX(-4px); keep that while it slides
      el.style.transform = `translateY(${dy}px)${el.classList.contains("off") ? " translateX(-4px)" : ""}`;
      moved.push(el);
    }
    if (!moved.length) return;
    void container.offsetHeight;                      // commit the inverted state before releasing it
    requestAnimationFrame(() => requestAnimationFrame(() => {
      for (const el of moved) { el.style.transition = "transform var(--t-move) var(--ease-out), opacity var(--t-move) linear"; el.style.transform = ""; el.style.opacity = ""; }
      setTimeout(() => moved.forEach(el => el.style.transition = ""), ms("--t-move") + 20);
    }));
  }
  // add a class for t ms and restart it if it is already running; the earlier timer must not cut the new run short
  const once = (el, cls, t) => {
    if (!el) return;
    const timers = el._once || (el._once = {});
    clearTimeout(timers[cls]);
    el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
    timers[cls] = setTimeout(() => { el.classList.remove(cls); delete timers[cls]; }, t);
  };
  const tap = el => { if (el) once(el, "tap", ms("--t-tap") + 20); };
  const flash = els => els.forEach(el => once(el, "flash", ms("--t-flash") + 20));
  const sweep = el => { if (!reduced()) once(el, "sweep", 260); };
  function collapseInto(lower, upper, done) {
    if (reduced() || !ms("--t-move")) { done(); return; }
    // rows have a CSS min-height: pin it too, or the height would stop at one row
    const h = lower.offsetHeight + "px";
    lower.style.height = h; lower.style.minHeight = h; lower.style.overflow = "hidden";
    requestAnimationFrame(() => {
      lower.style.transition = "height var(--t-move) var(--ease-out), min-height var(--t-move) var(--ease-out), opacity var(--t-move) linear";
      lower.style.height = "0px"; lower.style.minHeight = "0px"; lower.style.opacity = "0";
    });
    setTimeout(() => { done(); once(upper.querySelector(".t-title") || upper, "land", 160); }, ms("--t-move") + 10);
  }
  return { flip, tap, flash, sweep, collapseInto, once, reduced };
})();
