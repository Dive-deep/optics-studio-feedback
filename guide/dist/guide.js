'use strict';
const sections=[...document.querySelectorAll('.chapter')];
const navLinks=[...document.querySelectorAll('nav a')];
if('IntersectionObserver' in window){
  const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;for(const link of navLinks){const active=link.hash==='#'+entry.target.id;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');}}},{rootMargin:'-15% 0px -65% 0px'});
  sections.forEach(section=>observer.observe(section));
}

// Set only after the repository is created and verified. No requests are sent.
const repositoryURL = '';
for (const link of document.querySelectorAll('[data-repo],[data-feedback],[data-bug]')) {
  if (repositoryURL) {
    link.href = repositoryURL + (link.hasAttribute('data-feedback') ? '/issues/new?template=usability.yml' : link.hasAttribute('data-bug') ? '/issues/new?template=bug.yml' : '/releases');
    link.target = '_blank'; link.rel = 'noopener';
  } else {
    link.removeAttribute('href'); link.setAttribute('aria-disabled','true');
    link.title = 'GitHub 게시 준비 중. 아래 피드백 양식을 사용할 수 있습니다.';
    link.textContent = link.hasAttribute('data-repo') ? 'GitHub 게시 준비 중' : link.hasAttribute('data-feedback') ? '사용성 의견 · 게시 준비 중' : '오류 신고 · 게시 준비 중';
  }
}
