// Execute the shipped academy_order.js against a minimal DOM (no browser or network).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../gestion_joueurs/static/gestion_joueurs/js/academy_order.js'), 'utf8');
const checks = [];
function equal(actual, expected, label) {
    assert.equal(actual, expected, label);
    checks.push(label);
}
function mount(org, pack, price, editing) {
    const el = (value = '') => ({
        value, dataset: {}, checked: false, readOnly: false,
        addEventListener(k, fn) { this[k] = fn; }, dispatchEvent() {},
    });
    const elements = {
        id_client_organization: el(org), id_match_package: el(pack), id_total_payment: el(price),
        id_matches_processed: el('0'), id_whatsapp_conversation_date: el('2026-11-26'),
        id_deadline_from_whatsapp: el(), id_deadline: el(), hint_id_match_package: el(),
    };
    // Fictional response from the server. Django tests separately verify the real response.
    elements.id_match_package.dataset = {
        packageTariffs: JSON.stringify({default: {3: 300, 5: 350, 10: 400}, 2: {3: 350, 5: 500, 10: 700}}),
        existingOrder: String(editing),
    };
    const document = {
        getElementById: id => elements[id] || null,
        addEventListener(k, fn) { if (k === 'DOMContentLoaded') fn(); },
    };
    new Function('document', 'Event', source)(document, function () {});
    return elements;
}
let e = mount('2', '3', '999.00', false);
let p = e.id_total_payment, o = e.id_client_organization, m = e.id_match_package;
equal(p.value, '350.00', 'Elite 3');
m.value = '5'; m.change(); equal(p.value, '500.00', 'Elite 5');
m.value = '10'; m.change(); equal(p.value, '700.00', 'Elite 10');
o.value = '3'; o.change(); equal(p.value, '400.00', 'generic 10');
m.value = '5'; m.change(); equal(p.value, '350.00', 'generic 5');
m.value = '3'; m.change(); equal(p.value, '300.00', 'generic 3');
equal(p.readOnly, true, 'create pack readonly');
o.value = ''; o.change(); equal(p.value, '', 'clear auto price when direct');
equal(p.readOnly, false, 'direct editable');
e = mount('', '', '432.10', false); equal(e.id_total_payment.value, '432.10', 'direct custom');
e = mount('2', '5', '350.00', true);
p = e.id_total_payment; o = e.id_client_organization; m = e.id_match_package;
equal(p.value, '350.00', 'historical load');
m.value = '10'; m.change(); equal(p.value, '350.00', 'historical pack change not repriced');
o.value = '3'; o.change(); equal(p.value, '350.00', 'historical organization change not repriced');
equal(p.readOnly, false, 'edit explicitly editable');
console.log(checks.length + ' assertions passed: ' + checks.join(', '));
