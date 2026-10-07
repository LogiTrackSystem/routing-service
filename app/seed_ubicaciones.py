from .models import Ubicacion
from .texto import normalizar

# (codigo, nombre, departamento/estado, pais, codigo_pais, latitud, longitud, tipo)
UBICACIONES_SEMILLA = [
    # ---------- Colombia ----------
    ("CO-BOG", "Bogotá", "Bogotá D.C.", "Colombia", "CO", 4.7110, -74.0721, "capital"),
    ("CO-MDE", "Medellín", "Antioquia", "Colombia", "CO", 6.2442, -75.5812, "ciudad"),
    ("CO-CLO", "Cali", "Valle del Cauca", "Colombia", "CO", 3.4516, -76.5320, "ciudad"),
    ("CO-BAQ", "Barranquilla", "Atlántico", "Colombia", "CO", 10.9685, -74.7813, "puerto"),
    ("CO-CTG", "Cartagena", "Bolívar", "Colombia", "CO", 10.3910, -75.4794, "puerto"),
    ("CO-MTR", "Montería", "Córdoba", "Colombia", "CO", 8.7480, -75.8814, "ciudad"),
    ("CO-BGA", "Bucaramanga", "Santander", "Colombia", "CO", 7.1193, -73.1227, "ciudad"),
    ("CO-PEI", "Pereira", "Risaralda", "Colombia", "CO", 4.8133, -75.6961, "ciudad"),
    ("CO-MZL", "Manizales", "Caldas", "Colombia", "CO", 5.0703, -75.5138, "ciudad"),
    ("CO-AXM", "Armenia", "Quindío", "Colombia", "CO", 4.5339, -75.6811, "ciudad"),
    ("CO-CUC", "Cúcuta", "Norte de Santander", "Colombia", "CO", 7.8939, -72.5078, "ciudad"),
    ("CO-IBE", "Ibagué", "Tolima", "Colombia", "CO", 4.4389, -75.2322, "ciudad"),
    ("CO-NVA", "Neiva", "Huila", "Colombia", "CO", 2.9273, -75.2819, "ciudad"),
    ("CO-PSO", "Pasto", "Nariño", "Colombia", "CO", 1.2136, -77.2811, "ciudad"),
    ("CO-SMR", "Santa Marta", "Magdalena", "Colombia", "CO", 11.2408, -74.1990, "puerto"),
    ("CO-VUP", "Valledupar", "Cesar", "Colombia", "CO", 10.4631, -73.2532, "ciudad"),
    ("CO-SIN", "Sincelejo", "Sucre", "Colombia", "CO", 9.3047, -75.3978, "ciudad"),
    ("CO-VVC", "Villavicencio", "Meta", "Colombia", "CO", 4.1420, -73.6266, "ciudad"),
    ("CO-PPN", "Popayán", "Cauca", "Colombia", "CO", 2.4448, -76.6147, "ciudad"),
    ("CO-TUN", "Tunja", "Boyacá", "Colombia", "CO", 5.5353, -73.3678, "ciudad"),
    ("CO-RCH", "Riohacha", "La Guajira", "Colombia", "CO", 11.5444, -72.9072, "ciudad"),
    ("CO-UIB", "Quibdó", "Chocó", "Colombia", "CO", 5.6947, -76.6611, "ciudad"),
    ("CO-FLA", "Florencia", "Caquetá", "Colombia", "CO", 1.6144, -75.6062, "ciudad"),
    ("CO-EYP", "Yopal", "Casanare", "Colombia", "CO", 5.3378, -72.3959, "ciudad"),
    ("CO-AUC", "Arauca", "Arauca", "Colombia", "CO", 7.0847, -70.7591, "ciudad"),
    ("CO-MCJ", "Mocoa", "Putumayo", "Colombia", "CO", 1.1491, -76.6476, "ciudad"),
    ("CO-SJE", "San José del Guaviare", "Guaviare", "Colombia", "CO", 2.5729, -72.6459, "ciudad"),
    ("CO-BUN", "Buenaventura", "Valle del Cauca", "Colombia", "CO", 3.8801, -77.0312, "puerto"),
    ("CO-EJA", "Barrancabermeja", "Santander", "Colombia", "CO", 7.0653, -73.8547, "ciudad"),
    ("CO-IPI", "Ipiales", "Nariño", "Colombia", "CO", 0.8303, -77.6442, "ciudad"),
    ("CO-MCO", "Maicao", "La Guajira", "Colombia", "CO", 11.3783, -72.2389, "ciudad"),
    ("CO-GIR", "Girardot", "Cundinamarca", "Colombia", "CO", 4.3010, -74.8039, "ciudad"),
    ("CO-DUI", "Duitama", "Boyacá", "Colombia", "CO", 5.8268, -73.0341, "ciudad"),
    ("CO-APA", "Apartadó", "Antioquia", "Colombia", "CO", 7.8830, -76.6259, "ciudad"),
    ("CO-CRT", "Cartago", "Valle del Cauca", "Colombia", "CO", 4.7464, -75.9117, "ciudad"),
    ("CO-TLU", "Tuluá", "Valle del Cauca", "Colombia", "CO", 4.0847, -76.1954, "ciudad"),
    ("CO-RNG", "Rionegro", "Antioquia", "Colombia", "CO", 6.1550, -75.3737, "ciudad"),
    ("CO-CAU", "Caucasia", "Antioquia", "Colombia", "CO", 7.9847, -75.1983, "ciudad"),
    ("CO-LOR", "Lorica", "Córdoba", "Colombia", "CO", 9.2394, -75.8142, "ciudad"),
    ("CO-SON", "San Onofre", "Sucre", "Colombia", "CO", 9.7400, -75.5217, "ciudad"),
    # ---------- Capitales de Sudamérica ----------
    ("BR-BSB", "Brasília", "Distrito Federal", "Brasil", "BR", -15.7939, -47.8828, "capital"),
    ("PE-LIM", "Lima", "Lima", "Perú", "PE", -12.0464, -77.0428, "capital"),
    ("EC-UIO", "Quito", "Pichincha", "Ecuador", "EC", -0.1807, -78.4678, "capital"),
    ("BO-LPB", "La Paz", "La Paz", "Bolivia", "BO", -16.4897, -68.1193, "capital"),
    ("CL-SCL", "Santiago", "Región Metropolitana", "Chile", "CL", -33.4489, -70.6693, "capital"),
    ("AR-BUE", "Buenos Aires", "Ciudad Autónoma de Buenos Aires", "Argentina", "AR", -34.6037, -58.3816, "capital"),
    ("PY-ASU", "Asunción", "Asunción", "Paraguay", "PY", -25.2637, -57.5759, "capital"),
    ("UY-MVD", "Montevideo", "Montevideo", "Uruguay", "UY", -34.9011, -56.1645, "capital"),
    ("VE-CCS", "Caracas", "Distrito Capital", "Venezuela", "VE", 10.4806, -66.9036, "capital"),
    ("GY-GEO", "Georgetown", "Demerara-Mahaica", "Guyana", "GY", 6.8013, -58.1551, "capital"),
    ("SR-PBM", "Paramaribo", "Paramaribo", "Surinam", "SR", 5.8520, -55.2038, "capital"),
]


def sembrar_ubicaciones(db) -> int:
    """Inserta las ubicaciones de la semilla que aún no existen (idempotente).
    Devuelve cuántas se insertaron."""
    existentes = {codigo for (codigo,) in db.query(Ubicacion.codigo).all()}
    nuevas = 0
    for codigo, nombre, depto, pais, codigo_pais, lat, lon, tipo in UBICACIONES_SEMILLA:
        if codigo in existentes:
            continue
        db.add(Ubicacion(
            codigo=codigo,
            nombre=nombre,
            nombre_normalizado=normalizar(nombre),
            departamento=depto,
            pais=pais,
            codigo_pais=codigo_pais,
            latitud=lat,
            longitud=lon,
            tipo=tipo,
        ))
        nuevas += 1
    if nuevas:
        db.commit()
    return nuevas