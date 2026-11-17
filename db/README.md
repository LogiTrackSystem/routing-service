# Base de datos `routing_db`

| Archivo | Contenido |
|---|---|
| `esquema.sql` | Tablas, secuencias y restricciones (SQL generado con `alembic upgrade head --sql`); no contiene datos |

## Crear la base desde cero

1. Crea la base vacía `routing_db` en PostgreSQL.
2. **Esquema:** `psql "<URL_DE_LA_BASE>" -f db/esquema.sql` (o bien `alembic upgrade head` con `DATABASE_URL` apuntando a ella; el resultado es el mismo).
## Respaldo y restauración

```
# Respaldo (formato comprimido)
pg_dump -Fc --no-owner --no-privileges -f routing_db.dump "<URL_EXTERNA_DE_LA_BASE>"

# Restauración en otra base (vacía o existente)
pg_restore --no-owner --no-privileges --clean --if-exists -d "<URL_DE_DESTINO>" routing_db.dump
```

`<URL_...>` es la cadena de conexión real; **no la guardes en el repositorio** ni la pegues en chats o documentos. Los archivos `*.dump` no se suben a GitHub.
