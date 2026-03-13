#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
import ssl


# Django-sslserver (0.22) uses ssl.wrap_socket, which was removed in Python 3.12.
# Provide a minimal shim so runsslserver works for local HTTPS.
if not hasattr(ssl, "wrap_socket"):
    def _wrap_socket(sock, certfile=None, keyfile=None, server_side=False, **kwargs):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if certfile:
            context.load_cert_chain(certfile, keyfile)
        return context.wrap_socket(sock, server_side=server_side)

    ssl.wrap_socket = _wrap_socket  # type: ignore[attr-defined]


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mentor_followup.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
