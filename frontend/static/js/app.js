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
let currentView = 'invoices'; // 'invoices' or 'payments'

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

// ============ MOBILE DETECTION ============
const isMobile = () => window.innerWidth < 768;

// ============ VIEW SWITCHING ============

function showInvoicesView() {
    currentView = 'invoices';
    document.getElementById('invoices-view').classList.remove('hidden');
    document.getElementById('payments-view').classList.add('hidden');
    document.getElementById('view-invoices-btn').className = 'px-4 py-2 bg-blue-600 text-white rounded-lg font-medium';
    document.getElementById('view-payments-btn').className = 'px-4 py-2 bg-white text-gray-600 rounded-lg font-medium border hover:bg-gray-50';
}

function showPaymentsView() {
    currentView = 'payments';
    document.getElementById('invoices-view').classList.add('hidden');
    document.getElementById('payments-view').classList.remove('hidden');
    document.getElementById('view-invoices-btn').className = 'px-4 py-2 bg-white text-gray-600 rounded-lg font-medium border hover:bg-gray-50';
    document.getElementById('view-payments-btn').className = 'px-4 py-2 bg-blue-600 text-white rounded-lg font-medium';
    loadPayments();
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

    mInv.classList.add('hidden');
    mPay.classList.add('hidden');
    mCli.classList.add('hidden');

    if (view === 'invoices') {
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
        document.getElementById('stat-due').textContent = formatCurrency(stats.total_due || 0);
        document.getElementById('stat-received').textContent = formatCurrency(stats.total_paid || 0);
        document.getElementById('stat-total-outstanding').textContent = formatCurrency(stats.total_due || 0);

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
        const isPaid = inv.payment_status === 'paid' || (inv.amount_due !== undefined && inv.amount_due <= 0);
        const rowBg = isPaid ? 'bg-gray-100' : '';
        const textMuted = isPaid ? 'text-gray-400' : '';

        return `
        <tr class="${rowBg} hover:bg-gray-50">
            <td class="col-inv px-3 py-3 text-sm truncate">
                <span class="font-medium ${textMuted}">${inv.invoice_number}</span>
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
                ${formatCurrency(inv.amount, inv.currency)}
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
                ${isPaid
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
        const isPaid = inv.payment_status === 'paid' || (inv.amount_due !== undefined && inv.amount_due <= 0);
        return `
        <div class="invoice-card ${isPaid ? 'paid-card' : ''}" onclick="previewInvoice(${inv.id})">
            <div style="min-width:0; flex:1">
                <div class="flex items-center gap-2">
                    <span class="text-xs text-gray-400">${inv.invoice_number}</span>
                    ${isPaid ? '<span class="text-xs text-green-600 font-medium">Paid</span>' : ''}
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

// ============ PDF PREVIEW ============

function previewInvoice(invoiceId) {
    currentInvoiceId = invoiceId;
    pdfFrame.src = `${API_BASE}/api/invoices/${invoiceId}/preview`;
    sendBtn.style.display = 'none';
    pdfModal.classList.remove('hidden');
    pdfModal.classList.add('flex');
}

function previewAndSend(invoiceId) {
    currentInvoiceId = invoiceId;
    pdfFrame.src = `${API_BASE}/api/invoices/${invoiceId}/preview`;
    sendBtn.style.display = 'inline-flex';
    pdfModal.classList.remove('hidden');
    pdfModal.classList.add('flex');
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
            body: JSON.stringify({})
        });

        const result = await response.json();

        if (result.success) {
            alert(`Invoice sent successfully!\n${result.message}`);
            closePdfModal();
            loadInvoices();
            loadStats();
        } else {
            alert(`Error: ${result.message || 'Failed to send invoice'}`);
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
                    <td class="px-4 py-2 font-medium">${inv.invoice_number}</td>
                    <td class="px-4 py-2 text-gray-500">${formatDate(inv.issue_date)}</td>
                    <td class="px-4 py-2">${formatCurrency(inv.amount, inv.currency)}</td>
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

// ============ INIT ============

document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadInvoices();
    loadClients();
});
