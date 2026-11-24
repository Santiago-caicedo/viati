class SecurityHeadersMiddleware:
    """Mismos encabezados de seguridad que next.config.ts del proyecto original."""

    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for key, value in self.HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class RemoveTrailingSlashMiddleware:
    """Redirige /tienda/ → /tienda (301) para conservar las URLs del sitio original.

    El admin de Django sí usa "/" final, por eso se excluye.
    """

    EXCLUDED_PREFIXES = ("/admin", "/static", "/media")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path != "/" and path.endswith("/") and not path.startswith(self.EXCLUDED_PREFIXES):
            from django.http import HttpResponsePermanentRedirect

            query = request.META.get("QUERY_STRING", "")
            return HttpResponsePermanentRedirect(path.rstrip("/") + (f"?{query}" if query else ""))
        return self.get_response(request)
