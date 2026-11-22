function mensajeDeError(response) {
    const tipoContenido = response.headers.get("content-type") || "";
    if (tipoContenido.includes("application/json")) {
        return response.json().then(data =>
            typeof data.detail === "string"
                ? data.detail
                : "Revise los datos ingresados e intente de nuevo."
        );
    }

    return response.text().then(html => {
        const pagina = new DOMParser().parseFromString(html, "text/html");
        const alerta = pagina.querySelector(".alert-danger");
        return alerta?.textContent.trim()
            || "Revise los datos ingresados e intente de nuevo.";
    });
}

document.addEventListener("submit", async event => {
    const form = event.target;
    if (
        event.defaultPrevented
        || !(form instanceof HTMLFormElement)
        || form.method.toLowerCase() !== "post"
        || form.dataset.actionFeedback === "false"
    ) {
        return;
    }

    const accion = new URL(form.action, window.location.href);
    if (accion.origin !== window.location.origin || !window.Swal) return;

    event.preventDefault();
    Swal.fire({
        title: "Procesando...",
        text: "Espere mientras se completa la acción.",
        allowOutsideClick: false,
        allowEscapeKey: false,
        didOpen: () => Swal.showLoading()
    });

    try {
        const response = await fetch(accion.href, {
            method: "POST",
            body: new FormData(form),
            credentials: "same-origin"
        });
        const destino = new URL(response.url || accion.href);
        const redireccionNoAutorizada = response.redirected
            && destino.pathname === "/login"
            && !["/login", "/logout", "/setup-admin"].includes(accion.pathname);

        if (!response.ok || redireccionNoAutorizada) {
            const mensaje = response.ok
                ? "Su sesión terminó. Inicie sesión e intente de nuevo."
                : await mensajeDeError(response);
            await Swal.fire({
                icon: "error",
                title: "No se pudo completar",
                text: mensaje
            });
            return;
        }

        if (accion.hash && destino.pathname === accion.pathname) {
            destino.hash = accion.hash;
        }
        await Swal.fire({
            icon: "success",
            title: "Acción completada",
            text: "La operación terminó correctamente.",
            timer: 1300,
            showConfirmButton: false
        });
        window.location.assign(destino.href);
    } catch (error) {
        console.error(error);
        await Swal.fire({
            icon: "error",
            title: "Error de conexión",
            text: "No se pudo completar la acción. Revise su conexión e intente de nuevo."
        });
    }
});
