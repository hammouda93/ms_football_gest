(function () {
    'use strict';

    const body = document.body;
    const sidebar = document.getElementById('appSidebar');
    const mobileToggle = document.getElementById('mobileMenuToggle');
    const desktopToggle = document.getElementById('sidebarToggle');
    const overlay = document.getElementById('sidebarOverlay');
    const desktopBreakpoint = 992;

    function isDesktop() {
        return window.innerWidth >= desktopBreakpoint;
    }

    function setMobileMenu(open) {
        body.classList.toggle('sidebar-open', open);
        if (mobileToggle) mobileToggle.setAttribute('aria-expanded', String(open));
        if (overlay) overlay.setAttribute('aria-hidden', String(!open));
    }

    if (sidebar && window.localStorage.getItem('msSidebarCollapsed') === 'true' && isDesktop()) {
        body.classList.add('sidebar-collapsed');
    }

    if (mobileToggle) mobileToggle.addEventListener('click', function () { setMobileMenu(!body.classList.contains('sidebar-open')); });
    if (overlay) overlay.addEventListener('click', function () { setMobileMenu(false); });

    if (desktopToggle) {
        desktopToggle.addEventListener('click', function () {
            if (!isDesktop()) { setMobileMenu(false); return; }
            body.classList.toggle('sidebar-collapsed');
            window.localStorage.setItem('msSidebarCollapsed', String(body.classList.contains('sidebar-collapsed')));
        });
    }

    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') setMobileMenu(false); });
    window.addEventListener('resize', function () { if (isDesktop()) setMobileMenu(false); });

    document.querySelectorAll('.app-main input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="submit"]), .app-main select, .app-main textarea').forEach(function (field) {
        if (!field.classList.contains('form-control') && !field.classList.contains('form-check-input')) field.classList.add('form-control');
    });

    document.querySelectorAll('.app-main form[method="get"], .app-main #filter-form, .app-main #search-form, .app-main #searchForm').forEach(function (form) {
        form.classList.add('ui-filter-panel');
        form.setAttribute('role', 'search');
    });

    document.querySelectorAll('.app-main .card-header').forEach(function (header) {
        if (header.querySelector('h1, h2, h3, h4, h5')) header.classList.add('ui-card-heading');
    });

    document.querySelectorAll('.app-main table').forEach(function (table) {
        table.classList.add('ui-responsive-table');
        const headers = Array.from(table.querySelectorAll('thead th')).map(function (header) { return header.textContent.trim(); });
        table.querySelectorAll('tbody tr').forEach(function (row) {
            Array.from(row.children).forEach(function (cell, index) {
                if (!cell.dataset.label && headers[index]) cell.dataset.label = headers[index];
            });
        });
        if (!table.parentElement.classList.contains('table-responsive') && !table.parentElement.classList.contains('ui-table-scroll')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'ui-table-scroll';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }
    });

    document.querySelectorAll('.app-main form').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (form.target === '_blank') return;
            const submit = event.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
            if (!submit || submit.dataset.keepEnabled === 'true' || submit.name === 'decision') return;
            window.setTimeout(function () {
                submit.classList.add('is-loading');
                submit.setAttribute('aria-busy', 'true');
            }, 10);
        });
    });

    if (window.jQuery) {
        $(function () {
            if ($('#id_deadline').length) $('#id_deadline').datepicker({ format: 'yyyy-mm-dd', autoclose: true });
            $('[data-toggle="tooltip"], a[title], button[title]').tooltip({ boundary: 'window', trigger: 'hover' });
        });
    }
})();
