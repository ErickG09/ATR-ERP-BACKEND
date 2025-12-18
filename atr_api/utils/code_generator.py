def generate_operator_code_prefix(full_name: str) -> str:
    """
    A partir del nombre completo devuelve la letra de prefijo
    (primera letra del primer apellido).

    - Toma la primera palabra como primer apellido.
    - Devuelve la primera letra en mayúscula.
    """
    if not full_name:
        return "X"

    first_word = full_name.strip().split()[0]
    return first_word[0].upper()
