"use strict";
// Navigation is progressively enhanced; anchors and release links work offline without JS.
const sections = [...document.querySelectorAll(".chapter")];
const links = [...document.querySelectorAll("nav a")];
function markActive(id) {
  for (const link of links) {
    const active = link.hash === "#" + id;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
markActive(location.hash.slice(1) || "start");
window.addEventListener("hashchange", () => markActive(location.hash.slice(1) || "start"));
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) markActive(entry.target.id);
  }, {rootMargin: "-15% 0px -65% 0px"});
  sections.forEach(section => observer.observe(section));
}
