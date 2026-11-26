"""Tests de l'extraction et du filtrage des adresses e-mail."""

from pathlib import Path

import pytest

from app.core.extractor import ExtractedEmail, clean_email, extract_emails, extract_emails_from_text
from app.core.filters import is_excluded_email

FIXTURES = Path(__file__).parent / "fixtures"


def emails_of(items: list[ExtractedEmail]) -> list[str]:
    return [item.email for item in items]


# --- mailto -------------------------------------------------------------------------


def test_mailto_encoded_with_subject() -> None:
    html = '<a href="mailto:Contact%40Site1.fr?subject=Bonjour%20vous">écrire</a>'
    assert extract_emails(html) == [ExtractedEmail("contact@site1.fr", "mailto")]


def test_mailto_with_several_recipients() -> None:
    html = '<a href="MAILTO:a@site.fr;b@site.fr">écrire</a>'
    assert emails_of(extract_emails(html)) == ["a@site.fr", "b@site.fr"]


def test_mailto_takes_precedence_over_text() -> None:
    html = '<p>Écrivez à <a href="mailto:info@site.fr">info@site.fr</a></p>'
    assert extract_emails(html) == [ExtractedEmail("info@site.fr", "mailto")]


def test_empty_mailto_is_ignored() -> None:
    assert extract_emails('<a href="mailto:">écrire</a>') == []


# --- texte brut ----------------------------------------------------------------------


def test_plain_text_email() -> None:
    html = "<p>Contactez jean.dupont@entreprise-test.fr pour un devis.</p>"
    assert extract_emails(html) == [ExtractedEmail("jean.dupont@entreprise-test.fr", "regex")]


def test_html_entities_are_decoded() -> None:
    assert emails_of(extract_emails("<p>info&#64;site.fr</p>")) == ["info@site.fr"]


def test_json_ld_emails() -> None:
    html = """
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "GovernmentOrganization",
     "name": "Mairie", "email": "mailto:Accueil@Mairie.fr",
     "contactPoint": [{"@type": "ContactPoint", "email": "urbanisme@mairie.fr"},
                      {"@type": "ContactPoint", "Email": ["etat-civil@mairie.fr"]}],
     "logo": "https://mairie.fr/logo@2x.png"}
    </script>
    <script>var dsn = "abc@o42.ingest.sentry.io"; var x = "dev@mairie.fr";</script>
    """
    assert extract_emails(html) == [
        ExtractedEmail("accueil@mairie.fr", "structured"),
        ExtractedEmail("urbanisme@mairie.fr", "structured"),
        ExtractedEmail("etat-civil@mairie.fr", "structured"),
    ]


def test_malformed_json_ld_falls_back_to_text_search() -> None:
    html = '<script type="Application/LD+JSON">{"email": "info@site.fr",}</script>'
    assert extract_emails(html) == [ExtractedEmail("info@site.fr", "structured")]


def test_mailto_takes_precedence_over_json_ld() -> None:
    html = (
        '<script type="application/ld+json">{"email": "info@site.fr"}</script>'
        '<a href="mailto:info@site.fr">écrire</a>'
    )
    assert extract_emails(html) == [ExtractedEmail("info@site.fr", "mailto")]


def test_emails_in_scripts_and_styles_are_ignored() -> None:
    html = "<script>var e = 'dev@site.fr';</script><style>/* css@site.fr */</style><p>Bonjour</p>"
    assert extract_emails(html) == []


def test_bytes_with_meta_charset() -> None:
    html = '<meta charset="windows-1252"><p>Écrire à l\'accueil : info@site.fr</p>'.encode("cp1252")
    assert emails_of(extract_emails(html)) == ["info@site.fr"]


def test_emails_split_by_tags_are_separated() -> None:
    html = "<p>a@site.fr</p><p>b@site.fr</p>"
    assert emails_of(extract_emails(html)) == ["a@site.fr", "b@site.fr"]


@pytest.mark.parametrize(
    "text",
    [
        "Contact : info@site.fr.",
        "Contact : info@site.fr,",
        "Contact : info@site.fr;",
        "(info@site.fr)",
        "« info@site.fr »",
    ],
)
def test_trailing_punctuation_is_removed(text: str) -> None:
    assert emails_of(extract_emails_from_text(text)) == ["info@site.fr"]


def test_duplicates_and_uppercase() -> None:
    text = "Info@Site.FR, info@site.fr et INFO@SITE.FR"
    assert extract_emails_from_text(text) == [ExtractedEmail("info@site.fr", "regex")]


def test_text_without_email() -> None:
    text = "Rendez-vous au point de vente, look at this, 10 @ 12 €."
    assert extract_emails_from_text(text) == []


def test_word_point_after_real_email_is_not_glued() -> None:
    assert emails_of(extract_emails_from_text("jean@site.fr point de contact")) == ["jean@site.fr"]


# --- formes obfusquées ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "jean [at] site [dot] fr",
        "jean(at)site.fr",
        "jean (at) site (dot) fr",
        "jean arobase site point fr",
        "JEAN {AT} SITE {DOT} FR",
        "jean [arobase] site [point] fr",
        "jean[@]site[.]fr",
        "jean <at> site <dot> fr",
    ],
)
def test_obfuscated_forms(text: str) -> None:
    assert extract_emails_from_text(text) == [ExtractedEmail("jean@site.fr", "obfuscated")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("nom arobase site point fr point de vente", "nom@site.fr"),
        ("contact arobase mairie point fr et la mairie", "contact@mairie.fr"),
        ("info arobase site dot com dot the end", "info@site.com"),
        ("nom arobase mairie point ville point fr", "nom@mairie.ville.fr"),
        ("kontakt [at] firma [dot] de", "kontakt@firma.de"),  # crochets : « de » accepté
    ],
)
def test_word_dot_followed_by_common_word(text: str, expected: str) -> None:
    assert emails_of(extract_emails_from_text(text)) == [expected]


def test_obfuscated_with_subdomain_and_dotted_local_part() -> None:
    text = "marie.durand [at] mairie [dot] ville [dot] fr"
    assert emails_of(extract_emails_from_text(text)) == ["marie.durand@mairie.ville.fr"]


# --- faux positifs -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "logo@2x.png",
        "icon@3x.webp",
        "bundle@1.2.3.js",
        "prenom.nom@example.com",
        "contact@domain.com",
        "noreply@site.fr",
        "no-reply@site.fr",
        "abc123@o42.ingest.sentry.io",
        "x@sentry-next.wixpress.com",
    ],
)
def test_false_positives_are_excluded(text: str) -> None:
    assert extract_emails_from_text(text) == []


def test_aberrant_lengths_are_excluded() -> None:
    assert is_excluded_email("a" * 65 + "@site.fr")
    assert is_excluded_email("a@" + "b" * 250 + ".fr")
    assert not is_excluded_email("a" * 64 + "@site.fr")


def test_invalid_dots_are_excluded() -> None:
    assert is_excluded_email(".jean@site.fr")
    assert is_excluded_email("jean.@site.fr")
    assert is_excluded_email("jean..dupont@site.fr")


def test_exclusion_lists_are_configurable() -> None:
    assert not is_excluded_email("noreply@site.fr", excluded_local_parts=set())
    assert is_excluded_email("contact@concurrent.fr", excluded_domains={"concurrent.fr"})


# --- nettoyage -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Contact@Site.FR. ", "contact@site.fr"),
        ("mailto:Info@Site.fr", "info@site.fr"),
        ("info&#64;site.fr", "info@site.fr"),
        ("(info@site.fr)", "info@site.fr"),
        ("pas-une-adresse", None),
        ("logo@2x.png", None),
    ],
)
def test_clean_email(raw: str, expected: str | None) -> None:
    assert clean_email(raw) == expected


# --- page complète -------------------------------------------------------------------


def test_full_contact_page() -> None:
    html = (FIXTURES / "contact_page.html").read_text(encoding="utf-8")
    assert extract_emails(html) == [
        ExtractedEmail("accueil@entreprise.fr", "mailto"),
        ExtractedEmail("contact@entreprise.fr", "mailto"),
        ExtractedEmail("support@entreprise.fr", "mailto"),
        ExtractedEmail("commercial@entreprise.fr", "regex"),
        ExtractedEmail("direction@entreprise.fr", "obfuscated"),
        ExtractedEmail("compta@entreprise.fr", "obfuscated"),
        ExtractedEmail("rh@entreprise.fr", "obfuscated"),
    ]
