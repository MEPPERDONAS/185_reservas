let savedUserName = localStorage.getItem('bookedByName') || '';

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast-notification');
    const fresh = toast.cloneNode(true);
    toast.parentNode.replaceChild(fresh, toast);

    fresh.textContent = message;
    fresh.className = `toast-notification ${type}`;

    clearTimeout(fresh._hideTimeout);
    fresh._hideTimeout = setTimeout(() => {
        fresh.classList.add('hidden');
    }, 3000);
}


function attachSlotListeners() {
    document.querySelectorAll('td.slot.available').forEach(cell => {
        if (cell.dataset.listenerAttached) return;
        cell.dataset.listenerAttached = 'true';
        cell.addEventListener('click', () => handleSlotClick(cell));
    });
}

function handleSlotClick(cell) {
    const date = cell.dataset.date;
    const queue = cell.dataset.queue;
    const time = cell.dataset.time;

    const name = prompt(
        `Book slot for ${date} at ${time} in ${queue}.\nEnter your name:`,
        savedUserName
    );
    if (!name || !name.trim()) {
        if (name !== null) showToast('Name is required to book.', 'error');
        return;
    }
    const trimmedName = name.trim();
    savedUserName = trimmedName;
    localStorage.setItem('bookedByName', trimmedName);

    const originalHTML = cell.innerHTML;
    const originalClasses = cell.className;
    cell.className = 'slot booked slot-loading';
    cell.removeAttribute('data-listener-attached');
    cell.innerHTML = '<span>⏳</span> <span translate="no">' + trimmedName + '</span>';

    const formData = new FormData();
    formData.append('date', date);
    formData.append('queue', queue);
    formData.append('time', time);
    formData.append('booked_by', trimmedName);

    fetch('/book', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: formData
    })
        .then(res => res.json())
        .then(data => {
            cell.classList.remove('slot-loading');
            if (data.success) {
                cell.className = 'slot booked';
                cell.innerHTML =
                    '<span translate="no">' + trimmedName + '</span>' +
                    '<span class="cancel-x"' +
                    '      data-booking-id="' + (data.booking_id || '') + '"' +
                    '      data-booked-by-name="' + trimmedName + '"' +
                    '      title="Cancel this booking">&#x2716;</span>';
                const xBtn = cell.querySelector('.cancel-x');
                if (xBtn) attachCancelX(xBtn);
                showToast('Booked Confirmed for ' + queue.toUpperCase(), 'success');
            } else {
                revertCell(cell, originalHTML, originalClasses);
                showToast(data.message || 'This slot is no longer available.', 'error');
            }
        })
        .catch(() => {
            revertCell(cell, originalHTML, originalClasses);
            showToast('Network error. Please try again.', 'error');
        });
}

function revertCell(cell, originalHTML, originalClasses) {
    cell.innerHTML = originalHTML;
    cell.className = originalClasses;
    cell.removeAttribute('data-listener-attached');
    attachSlotListeners();
}
//  CANCEL BOOKINGS
function attachCancelX(xButton) {
    xButton.addEventListener('click', function (e) {
        e.stopPropagation();
        showCancelModal(this.dataset.bookingId, this.dataset.bookedByName);
    });
}

let currentBookingIdToCancel = null;
let currentBookedByName = null;

window.showCancelModal = function (bookingId, bookedByName) {
    currentBookingIdToCancel = bookingId;
    currentBookedByName = bookedByName;
    document.getElementById('modalBookingId').textContent = bookingId;
    document.getElementById('modalBookedBy').textContent = bookedByName;
    document.getElementById('confirmCancelName').value = savedUserName;
    document.getElementById('cancelMessage').textContent = '';
    document.getElementById('cancelMessage').style.color = 'red';
    document.getElementById('cancelModal').style.display = 'block';
};

window.closeCancelModal = function () {
    document.getElementById('cancelModal').style.display = 'none';
    currentBookingIdToCancel = null;
    currentBookedByName = null;
};

window.onclick = function (event) {
    const modal = document.getElementById('cancelModal');
    if (event.target === modal) closeCancelModal();
};

// ════════════════════════════════════════════════════════════
//  MAIN — DOMContentLoaded
// ════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', function () {

    // Slot listeners
    attachSlotListeners();

    // Show More / Show Less
    const toggleDaysButton = document.getElementById('toggleDaysButton');
    const hiddenDayContainers = document.querySelectorAll('.hidden-day-container');
    let showingAllDays = false;

    if (hiddenDayContainers.length > 0) {
        hiddenDayContainers.forEach(function (c) { c.style.display = 'none'; });
        if (toggleDaysButton) toggleDaysButton.textContent = 'Show More Days';
    } else {
        if (toggleDaysButton) toggleDaysButton.style.display = 'none';
    }

    if (toggleDaysButton) {
        toggleDaysButton.addEventListener('click', function () {
            showingAllDays = !showingAllDays;
            hiddenDayContainers.forEach(function (c) {
                c.style.display = showingAllDays ? 'block' : 'none';
            });
            this.textContent = showingAllDays ? 'Show Less Days' : 'Show More Days';
        });
    }

    // Find Slot Form
    const findSlotForm = document.getElementById('find-slot-form');
    const findSlotResults = document.getElementById('find-slot-results');
    const resultMessage = document.getElementById('result-message');
    const resultDetails = document.getElementById('result-details');
    const resultCountdown = document.getElementById('result-countdown');
    let countdownInterval;

    if (findSlotForm) {
        findSlotForm.addEventListener('submit', async function (event) {
            event.preventDefault();
            const formData = new FormData(findSlotForm);
            const data = Object.fromEntries(formData.entries());

            findSlotResults.style.display = 'block';
            resultMessage.textContent = 'Calculating...';
            resultDetails.textContent = '';
            resultCountdown.textContent = '';
            clearInterval(countdownInterval);

            try {
                const response = await fetch('/find_closest_slot', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams(data).toString()
                });
                const result = await response.json();

                if (result.success) {
                    resultMessage.textContent = result.message;
                    resultDetails.innerHTML =
                        '<strong>Calculated Date:</strong> ' + result.date + '<br>' +
                        '<strong>Calculated Hour (UTC):</strong> ' + result.time;

                    const targetMs = result.timestamp_utc
                        ? result.timestamp_utc * 1000
                        : new Date(result.date + 'T' + result.time + ':00Z').getTime();
                    startCountdown(targetMs, resultCountdown);
                    scrollToDate(result.date, result.time, showingAllDays, toggleDaysButton, hiddenDayContainers);
                } else {
                    resultMessage.textContent = 'Error: ' + result.message;
                    resultDetails.textContent = '';
                    resultCountdown.textContent = '';
                }
            } catch (error) {
                console.error('Error calculating time:', error);
                resultMessage.textContent = 'An error occurred while calculating.';
            }
        });
    }

    function startCountdown(targetTimestampMs, displayElement) {
        clearInterval(countdownInterval);
        function update() {
            const diffMs = targetTimestampMs - Date.now();
            if (diffMs <= 0) {
                displayElement.textContent = 'The time calculated is now or has already passed!';
                clearInterval(countdownInterval);
                return;
            }
            const days = Math.floor(diffMs / 86400000);
            const hours = Math.floor((diffMs % 86400000) / 3600000);
            const minutes = Math.floor((diffMs % 3600000) / 60000);
            const seconds = Math.floor((diffMs % 60000) / 1000);
            displayElement.textContent =
                'TIME: ' + days + ' Days, ' + hours + ' Hours, ' + minutes + ' mins, ' + seconds + ' seconds';
        }
        update();
        countdownInterval = setInterval(update, 1000);
    }

    function scrollToDate(dateStr, timeStr, showingAll, toggleBtn, hiddenContainers) {
        const table = document.querySelector('table[data-date="' + dateStr + '"]');
        if (!table) return;
        const wrapper = table.closest('.hidden-day-container');
        if (wrapper && !showingAll) {
            hiddenContainers.forEach(function (c) { c.style.display = 'block'; });
            if (toggleBtn) toggleBtn.textContent = 'Show Less Days';
        }
        const hour = parseInt(timeStr.split(':')[0]);
        const targetRow = table.querySelectorAll('tbody tr')[hour];
        if (targetRow) {
            targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
            targetRow.classList.add('highlight-row');
            setTimeout(function () { targetRow.classList.remove('highlight-row'); }, 2500);
        }
    }

    // Cancel modal
    const closeButton = document.querySelector('.close-button');
    const confirmCancelBtn = document.getElementById('confirmCancelButton');
    const cancelMessage = document.getElementById('cancelMessage');

    if (closeButton) closeButton.addEventListener('click', closeCancelModal);

    if (confirmCancelBtn) {
        confirmCancelBtn.addEventListener('click', async function () {
            const userNameConfirm = document.getElementById('confirmCancelName').value.trim();

            if (!userNameConfirm) {
                cancelMessage.textContent = 'Please enter your name to confirm.';
                return;
            }
            if (userNameConfirm !== currentBookedByName) {
                cancelMessage.textContent = 'The name entered does not match the booking name.';
                return;
            }

            cancelMessage.style.color = 'orange';
            cancelMessage.textContent = 'Cancelling...';

            try {
                const response = await fetch('/cancel_booking', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({
                        booking_id: currentBookingIdToCancel,
                        booked_by_user: userNameConfirm
                    }).toString()
                });
                const result = await response.json();

                if (result.success) {
                    // Optimistic cancel — revertir celda a Available sin recargar
                    const xBtn = document.querySelector(
                        '.cancel-x[data-booking-id="' + currentBookingIdToCancel + '"]'
                    );
                    const cell = xBtn ? xBtn.closest('td.slot') : null;
                    closeCancelModal();
                    if (cell) {
                        cell.className = 'slot available';
                        cell.innerHTML = 'Available';
                        cell.removeAttribute('data-listener-attached');
                        attachSlotListeners();
                    }
                    showToast('Booking cancelled successfully.', 'success');
                } else {
                    cancelMessage.style.color = 'red';
                    cancelMessage.textContent = 'Error: ' + result.message;
                }
            } catch (error) {
                console.error('Error cancelling booking:', error);
                cancelMessage.style.color = 'red';
                cancelMessage.textContent = 'An unexpected error occurred.';
            }
        });
    }

    // Cancel X buttons del HTML inicial
    document.querySelectorAll('.cancel-x').forEach(function (xBtn) { attachCancelX(xBtn); });

});

document.addEventListener('DOMContentLoaded', () => {
    const flashData = document.getElementById('flash-data');
    if (!flashData) return;

    flashData.querySelectorAll('span').forEach((el, i) => {
        const category = el.dataset.category;
        const message = el.dataset.message;

        const type = category === 'error' ? 'error'
            : category === 'warning' ? 'info'
                : 'success';

        setTimeout(() => showToast(message, type), i * 400);
    });
});