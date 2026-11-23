"""HTTPS with LibreOffice's own Python, on every system, without extra packages.

Linux distributions build LibreOffice against the system's Python, which finds the system's
certificate authorities. LibreOffice's own builds (Windows, macOS, and the Linux downloads from
libreoffice.org) bring their own Python and OpenSSL, which look for them in the build's folders:
LibreOffice 26.8.3's Python for Linux looks in /usr/local/ssl and, started on its own, fails every
HTTPS request ("certificate verify failed"). Inside soffice it works because soffice sets
SSL_CERT_FILE to the system's bundle; whether every build and system does that is not documented.
On Windows, Python reads the system's certificate store itself.

So: when the default context holds no authorities and SSL_CERT_FILE is not set, the system's own
bundle is added. Certificates are always verified, never switched off.
"""

import os
import ssl

# The system's bundle of certificate authorities, by system (the first one that exists is used).
CA_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL, CentOS
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora, RHEL (newer)
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # macOS, Alpine, OpenBSD
    "/usr/local/etc/ssl/cert.pem",  # FreeBSD
    "/usr/local/share/certs/ca-root-nss.crt",  # FreeBSD (ca_root_nss)
)


def authorities(context):
    try:
        return context.cert_store_stats().get("x509_ca", 0)
    except Exception:
        return 0


def make_context(ca_files=CA_FILES, exists=os.path.isfile):
    """A verifying TLS context that knows the system's certificate authorities."""
    context = ssl.create_default_context()
    if authorities(context) == 0 and not os.environ.get("SSL_CERT_FILE"):
        for path in ca_files:
            if exists(path):
                try:
                    context.load_verify_locations(cafile=path)
                except (OSError, ssl.SSLError):
                    continue
                if authorities(context):
                    break
    return context
