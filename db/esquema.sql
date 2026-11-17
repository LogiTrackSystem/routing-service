-- Esquema de routing_db (routing-service): SQL generado por 'alembic upgrade head --sql' a partir de alembic/versions.
-- Crea todas las tablas, secuencias y restricciones. No contiene datos.
BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 2079f086f642

CREATE TABLE rutas (
    id UUID NOT NULL, 
    envio_id UUID NOT NULL, 
    vehiculo_id UUID, 
    paradas JSONB, 
    distancia_km NUMERIC(10, 2), 
    hora_estimada_llegada TIMESTAMP WITH TIME ZONE, 
    veces_recalculada INTEGER NOT NULL, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_rutas_envio_id ON rutas (envio_id);

CREATE TABLE historial_rutas (
    id UUID NOT NULL, 
    ruta_id UUID NOT NULL, 
    paradas_anteriores JSONB, 
    distancia_km_anterior NUMERIC(10, 2), 
    hora_estimada_llegada_anterior TIMESTAMP WITH TIME ZONE, 
    motivo_recalculo TEXT, 
    recalculado_en TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    PRIMARY KEY (id), 
    FOREIGN KEY(ruta_id) REFERENCES rutas (id)
);

CREATE INDEX ix_historial_rutas_ruta_id ON historial_rutas (ruta_id);

INSERT INTO alembic_version (version_num) VALUES ('2079f086f642') RETURNING alembic_version.version_num;

-- Running upgrade 2079f086f642 -> cc603030054d

ALTER TABLE rutas ADD COLUMN kilometraje_inicio_ruta NUMERIC(10, 2);

UPDATE alembic_version SET version_num='cc603030054d' WHERE alembic_version.version_num = '2079f086f642';

-- Running upgrade cc603030054d -> 7b7f58b8f9ef

UPDATE alembic_version SET version_num='7b7f58b8f9ef' WHERE alembic_version.version_num = 'cc603030054d';

-- Running upgrade 7b7f58b8f9ef -> ec0415556b15

CREATE TABLE ubicaciones (
    id UUID NOT NULL, 
    codigo VARCHAR(12) NOT NULL, 
    nombre VARCHAR(100) NOT NULL, 
    nombre_normalizado VARCHAR(100) NOT NULL, 
    departamento VARCHAR(100) NOT NULL, 
    pais VARCHAR(60) NOT NULL, 
    codigo_pais VARCHAR(2) NOT NULL, 
    latitud NUMERIC(9, 6) NOT NULL, 
    longitud NUMERIC(9, 6) NOT NULL, 
    tipo VARCHAR(20) DEFAULT 'ciudad' NOT NULL, 
    activo BOOLEAN DEFAULT true NOT NULL, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_ubicaciones_codigo UNIQUE (codigo), 
    CONSTRAINT uq_ubicaciones_pais_nombre_depto UNIQUE (codigo_pais, nombre_normalizado, departamento)
);

CREATE INDEX ix_ubicaciones_nombre_normalizado ON ubicaciones (nombre_normalizado);

CREATE INDEX ix_ubicaciones_codigo_pais ON ubicaciones (codigo_pais);

UPDATE alembic_version SET version_num='ec0415556b15' WHERE alembic_version.version_num = '7b7f58b8f9ef';

-- Running upgrade ec0415556b15 -> fd922d88f28c

CREATE SEQUENCE IF NOT EXISTS seq_codigo_ruta START WITH 1 MINVALUE 1 MAXVALUE 99999999;

CREATE TABLE rutas_maestras (
    id UUID NOT NULL, 
    codigo_ruta VARCHAR(12) DEFAULT 'RUT-' || lpad(nextval('seq_codigo_ruta')::text, 8, '0') NOT NULL, 
    origen_id UUID NOT NULL, 
    destino_id UUID NOT NULL, 
    distancia_km NUMERIC(10, 2) NOT NULL, 
    duracion_horas NUMERIC(8, 2) NOT NULL, 
    geometria TEXT NOT NULL, 
    paradas JSONB, 
    fuente VARCHAR(10) DEFAULT 'osrm' NOT NULL, 
    calculada_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_rutas_maestras_codigo UNIQUE (codigo_ruta), 
    CONSTRAINT uq_rutas_maestras_par UNIQUE (origen_id, destino_id), 
    FOREIGN KEY(origen_id) REFERENCES ubicaciones (id), 
    FOREIGN KEY(destino_id) REFERENCES ubicaciones (id)
);

ALTER SEQUENCE seq_codigo_ruta OWNED BY rutas_maestras.codigo_ruta;

UPDATE alembic_version SET version_num='fd922d88f28c' WHERE alembic_version.version_num = 'ec0415556b15';

-- Running upgrade fd922d88f28c -> 6c3c902b7e97

ALTER TABLE rutas ADD COLUMN estado VARCHAR(20) DEFAULT 'manual' NOT NULL;

UPDATE rutas SET estado = 'historica';

ALTER TABLE rutas ADD COLUMN conductor_id UUID;

ALTER TABLE rutas ADD COLUMN reserva_id UUID;

ALTER TABLE rutas ADD COLUMN ruta_maestra_id UUID;

ALTER TABLE rutas ADD COLUMN requisitos JSONB;

ALTER TABLE rutas ADD COLUMN detalle_asignacion JSONB;

ALTER TABLE rutas ADD COLUMN distancia_planificada_km NUMERIC(10, 2);

ALTER TABLE rutas ADD COLUMN intentos INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE rutas ADD COLUMN proximo_reintento_en TIMESTAMP WITH TIME ZONE;

ALTER TABLE rutas ADD COLUMN ultimo_error TEXT;

ALTER TABLE rutas ADD COLUMN evento_pendiente VARCHAR(30);

ALTER TABLE rutas ADD CONSTRAINT fk_rutas_ruta_maestra FOREIGN KEY(ruta_maestra_id) REFERENCES rutas_maestras (id);

CREATE INDEX ix_rutas_estado ON rutas (estado);

CREATE UNIQUE INDEX uq_rutas_envio_vigente ON rutas (envio_id) WHERE estado NOT IN ('historica', 'manual');

UPDATE alembic_version SET version_num='6c3c902b7e97' WHERE alembic_version.version_num = 'fd922d88f28c';

-- Running upgrade 6c3c902b7e97 -> b81f3c0d7a24

ALTER TABLE rutas ADD COLUMN modo VARCHAR(12) DEFAULT 'exclusiva' NOT NULL;

ALTER TABLE rutas ADD COLUMN ruta_anfitriona_id UUID;

ALTER TABLE rutas ADD COLUMN km_recogida NUMERIC(10, 2);

ALTER TABLE rutas ADD COLUMN km_entrega NUMERIC(10, 2);

ALTER TABLE rutas ADD COLUMN reposicion JSONB;

ALTER TABLE rutas ADD CONSTRAINT fk_rutas_ruta_anfitriona FOREIGN KEY(ruta_anfitriona_id) REFERENCES rutas (id);

CREATE INDEX ix_rutas_ruta_anfitriona_id ON rutas (ruta_anfitriona_id);

CREATE INDEX ix_rutas_vehiculo_estado ON rutas (vehiculo_id, estado);

UPDATE alembic_version SET version_num='b81f3c0d7a24' WHERE alembic_version.version_num = '6c3c902b7e97';

COMMIT;

