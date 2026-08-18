from __future__ import annotations

from ..config import settings
from .arbeitnow import ArbeitnowSource
from .ashby import AshbySource
from .base import JobSource
from .greenhouse import GreenhouseSource
from .himalayas import HimalayasSource
from .lever import LeverSource
from .remotive import RemotiveSource
from .srilanka import (
    DevJobsLKSource,
    DreamJobsLKSource,
    ITJobsLKSource,
    ITProLKSource,
    IkmanJobsSource,
    JobseekerLKSource,
    LinkedInSriLankaSource,
    SriLankaDirectITCompanySource,
    TopJobsSource,
    XpressJobsSource,
)
from .weworkremotely import WeWorkRemotelySource


def build_sources() -> list[JobSource]:
    return [
        # ── Sri Lanka local boards & Direct IT Company Hiring Emails (TOP PRIORITY) ──
        SriLankaDirectITCompanySource(),
        XpressJobsSource(),
        ITProLKSource(),
        DevJobsLKSource(),
        TopJobsSource(),
        IkmanJobsSource(),
        DreamJobsLKSource(),
        JobseekerLKSource(),
        ITJobsLKSource(),
        LinkedInSriLankaSource(),

        # ── Global remote boards ──
        GreenhouseSource(settings.greenhouse_companies),
        LeverSource(settings.lever_companies),
        AshbySource(settings.ashby_companies),
        RemotiveSource(settings.remotive_categories),
        ArbeitnowSource(),
        HimalayasSource(),
        WeWorkRemotelySource(),
    ]
