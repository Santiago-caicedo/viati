from .cart import SESSION_KEY


def carrito(request):
    """Cantidad de artículos en el carrito para el badge del header."""
    data = request.session.get(SESSION_KEY) or {}
    return {"CART_COUNT": sum(int(item.get("qty", 0)) for item in data.values())}
