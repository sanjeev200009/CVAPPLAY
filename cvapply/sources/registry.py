from __future__ import annotations

from ..config import settings
from .arbeitnow import ArbeitnowSource
from .ashby import AshbySource
from .base import JobSource
from .euremotejobs import EuroRemoteJobsSource
from .fourdayweek import FourDayWeekSource
from .getonboard import GetOnBoardSource
from .greenhouse import GreenhouseSource
from .himalayas import HimalayasSource
from .indeed_lk import IndeedLKSource
from .jobgether import JobgetherSource
from .jobicy import JobicySource
from .jobstreet_lk import JobStreetLKSource
from .landingjobs import LandingJobsSource
from .lever import LeverSource
from .linkedin_global import LinkedInGlobalSource
from .nodesk import NoDeskSource
from .pyjobs import PyJobsSource
from .remoteok import RemoteOKSource
from .remotive import RemotiveSource
from .startup_jobs import StartupJobsSource
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
from .wellfound import WellfoundSource
from .weworkremotely import WeWorkRemotelySource
from .ycjobs import YCJobsSource


def build_sources() -> list[JobSource]:
    return [
        # ── Sri Lanka local boards & Direct IT Company Hiring Emails (TOP PRIORITY) ──
        SriLankaDirectITCompanySource(),
        XpressJobsSource(),
        JobStreetLKSource(),         # NEW: JobStreet Sri Lanka
        ITProLKSource(),
        DevJobsLKSource(),
        TopJobsSource(),
        IkmanJobsSource(),
        DreamJobsLKSource(),
        JobseekerLKSource(),
        ITJobsLKSource(),
        LinkedInSriLankaSource(),
        IndeedLKSource(),            # NEW: Indeed Sri Lanka (JSON + Playwright fallback)

        # ── Global remote boards (API / RSS — fast & reliable) ──
        GreenhouseSource(settings.greenhouse_companies),
        LeverSource(settings.lever_companies),
        AshbySource(settings.ashby_companies),
        RemotiveSource(settings.remotive_categories),
        ArbeitnowSource(),
        HimalayasSource(),
        WeWorkRemotelySource(),
        JobicySource(),
        LandingJobsSource(),
        FourDayWeekSource(),
        RemoteOKSource(),

        # ── New global sources ──
        WellfoundSource(),           # NEW: Wellfound (ex-AngelList) startup jobs
        YCJobsSource(),              # NEW: Y Combinator Work at a Startup
        StartupJobsSource(),         # NEW: startup.jobs engineering RSS
        PyJobsSource(),              # NEW: pyjobs.com Python-specific
        GetOnBoardSource(),          # NEW: getonbrd.com Latin America + remote
        JobgetherSource(),           # NEW: jobgether.com remote-first
        NoDeskSource(),              # NEW: nodesk.co remote RSS
        EuroRemoteJobsSource(),      # NEW: euremotejobs.com RSS

        # ── Playwright-based global sources (last — slowest) ──
        LinkedInGlobalSource(),      # NEW: LinkedIn global remote search
    ]
