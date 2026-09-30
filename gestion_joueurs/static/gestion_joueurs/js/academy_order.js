document.addEventListener('DOMContentLoaded', function () {
    const organization = document.getElementById('id_client_organization');
    const whatsappDate = document.getElementById('id_whatsapp_conversation_date');
    const deadlineToggle = document.getElementById('id_deadline_from_whatsapp');
    const matchPackage = document.getElementById('id_match_package');
    const matchesProcessed = document.getElementById('id_matches_processed');
    const deadline = document.getElementById('id_deadline');
    const totalPayment = document.getElementById('id_total_payment');

    if (!organization) return;

    const academyFieldIds = [
        'div_id_whatsapp_conversation_date',
        'div_id_deadline_from_whatsapp',
        'div_id_match_package',
        'div_id_matches_processed',
    ];

    const prices = {
        '3': '300.00',
        '5': '350.00',
        '10': '400.00',
    };

    function refreshAcademyFields() {
        const linked = Boolean(organization.value);
        academyFieldIds.forEach(function (id) {
            const wrapper = document.getElementById(id);
            if (wrapper) wrapper.hidden = !linked;
        });

        if (!linked) {
            if (matchPackage) matchPackage.value = '';
            if (matchesProcessed) matchesProcessed.value = '0';
            if (deadlineToggle) deadlineToggle.checked = false;
        }

        if (totalPayment) {
            const packagePrice = linked && matchPackage ? prices[matchPackage.value] : null;
            if (packagePrice) {
                totalPayment.value = packagePrice;
                totalPayment.readOnly = true;
            } else {
                totalPayment.readOnly = false;
            }
        }
    }

    function refreshDeadline() {
        if (!deadlineToggle || !deadlineToggle.checked || !whatsappDate || !whatsappDate.value || !deadline) {
            return;
        }
        const parts = whatsappDate.value.split('-').map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) return;
        const target = new Date(parts[0], parts[1] - 1, parts[2]);
        target.setDate(target.getDate() + 5);
        const year = target.getFullYear();
        const month = String(target.getMonth() + 1).padStart(2, '0');
        const day = String(target.getDate()).padStart(2, '0');
        deadline.value = year + '-' + month + '-' + day;
        deadline.dispatchEvent(new Event('change', { bubbles: true }));
    }

    organization.addEventListener('change', refreshAcademyFields);
    if (matchPackage) matchPackage.addEventListener('change', refreshAcademyFields);
    if (deadlineToggle) deadlineToggle.addEventListener('change', refreshDeadline);
    if (whatsappDate) whatsappDate.addEventListener('change', refreshDeadline);

    refreshAcademyFields();
    refreshDeadline();
});
