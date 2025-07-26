document.addEventListener('DOMContentLoaded', () => {
    // Obtener el formulario oculto y sus campos
    const bookingForm = document.getElementById('booking-form');
    const formDate = document.getElementById('form-date');
    const formQueue = document.getElementById('form-queue');
    const formTime = document.getElementById('form-time');
    const formBookedBy = document.getElementById('form-booked-by');

    // Seleccionar todas las celdas de slot (Research, Building, Training)
    const slotCells = document.querySelectorAll('.slot');

    slotCells.forEach(cell => {
        cell.addEventListener('click', () => {
            // Solo permitir hacer clic en slots disponibles
            if (cell.classList.contains('available')) {
                const date = cell.dataset.date;
                const queue = cell.dataset.queue;
                const time = cell.dataset.time;

                // Pedir el nombre al usuario
                const bookedByName = prompt(`Book slot for ${date} at ${time} in ${queue}. Please enter your name:`);

                if (bookedByName && bookedByName.trim() !== '') {
                    // Rellenar el formulario oculto con los datos
                    formDate.value = date;
                    formQueue.value = queue;
                    formTime.value = time;
                    formBookedBy.value = bookedByName.trim();

                    // Enviar el formulario
                    bookingForm.submit();
                } else if (bookedByName !== null) { // Si el usuario no canceló, pero dejó el campo vacío
                    alert('Name is required to make a reservation.');
                }
            } else {
                // Si el slot no está disponible, mostrar un mensaje
                if (cell.classList.contains('past-slot')) {
                    alert('This slot has already passed and cannot be booked.');
                } else {
                    alert('This slot is already booked.');
                }
            }
        });
    });
});
