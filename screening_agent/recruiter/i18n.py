from enum import StrEnum


class Locale(StrEnum):
    ES_MX = "es-MX"
    ES_ES = "es-ES"
    EN_US = "en-US"


DEFAULT_LOCALE = Locale.ES_MX
LOCALE_COOKIE = "recruiter_lang"
LOCALE_COOKIE_MAX_AGE = 365 * 24 * 3600
LANGUAGE_FALLBACK = {"es": Locale.ES_MX, "en": Locale.EN_US}

STRINGS: dict[Locale, dict[str, str]] = {
    Locale.ES_MX: {
        "locale_name": "Español (MX)",
        "brand_subtitle": "reclutamiento · repartidores",
        "kicker": "Pase de cocina",
        "title_login": "Ingresar",
        "title_check_inbox": "Revisa tu correo",
        "title_confirm": "Ingresar",
        "heading_login": "Acceso para reclutadores",
        "label_email": "Correo de trabajo",
        "button_send_link": "Envíame una liga de acceso",
        "check_inbox_heading": "Revisa tu correo",
        "check_inbox_body_named": (
            "Si {email} pertenece a un reclutador invitado, tu liga de acceso ya va en camino. "
            "Funciona una sola vez y caduca pronto."
        ),
        "check_inbox_body_anon": (
            "Si esa dirección pertenece a un reclutador invitado, tu liga de acceso ya va en "
            "camino. Funciona una sola vez y caduca pronto."
        ),
        "use_other_address": "Usar otro correo",
        "confirm_body": "Da clic en el botón para terminar de ingresar. La liga funciona una sola vez.",
        "button_sign_in": "Ingresar",
        "error_link_used": "Esa liga ya caducó o ya se usó",
        "error_inactive": "Esta cuenta no está activa",
        "email_subject": "Tu liga de acceso al panel de reclutadores de Grupo Sazón",
        "email_body": (
            "Abre esta liga para ingresar al panel de reclutadores. Funciona una sola vez y "
            "caduca en {minutes:g} minutos.\n\n{link}\n\nSi no la pediste, ignora este correo."
        ),
    },
    Locale.ES_ES: {
        "locale_name": "Español (ES)",
        "brand_subtitle": "reclutamiento · repartidores",
        "kicker": "Pase de cocina",
        "title_login": "Entrar",
        "title_check_inbox": "Revisa tu correo",
        "title_confirm": "Entrar",
        "heading_login": "Acceso para reclutadores",
        "label_email": "Correo electrónico de trabajo",
        "button_send_link": "Enviarme un enlace de acceso",
        "check_inbox_heading": "Revisa tu correo",
        "check_inbox_body_named": (
            "Si {email} pertenece a un reclutador invitado, tu enlace de acceso está en camino. "
            "Funciona una sola vez y caduca pronto."
        ),
        "check_inbox_body_anon": (
            "Si esa dirección pertenece a un reclutador invitado, tu enlace de acceso está en "
            "camino. Funciona una sola vez y caduca pronto."
        ),
        "use_other_address": "Usar otra dirección",
        "confirm_body": "Haz clic en el botón para terminar de entrar. El enlace funciona una sola vez.",
        "button_sign_in": "Entrar",
        "error_link_used": "Ese enlace ha caducado o ya se ha usado",
        "error_inactive": "Esta cuenta no está activa",
        "email_subject": "Tu enlace de acceso al panel de reclutadores de Grupo Sazón",
        "email_body": (
            "Abre este enlace para entrar en el panel de reclutadores. Funciona una sola vez y "
            "caduca en {minutes:g} minutos.\n\n{link}\n\nSi no lo has pedido, ignora este correo."
        ),
    },
    Locale.EN_US: {
        "locale_name": "English",
        "brand_subtitle": "recruiting · delivery drivers",
        "kicker": "Kitchen pass",
        "title_login": "Login",
        "title_check_inbox": "Check your inbox",
        "title_confirm": "Sign in",
        "heading_login": "Recruiter login",
        "label_email": "Work email",
        "button_send_link": "Send me a login link",
        "check_inbox_heading": "Check your inbox",
        "check_inbox_body_named": (
            "If {email} belongs to an invited recruiter, a login link is on its way. "
            "It works once and expires soon."
        ),
        "check_inbox_body_anon": (
            "If that address belongs to an invited recruiter, a login link is on its way. "
            "It works once and expires soon."
        ),
        "use_other_address": "Use a different address",
        "confirm_body": "Press the button to finish signing in. The link works once.",
        "button_sign_in": "Sign in",
        "error_link_used": "That link has expired or was already used",
        "error_inactive": "This account is not active",
        "email_subject": "Your Grupo Sazón recruiter login link",
        "email_body": (
            "Open this link to sign in to the recruiter console. It works once and expires in "
            "{minutes:g} minutes.\n\n{link}\n\nIf you did not ask for it, ignore this email."
        ),
    },
}


def parse_locale(value: str | None) -> Locale | None:
    if value is None:
        return None
    try:
        return Locale(value)
    except ValueError:
        return None


def locale_from_accept_language(header: str | None) -> Locale | None:
    """First exact tag wins; otherwise the first tag whose language has a fallback."""
    if not header:
        return None
    tags = [part.split(";")[0].strip() for part in header.split(",")]
    for tag in tags:
        exact = next((loc for loc in Locale if loc.value.lower() == tag.lower()), None)
        if exact is not None:
            return exact
    for tag in tags:
        fallback = LANGUAGE_FALLBACK.get(tag.split("-")[0].lower())
        if fallback is not None:
            return fallback
    return None


def resolve_locale(query: str | None, cookie: str | None, accept_language: str | None) -> Locale:
    return (
        parse_locale(query)
        or parse_locale(cookie)
        or locale_from_accept_language(accept_language)
        or DEFAULT_LOCALE
    )
