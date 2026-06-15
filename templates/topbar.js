/* Dropdown Quiz — topbar universelle */
(function () {
    const btn  = document.getElementById('quiz-dd-btn');
    const menu = document.getElementById('quiz-dd-menu');
    if (!btn || !menu) return;

    btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const open = menu.classList.toggle('open');
        btn.classList.toggle('open', open);
        btn.setAttribute('aria-expanded', open);
    });

    document.addEventListener('click', function () {
        menu.classList.remove('open');
        btn.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            menu.classList.remove('open');
            btn.classList.remove('open');
            btn.setAttribute('aria-expanded', 'false');
            btn.focus();
        }
    });
})();
