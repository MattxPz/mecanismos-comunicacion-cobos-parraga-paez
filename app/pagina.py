# Código generado con IA (Claude Code, modelo Claude Opus 5.5).
# Ver docs/bitacora-ia.md.

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()

# La página va dentro del código para que la sirva la propia API.
# Usa solo HTML, CSS y JavaScript del navegador, sin librerías.
PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pedidos de cafetería</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #222; }
    form { display: grid; gap: 0.75rem; padding: 1rem; border: 1px solid #ccc; border-radius: 8px; }
    label { display: grid; gap: 0.25rem; }
    input, button { font: inherit; padding: 0.4rem; }
    button { cursor: pointer; }
    #mensaje { min-height: 1.5rem; }
    .error { color: #b00020; }
    .ok { color: #1b5e20; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
    th, td { text-align: left; padding: 0.4rem; border-bottom: 1px solid #ddd; }
    #estadisticas { display: flex; gap: 2rem; }
    #estadisticas strong { font-size: 1.5rem; display: block; }
    .aviso { background: #e8f5e9; border: 1px solid #1b5e20; border-radius: 8px; padding: 0.5rem 0.75rem; margin: 0.5rem 0; }
  </style>
</head>
<body>
  <h1>Pedidos de cafetería</h1>
  <p id="conexion">Avisos: conectando...</p>
  <div id="avisos" aria-live="polite"></div>

  <form id="formulario">
    <label>Cliente <input name="cliente" required></label>
    <label>Producto <input name="nombre" required></label>
    <label>Cantidad <input name="cantidad" type="number" min="1" step="1" value="1" required></label>
    <label>Precio <input name="precio" type="number" min="0.01" step="0.01" required></label>
    <button type="submit">Crear pedido</button>
  </form>
  <p id="mensaje"></p>

  <h2>Estadísticas</h2>
  <div id="estadisticas">
    <p>Pedidos listos <strong id="pedidos-listos">-</strong></p>
    <p>Importe total <strong id="importe-total">-</strong></p>
  </div>

  <h2>Pedidos <button id="actualizar" type="button">Actualizar</button></h2>
  <table>
    <thead><tr><th>Cliente</th><th>Productos</th><th>Total</th><th>Estado</th></tr></thead>
    <tbody id="lista"></tbody>
  </table>

  <script>
    const formulario = document.getElementById("formulario");
    const mensaje = document.getElementById("mensaje");
    const lista = document.getElementById("lista");
    const avisos = document.getElementById("avisos");
    const conexion = document.getElementById("conexion");

    function mostrarMensaje(texto, clase) {
      mensaje.textContent = texto;
      mensaje.className = clase;
    }

    function celda(fila, texto) {
      const td = document.createElement("td");
      td.textContent = texto;  // textContent evita inyectar HTML.
      fila.appendChild(td);
    }

    function mostrarAviso(datos) {
      const aviso = document.createElement("p");
      aviso.className = "aviso";
      aviso.textContent = "Pedido " + datos.id + " está " + datos.estado;
      avisos.prepend(aviso);
      setTimeout(() => aviso.remove(), 8000);
    }

    function conectarAvisos() {
      // Misma máquina y puerto que la página; wss:// si la página usa https.
      const protocolo = location.protocol === "https:" ? "wss://" : "ws://";
      const socket = new WebSocket(protocolo + location.host + "/ws");
      socket.addEventListener("open", () => { conexion.textContent = "Avisos: conectado"; });
      socket.addEventListener("message", (evento) => {
        const datos = JSON.parse(evento.data);
        if (datos.estado === "listo") {
          mostrarAviso(datos);
          cargarPedidos();
        }
      });
      socket.addEventListener("close", () => {
        // Si el servidor se reinicia, se reintenta la conexión.
        conexion.textContent = "Avisos: desconectado, reintentando...";
        setTimeout(conectarAvisos, 2000);
      });
    }

    async function cargarEstadisticas() {
      try {
        const respuesta = await fetch("/estadisticas");
        if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
        const datos = await respuesta.json();
        document.getElementById("pedidos-listos").textContent = datos.pedidos_listos;
        document.getElementById("importe-total").textContent = datos.importe_total;
      } catch (error) {
        mostrarMensaje("No se pudieron cargar las estadísticas: " + error.message, "error");
      }
    }

    async function cargarPedidos() {
      try {
        const respuesta = await fetch("/pedidos");
        if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
        const pedidos = await respuesta.json();
        lista.replaceChildren();
        for (const pedido of pedidos) {
          const fila = document.createElement("tr");
          celda(fila, pedido.cliente);
          celda(fila, pedido.productos.map(p => p.cantidad + " x " + p.nombre).join(", "));
          celda(fila, pedido.total);
          celda(fila, pedido.estado);
          lista.appendChild(fila);
        }
        // Las estadísticas cambian cuando cambia la lista (pedido nuevo o listo).
        await cargarEstadisticas();
      } catch (error) {
        mostrarMensaje("No se pudo cargar la lista: " + error.message, "error");
      }
    }

    formulario.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const campos = new FormData(formulario);
      const datos = {
        cliente: campos.get("cliente"),
        productos: [{
          nombre: campos.get("nombre"),
          cantidad: Number(campos.get("cantidad")),
          precio: campos.get("precio"),
        }],
      };

      try {
        const respuesta = await fetch("/pedidos", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify(datos),
        });
        const cuerpo = await respuesta.json();
        if (!respuesta.ok) {
          const detalle = Array.isArray(cuerpo.detail)
            ? cuerpo.detail.map(d => d.loc.join(".") + ": " + d.msg).join("; ")
            : cuerpo.detail;
          mostrarMensaje("Error " + respuesta.status + ": " + detalle, "error");
          return;
        }
        mostrarMensaje("Pedido creado con total " + cuerpo.total, "ok");
        formulario.reset();
        await cargarPedidos();
      } catch (error) {
        mostrarMensaje("No se pudo conectar con la API: " + error.message, "error");
      }
    });

    document.getElementById("actualizar").addEventListener("click", cargarPedidos);
    cargarPedidos();
    conectarAvisos();
  </script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina() -> str:
    return PAGINA
