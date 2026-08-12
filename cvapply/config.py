from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

GREENHOUSE_COMPANIES: list[str] = [
    "airbnb", "dropbox", "monzo", "wise", "gitlab", "zapier",
    "stripe", "gusto", "instacart", "box", "datadog", "digitalocean", "ramp",
    "vanta", "okta", "reddit", "pinterest", "airtable", "brex", "twilio",
    "coinbase", "hashicorp", "mongodb", "hubspot", "deliveroo", "lyft",
    "vercel", "dbtlabs", "grafanalabs", "elastic",
    "anthropic", "canonical", "postman", "webflow", "automattic",
    "temporal", "sourcegraph", "cockroachlabs", "launchdarkly",
    "pulumi", "chainguard", "snyk", "kong", "circleci", "huggingface", "prisma",
]

LEVER_COMPANIES: list[str] = [
    "quantcast", "ancestry", "casper", "postmates", "shippo",
    "recurly", "gopuff", "spotify", "squarespace",
    "gong", "homeaway", "vroom", "browserstack", "cohere",
]

ASHBY_COMPANIES: list[str] = [
    "linear", "supabase", "posthog", "vercel", "notion", "sentry",
    "render", "1password", "clickup", "ashby", "resend", "mux",
    "cursor", "baseten", "workos", "deepgram", "replit", "elevenlabs",
    "firecrawl", "mural", "mistral", "anthropic", "scale", "together",
]


REMOTIVE_CATEGORIES: list[str] = [
    "software development", "devops / sysadmin", "data", "product",
    "qa", "security",
]


@dataclass(frozen=True)
class Settings:
    convex_deploy_url: str = os.getenv("CONVEX_DEPLOY_URL", "")
    convex_deploy_key: str = os.getenv("CONVEX_DEPLOY_KEY", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

    match_threshold: int = int(os.getenv("MATCH_THRESHOLD", "55"))
    daily_app_cap: int = int(os.getenv("DAILY_APP_CAP", "250"))
    min_delay_seconds: int = int(os.getenv("MIN_DELAY", "3"))
    max_delay_seconds: int = int(os.getenv("MAX_DELAY", "8"))
    max_experience_years: int = 1
    only_sri_lanka: bool = os.getenv("ONLY_SRI_LANKA", "1") == "1"



    scoring_model: str = "google/gemini-2.5-flash"
    cover_letter_model: str = "openai/gpt-4o-mini"
    nvidia_api_key: str = os.getenv("NVIDIA_API_KEY", "")
    nvidia_model: str = os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")


    cv_pdf_path: str = os.getenv("CV_PDF_PATH", r"C:\Users\user\Downloads\sanjeevcv.pdf (6) (1).pdf")
    cv_version_label: str = "v2"

    # Candidate contact details (used to fill application forms)
    candidate_first_name: str = "Sivasuthakaran"
    candidate_last_name: str = "Sanjeev"
    candidate_email: str = "sanjaysanjeev2000@gmail.com"
    candidate_phone: str = os.getenv("CANDIDATE_PHONE", "0753883167")
    candidate_phone_alt: str = os.getenv("CANDIDATE_PHONE_ALT", "0722858346")
    candidate_linkedin: str = os.getenv("CANDIDATE_LINKEDIN", "")
    candidate_website: str = os.getenv(
        "CANDIDATE_WEBSITE",
        "https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/",
    )
    candidate_github: str = os.getenv("CANDIDATE_GITHUB", "https://github.com/sanjeev200009")
    candidate_city: str = "Colombo, Sri Lanka"
    candidate_notice_period: str = os.getenv("CANDIDATE_NOTICE_PERIOD", "2 weeks")
    candidate_current_salary: str = os.getenv("CANDIDATE_CURRENT_SALARY", "55,000 LKR")
    candidate_expected_salary: str = os.getenv("CANDIDATE_EXPECTED_SALARY", "60,000 - 70,000 LKR")
    candidate_expected_salary_num: str = os.getenv("CANDIDATE_EXPECTED_SALARY_NUM", "65000")
    candidate_expected_salary_usd: str = os.getenv("CANDIDATE_EXPECTED_SALARY_USD", "$35,000 - $45,000 USD / year")
    candidate_start_date: str = os.getenv("CANDIDATE_START_DATE", "Immediately / 2 weeks")


    # Email-based applications (Gmail SMTP with App Password)
    email_enabled: bool = os.getenv("EMAIL_APPLY_ENABLED", "0") == "1"
    email_smtp_host: str = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    email_smtp_port: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    email_user: str = os.getenv("EMAIL_USER", "sanjaysanjeev2000@gmail.com")
    email_app_password: str = os.getenv("EMAIL_APP_PASSWORD", "")

    cv_file_path: str = os.getenv("CV_FILE_PATH", cv_pdf_path)
    cv_file_name: str = os.getenv("CV_FILE_NAME", "Sanjeev_CV.pdf")
    screenshots_dir: str = os.path.join(os.path.dirname(__file__), "..", "screenshots")

    greenhouse_companies: list[str] = field(default_factory=lambda: GREENHOUSE_COMPANIES)
    lever_companies: list[str] = field(default_factory=lambda: LEVER_COMPANIES)
    ashby_companies: list[str] = field(default_factory=lambda: ASHBY_COMPANIES)
    remotive_categories: list[str] = field(default_factory=lambda: REMOTIVE_CATEGORIES)


settings = Settings()
