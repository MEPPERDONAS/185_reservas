document.addEventListener('DOMContentLoaded', () => {
    // ... (Tu lógica existente para bookingForm y slotCells, no necesita cambios aquí) ...
    const bookingForm = document.getElementById('booking-form');
    const formDate = document.getElementById('form-date');
    const formQueue = document.getElementById('form-queue');
    const formTime = document.getElementById('form-time');
    const formBookedBy = document.getElementById('form-booked-by');

    const slotCells = document.querySelectorAll('.slot');

    slotCells.forEach(cell => {
        cell.addEventListener('click', () => {
            if (cell.classList.contains('available')) {
                const date = cell.dataset.date;
                const queue = cell.dataset.queue;
                const time = cell.dataset.time;

                const bookedByName = prompt(`Book slot for ${date} at ${time} in ${queue}. Please enter your name:`);

                if (bookedByName && bookedByName.trim() !== '') {
                    formDate.value = date;
                    formQueue.value = queue;
                    formTime.value = time;
                    formBookedBy.value = bookedByName.trim();

                    bookingForm.submit();
                } else if (bookedByName !== null) {
                    alert('Name is required to make a reservation.');
                }
            } else {
                if (cell.classList.contains('past-slot')) {
                    alert('This slot has already passed and cannot be booked.');
                } else {
                    alert('This slot is already booked.');
                }
            }
        });
    });

    // --- LÓGICA PARA EL BOTÓN SHOW MORE / SHOW LESS ---
    const toggleDaysButton = document.getElementById('toggleDaysButton');
    const hiddenDayContainers = document.querySelectorAll('.hidden-day-container');
    
    let showingAllDays = false; // Estado inicial: solo se muestran los primeros dos días

    // *** MODIFICACIÓN CLAVE AQUÍ: FORZAR OCULTAMIENTO AL CARGAR ***
    // Si hay contenedores que deberían estar ocultos, asegúrate de que lo estén.
    // Esto maneja el caso donde el CSS podría no haberlos ocultado por alguna razón
    // o si el JS se ejecuta antes de que el CSS se aplique completamente.
    if (hiddenDayContainers.length > 0) {
        hiddenDayContainers.forEach(container => {
            container.style.display = 'none';
        });
        toggleDaysButton.textContent = 'Show More Days'; // Asegurar el texto inicial
        showingAllDays = false; // Confirmar el estado inicial
    } else {
        // Si no hay días para ocultar (por ejemplo, si solo muestras 2 días o menos en total)
        // entonces el botón no es necesario o debería tener otro estado/texto
        if (toggleDaysButton) {
            toggleDaysButton.style.display = 'none'; // Oculta el botón si no hay nada que mostrar/ocultar
        }
    }


    if (toggleDaysButton) {
        toggleDaysButton.addEventListener('click', function() {
            if (showingAllDays) {
                hiddenDayContainers.forEach(container => {
                    container.style.display = 'none';
                });
                this.textContent = 'Show More Days'; // Usar 'this' para referirse al botón
                showingAllDays = false;
            } else {
                hiddenDayContainers.forEach(container => {
                    container.style.display = 'block'; 
                });
                this.textContent = 'Show Less Days'; // Usar 'this' para referirse al botón
                showingAllDays = true;
            }
        });
    }
});