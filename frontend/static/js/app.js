/**
 * Invoice Tracker App - Dashboard JavaScript
 */

const API_BASE = '';

// State
let invoices = [];
let clients = [];
let currentInvoiceId = null;
let currentClientId = null;

// DOM Elements
const filterStatus = document.getElementById('filter-status');
const filterClient = document.getElementById('filter-client');
const invoiceTable = document.getElementById('invoice-table');
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
    return date.toLocaleDateString('de-DE');
}

// Load dashboard stats
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

        // Client breakdown - show all clients as clickable cards
        const breakdown = document.getElementById('client-breakdown');
        const dueByClient = stats.due_by_client || {};
        const totalByClient = stats.total_by_client || {};

        // Get all clients, sorted by outstanding amount descending
        const allClients = Object.keys(totalByClient);
        const sortedClients = allClients.sort((a, b) => (dueByClient[b] || 0) - (dueByClient[a] || 0));

        if (sortedClients.length === 0) {
            breakdown.innerHTML = '<p class="text-gray-500">No clients yet</p>';
        } else {
            breakdown.innerHTML = sortedClients.map(client => {
                const due = dueByClient[client] || 0;
                const isPaid = due === 0;
                const bgColor = isPaid ? 'bg-gray-100' : 'bg-red-50 border-red-200';
                const textColor = isPaid ? 'text-gray-500' : 'text-red-600';
                const statusText = isPaid ? 'Paid' : formatCurrency(due);

                return `
                    <div class="p-3 rounded-lg border ${bgColor} cursor-pointer hover:shadow-md transition-shadow"
                         onclick="filterByClientName('${client.replace(/'/g, "\\'")}')">
                        <div class="font-medium text-gray-900 truncate">${client}</div>
                        <div class="text-lg font-bold ${textColor}">${statusText}</div>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Load invoices
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
    } catch (error) {
        console.error('Error loading invoices:', error);
        invoiceTable.innerHTML = '<tr><td colspan="9" class="px-6 py-4 text-center text-red-500">Error loading invoices</td></tr>';
    }
}

// Get payment status class
function getPaymentStatusClass(status) {
    switch (status) {
        case 'paid': return 'payment-paid';
        case 'partial': return 'payment-partial';
        default: return 'payment-unpaid';
    }
}

// Render invoices table
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
        const isPaid = inv.payment_status === 'paid' || inv.amount_due === 0;
        const rowClass = isPaid ? 'bg-gray-100 text-gray-500' : 'hover:bg-gray-50';

        return `
        <tr class="${rowClass}">
            <td class="px-4 py-3 whitespace-nowrap">
                <span class="font-medium">${inv.invoice_number}</span>
            </td>
            <td class="px-4 py-3">
                <button onclick="filterByClientName('${(inv.client?.name || '').replace(/'/g, "\\'")}')" class="${isPaid ? 'text-gray-600' : 'text-blue-600 hover:text-blue-800'} hover:underline text-left">
                    ${inv.client?.name || '-'}
                </button>
            </td>
            <td class="px-4 py-3">
                <span class="truncate block max-w-xs" title="${inv.description}">
                    ${inv.description}
                </span>
            </td>
            <td class="px-4 py-3 whitespace-nowrap font-medium">
                ${formatCurrency(inv.amount, inv.currency)}
            </td>
            <td class="px-4 py-3 whitespace-nowrap ${isPaid ? '' : 'text-green-600'}">
                ${formatCurrency(inv.amount_paid || 0, inv.currency)}
            </td>
            <td class="px-4 py-3 whitespace-nowrap ${inv.amount_due > 0 ? 'text-red-600 font-bold' : ''}">
                ${inv.amount_due > 0 ? formatCurrency(inv.amount_due, inv.currency) : '-'}
            </td>
            <td class="px-4 py-3 whitespace-nowrap">
                ${formatDate(inv.issue_date)}
            </td>
            <td class="px-4 py-3 whitespace-nowrap">
                ${isPaid ? '<span class="text-green-600 font-medium">Paid</span>' :
                  inv.amount_due > 0 ? `<span class="text-red-600 font-medium">Due ${formatCurrency(inv.amount_due, inv.currency)}</span>` :
                  `<span class="px-2 py-1 rounded-full text-xs font-medium status-${inv.status}">${inv.status}</span>`}
            </td>
            <td class="px-4 py-3 whitespace-nowrap">
                <div class="flex items-center space-x-2">
                    <button onclick="previewInvoice(${inv.id})" class="text-blue-600 hover:text-blue-800" title="Preview">
                        <i class="fas fa-eye"></i>
                    </button>
                    ${inv.status === 'draft' ? `
                        <button onclick="previewAndSend(${inv.id})" class="text-green-600 hover:text-green-800" title="Send">
                            <i class="fas fa-paper-plane"></i>
                        </button>
                    ` : ''}
                    ${inv.amount_due > 0 ? `
                        <button onclick="openPaymentModalForInvoice(${inv.id})" class="text-green-600 hover:text-green-800" title="Add Payment">
                            <i class="fas fa-plus-circle"></i>
                        </button>
                    ` : ''}
                </div>
            </td>
        </tr>
        `;
    }).join('');
}

// Load clients for filter
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

// Preview invoice PDF
function previewInvoice(invoiceId) {
    currentInvoiceId = invoiceId;
    pdfFrame.src = `${API_BASE}/api/invoices/${invoiceId}/preview`;
    sendBtn.style.display = 'none';
    pdfModal.classList.remove('hidden');
    pdfModal.classList.add('flex');
}

// Preview and send
function previewAndSend(invoiceId) {
    currentInvoiceId = invoiceId;
    pdfFrame.src = `${API_BASE}/api/invoices/${invoiceId}/preview`;
    sendBtn.style.display = 'inline-flex';
    pdfModal.classList.remove('hidden');
    pdfModal.classList.add('flex');
}

// Close PDF modal
function closePdfModal() {
    pdfModal.classList.add('hidden');
    pdfModal.classList.remove('flex');
    pdfFrame.src = '';
    currentInvoiceId = null;
}

// Send invoice
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

// Mark invoice as paid
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

// Client modal functions
function openClientModal() {
    clientModal.classList.remove('hidden');
    clientModal.classList.add('flex');
}

function closeClientModal() {
    clientModal.classList.add('hidden');
    clientModal.classList.remove('flex');
    clientForm.reset();
}

// Add new client
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

// Current filter state
let currentClientFilter = null;

// Filter change handlers
filterStatus.addEventListener('change', loadInvoices);
filterClient.addEventListener('change', () => {
    updateFilterUI();
    loadInvoices();
});

// Update filter UI elements
function updateFilterUI() {
    const showAllBtn = document.getElementById('show-all-btn');
    const currentFilter = document.getElementById('current-filter');
    const filterClientName = document.getElementById('filter-client-name');

    if (currentClientFilter) {
        showAllBtn.classList.remove('hidden');
        currentFilter.classList.remove('hidden');
        filterClientName.textContent = currentClientFilter;
    } else {
        showAllBtn.classList.add('hidden');
        currentFilter.classList.add('hidden');
    }
}

// Filter by client name (clicked from breakdown or invoice table)
function filterByClientName(clientName) {
    // Find client ID by name
    const client = clients.find(c => c.name === clientName);
    if (client) {
        filterClient.value = client.id;
        currentClientFilter = clientName;
        updateFilterUI();
        loadInvoices();
    }
}

// Clear client filter
function clearClientFilter() {
    filterClient.value = '';
    currentClientFilter = null;
    updateFilterUI();
    loadInvoices();
}

// Close modals on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closePdfModal();
        closeClientModal();
        closePaymentModal();
        closeClientDetailModal();
    }
});

// Close modals on background click
pdfModal.addEventListener('click', (e) => {
    if (e.target === pdfModal) closePdfModal();
});
clientModal.addEventListener('click', (e) => {
    if (e.target === clientModal) closeClientModal();
});

// ============ PAYMENT MODAL ============

// Open payment modal
function openPaymentModal() {
    // Populate client dropdown
    paymentClientSelect.innerHTML = '<option value="">Select client...</option>' +
        clients.map(c => `<option value="${c.id}">${c.name}</option>`).join('');

    paymentInvoiceSelect.innerHTML = '<option value="">Select client first...</option>';
    document.getElementById('invoice-due-info').textContent = '';
    document.getElementById('payment-amount').value = '';

    paymentModal.classList.remove('hidden');
    paymentModal.classList.add('flex');
}

// Open payment modal for specific invoice
function openPaymentModalForInvoice(invoiceId) {
    const invoice = invoices.find(i => i.id === invoiceId);
    if (!invoice) return;

    openPaymentModal();

    // Pre-select client
    paymentClientSelect.value = invoice.client_id;
    loadInvoicesForPayment(invoice.client_id).then(() => {
        paymentInvoiceSelect.value = invoiceId;
        updateInvoiceDueInfo();
    });
}

// Load invoices for payment dropdown (filtered by client)
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

// Update invoice due info when selection changes
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

// Close payment modal
function closePaymentModal() {
    paymentModal.classList.add('hidden');
    paymentModal.classList.remove('flex');
    paymentForm.reset();
}

// Handle client selection change in payment modal
paymentClientSelect.addEventListener('change', () => {
    loadInvoicesForPayment(paymentClientSelect.value);
    document.getElementById('invoice-due-info').textContent = '';
});

// Handle invoice selection change
paymentInvoiceSelect.addEventListener('change', updateInvoiceDueInfo);

// Submit payment form
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

// Show client detail
async function showClientDetail(clientId) {
    if (!clientId) return;

    currentClientId = clientId;

    try {
        const response = await fetch(`${API_BASE}/api/clients/${clientId}/summary`);
        if (!response.ok) {
            throw new Error('Failed to load client details');
        }

        const data = await response.json();

        // Update title
        document.getElementById('client-detail-title').textContent = data.client.name;

        // Update totals
        document.getElementById('client-total-invoiced').textContent = formatCurrency(data.total_invoiced);
        document.getElementById('client-total-paid').textContent = formatCurrency(data.total_paid);
        document.getElementById('client-total-due').textContent = formatCurrency(data.total_due);

        // Populate invoices table
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

        // Populate payments table
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

        // Show modal
        clientDetailModal.classList.remove('hidden');
        clientDetailModal.classList.add('flex');

    } catch (error) {
        console.error('Error loading client details:', error);
        alert('Error loading client details');
    }
}

// Close client detail modal
function closeClientDetailModal() {
    clientDetailModal.classList.add('hidden');
    clientDetailModal.classList.remove('flex');
    currentClientId = null;
}

// Close modals on background click
paymentModal.addEventListener('click', (e) => {
    if (e.target === paymentModal) closePaymentModal();
});

clientDetailModal.addEventListener('click', (e) => {
    if (e.target === clientDetailModal) closeClientDetailModal();
});

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadInvoices();
    loadClients();
});
