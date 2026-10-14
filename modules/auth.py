"""Login OIDC obligatorio antes de que la app toque datos.

La app habla con Supabase usando la service_role key, que ignora RLS: quien
abre la app puede leer y escribir todo. Por eso el control de acceso vive
aca, en la puerta de la app, y falla cerrado: sin configuracion de login o
sin lista de emails permitidos no entra nadie.

Configuracion en .streamlit/secrets.toml (ver secrets.example.toml):
- [auth]: redirect_uri, cookie_secret, client_id, client_secret,
  server_metadata_url (st.login de Streamlit, proveedor OIDC por ej. Google).
- ALLOWED_EMAILS: lista de emails que pueden entrar.
- THRESHOLD_AUTH_DISABLED = true: apaga el login. Solo para desarrollo local
  en una maquina propia; nunca en una app publicada.
"""

from __future__ import annotations

import os

import streamlit as st

ALLOWED_EMAILS_KEY = "ALLOWED_EMAILS"
AUTH_DISABLED_KEY = "THRESHOLD_AUTH_DISABLED"
REQUIRED_AUTH_SETTINGS = (
    "redirect_uri",
    "cookie_secret",
    "client_id",
    "client_secret",
    "server_metadata_url",
)
_TRUTHY = {"1", "true", "yes", "si", "on"}


def _read_secret(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


def auth_disabled() -> bool:
    value = _read_secret(AUTH_DISABLED_KEY)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUTHY


def auth_configured() -> bool:
    try:
        auth_section = st.secrets.get("auth")
    except Exception:
        return False
    if not auth_section:
        return False
    return all(str(auth_section.get(setting) or "").strip() for setting in REQUIRED_AUTH_SETTINGS)


def allowed_emails() -> set[str]:
    raw = _read_secret(ALLOWED_EMAILS_KEY)
    if raw is None:
        return set()
    if isinstance(raw, str):
        items = raw.split(",")
    else:
        items = list(raw)
    return {str(item).strip().lower() for item in items if str(item).strip()}


def is_email_allowed(email: object, allowed: set[str]) -> bool:
    normalized = str(email or "").strip().lower()
    return bool(normalized) and normalized in allowed


def _render_logout_sidebar(email: str) -> None:
    with st.sidebar:
        st.caption(f"Sesion: {email}")
        if st.button("Cerrar sesion", key="auth_logout"):
            st.logout()


def require_login() -> None:
    """Corta la ejecucion (st.stop) si el usuario no esta autorizado.

    Debe llamarse antes de cualquier lectura de datos o hidratacion desde
    Supabase en cada entrypoint (app.py y cada archivo de pages/).
    """
    if auth_disabled():
        st.sidebar.warning("Login desactivado (THRESHOLD_AUTH_DISABLED). Solo para uso local.")
        return

    if not auth_configured():
        st.error(
            "El login no esta configurado. Falta la seccion [auth] en "
            ".streamlit/secrets.toml (ver secrets.example.toml). "
            "Por seguridad la app no carga datos sin login."
        )
        st.stop()

    allowed = allowed_emails()
    if not allowed:
        st.error(
            "No hay emails autorizados. Agrega ALLOWED_EMAILS en "
            ".streamlit/secrets.toml para habilitar el acceso."
        )
        st.stop()

    # .get y no el atributo: si Streamlit no cargo el campo (secrets no
    # visibles en ese contexto), el atributo lanza AttributeError. Solo un
    # True explicito cuenta como sesion iniciada.
    if st.user.get("is_logged_in") is not True:
        st.title("Threshold S&C")
        st.write("Inicia sesion para acceder a los datos de los atletas.")
        if st.button("Iniciar sesion con Google", key="auth_login", type="primary"):
            st.login()
        st.stop()

    email = st.user.get("email")
    # Un email no verificado por el proveedor no prueba que la persona sea
    # duena de esa casilla: no alcanza para estar en la lista de permitidos.
    email_verified = st.user.get("email_verified")
    if email_verified is False or not is_email_allowed(email, allowed):
        st.error(f"La cuenta {email or '(sin email)'} no tiene acceso a esta app.")
        if st.button("Cerrar sesion y usar otra cuenta", key="auth_logout_denied"):
            st.logout()
        st.stop()

    _render_logout_sidebar(str(email))
