"""Tests for SERVICE_KEYWORDS, _WORD_BOUNDARY_KEYWORDS, and _NOTABLE_SUB_TYPES
coverage in slot_extractor.py.

Validates that all 17 keyword clusters from the service discovery audit
(April 2026) are correctly mapped, sub-type labels are set for confirmation
messages, word-boundary keywords don't false-positive on substrings, and
peer navigator sample queries extract correctly.

Run: pytest tests/unit/test_service_keywords.py -v
"""

import pytest
from app.services.slot_extractor import extract_slots


class TestHIVHarmReduction:
    """188 services — previously only reachable via 'hiv testing'."""

    def test_harm_reduction(self):
        r = extract_slots("I need harm reduction services")
        assert r["service_type"] == "medical"
        assert r["service_detail"] == "harm reduction services"

    def test_needle_exchange(self):
        r = extract_slots("where can I get a needle exchange")
        assert r["service_type"] == "medical"

    def test_syringe_exchange(self):
        r = extract_slots("I need a syringe exchange")
        assert r["service_type"] == "medical"

    def test_hepatitis(self):
        r = extract_slots("I have hepatitis")
        assert r["service_type"] == "medical"

    def test_hep_c(self):
        r = extract_slots("I need help with hep c")
        assert r["service_type"] == "medical"

    def test_hiv_word_boundary(self):
        r = extract_slots("I need HIV services")
        assert r["service_type"] == "medical"

    def test_prep_word_boundary(self):
        r = extract_slots("I need PrEP")
        assert r["service_type"] == "medical"

    def test_prep_not_prepare(self):
        """'prep' should NOT match inside 'prepare'."""
        r = extract_slots("I need to prepare for tomorrow")
        assert r["service_type"] is None

    def test_hiv_not_shiver(self):
        """'hiv' should NOT match inside 'shiver'."""
        r = extract_slots("I shiver in the cold")
        assert r["service_type"] is None


class TestSubstanceTreatment:
    """6 services with exact taxonomy name 'Substance Use Treatment'."""

    def test_substance_use_treatment(self):
        r = extract_slots("I need substance use treatment")
        assert r["service_type"] == "mental_health"
        assert r["service_detail"] == "substance use treatment"

    def test_treatment_program(self):
        r = extract_slots("I need a treatment program")
        assert r["service_type"] == "mental_health"

    def test_inpatient(self):
        r = extract_slots("I need inpatient treatment")
        assert r["service_type"] == "mental_health"

    def test_outpatient(self):
        r = extract_slots("I need outpatient treatment")
        assert r["service_type"] == "mental_health"

    def test_sober_living(self):
        r = extract_slots("I need sober living")
        assert r["service_type"] == "mental_health"

    def test_halfway_house(self):
        r = extract_slots("looking for a halfway house")
        assert r["service_type"] == "mental_health"

    def test_anger_management(self):
        r = extract_slots("I need anger management")
        assert r["service_type"] == "mental_health"
        assert r["service_detail"] == "anger management"


class TestDVServices:
    """59 services — previously only reachable via crisis handler."""

    def test_domestic_violence_help(self):
        r = extract_slots("I need domestic violence help")
        assert r["service_type"] == "legal"
        assert r["service_detail"] == "domestic violence services"

    def test_dv_services(self):
        r = extract_slots("I need dv services")
        assert r["service_type"] == "legal"

    def test_abuse_counseling(self):
        r = extract_slots("I need abuse counseling")
        assert r["service_type"] == "legal"

    def test_order_of_protection(self):
        r = extract_slots("I need an order of protection")
        assert r["service_type"] == "legal"


class TestImmigrationAdvanced:
    """66 services beyond basic 'immigration' and 'asylum'."""

    def test_citizenship(self):
        r = extract_slots("I need help with citizenship")
        assert r["service_type"] == "legal"
        assert r["service_detail"] == "citizenship services"

    def test_naturalization(self):
        r = extract_slots("help with naturalization")
        assert r["service_type"] == "legal"

    def test_daca(self):
        r = extract_slots("help with DACA renewal")
        assert r["service_type"] == "legal"
        assert r["service_detail"] == "DACA services"

    def test_tps(self):
        r = extract_slots("I need TPS help")
        assert r["service_type"] == "legal"

    def test_work_authorization(self):
        r = extract_slots("I need work authorization")
        assert r["service_type"] == "legal"


class TestFinancial:
    """32 services — sample query 'I am so bad with money' had 0% coverage."""

    def test_financial_help(self):
        r = extract_slots("I need financial help")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "financial services"

    def test_bad_with_money(self):
        """The original sample query that failed."""
        r = extract_slots("I am so bad with money")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "financial services"

    def test_budgeting(self):
        r = extract_slots("I need help with budgeting")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "budgeting help"

    def test_financial_literacy(self):
        r = extract_slots("I need financial literacy")
        assert r["service_type"] == "other"

    def test_credit_counseling(self):
        r = extract_slots("I need credit counseling")
        assert r["service_type"] == "other"

    def test_money_management(self):
        r = extract_slots("I need money management")
        assert r["service_type"] == "other"


class TestEducation:
    """131 services — ESL, GED, computer classes."""

    def test_english_classes(self):
        r = extract_slots("I need English classes")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "English classes"

    def test_learn_english(self):
        r = extract_slots("I want to learn english")
        assert r["service_type"] == "other"

    def test_adult_education(self):
        r = extract_slots("I need adult education")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "adult education"

    def test_computer_class(self):
        r = extract_slots("I need a computer class")
        assert r["service_type"] == "other"

    def test_digital_literacy(self):
        r = extract_slots("I need digital literacy")
        assert r["service_type"] == "other"

    def test_esl_word_boundary(self):
        r = extract_slots("I need ESL")
        assert r["service_type"] == "other"

    def test_esl_not_diesel(self):
        """'esl' should NOT match inside 'diesel'."""
        r = extract_slots("the diesel engine broke")
        assert r["service_type"] is None

    def test_ged_word_boundary(self):
        r = extract_slots("I need my GED")
        assert r["service_type"] == "other"

    def test_ged_not_managed(self):
        """'ged' should NOT match inside 'managed'."""
        r = extract_slots("I managed to get here")
        assert r["service_type"] is None

    def test_high_school_equivalency(self):
        r = extract_slots("I need my high school equivalency")
        assert r["service_type"] == "other"


class TestHousingAssistance:
    """112 services — distinct from shelter (beds vs rent programs)."""

    def test_rental_assistance(self):
        r = extract_slots("I need rental assistance")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "rental assistance"

    def test_behind_on_rent(self):
        r = extract_slots("I'm behind on rent")
        assert r["service_type"] == "other"

    def test_housing_voucher(self):
        r = extract_slots("I need a housing voucher")
        assert r["service_type"] == "other"

    def test_eviction_prevention(self):
        r = extract_slots("I need eviction prevention")
        assert r["service_type"] == "other"

    def test_housing_vs_shelter(self):
        """'housing' alone → shelter (urgent). 'housing assistance' → other (program)."""
        r_housing = extract_slots("I need housing")
        r_assist = extract_slots("I need housing assistance")
        assert r_housing["service_type"] == "shelter"
        assert r_assist["service_type"] == "other"


class TestSenior:
    """23 services."""

    def test_senior_center(self):
        r = extract_slots("I need a senior center")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "senior services"

    def test_older_adult(self):
        r = extract_slots("services for older adults")
        assert r["service_type"] == "other"

    def test_aging_services(self):
        r = extract_slots("I need aging services")
        assert r["service_type"] == "other"


class TestReentry:
    """40 services."""

    def test_released_from_jail(self):
        r = extract_slots("I was released from jail")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "re-entry services"

    def test_reentry(self):
        r = extract_slots("I need reentry services")
        assert r["service_type"] == "other"

    def test_parole_word_boundary(self):
        r = extract_slots("I'm on parole")
        assert r["service_type"] == "other"

    def test_probation_word_boundary(self):
        r = extract_slots("I'm on probation")
        assert r["service_type"] == "other"


class TestPregnancy:
    """41 services — previously only detected as family_status."""

    def test_prenatal_care(self):
        r = extract_slots("I need prenatal care")
        assert r["service_type"] == "medical"
        assert r["service_detail"] == "prenatal care"

    def test_maternity(self):
        r = extract_slots("I need maternity services")
        assert r["service_type"] == "medical"

    def test_postpartum(self):
        r = extract_slots("I need postpartum care")
        assert r["service_type"] == "medical"


class TestTradeCareer:
    """15 services."""

    def test_hvac_training(self):
        r = extract_slots("I need HVAC training")
        assert r["service_type"] == "employment"

    def test_vocational_training(self):
        r = extract_slots("I want vocational training")
        assert r["service_type"] == "employment"

    def test_workforce_development(self):
        r = extract_slots("I need workforce development")
        assert r["service_type"] == "employment"

    def test_syep_word_boundary(self):
        r = extract_slots("how do I sign up for SYEP")
        assert r["service_type"] == "employment"


class TestVernacular:
    """Phrases real users say that previously returned nothing."""

    def test_place_to_crash(self):
        r = extract_slots("I need a place to crash")
        assert r["service_type"] == "shelter"

    def test_got_put_out(self):
        r = extract_slots("I got put out")
        assert r["service_type"] == "shelter"

    def test_somewhere_warm(self):
        r = extract_slots("I need somewhere warm")
        assert r["service_type"] == "shelter"

    def test_starving(self):
        r = extract_slots("I'm starving")
        assert r["service_type"] == "food"

    def test_couch_surfing(self):
        r = extract_slots("I've been couch surfing")
        assert r["service_type"] == "shelter"

    def test_sleeping_in_car(self):
        r = extract_slots("I'm sleeping in my car")
        assert r["service_type"] == "shelter"


class TestReclassifications:
    """Items moved between categories."""

    def test_diapers_now_other(self):
        """Diapers moved from food → other (baby supplies)."""
        r = extract_slots("I need diapers")
        assert r["service_type"] == "other"
        assert r["service_detail"] == "baby supplies"

    def test_baby_supplies(self):
        r = extract_slots("I need baby supplies")
        assert r["service_type"] == "other"

    def test_baby_formula_still_food(self):
        """Baby formula stays in food (it IS food)."""
        r = extract_slots("I need baby formula")
        assert r["service_type"] == "food"


class TestFalsePositives:
    """Ensure word-boundary keywords don't match substrings."""

    def test_ssi_not_mission(self):
        r = extract_slots("I'm on a mission")
        assert r["service_type"] is None

    def test_prep_not_prepare(self):
        """'prep' should NOT match inside 'prepare'."""
        r = extract_slots("I want to prepare my documents")
        assert r["service_type"] is None

    def test_ged_not_changed(self):
        r = extract_slots("things have changed")
        assert r["service_type"] is None

    def test_esl_not_weasel(self):
        r = extract_slots("that weasel stole my stuff")
        assert r["service_type"] is None

    def test_hiv_not_archive(self):
        r = extract_slots("check the archive")
        assert r["service_type"] is None


class TestPeerNavigatorSampleQueries:
    """All sample queries from the Cornell team document."""

    def test_lgbtq_youth_shelter(self):
        r = extract_slots("21, LGBTQ, in Soho, need a bed tonight")
        assert r["service_type"] == "shelter"
        assert r["location"] == "soho"
        assert r["age"] == 21
        assert r["_gender"] == "lgbtq"

    def test_immigration_manhattan(self):
        r = extract_slots("Recently arrived in the US, need immigration help in Manhattan")
        assert r["service_type"] == "legal"
        assert r["service_detail"] == "immigration services"
        assert r["location"] == "manhattan"

    def test_transman_clothing(self):
        r = extract_slots("I cannot afford clothes on Amazon. I am a transman")
        assert r["service_type"] == "clothing"
        assert r["_gender"] == "male"

    def test_bad_with_money(self):
        r = extract_slots("I am so bad with money.")
        assert r["service_type"] == "other"

    def test_detox_manhattan(self):
        r = extract_slots("I need to detox from Alcohol and Opiates. Where can I go in Manhattan?")
        assert r["service_type"] == "mental_health"
        assert r["location"] == "manhattan"

    def test_dv_with_toddler(self):
        r = extract_slots("19, with a toddler, fleeing domestic violence, need somewhere safe tonight")
        assert r["service_type"] == "shelter"
        assert r["age"] == 19
        assert r["family_status"] == "with_children"
        assert r["urgency"] == "high"


# ---------------------------------------------------------------------------
# YourPeer alignment — template and query verification
# ---------------------------------------------------------------------------

class TestYourPeerAlignment:
    """Verify fixes from the YourPeer web app comparison audit.

    These tests ensure the chatbot's query layer matches YourPeer's
    search behavior for taxonomy coverage and schedule data source.
    """

    def test_legal_template_includes_advocates(self):
        """Phase 0b: 'Advocates / Legal Aid' must be in legal taxonomy_names.
        YourPeer includes this in TAXONOMY_CATEGORIES but the chatbot
        was missing it — legal searches skipped an entire taxonomy."""
        from app.rag.query_templates import TEMPLATES
        legal_taxonomies = TEMPLATES["legal"]["default_params"]["taxonomy_names"]
        assert "advocates / legal aid" in legal_taxonomies

    def test_legal_template_includes_immigration(self):
        from app.rag.query_templates import TEMPLATES
        legal_taxonomies = TEMPLATES["legal"]["default_params"]["taxonomy_names"]
        assert "immigration services" in legal_taxonomies

    def test_legal_query_sql_includes_advocates(self):
        """Verify the generated SQL actually queries the taxonomy."""
        from app.rag.query_templates import build_query
        _, params = build_query("legal", {"borough": "Manhattan"})
        assert "advocates / legal aid" in params["taxonomy_names"]

    def test_schedule_uses_holiday_schedules(self):
        """Phase 0a: chatbot must read holiday_schedules (10,593 rows,
        current hours) not regular_schedules (1,049 rows, stale).
        YourPeer uses HolidaySchedules for all schedule display."""
        from app.rag.query_templates import build_query
        sql, _ = build_query("food", {"borough": "Manhattan"})
        assert "JOIN holiday_schedules" in sql
        assert "JOIN regular_schedules" not in sql

    def test_schedule_uses_covid19_occasion(self):
        """All current schedule data has occasion='COVID19'."""
        from app.rag.query_templates import build_query
        sql, _ = build_query("food", {"borough": "Manhattan"})
        assert "occasion = 'COVID19'" in sql

    def test_schedule_weekday_isodow(self):
        """holiday_schedules uses 1-7 (ISODOW), not 0-6.
        The join must NOT subtract 1 from ISODOW."""
        from app.rag.query_templates import build_query
        sql, _ = build_query("food", {"borough": "Manhattan"})
        # Should have ISODOW without "- 1"
        assert "ISODOW FROM CURRENT_DATE)::int\n" in sql or \
               "ISODOW FROM CURRENT_DATE)::int " in sql
        assert "ISODOW FROM CURRENT_DATE)::int - 1" not in sql
