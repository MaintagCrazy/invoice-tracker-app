/**
 * Invoice Tracker App - Dashboard JavaScript
 */

const API_BASE = '';

// State
let invoices = [];
let clients = [];
let currentInvoiceId = null;

// DOM Elements
const filterStatus = document.getElementById('filter-status');
const filterClient = document.getElementById('filter-client');
const invoiceTable = document.getElementById('invoice-table');
const pdfModal = document.getElementById('pdf-modal');
const pdfFrame = document.getElementById('pdf-frame');
const sendBtn = document.getElementById('send-btn');
const clientModal = document.getElementById('client-modal');
const clientForm = document.getElementById('client-form');

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
        document.getElementById('stat-total-amount').textContent = formatCurrency(stats.total_amount);

        // Client breakdown
        const breakdown = document.getElementById('client-breakdown');
        breakdown.innerHTML = Object.entries(stats.total_by_client || {})
            .map(([client, total]) => `
                <div class="flex justify-between items-center">
                    <span class="text-gray-600">${client}</span>
                    <span class="font-medium">${formatCurrency(total)}</span>
                </div>
            `).join('') || '<p class="text-gray-500">No invoices yet</p>';
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
        invoiceTable.innerHTML = '<tr><td colspan="7" class="px-6 py-4 text-center text-red-500">Error loading invoices</td></tr>';
    }
}

// Render invoices table
function renderInvoices() {
    if (invoices.length === 0) {
        invoiceTable.innerHTML = `
            <tr>
                <td colspan="7" class="px-6 py-8 text-center text-gray-500">
                    <i class="fas fa-file-invoice text-4xl mb-3 text-gray-300"></i>
                    <p>No invoices found</p>
                    <a href="/chat" class="text-blue-600 hover:underline">Create your first invoice</a>
                </td>
            </tr>
        `;
        return;
    }

    invoiceTable.innerHTML = invoices.map(inv => `
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="font-medium">${inv.invoice_number}</span>
            </td>
            <td class="px-6 py-4">
                ${inv.client?.name || '-'}
            </td>
            <td class="px-6 py-4">
                <span class="truncate block max-w-xs" title="${inv.description}">
                    ${inv.description}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap font-medium">
                ${formatCurrency(inv.amount, inv.currency)}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-gray-500">
                ${formatDate(inv.issue_date)}
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 py-1 rounded-full text-xs font-medium status-${inv.status}">
                    ${inv.status.charAt(0).toUpperCase() + inv.status.slice(1)}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center space-x-2">
                    <button onclick="previewInvoice(${inv.id})" class="text-blue-600 hover:text-blue-800" title="Preview">
                        <i class="fas fa-eye"></i>
                    </button>
                    ${inv.status === 'draft' ? `
                        <button onclick="previewAndSend(${inv.id})" class="text-green-600 hover:text-green-800" title="Send">
                            <i class="fas fa-paper-plane"></i>
                        </button>
                    ` : ''}
                    ${inv.status === 'sent' ? `
                        <button onclick="markPaid(${inv.id})" class="text-green-600 hover:text-green-800" title="Mark Paid">
                            <i class="fas fa-check-circle"></i>
                        </button>
                    ` : ''}
                </div>
            </td>
        </tr>
    `).join('');
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

// Filter change handlers
filterStatus.addEventListener('change', loadInvoices);
filterClient.addEventListener('change', loadInvoices);

// Close modals on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closePdfModal();
        closeClientModal();
    }
});

// Close modals on background click
pdfModal.addEventListener('click', (e) => {
    if (e.target === pdfModal) closePdfModal();
});
clientModal.addEventListener('click', (e) => {
    if (e.target === clientModal) closeClientModal();
});

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadInvoices();
    loadClients();
});
