document.addEventListener('DOMContentLoaded', () => {
    // Obtener el formulario oculto y sus campos para la reserva normal
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

    // --- Lógica para el botón SHOW MORE / SHOW LESS ---
    const toggleDaysButton = document.getElementById('toggleDaysButton');
    const hiddenDayContainers = document.querySelectorAll('.hidden-day-container');
    
    let showingAllDays = false; // Estado inicial: solo se muestran los primeros dos días

    // *** MODIFICACIÓN CLAVE AQUÍ: FORZAR OCULTAMIENTO AL CARGAR ***
    if (hiddenDayContainers.length > 0) {
        hiddenDayContainers.forEach(container => {
            container.style.display = 'none';
        });
        if (toggleDaysButton) { // Asegurarse de que el botón existe antes de manipularlo
            toggleDaysButton.textContent = 'Show More Days'; // Asegurar el texto inicial
        }
        showingAllDays = false; // Confirmar el estado inicial
    } else {
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
                this.textContent = 'Show More Days';
                showingAllDays = false;
            } else {
                hiddenDayContainers.forEach(container => {
                    container.style.display = 'block'; 
                });
                this.textContent = 'Show Less Days';
                showingAllDays = true;
            }
        });
    }
    // --- LÓGICA PARA CALCULAR EL TIEMPO FUTURO ---
    const findSlotForm = document.getElementById('find-slot-form');
    const findSlotResults = document.getElementById('find-slot-results');
    const resultMessage = document.getElementById('result-message');
    const resultDetails = document.getElementById('result-details');
    const resultCountdown = document.getElementById('result-countdown');

    let countdownInterval; // Variable para almacenar el ID del intervalo de la cuenta regresiva

    if (findSlotForm) {
        findSlotForm.addEventListener('submit', async (event) => {
            event.preventDefault(); // Prevenir la recarga de la página

            const formData = new FormData(findSlotForm);
            const data = Object.fromEntries(formData.entries());

            // Mostrar "Calculando..." y limpiar resultados anteriores
            findSlotResults.style.display = 'block'; 
            resultMessage.textContent = 'Calculando...';
            resultDetails.textContent = '';
            resultCountdown.textContent = '';
            clearInterval(countdownInterval); 

            try {
                const response = await fetch('/find_closest_slot', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    body: new URLSearchParams(data).toString()
                });

                const result = await response.json();

                if (result.success) {
                    resultMessage.textContent = result.message;
                    resultDetails.innerHTML = `
                        <strong>Calculated Date:</strong> ${result.date}<br>
                        <strong>Calculated Hour (UTC):</strong> ${result.time}
                    `;
                    
                    // Iniciar cuenta regresiva usando el timestamp UTC
                    if (result.timestamp_utc) {
                        startCountdown(result.timestamp_utc * 1000, resultCountdown); // Convertir a milisegundos
                    } else {
                        // Fallback si por alguna razón no se recibe timestamp_utc (no debería pasar con el nuevo app.py)
                        const targetDateTime = new Date(`${result.date}T${result.time}:00Z`);
                        startCountdown(targetDateTime.getTime(), resultCountdown);
                    }

                } else {
                    resultMessage.textContent = `Error: ${result.message}`;
                    resultDetails.textContent = '';
                    resultCountdown.textContent = '';
                }

            } catch (error) {
                console.error('Error al calcular el tiempo:', error);
                findSlotResults.style.display = 'block';
                resultMessage.textContent = 'Ocurrió un error al calcular el tiempo.';
                resultDetails.textContent = '';
                resultCountdown.textContent = '';
            }
        });
    }

    // Esta función permanece igual, ya que ahora el backend siempre devuelve un timestamp_utc
    function startCountdown(targetTimestampMs, displayElement) {
        clearInterval(countdownInterval); // Limpiar cualquier intervalo anterior

        function update() {
            const now = new Date().getTime(); // Tiempo actual en milisegundos desde la época
            let diffMs = targetTimestampMs - now; // Diferencia en milisegundos

            if (diffMs <= 0) {
                displayElement.textContent = 'The time calculated is now or it has already passed!';
                clearInterval(countdownInterval);
                return;
            }

            const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
            diffMs -= days * (1000 * 60 * 60 * 24);
            const hours = Math.floor(diffMs / (1000 * 60 * 60));
            diffMs -= hours * (1000 * 60 * 60);
            const minutes = Math.floor(diffMs / (1000 * 60));
            diffMs -= minutes * (1000 * 60);
            const seconds = Math.floor(diffMs / 1000);

            displayElement.textContent = `TIME: ${days} Days, ${hours} Hours, ${minutes} mins, ${seconds} seconds`;
        }

        update(); // Llamada inicial para mostrar el tiempo inmediatamente
        countdownInterval = setInterval(update, 1000); // Actualizar cada segundo
    }
    
    // Función de ayuda para capitalizar la primera letra (si no la tienes ya)
    if (!String.prototype.capitalize) {
        String.prototype.capitalize = function() {
            return this.charAt(0).toUpperCase() + this.slice(1);
        }
    }
    // --- LÓGICA PARA CANCELAR RESERVAS ---
    const cancelModal = document.getElementById('cancelModal');
    const closeButton = document.querySelector('.close-button');
    const modalBookingId = document.getElementById('modalBookingId');
    const modalBookedBy = document.getElementById('modalBookedBy');
    const confirmCancelName = document.getElementById('confirmCancelName');
    const confirmCancelButton = document.getElementById('confirmCancelButton');
    const cancelMessage = document.getElementById('cancelMessage');

    let currentBookingIdToCancel = null;
    let currentBookedByName = null;

    // Función para mostrar el modal (igual que antes)
    window.showCancelModal = (bookingId, bookedByName) => { // Ahora recibe los parámetros directamente
        currentBookingIdToCancel = bookingId;
        currentBookedByName = bookedByName;
        
        modalBookingId.textContent = currentBookingIdToCancel;
        modalBookedBy.textContent = currentBookedByName;
        confirmCancelName.value = ''; // Limpiar el input de confirmación
        cancelMessage.textContent = ''; // Limpiar mensajes anteriores
        cancelModal.style.display = 'block';
    };

    // Función para cerrar el modal (igual que antes)
    window.closeCancelModal = () => {
        cancelModal.style.display = 'none';
        currentBookingIdToCancel = null;
        currentBookedByName = null;
    };

    // Cerrar el modal al hacer clic fuera de él (igual que antes)
    window.onclick = (event) => {
        if (event.target === cancelModal) {
            closeCancelModal();
        }
    };

    // Manejar el clic del botón de confirmar cancelación (igual que antes)
    if (confirmCancelButton) {
        confirmCancelButton.addEventListener('click', async () => {
            const userNameConfirm = confirmCancelName.value.trim();

            if (!userNameConfirm) {
                cancelMessage.textContent = 'Please enter your name to confirm.';
                return;
            }

            if (userNameConfirm !== currentBookedByName) {
                cancelMessage.textContent = 'The name entered does not match the booking name.';
                return;
            }

            cancelMessage.textContent = 'Cancelling...';

            try {
                const response = await fetch('/cancel_booking', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    body: new URLSearchParams({
                        booking_id: currentBookingIdToCancel,
                        booked_by_user: userNameConfirm
                    }).toString()
                });

                const result = await response.json();

                if (result.success) {
                    cancelMessage.style.color = 'green';
                    cancelMessage.textContent = result.message;
                    setTimeout(() => {
                        closeCancelModal();
                        location.reload(); // Recargar la página
                    }, 1500);
                } else {
                    cancelMessage.style.color = 'red';
                    cancelMessage.textContent = `Error: ${result.message}`;
                }

            } catch (error) {
                console.error('Error cancelling booking:', error);
                cancelMessage.style.color = 'red';
                cancelMessage.textContent = 'An unexpected error occurred during cancellation.';
            }
        });
    }

    // Cerrar modal con el botón 'x'
    if (closeButton) {
        closeButton.addEventListener('click', closeCancelModal);
    }

    // --- NUEVO: Manejar clics en las 'X' de cancelación ---
    // Seleccionar todos los elementos con la clase 'cancel-x'
    const cancelXButtons = document.querySelectorAll('.cancel-x');

    cancelXButtons.forEach(xButton => {
        xButton.addEventListener('click', (event) => {
            // Detener la propagación del evento para que no se active el clic del slot-item si lo tiene
            event.stopPropagation(); 
            const bookingId = xButton.dataset.bookingId;
            const bookedByName = xButton.dataset.bookedByName;
            showCancelModal(bookingId, bookedByName);
        });
    });

    // ... (El resto de tu código JS existente) ...
});