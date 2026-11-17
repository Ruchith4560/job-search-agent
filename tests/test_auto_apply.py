"""Tests for the Auto-Apply Module (agent.apply.auto_apply)."""

import sqlite3
import pytest
from agent.apply.auto_apply import (
    CGPA,
    DEFAULTS,
    norm,
    parse_answers,
    pick_option,
    resolve,
    slug,
)


def test_fixed_facts_cgpa():
    """Verify single source of truth for CGPA is strictly 9.05."""
    assert CGPA == "9.05"
    assert DEFAULTS["cgpa"] == "9.05"
    assert DEFAULTS["college"] == "Anurag University"
    assert DEFAULTS["grad_year"] == "2028"


def test_parse_answers_standard():
    body = """
    Hi Agent,
    Here are the details:
    Q1: Yes, I am legally authorized to work in India.
    Q2: No visa sponsorship needed.
    Q3: 15 days notice period.
    """
    ans = parse_answers(body)
    assert ans[1] == "Yes, I am legally authorized to work in India."
    assert ans[2] == "No visa sponsorship needed."
    assert ans[3] == "15 days notice period."


def test_parse_answers_various_delimiters():
    body = "Q1 - Immediate\nQ2. Anurag University\nQ3) Hyderabad"
    ans = parse_answers(body)
    assert ans[1] == "Immediate"
    assert ans[2] == "Anurag University"
    assert ans[3] == "Hyderabad"


def test_pick_option_exact_and_fuzzy():
    labels = ["Male", "Female", "Prefer not to disclose", "Other"]
    # Sensitive decline token
    assert pick_option("__DECLINE__", labels) == "Prefer not to disclose"

    # Exact and case-insensitive
    degrees = ["B.Tech", "M.Tech", "PhD", "High School"]
    assert pick_option("b.tech", degrees) == "B.Tech"

    # Yes / No
    yes_no = ["Yes, absolutely", "No, definitely not"]
    assert pick_option("yes", yes_no) == "Yes, absolutely"
    assert pick_option("no", yes_no) == "No, definitely not"


def test_resolve_rules():
    profile = {
        "first_name": "Macha",
        "last_name": "Ruchith",
        "full_name": "Macha Ruchith",
        "email": "macharuchith1@gmail.com",
        "cgpa": "9.05",
        "college": "Anurag University",
        "grad_year": "2028",
    }
    answers = {
        "what is your notice period": "Immediate",
    }

    # Custom answer takes priority
    f_notice = {"label": "What is your notice period?", "kind": "text", "options": []}
    assert resolve(f_notice, profile, answers) == "Immediate"

    # Built-in profile rules
    f_cgpa = {"label": "Cumulative GPA / CGPA *", "kind": "text", "options": []}
    assert resolve(f_cgpa, profile, answers) == "9.05"

    f_first = {"label": "First Name *", "kind": "text", "options": []}
    assert resolve(f_first, profile, answers) == "Macha"

    # Sensitive demographic field -> declines
    f_gender = {"label": "Gender Identity", "kind": "select", "options": []}
    assert resolve(f_gender, profile, answers) == "__DECLINE__"

    # Consent checkbox -> yes
    f_consent = {"label": "I agree to the privacy policy and terms", "kind": "checkbox", "options": []}
    assert resolve(f_consent, profile, answers) == "yes"


def test_slug_generation():
    job = {"company": "Google LLC", "role": "Software Engineer, Intern 2026"}
    s = slug(job)
    assert "google_llc" in s
    assert "software_engineer" in s
