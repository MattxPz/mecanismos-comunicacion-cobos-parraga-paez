# Contexto del sistema de cafetería · C4 nivel 1

El alcance acordado por el grupo es el sistema de cafetería. La preparación,
la facturación y las notificaciones quedan dentro de ese límite. Los estudiantes
y el personal de cocina, caja y administración interactúan con el software desde
fuera del límite. [Diagrama de contexto del modelo C4](https://c4model.com/diagrams/system-context).

```mermaid
C4Context
    title Contexto C4 nivel 1 del sistema de cafetería

    Person_Ext(estudiantes, "Estudiantes")
    Person_Ext(cocina, "Personal de cocina")
    System(cafeteria, "Sistema de cafetería", "Gestiona pedidos, preparación, cobros, avisos y estadísticas.")
    Person_Ext(caja, "Personal de caja")
    Person_Ext(administracion, "Administración")

    BiRel(estudiantes, cafeteria, "Crean pedidos, consultan su estado y reciben avisos")
    Rel(cocina, cafeteria, "Consulta pedidos para prepararlos")
    Rel(caja, cafeteria, "Gestiona el cobro")
    Rel(administracion, cafeteria, "Consulta estadísticas")
    UpdateLayoutConfig($c4ShapeInRow="2")
```

El diagrama representa el diseño acordado. En el proyecto actual, la API REST
permite crear y consultar pedidos. Las interfaces para los actores, los módulos
de cocina TCP y avisos WebSocket, el cobro y las estadísticas quedan pendientes.
