import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para buscar 'bogota' y encontrar 'Bogotá'."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return sin_tildes.strip().lower()