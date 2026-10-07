import math

RADIO_TIERRA_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))


def decodificar_polyline(cadena, precision=5):
    """Convierte la polyline codificada de OSRM en una lista de (lat, lon)."""
    indice = lat = lon = 0
    factor = 10 ** precision
    puntos = []
    while indice < len(cadena):
        for coordenada in (0, 1):
            desplazamiento = resultado = 0
            while True:
                b = ord(cadena[indice]) - 63
                indice += 1
                resultado |= (b & 0x1F) << desplazamiento
                desplazamiento += 5
                if b < 0x20:
                    break
            delta = ~(resultado >> 1) if resultado & 1 else resultado >> 1
            if coordenada == 0:
                lat += delta
            else:
                lon += delta
        puntos.append((lat / factor, lon / factor))
    return puntos


def _codificar_valor(valor):
    valor = ~(valor << 1) if valor < 0 else (valor << 1)
    salida = ""
    while valor >= 0x20:
        salida += chr((0x20 | (valor & 0x1F)) + 63)
        valor >>= 5
    salida += chr(valor + 63)
    return salida


def codificar_polyline(puntos, precision=5):
    factor = 10 ** precision
    lat_ant = lon_ant = 0
    salida = ""
    for lat, lon in puntos:
        lat_i, lon_i = round(lat * factor), round(lon * factor)
        salida += _codificar_valor(lat_i - lat_ant) + _codificar_valor(lon_i - lon_ant)
        lat_ant, lon_ant = lat_i, lon_i
    return salida


def distancia_a_segmento_km(lat, lon, a, b):
    """Distancia (km) de un punto a un segmento a-b, y la fracción t (0..1) del punto más cercano."""
    k_lat = 111.32
    k_lon = 111.32 * math.cos(math.radians(lat))
    ax, ay = (a[1] - lon) * k_lon, (a[0] - lat) * k_lat
    bx, by = (b[1] - lon) * k_lon, (b[0] - lat) * k_lat
    dx, dy = bx - ax, by - ay
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / largo2))
    return math.hypot(ax + t * dx, ay + t * dy), t


def calcular_paradas(puntos, distancia_total_km, candidatas, radio_km=20.0, margen_km=10.0):
    """Ciudades del catálogo que quedan a menos de radio_km de la carretera,
    ordenadas por kilómetro desde el origen. Excluye las que están pegadas al origen o al destino."""
    if len(puntos) < 2:
        return []
    acumulado = [0.0]
    for i in range(1, len(puntos)):
        acumulado.append(acumulado[-1] + haversine_km(puntos[i - 1][0], puntos[i - 1][1], puntos[i][0], puntos[i][1]))
    largo = acumulado[-1]
    if largo <= 0:
        return []
    escala = distancia_total_km / largo  # ajusta al kilometraje real que reporta OSRM

    paradas = []
    for c in candidatas:
        lat, lon = float(c.latitud), float(c.longitud)
        mejor_dist, mejor_km = None, 0.0
        for i in range(len(puntos) - 1):
            dist, t = distancia_a_segmento_km(lat, lon, puntos[i], puntos[i + 1])
            if mejor_dist is None or dist < mejor_dist:
                mejor_dist = dist
                mejor_km = acumulado[i] + t * (acumulado[i + 1] - acumulado[i])
        if mejor_dist is None or mejor_dist > radio_km:
            continue
        km = mejor_km * escala
        if km < margen_km or km > distancia_total_km - margen_km:
            continue
        paradas.append({
            "ubicacion_id": str(c.id),
            "codigo": c.codigo,
            "nombre": c.nombre,
            "latitud": lat,
            "longitud": lon,
            "km_desde_origen": round(km, 1),
            "distancia_a_la_via_km": round(mejor_dist, 1),
        })
    paradas.sort(key=lambda p: p["km_desde_origen"])
    return paradas