def time_str_to_seconds(time_str: str) -> float:
    """Convierte 'MM:SS' a segundos float para las gráficas."""
    if not time_str: return 0.0
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            return float(int(parts[0]) * 60 + int(parts[1]))
        elif len(parts) == 3:
            return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
        return 0.0
    except ValueError:
        return 0.0

def format_timestamp(seconds: float) -> str:
    """Convierte segundos float a formato 'MM:SS'."""
    td_mins = int(seconds // 60)
    td_secs = int(seconds % 60)
    return f"{td_mins:02}:{td_secs:02}"