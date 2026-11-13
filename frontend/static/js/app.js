/**
 * Invoice Tracker App - Dashboard JavaScript
 */

const API_BASE = '';

// State
let invoices = [];
let clients = [];
let payments = [];
let currentInvoiceId = null;
let currentClientId = null;
let currentClientFilter = null; // client name being filtered
let currentView = 'invoices'; // 'invoices', 'payments', 'zus' or 'drive'
let exchangeRate = null; // EUR->PLN rate from NBP
let zusMonths = [];      // ZUS rows from the API, newest first
let zusWindow = 12;      // how many months back the ZUS list is showing

// DOM Elements
const filterStatus = document.getElementById('filter-status');
const filterClient = document.getElementById('filter-client');
const invoiceTable = document.getElementById('invoice-table');
const paymentsTable = document.getElementById('payments-table');
const pdfModal = document.getElementById('pdf-modal');
const pdfFrame = document.getElementById('pdf-frame');
const sendBtn = document.getElementById('send-btn');
const clientModal = document.getElementById('client-modal');
const clientForm = document.getElementById('client-form');
const paymentModal = document.getElementById('payment-modal');
const paymentForm = document.getElementById('payment-form');
const paymentClientSelect = document.getElementById('payment-client');
const paymentInvoiceSelect = document.getElementById('payment-invoice');
const clientDetailModal = document.getElementById('client-detail-modal');

// Format currency
function formatCurrency(amount, currency = 'EUR') {
    return `${currency} ${parseFloat(amount).toLocaleString('de-DE', { minimumFractionDigits: 2 })}`;
}

// Format date
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr; // Return raw string if invalid
    return date.toLocaleDateString('de-DE');
}

// Format PLN equivalent
function formatPlnEquiv(eurAmount) {
    if (!exchangeRate || !eurAmount) return '';
    const pln = eurAmount * exchangeRate;
    return `(~ PLN ${pln.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })})`;
}

// Fetch EUR/PLN exchange rate from NBP API
async function fetchExchangeRate() {
    try {
        const resp = await fetch('https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json');
        const data = await resp.json();
        exchangeRate = data.rates[0].mid;
    } catch (e) {
        exchangeRate = 4.30; // Fallback
    }
}

// ============ MOBILE DETECTION ============
const isMobile = () => window.innerWidth < 768;

// ============ VIEW SWITCHING ============

const VIEW_BTN_ACTIVE = 'px-4 py-2 bg-blue-600 text-white rounded-lg font-medium';
const VIEW_BTN_IDLE = 'px-4 py-2 bg-white text-gray-600 rounded-lg font-medium border hover:bg-gray-50';

// Show one desktop view, hide the rest, and highlight the matching toggle button
function setDesktopView(view) {
    currentView = view;

    const views = {
        invoices: 'invoices-view',
        payments: 'payments-view',
        zus: 'zus-view',
        drive: 'drive-files-view'
    };
    Object.entries(views).forEach(([name, id]) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', name !== view);
    });

    const buttons = {
        invoices: 'view-invoices-btn',
        payments: 'view-payments-btn',
        zus: 'view-zus-btn'
    };
    Object.entries(buttons).forEach(([name, id]) => {
        const btn = document.getElementById(id);
        if (btn) btn.className = (name === view) ? VIEW_BTN_ACTIVE : VIEW_BTN_IDLE;
    });
}

function showInvoicesView() {
    setDesktopView('invoices');
}

function showPaymentsView() {
    setDesktopView('payments');
    loadPayments();
}

function showZusView() {
    setDesktopView('zus');
    loadZus();
}

function showDriveView() {
    setDesktopView('drive');
    loadDriveFiles();
}

// Mobile navigation
let mobileCurrentView = 'invoices';

function mobileNav(view) {
    mobileCurrentView = view;

    // Update nav buttons
    document.querySelectorAll('.floating-nav button').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById('mnav-' + view);
    if (btn) btn.classList.add('active');

    // Toggle views
    const mInv = document.getElementById('mobile-invoices-view');
    const mPay = document.getElementById('mobile-payments-view');
    const mCli = document.getElementById('mobile-clients-view');
    const mDrv = document.getElementById('mobile-drive-view');
    const mZus = document.getElementById('mobile-zus-view');

    mInv.classList.add('hidden');
    mPay.classList.add('hidden');
    mCli.classList.add('hidden');
    mDrv.classList.add('hidden');
    if (mZus) mZus.classList.add('hidden');

    if (view === 'zus') {
        if (mZus) mZus.classList.remove('hidden');
        document.querySelector('.mobile-only.bg-white.border-b span').textContent = 'ZUS';
        loadZus();
    } else if (view === 'invoices') {
        mInv.classList.remove('hidden');
        document.querySelector('.mobile-only.bg-white.border-b span').textContent = 'Invoices';
    } else if (view === 'payments') {
        mPay.classList.remove('hidden');
        document.querySelector('.mobile-only.bg-white.border-b span').textContent = 'Payments';
        loadPayments();
    } else if (view === 'clients') {
        mCli.classList.remove('hidden');
        document.querySelector('.mobile-only.bg-white.border-b span').textContent = 'Clients';
        renderMobileClients();
    } else if (view === 'drive') {
        mDrv.classList.remove('hidden');
        document.querySelector('.mobile-only.bg-white.border-b span').textContent = 'Google Drive';
        loadDriveFiles();
    }
}

// ============ STATS ============

async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/api/invoices/stats`);
        const stats = await response.json();

        document.getElementById('stat-total').textContent = stats.total_invoices;
        document.getElementById('stat-draft').textContent = stats.draft_count;
        document.getElementById('stat-sent').textContent = stats.sent_count;
        document.getElementById('stat-paid').textContent = stats.paid_count;
        const dueEl = document.getElementById('stat-due');
        const recvEl = document.getElementById('stat-received');
        const outEl = document.getElementById('stat-total-outstanding');

        dueEl.textContent = formatCurrency(stats.total_due || 0);
        recvEl.textContent = formatCurrency(stats.total_paid || 0);
        outEl.textContent = formatCurrency(stats.total_due || 0);

        // PLN equivalents
        if (exchangeRate) {
            dueEl.title = formatPlnEquiv(stats.total_due || 0);
            recvEl.title = formatPlnEquiv(stats.total_paid || 0);
            const plnStr = formatPlnEquiv(stats.total_due || 0);
            if (plnStr) outEl.innerHTML = formatCurrency(stats.total_due || 0) + `<span class="block text-sm font-normal text-red-400">${plnStr}</span>`;
        }

        // Mobile outstanding
        const mobileOut = document.getElementById('mobile-outstanding');
        if (mobileOut) mobileOut.textContent = stats.total_due > 0 ? formatCurrency(stats.total_due) + ' due' : '';

        // Client breakdown - vertical list
        const breakdown = document.getElementById('client-breakdown');
        const dueByClient = stats.due_by_client || {};
        const totalByClient = stats.total_by_client || {};

        const allClients = Object.keys({...dueByClient, ...totalByClient});
        // Sort: clients with outstanding first (by amount desc), then paid clients
        const sorted = allClients.sort((a, b) => (dueByClient[b] || 0) - (dueByClient[a] || 0));

        if (sorted.length === 0) {
            breakdown.innerHTML = '<p class="text-gray-500">No clients yet</p>';
        } else {
            breakdown.innerHTML = sorted.map(client => {
                const due = dueByClient[client] || 0;
                const total = totalByClient[client] || 0;
                const isPaid = due === 0;
                const isActive = currentClientFilter === client;

                return `
                    <div class="client-item flex justify-between items-center px-3 py-2 rounded-lg border cursor-pointer ${isActive ? 'active border-blue-500 bg-blue-50' : isPaid ? 'border-gray-200 bg-gray-50' : 'border-red-200 bg-red-50'}"
                         onclick="filterByClientName('${client.replace(/'/g, "\\'")}')">
                        <div class="flex items-center space-x-2">
                            ${isActive ? '<i class="fas fa-chevron-right text-blue-500 text-xs"></i>' : ''}
                            <span class="${isActive ? 'font-semibold text-blue-700' : isPaid ? 'text-gray-600' : 'text-gray-900'}">${client}</span>
                        </div>
                        <span class="${isPaid ? 'text-gray-400 text-sm' : 'font-semibold text-red-600'}">
                            ${isPaid ? 'Paid' : formatCurrency(due)}
                        </span>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// ============ INVOICES ============

async function loadInvoices() {
    try {
        let url = `${API_BASE}/api/invoices/`;
        const params = new URLSearchParams();

        if (filterStatus.value) params.append('status', filterStatus.value);
        if (filterClient.value) params.append('client_id', filterClient.value);

        if (params.toString()) url += '?' + params.toString();

        const response = await fetch(url);
        invoices = await response.json();
        renderInvoices();
        renderMobileInvoices();
    } catch (error) {
        console.error('Error loading invoices:', error);
        invoiceTable.innerHTML = '<tr><td colspan="9" class="px-6 py-4 text-center text-red-500">Error loading invoices</td></tr>';
    }
}

function getPaymentStatusClass(status) {
    switch (status) {
        case 'paid': return 'payment-paid';
        case 'partial': return 'payment-partial';
        default: return 'payment-unpaid';
    }
}

function ksefBadge(inv) {
    const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    if (inv.ksef_reference) {
        return `<span class="ml-1 px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-700" title="KSeF ${esc(inv.ksef_reference)}">KSeF ${esc(inv.ksef_reference)}</span>`;
    }
    if (inv.ksef_status) {
        return `<span class="ml-1 px-1.5 py-0.5 rounded text-xs bg-red-100 text-red-700" title="${esc(inv.ksef_status)}">KSeF: ${esc(inv.ksef_status)}</span>`;
    }
    return '';
}

// Amount cell: a corrected invoice shows its original value struck through and the value
// after its correction invoices; a correction shows its own (signed) difference.
function amountHtml(inv) {
    if (inv.corrected_amount !== undefined && inv.corrected_amount !== null && inv.corrected_amount !== inv.amount) {
        const by = (inv.corrections || []).map(c => c.invoice_number).join(', ');
        return `<span class="line-through text-gray-400 text-xs" title="Korrigiert durch ${by}">${formatCurrency(inv.amount, inv.currency)}</span> ${formatCurrency(inv.corrected_amount, inv.currency)}`;
    }
    return formatCurrency(inv.amount, inv.currency);
}

function renderInvoices() {
    if (invoices.length === 0) {
        invoiceTable.innerHTML = `
            <tr>
                <td colspan="9" class="px-4 py-8 text-center text-gray-500">
                    <i class="fas fa-file-invoice text-4xl mb-3 text-gray-300"></i>
                    <p>No invoices found</p>
                    <a href="/chat" class="text-blue-600 hover:underline">Create your first invoice</a>
                </td>
            </tr>
        `;
        return;
    }

    invoiceTable.innerHTML = invoices.map(inv => {
        const isCorrection = !!inv.correction;
        const isPaid = !isCorrection && (inv.payment_status === 'paid' || (inv.amount_due !== undefined && inv.amount_due <= 0));
        const rowBg = isPaid ? 'bg-gray-100' : '';
        const textMuted = isPaid ? 'text-gray-400' : '';

        return `
        <tr class="${rowBg} hover:bg-gray-50">
            <td class="col-inv px-3 py-3 text-sm truncate">
                <span class="font-medium ${textMuted}">${inv.invoice_number}</span>${ksefBadge(inv)}
            </td>
            <td class="col-client px-3 py-3 text-sm truncate">
                <button onclick="filterByClientName('${(inv.client?.name || '').replace(/'/g, "\\'")}')" class="${isPaid ? 'text-gray-500' : 'text-blue-600 hover:text-blue-800'} hover:underline text-left truncate block w-full">
                    ${inv.client?.name || '-'}
                </button>
            </td>
            <td class="col-desc px-3 py-3 text-sm ${textMuted} truncate" title="${(inv.description || '').replace(/"/g, '&quot;')}">
                ${inv.description || '-'}
            </td>
            <td class="col-amount px-3 py-3 text-sm font-medium ${textMuted} truncate">
                ${amountHtml(inv)}
            </td>
            <td class="col-paid px-3 py-3 text-sm ${isPaid ? 'text-gray-400' : 'text-green-600'} truncate">
                ${formatCurrency(inv.amount_paid || 0, inv.currency)}
            </td>
            <td class="col-outstanding px-3 py-3 text-sm ${inv.amount_due > 0 ? 'text-red-600 font-bold' : textMuted} truncate">
                ${inv.amount_due > 0 ? formatCurrency(inv.amount_due, inv.currency) : '-'}
            </td>
            <td class="col-date px-3 py-3 text-sm ${textMuted} truncate">
                ${formatDate(inv.issue_date)}
            </td>
            <td class="col-status px-3 py-3 text-sm">
                ${isCorrection
                    ? `<span class="text-amber-700 font-medium" title="Korekta zu ${inv.correction.original_invoice_number || ''}">Korekta</span>`
                    : isPaid
                    ? '<span class="text-green-600 font-medium">Paid</span>'
                    : inv.amount_due > 0
                        ? '<span class="text-red-600 font-medium">Due</span>'
                        : `<span class="text-gray-500">${inv.status}</span>`
                }
            </td>
            <td class="col-actions px-2 py-3">
                <button onclick="previewInvoice(${inv.id})" class="text-blue-600 hover:text-blue-800" title="Preview">
                    <i class="fas fa-eye text-xs"></i>
                </button>
            </td>
        </tr>
        `;
    }).join('');
}

// ============ MOBILE RENDERERS ============

function renderMobileInvoices() {
    const list = document.getElementById('mobile-invoice-list');
    if (!list) return;

    if (invoices.length === 0) {
        list.innerHTML = '<div class="px-4 py-8 text-center text-gray-400">No invoices found</div>';
        return;
    }

    list.innerHTML = invoices.map(inv => {
        const isCorrection = !!inv.correction;
        const isPaid = !isCorrection && (inv.payment_status === 'paid' || (inv.amount_due !== undefined && inv.amount_due <= 0));
        return `
        <div class="invoice-card ${isPaid ? 'paid-card' : ''}" onclick="previewInvoice(${inv.id})">
            <div style="min-width:0; flex:1">
                <div class="flex items-center gap-2">
                    <span class="text-xs text-gray-400">${inv.invoice_number}</span>
                    ${isPaid ? '<span class="text-xs text-green-600 font-medium">Paid</span>' : ''}
                    ${isCorrection ? `<span class="text-xs text-amber-700 font-medium">Korekta ${formatCurrency(inv.amount, inv.currency)}</span>` : ''}
                </div>
                <div class="font-medium text-gray-900 text-sm truncate">${inv.client?.name || '-'}</div>
            </div>
            <div class="text-right flex-shrink-0 ml-3">
                <div class="text-sm ${isPaid ? 'text-gray-400' : 'text-green-600'}">${formatCurrency(inv.amount_paid || 0)}</div>
                ${inv.amount_due > 0
                    ? `<div class="text-sm font-bold text-red-600">${formatCurrency(inv.amount_due)}</div>`
                    : '<div class="text-xs text-gray-400">-</div>'
                }
            </div>
        </div>`;
    }).join('');
}

function renderMobilePayments() {
    const list = document.getElementById('mobile-payments-list');
    if (!list) return;

    if (payments.length === 0) {
        list.innerHTML = '<div class="px-4 py-8 text-center text-gray-400">No payments recorded</div>';
        return;
    }

    list.innerHTML = payments.map(p => `
        <div class="invoice-card">
            <div style="min-width:0; flex:1">
                <div class="text-xs text-gray-400">${p.date || '-'}</div>
                <div class="font-medium text-gray-900 text-sm truncate">${p.client || '-'}</div>
                <div class="text-xs text-gray-400">${p.method || ''} ${p.notes ? '- ' + p.notes : ''}</div>
            </div>
            <div class="text-right flex-shrink-0 ml-3">
                <div class="text-sm font-bold text-green-600">${formatCurrency(p.amount, p.currency)}</div>
            </div>
        </div>
    `).join('');
}

function renderMobileClients() {
    const list = document.getElementById('mobile-client-list');
    if (!list) return;

    // Use cached stats from loadStats
    fetch(`${API_BASE}/api/invoices/stats`).then(r => r.json()).then(stats => {
        const dueByClient = stats.due_by_client || {};
        const totalByClient = stats.total_by_client || {};
        const allClients = Object.keys({...dueByClient, ...totalByClient});
        const sorted = allClients.sort((a, b) => (dueByClient[b] || 0) - (dueByClient[a] || 0));

        list.innerHTML = sorted.map(client => {
            const due = dueByClient[client] || 0;
            const isPaid = due === 0;
            const isActive = currentClientFilter === client;

            return `
            <div class="px-4 py-3 flex justify-between items-center cursor-pointer ${isActive ? 'bg-blue-50' : ''}" onclick="filterByClientName('${client.replace(/'/g, "\\'")}'); mobileNav('invoices');">
                <div class="flex items-center gap-2">
                    ${isActive ? '<i class="fas fa-chevron-right text-blue-500 text-xs"></i>' : '<i class="fas fa-building text-gray-300 text-xs"></i>'}
                    <span class="${isActive ? 'font-semibold text-blue-700' : 'text-gray-900'} text-sm">${client}</span>
                </div>
                <span class="${isPaid ? 'text-gray-400 text-xs' : 'font-semibold text-red-600 text-sm'}">
                    ${isPaid ? 'Paid' : formatCurrency(due)}
                </span>
            </div>`;
        }).join('');
    });
}

// ============ PAYMENTS VIEW ============

async function loadPayments() {
    try {
        let url = `${API_BASE}/api/payments/`;
        if (filterClient.value) {
            url += `?client_id=${filterClient.value}`;
        }

        const response = await fetch(url);
        payments = await response.json();
        renderPayments();
        renderMobilePayments();
    } catch (error) {
        console.error('Error loading payments:', error);
        paymentsTable.innerHTML = '<tr><td colspan="6" class="px-4 py-4 text-center text-red-500">Error loading payments</td></tr>';
    }
}

function renderPayments() {
    if (payments.length === 0) {
        paymentsTable.innerHTML = `
            <tr>
                <td colspan="6" class="px-4 py-8 text-center text-gray-500">
                    <i class="fas fa-coins text-4xl mb-3 text-gray-300"></i>
                    <p>No payments recorded</p>
                </td>
            </tr>
        `;
        return;
    }

    paymentsTable.innerHTML = payments.map(p => `
        <tr class="hover:bg-gray-50">
            <td class="px-4 py-3 whitespace-nowrap text-gray-700">${p.date || '-'}</td>
            <td class="px-4 py-3 whitespace-nowrap">
                <button onclick="filterByClientName('${(p.client || '').replace(/'/g, "\\'")}')" class="text-blue-600 hover:underline text-left">
                    ${p.client || '-'}
                </button>
            </td>
            <td class="px-4 py-3 whitespace-nowrap text-gray-600">#${p.invoice_id || '-'}</td>
            <td class="px-4 py-3 whitespace-nowrap font-semibold text-green-600">${formatCurrency(p.amount, p.currency)}</td>
            <td class="px-4 py-3 whitespace-nowrap text-gray-500">${p.method || '-'}</td>
            <td class="px-4 py-3 text-gray-500">${p.notes || '-'}</td>
        </tr>
    `).join('');
}

// ============ ZUS (monthly social-security contribution) ============

async function loadZus() {
    try {
        const response = await fetch(`${API_BASE}/api/zus/?months=${zusWindow}`);
        const data = await response.json();
        zusMonths = data.months || [];
        renderZus(data);
        renderMobileZus();
    } catch (error) {
        console.error('Error loading ZUS payments:', error);
        const table = document.getElementById('zus-table');
        if (table) table.innerHTML = '<tr><td colspan="4" class="px-4 py-4 text-center text-red-500">Error loading ZUS payments</td></tr>';
        const list = document.getElementById('mobile-zus-list');
        if (list) list.innerHTML = '<div class="px-4 py-8 text-center text-red-500">Error loading ZUS payments</div>';
    }
}

function loadMoreZusMonths() {
    zusWindow += 12;
    loadZus();
}

// The fixed base rate, plus a FLAG (never a calculated figure) when invoices
// were issued that month — the real ZUS is then usually higher, but we have no
// formula for it, so we only ever state the invoice count we read from the DB.
function zusAmountHtml(m) {
    const amount = formatCurrency(m.base_amount, m.currency);
    if (!m.likely_higher) return amount;

    const label = m.invoice_count === 1 ? 'invoice' : 'invoices';
    const title = (m.invoice_numbers || []).join(', ');
    return `${amount} <span class="text-amber-600 text-xs" title="${title}">(likely higher — ${m.invoice_count} ${label} issued this month)</span>`;
}

function zusToggleButton(m) {
    return m.paid
        ? `<button onclick="toggleZusPaid('${m.month}')" class="px-3 py-1.5 rounded-lg bg-green-100 text-green-700 text-sm font-medium hover:bg-green-200" title="Click to un-mark">
               <i class="fas fa-check-circle mr-1"></i>Paid
           </button>`
        : `<button onclick="toggleZusPaid('${m.month}')" class="px-3 py-1.5 rounded-lg border border-gray-300 text-gray-600 text-sm font-medium hover:bg-gray-50">
               <i class="far fa-square mr-1"></i>Mark paid
           </button>`;
}

function renderZus(data) {
    const table = document.getElementById('zus-table');
    const summary = document.getElementById('zus-summary');
    if (!table) return;

    if (summary && data) {
        summary.textContent = `${data.paid_count} paid · ${data.unpaid_count} outstanding`;
    }

    if (zusMonths.length === 0) {
        table.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">No months to show</td></tr>';
        return;
    }

    table.innerHTML = zusMonths.map(m => `
        <tr class="hover:bg-gray-50 ${m.paid ? 'bg-gray-50' : ''}">
            <td class="px-4 py-3 whitespace-nowrap font-medium ${m.paid ? 'text-gray-500' : 'text-gray-900'}">${m.label}</td>
            <td class="px-4 py-3 text-sm ${m.paid ? 'text-gray-500' : 'text-gray-900'}">${zusAmountHtml(m)}</td>
            <td class="px-4 py-3 whitespace-nowrap text-sm">
                ${m.paid
                    ? `<span class="text-green-600 font-medium">Paid</span>${m.paid_at ? `<span class="text-gray-400 text-xs block">${formatDate(m.paid_at)}</span>` : ''}`
                    : '<span class="text-gray-400">Not paid</span>'
                }
            </td>
            <td class="px-4 py-3 whitespace-nowrap text-right">${zusToggleButton(m)}</td>
        </tr>
    `).join('');
}

function renderMobileZus() {
    const list = document.getElementById('mobile-zus-list');
    if (!list) return;

    if (zusMonths.length === 0) {
        list.innerHTML = '<div class="px-4 py-8 text-center text-gray-400">No months to show</div>';
        return;
    }

    list.innerHTML = zusMonths.map(m => `
        <div class="px-4 py-3 flex items-center justify-between ${m.paid ? 'bg-gray-50' : ''}">
            <div style="min-width:0; flex:1">
                <div class="font-medium text-sm ${m.paid ? 'text-gray-500' : 'text-gray-900'}">${m.label}</div>
                <div class="text-xs ${m.paid ? 'text-gray-400' : 'text-gray-600'}">${zusAmountHtml(m)}</div>
                ${m.paid && m.paid_at ? `<div class="text-xs text-gray-400">Paid ${formatDate(m.paid_at)}</div>` : ''}
            </div>
            <div class="flex-shrink-0 ml-3">${zusToggleButton(m)}</div>
        </div>
    `).join('');
}

async function toggleZusPaid(month) {
    const entry = zusMonths.find(m => m.month === month);
    if (!entry) return;

    const action = entry.paid ? 'mark-unpaid' : 'mark-paid';

    try {
        const response = await fetch(`${API_BASE}/api/zus/${month}/${action}`, { method: 'POST' });

        if (response.ok) {
            await loadZus();
        } else {
            const error = await response.json();
            alert(`Error: ${error.detail || 'Failed to update ZUS month'}`);
        }
    } catch (error) {
        console.error('Error updating ZUS month:', error);
        alert('Error updating ZUS month. Please try again.');
    }
}

// ============ CLIENT FILTER ============

async function loadClients() {
    try {
        const response = await fetch(`${API_BASE}/api/clients/`);
        clients = await response.json();

        filterClient.innerHTML = '<option value="">All</option>' +
            clients.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    } catch (error) {
        console.error('Error loading clients:', error);
    }
}

function filterByClientName(clientName) {
    const client = clients.find(c => c.name === clientName);
    if (client) {
        filterClient.value = client.id;
        currentClientFilter = clientName;
        updateFilterUI();
        loadInvoices();
        if (currentView === 'payments') loadPayments();
        // Re-render client breakdown to show highlight
        loadStats();
    }
}

function clearClientFilter() {
    filterClient.value = '';
    currentClientFilter = null;
    updateFilterUI();
    loadInvoices();
    if (currentView === 'payments') loadPayments();
    loadStats();
}

function updateFilterUI() {
    // Desktop
    const showAllBtn = document.getElementById('show-all-btn');
    const filterLabel = document.getElementById('current-filter-label');
    const filterName = document.getElementById('filter-client-name');

    if (currentClientFilter) {
        showAllBtn.classList.remove('hidden');
        filterLabel.classList.remove('hidden');
        filterName.textContent = currentClientFilter;
    } else {
        showAllBtn.classList.add('hidden');
        filterLabel.classList.add('hidden');
    }

    // Mobile
    const mobileFilterBar = document.getElementById('mobile-filter-bar');
    const mobileFilterName = document.getElementById('mobile-filter-name');
    if (mobileFilterBar) {
        if (currentClientFilter) {
            mobileFilterBar.classList.remove('hidden');
            mobileFilterName.textContent = currentClientFilter;
        } else {
            mobileFilterBar.classList.add('hidden');
        }
    }
}

// ============ MOBILE ACTION MENU ============

function toggleActionMenu() {
    const menu = document.getElementById('mobile-action-menu');
    const icon = document.getElementById('mnav-add-icon');
    if (menu.classList.contains('hidden')) {
        menu.classList.remove('hidden');
        icon.className = 'fas fa-times';
    } else {
        menu.classList.add('hidden');
        icon.className = 'fas fa-plus';
    }
}

function closeActionMenu() {
    const menu = document.getElementById('mobile-action-menu');
    const icon = document.getElementById('mnav-add-icon');
    menu.classList.add('hidden');
    icon.className = 'fas fa-plus';
}

// ============ PDF PREVIEW ============

// A filed invoice (KSeF number) that is not itself a correction can be corrected
function canCorrect(inv) {
    return !!(inv && inv.ksef_reference && !inv.correction);
}

function previewInvoice(invoiceId) {
    currentInvoiceId = invoiceId;
    pdfFrame.src = `${API_BASE}/api/invoices/${invoiceId}/preview`;
    sendBtn.style.display = 'none';
    korektaBtn.style.display = canCorrect(invoices.find(i => i.id === invoiceId)) ? 'inline-flex' : 'none';
    pdfModal.classList.remove('hidden');
    pdfModal.classList.add('flex');
}

function previewAndSend(invoiceId) {
    currentInvoiceId = invoiceId;
    pdfFrame.src = `${API_BASE}/api/invoices/${invoiceId}/preview`;
    sendBtn.style.display = 'inline-flex';
    korektaBtn.style.display = canCorrect(invoices.find(i => i.id === invoiceId)) ? 'inline-flex' : 'none';
    pdfModal.classList.remove('hidden');
    pdfModal.classList.add('flex');
}

// ============ CORRECTION (KOREKTA) ============
// New amount -> read-only preview (XML checked against the FA(3) XSD, PDF) -> confirm,
// which saves the correction invoice and files it in KSeF. Confirm is enabled only for the
// exact inputs of the last valid preview.

const korektaBtn = document.getElementById('korekta-btn');
const korektaModal = document.getElementById('korekta-modal');
let korektaInvoiceId = null;
let korektaPreviewKey = null;   // inputs of the last valid preview
let korektaCreatedId = null;    // correction saved but not filed: offered for a retry

const escHtml = t => String(t ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function korektaInputs() {
    return {
        new_amount: document.getElementById('korekta-amount').value.trim(),
        reason: document.getElementById('korekta-reason').value.trim(),
        correction_type: parseInt(document.getElementById('korekta-type').value, 10)
    };
}

function korektaMessage(html, kind) {
    const el = document.getElementById('korekta-message');
    const styles = { error: 'bg-red-50 text-red-700 border border-red-200', ok: 'bg-green-50 text-green-800 border border-green-200', info: 'bg-blue-50 text-blue-800 border border-blue-200' };
    el.className = `text-sm rounded p-3 ${styles[kind] || styles.info}`;
    el.innerHTML = html;
    el.classList.remove('hidden');
}

function korektaInvalidate() {
    korektaPreviewKey = null;
    document.getElementById('korekta-confirm-btn').disabled = true;
}

function openKorektaModal(invoiceId) {
    const inv = invoices.find(i => i.id === invoiceId);
    if (!canCorrect(inv)) {
        alert('Only an invoice filed in KSeF (and not itself a correction) can be corrected.');
        return;
    }
    closePdfModal();
    korektaInvoiceId = invoiceId;
    korektaCreatedId = null;
    const current = inv.corrected_amount ?? inv.amount;
    document.getElementById('korekta-title').textContent = `${inv.invoice_number} · ${inv.client?.name || ''}`;
    document.getElementById('korekta-current').innerHTML =
        `Current value: <strong>${escHtml(formatCurrency(current, inv.currency))}</strong> · KSeF ${escHtml(inv.ksef_reference)}` +
        (inv.corrections?.length ? ` · already corrected by ${inv.corrections.map(c => escHtml(c.invoice_number)).join(', ')}` : '');
    document.getElementById('korekta-amount').value = current;
    document.getElementById('korekta-reason').value = 'Zmiana wartości usługi';
    document.getElementById('korekta-type').value = '2';
    document.getElementById('korekta-result').classList.add('hidden');
    document.getElementById('korekta-message').classList.add('hidden');
    document.getElementById('korekta-frame').srcdoc = '';
    document.getElementById('korekta-retry-btn').style.display = 'none';
    document.getElementById('korekta-confirm-btn').style.display = 'inline-flex';
    korektaInvalidate();
    korektaModal.classList.remove('hidden');
    korektaModal.classList.add('flex');
}

function closeKorektaModal() {
    korektaModal.classList.add('hidden');
    korektaModal.classList.remove('flex');
    korektaInvoiceId = null;
    korektaInvalidate();
}

['korekta-amount', 'korekta-reason', 'korekta-type'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', korektaInvalidate);
});

async function previewKorekta() {
    if (!korektaInvoiceId) return;
    const body = korektaInputs();
    if (body.new_amount === '') { korektaMessage('Enter the new amount.', 'error'); return; }
    const btn = document.getElementById('korekta-preview-btn');
    btn.disabled = true;
    korektaInvalidate();
    document.getElementById('korekta-message').classList.add('hidden');
    try {
        const resp = await fetch(`${API_BASE}/api/invoices/${korektaInvoiceId}/correction/preview`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        const data = await resp.json();
        if (!resp.ok) {
            document.getElementById('korekta-result').classList.add('hidden');
            korektaMessage(`Not possible: ${escHtml(data.detail || resp.statusText)}`, 'error');
            return;
        }
        const cur = data.currency;
        document.getElementById('korekta-summary').innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
                <div>Correction number: <strong>${escHtml(data.correction_number)}</strong> (issued ${escHtml(data.issue_date)})</div>
                <div>Corrects: <strong>${escHtml(data.original.invoice_number)}</strong> of ${escHtml(data.original.issue_date)}</div>
                <div>Before: ${escHtml(formatCurrency(data.amount_before, cur))}</div>
                <div class="col-span-1">KSeF of the original: ${escHtml(data.original.ksef_reference)}</div>
                <div>After: <strong>${escHtml(formatCurrency(data.amount_after, cur))}</strong></div>
                <div>Reason: ${escHtml(data.reason)}</div>
                <div>Difference: <strong>${escHtml(formatCurrency(data.difference, cur))}</strong></div>
                <div>Type ${escHtml(data.correction_type)}: ${escHtml(data.correction_type_label)}</div>
            </div>
            <div class="mt-2 ${data.xsd_valid ? 'text-green-700' : 'text-red-700'}">
                ${data.xsd_valid ? '<i class="fas fa-check-circle mr-1"></i>FA(3) XML is valid against the official KSeF schema.'
                                 : '<i class="fas fa-times-circle mr-1"></i>FA(3) XML fails the KSeF schema: ' + escHtml((data.xsd_errors || []).join('; '))}
            </div>`;
        document.getElementById('korekta-frame').srcdoc = data.html || '';
        document.getElementById('korekta-result').classList.remove('hidden');
        if (data.xsd_valid) {
            korektaPreviewKey = JSON.stringify(body);
            document.getElementById('korekta-confirm-btn').disabled = false;
            korektaMessage(escHtml(data.warning), 'info');
        } else {
            korektaMessage('This correction cannot be filed until the schema errors above are fixed.', 'error');
        }
    } catch (e) {
        console.error('Correction preview failed:', e);
        korektaMessage('Preview failed (no answer from the server). Nothing was saved.', 'error');
    } finally {
        btn.disabled = false;
    }
}

async function confirmKorekta() {
    if (!korektaInvoiceId || !korektaPreviewKey) return;
    const body = korektaInputs();
    if (JSON.stringify(body) !== korektaPreviewKey) { korektaInvalidate(); korektaMessage('The inputs changed; preview again.', 'error'); return; }
    if (!confirm('Save this correction invoice and file it in KSeF now? A KSeF filing is legally binding and cannot be withdrawn.')) return;
    const btn = document.getElementById('korekta-confirm-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Filing...';
    try {
        const resp = await fetch(`${API_BASE}/api/invoices/${korektaInvoiceId}/correction`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, confirmed: true })
        });
        const data = await resp.json();
        if (!resp.ok) {
            korektaMessage(`Nothing saved: ${escHtml(data.detail || resp.statusText)}`, 'error');
            btn.disabled = false;
            return;
        }
        korektaPreviewKey = null;
        btn.style.display = 'none';
        if (data.filed) {
            korektaMessage(`Correction <strong>${escHtml(data.invoice_number)}</strong> saved and filed in KSeF: <strong>${escHtml(data.ksef_reference)}</strong>. New value of ${escHtml(data.summary.original.invoice_number)}: ${escHtml(formatCurrency(data.summary.amount_after, data.currency))}.`, 'ok');
        } else {
            korektaCreatedId = data.id;
            document.getElementById('korekta-retry-btn').style.display = 'inline-flex';
            korektaMessage(`Correction <strong>${escHtml(data.invoice_number)}</strong> is saved but NOT filed in KSeF: ${escHtml(data.ksef_error || data.ksef_status)}. File it again before sending it.`, 'error');
        }
        loadInvoices();
        loadStats();
    } catch (e) {
        console.error('Correction create failed:', e);
        korektaMessage('No answer from the server. Reload the list to see whether the correction was saved before trying again.', 'error');
    } finally {
        btn.innerHTML = '<i class="fas fa-file-signature mr-2"></i>Confirm and file in KSeF';
    }
}

async function retryKorektaFiling() {
    if (!korektaCreatedId) return;
    if (!confirm('File this correction invoice in KSeF now? A KSeF filing is legally binding and cannot be withdrawn.')) return;
    const btn = document.getElementById('korekta-retry-btn');
    btn.disabled = true;
    try {
        const resp = await fetch(`${API_BASE}/api/ksef/submit/${korektaCreatedId}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true })
        });
        const data = await resp.json();
        if (resp.ok && data.ksef_number) {
            btn.style.display = 'none';
            korektaCreatedId = null;
            korektaMessage(`Filed in KSeF: <strong>${escHtml(data.ksef_number)}</strong>.`, 'ok');
        } else {
            korektaMessage(`Still NOT filed: ${escHtml(data.detail || resp.statusText)}`, 'error');
        }
        loadInvoices();
        loadStats();
    } catch (e) {
        korektaMessage('No answer from the server; reload the list to see the KSeF status.', 'error');
    } finally {
        btn.disabled = false;
    }
}

function closePdfModal() {
    pdfModal.classList.add('hidden');
    pdfModal.classList.remove('flex');
    pdfFrame.src = '';
    currentInvoiceId = null;
}

function downloadInvoice() {
    if (!currentInvoiceId) return;
    window.open(`${API_BASE}/api/invoices/${currentInvoiceId}/download`, '_blank');
}

sendBtn.addEventListener('click', async () => {
    if (!currentInvoiceId) return;

    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Sending...';

    try {
        const response = await fetch(`${API_BASE}/api/invoices/${currentInvoiceId}/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed: true })
        });

        const result = await response.json();

        if (result.success) {
            alert(`Invoice sent successfully!\n${result.message}`);
            closePdfModal();
            loadInvoices();
            loadStats();
        } else {
            alert(`Error: ${result.detail || result.message || 'Failed to send invoice'}`);
        }
    } catch (error) {
        console.error('Error sending invoice:', error);
        alert('Error sending invoice. Please try again.');
    }

    sendBtn.disabled = false;
    sendBtn.innerHTML = '<i class="fas fa-paper-plane mr-2"></i>Send Invoice';
});

// ============ MARK PAID ============

async function markPaid(invoiceId) {
    if (!confirm('Mark this invoice as paid?')) return;

    try {
        const response = await fetch(`${API_BASE}/api/invoices/${invoiceId}/mark-paid`, {
            method: 'POST'
        });

        if (response.ok) {
            loadInvoices();
            loadStats();
        } else {
            alert('Failed to update invoice status');
        }
    } catch (error) {
        console.error('Error marking paid:', error);
        alert('Error updating invoice');
    }
}

// ============ CLIENT MODAL ============

function openClientModal() {
    clientModal.classList.remove('hidden');
    clientModal.classList.add('flex');
}

function closeClientModal() {
    clientModal.classList.add('hidden');
    clientModal.classList.remove('flex');
    clientForm.reset();
}

clientForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData(clientForm);
    const data = {
        name: formData.get('name'),
        address: formData.get('address'),
        company_id: formData.get('company_id'),
        email: formData.get('email') || null
    };

    try {
        const response = await fetch(`${API_BASE}/api/clients/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            closeClientModal();
            loadClients();
            alert('Client added successfully!');
        } else {
            const error = await response.json();
            alert(`Error: ${error.detail || 'Failed to add client'}`);
        }
    } catch (error) {
        console.error('Error adding client:', error);
        alert('Error adding client');
    }
});

// ============ PAYMENT MODAL ============

function openPaymentModal() {
    paymentClientSelect.innerHTML = '<option value="">Select client...</option>' +
        clients.map(c => `<option value="${c.id}">${c.name}</option>`).join('');

    paymentInvoiceSelect.innerHTML = '<option value="">Select client first...</option>';
    document.getElementById('invoice-due-info').textContent = '';
    document.getElementById('payment-amount').value = '';

    paymentModal.classList.remove('hidden');
    paymentModal.classList.add('flex');
}

function openPaymentModalForInvoice(invoiceId) {
    const invoice = invoices.find(i => i.id === invoiceId);
    if (!invoice) return;

    openPaymentModal();

    paymentClientSelect.value = invoice.client_id;
    loadInvoicesForPayment(invoice.client_id).then(() => {
        paymentInvoiceSelect.value = invoiceId;
        updateInvoiceDueInfo();
    });
}

async function loadInvoicesForPayment(clientId) {
    if (!clientId) {
        paymentInvoiceSelect.innerHTML = '<option value="">Select client first...</option>';
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/clients/${clientId}/unpaid-invoices`);
        const data = await response.json();
        const unpaidInvoices = data.unpaid_invoices || [];

        if (unpaidInvoices.length === 0) {
            paymentInvoiceSelect.innerHTML = '<option value="">No unpaid invoices</option>';
        } else {
            paymentInvoiceSelect.innerHTML = '<option value="">Select invoice...</option>' +
                unpaidInvoices.map(inv =>
                    `<option value="${inv.id}" data-due="${inv.amount_due}" data-currency="${inv.currency}">
                        #${inv.invoice_number} (${formatCurrency(inv.amount_due, inv.currency)} due)
                    </option>`
                ).join('');
        }
    } catch (error) {
        console.error('Error loading invoices for payment:', error);
        paymentInvoiceSelect.innerHTML = '<option value="">Error loading invoices</option>';
    }
}

function updateInvoiceDueInfo() {
    const selectedOption = paymentInvoiceSelect.selectedOptions[0];
    const infoEl = document.getElementById('invoice-due-info');

    if (selectedOption && selectedOption.value) {
        const due = selectedOption.dataset.due;
        const currency = selectedOption.dataset.currency || 'EUR';
        infoEl.textContent = `Amount due: ${formatCurrency(parseFloat(due), currency)}`;
        document.getElementById('payment-amount').max = due;
    } else {
        infoEl.textContent = '';
    }
}

function closePaymentModal() {
    paymentModal.classList.add('hidden');
    paymentModal.classList.remove('flex');
    paymentForm.reset();
}

paymentClientSelect.addEventListener('change', () => {
    loadInvoicesForPayment(paymentClientSelect.value);
    document.getElementById('invoice-due-info').textContent = '';
});

paymentInvoiceSelect.addEventListener('change', updateInvoiceDueInfo);

paymentForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData(paymentForm);
    const invoiceId = formData.get('invoice_id');
    const amount = parseFloat(formData.get('amount'));

    if (!invoiceId || !amount) {
        alert('Please select an invoice and enter an amount');
        return;
    }

    const submitBtn = paymentForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Recording...';

    try {
        const response = await fetch(`${API_BASE}/api/payments/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                invoice_id: parseInt(invoiceId),
                amount: amount,
                currency: formData.get('currency') || 'EUR',
                date: formData.get('date') || null,
                method: formData.get('method') || null,
                notes: formData.get('notes') || null
            })
        });

        if (response.ok) {
            const payment = await response.json();
            alert(`Payment of ${formatCurrency(payment.amount, payment.currency)} recorded successfully!`);
            closePaymentModal();
            loadInvoices();
            loadStats();
            if (currentView === 'payments') loadPayments();
        } else {
            const error = await response.json();
            alert(`Error: ${error.detail || 'Failed to record payment'}`);
        }
    } catch (error) {
        console.error('Error recording payment:', error);
        alert('Error recording payment. Please try again.');
    }

    submitBtn.disabled = false;
    submitBtn.innerHTML = '<i class="fas fa-check mr-2"></i>Record Payment';
});

// ============ CLIENT DETAIL MODAL ============

async function showClientDetail(clientId) {
    if (!clientId) return;

    currentClientId = clientId;

    try {
        const response = await fetch(`${API_BASE}/api/clients/${clientId}/summary`);
        if (!response.ok) {
            throw new Error('Failed to load client details');
        }

        const data = await response.json();

        document.getElementById('client-detail-title').textContent = data.client.name;
        document.getElementById('client-total-invoiced').textContent = formatCurrency(data.total_invoiced);
        document.getElementById('client-total-paid').textContent = formatCurrency(data.total_paid);
        document.getElementById('client-total-due').textContent = formatCurrency(data.total_due);

        const invoicesTable = document.getElementById('client-invoices-table');
        if (data.invoices.length === 0) {
            invoicesTable.innerHTML = '<tr><td colspan="6" class="px-4 py-3 text-center text-gray-500">No invoices</td></tr>';
        } else {
            invoicesTable.innerHTML = data.invoices.map(inv => `
                <tr class="bg-white">
                    <td class="px-4 py-2 font-medium">${inv.invoice_number}${ksefBadge(inv)}</td>
                    <td class="px-4 py-2 text-gray-500">${formatDate(inv.issue_date)}</td>
                    <td class="px-4 py-2">${amountHtml(inv)}</td>
                    <td class="px-4 py-2 text-green-600">${formatCurrency(inv.amount_paid || 0, inv.currency)}</td>
                    <td class="px-4 py-2 ${inv.amount_due > 0 ? 'text-red-600' : 'text-gray-400'}">${formatCurrency(inv.amount_due || 0, inv.currency)}</td>
                    <td class="px-4 py-2">
                        <span class="px-2 py-1 rounded-full text-xs font-medium ${getPaymentStatusClass(inv.payment_status)}">
                            ${(inv.payment_status || 'unpaid').charAt(0).toUpperCase() + (inv.payment_status || 'unpaid').slice(1)}
                        </span>
                    </td>
                </tr>
            `).join('');
        }

        const paymentsTable = document.getElementById('client-payments-table');
        if (data.payments.length === 0) {
            paymentsTable.innerHTML = '<tr><td colspan="5" class="px-4 py-3 text-center text-gray-500">No payments recorded</td></tr>';
        } else {
            paymentsTable.innerHTML = data.payments.map(p => `
                <tr class="bg-white">
                    <td class="px-4 py-2 text-gray-500">${p.date || '-'}</td>
                    <td class="px-4 py-2 font-medium text-green-600">${formatCurrency(p.amount, p.currency)}</td>
                    <td class="px-4 py-2">#${p.invoice_id}</td>
                    <td class="px-4 py-2 text-gray-500">${p.method || '-'}</td>
                    <td class="px-4 py-2 text-gray-500">${p.notes || '-'}</td>
                </tr>
            `).join('');
        }

        clientDetailModal.classList.remove('hidden');
        clientDetailModal.classList.add('flex');

    } catch (error) {
        console.error('Error loading client details:', error);
        alert('Error loading client details');
    }
}

function closeClientDetailModal() {
    clientDetailModal.classList.add('hidden');
    clientDetailModal.classList.remove('flex');
    currentClientId = null;
}

// ============ KEYBOARD & CLICK HANDLERS ============

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closePdfModal();
        closeClientModal();
        closePaymentModal();
        closeClientDetailModal();
        closeKorektaModal();
    }
});

pdfModal.addEventListener('click', (e) => {
    if (e.target === pdfModal) closePdfModal();
});
clientModal.addEventListener('click', (e) => {
    if (e.target === clientModal) closeClientModal();
});
paymentModal.addEventListener('click', (e) => {
    if (e.target === paymentModal) closePaymentModal();
});
clientDetailModal.addEventListener('click', (e) => {
    if (e.target === clientDetailModal) closeClientDetailModal();
});

// ============ DRIVE FILES ============

async function loadDriveFiles() {
    try {
        const response = await fetch(`${API_BASE}/api/invoices/`);
        const invoices = await response.json();

        // Sort by file number descending
        invoices.sort((a, b) => b.file_number - a.file_number);

        // Render mobile view
        const mobileList = document.getElementById('mobile-drive-list');
        // Render desktop view
        const desktopList = document.getElementById('desktop-drive-list');
        const countEl = document.getElementById('drive-file-count');

        if (countEl) countEl.textContent = `${invoices.length} invoices`;

        const renderFileItem = (inv, isMobile) => {
            const fileName = inv.drive_file_id || `Faktura ${inv.file_number}.pdf`;
            const clientName = inv.client ? inv.client.name : '';
            const amount = `${inv.currency} ${inv.amount.toLocaleString('en', {minimumFractionDigits: 2})}`;
            const date = inv.issue_date || '';

            if (isMobile) {
                return `
                    <div class="px-4 py-3 flex items-center justify-between" onclick="previewInvoice(${inv.id})" style="cursor:pointer">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="flex-shrink-0 w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center">
                                <i class="fas fa-file-pdf text-red-500 text-sm"></i>
                            </div>
                            <div class="min-w-0">
                                <p class="text-sm font-medium text-gray-900 truncate">Faktura ${inv.file_number} — ${clientName}</p>
                                <p class="text-xs text-gray-500">${inv.invoice_number} · ${date} · ${amount}</p>
                            </div>
                        </div>
                        <i class="fas fa-chevron-right text-gray-300 text-xs flex-shrink-0 ml-2"></i>
                    </div>`;
            } else {
                return `
                    <div class="px-4 py-3 flex items-center justify-between hover:bg-gray-50 cursor-pointer" onclick="previewInvoice(${inv.id})">
                        <div class="flex items-center gap-3">
                            <div class="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center">
                                <i class="fas fa-file-pdf text-red-500"></i>
                            </div>
                            <div>
                                <p class="text-sm font-medium text-gray-900">Faktura ${inv.file_number} — ${clientName}</p>
                                <p class="text-xs text-gray-500">${inv.invoice_number} · ${date}</p>
                            </div>
                        </div>
                        <div class="flex items-center gap-4">
                            <span class="text-sm font-medium text-gray-700">${amount}</span>
                            <a href="${API_BASE}/api/invoices/${inv.id}/download" class="text-blue-500 hover:text-blue-700" onclick="event.stopPropagation()" title="Download"><i class="fas fa-download"></i></a>
                        </div>
                    </div>`;
            }
        };

        if (mobileList) {
            mobileList.innerHTML = invoices.length
                ? invoices.map(inv => renderFileItem(inv, true)).join('')
                : '<div class="px-4 py-8 text-center text-gray-400">No invoice files yet</div>';
        }
        if (desktopList) {
            desktopList.innerHTML = invoices.length
                ? invoices.map(inv => renderFileItem(inv, false)).join('')
                : '<div class="px-4 py-8 text-center text-gray-400">No invoice files yet</div>';
        }
    } catch (err) {
        console.error('Error loading drive files:', err);
        const msg = '<div class="px-4 py-8 text-center text-red-500">Error loading files</div>';
        const m = document.getElementById('mobile-drive-list');
        const d = document.getElementById('desktop-drive-list');
        if (m) m.innerHTML = msg;
        if (d) d.innerHTML = msg;
    }
}

// ============ INIT ============

document.addEventListener('DOMContentLoaded', async () => {
    await fetchExchangeRate();
    loadStats();
    loadInvoices();
    loadClients();
});
