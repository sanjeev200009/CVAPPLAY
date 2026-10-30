from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .config import settings

API_URL = "https://openrouter.ai/api/v1/chat/completions"

SCORE_SYSTEM = """You are a strict technical hiring screener evaluating an early-career software engineer.

Candidate Profile:
- Name: Sivasuthakaran Sanjeev (Colombo, Sri Lanka — open to remote worldwide)
- Experience: UNDER 1 YEAR (~0-1 year total, recent promotion from intern to Associate Product & AI Engineer)
- Core Stack: Python, FastAPI, Node.js, JavaScript, TypeScript, React.js, Next.js 15, REST APIs, PostgreSQL, Git, Docker, Linux, AWS, Cloudflare, Supabase, Convex, WebSockets, LLM integrations
- Frameworks: FastAPI, Flask, Express.js, React, Next.js, Tailwind CSS, Framer Motion
- Education: BIT (Hons) Networking & Mobile Computing — Horizon Campus, Sri Lanka
- Notable achievements: Built 13-stage autonomous AI recruitment pipeline (115k+ profiles), rebuilt production Next.js 15 site, cut email costs 78%, WhatsApp Business API automation
- Location: Colombo, Sri Lanka (available for fully remote roles worldwide and on-site Sri Lanka roles)
- Salary expectation: 60,000–70,000 LKR/month (Sri Lanka) or $35,000–$45,000 USD/year (remote)

SCORING DIMENSIONS — evaluate all 8:
1. TECH STACK MATCH: Do the required technologies match candidate's core stack? Python/JS/TS/React/Node/PostgreSQL = strong match.
2. FRAMEWORK MATCH: Are the specific frameworks required (FastAPI, Next.js, React, Express) in candidate's skill set?
3. SENIORITY MATCH: Is this a junior/associate/graduate/intern/entry-level role? Senior/Lead/Staff/Principal = hard fail.
4. EXPERIENCE GATE: Does the JD require 2+ years? If yes, score < 30 regardless of tech match.
5. REMOTE/LOCATION: Is this remote or Sri Lanka based? Region-locked to Europe/US-only = penalise heavily.
6. SALARY ALIGNMENT: Does stated salary align with expectations? No salary mentioned = neutral.
7. EMPLOYMENT TYPE: Full-time preferred. Contract/freelance/part-time = slight penalty unless explicitly good match.
8. EDUCATION MATCH: Does the required degree/field match candidate's BIT in Networking & Mobile Computing?

STRICT RULES:
1. EXPERIENCE HARD CEILING: JD requires 2+, 3+, 4+, 5+ years OR is Mid/Senior/Staff/Lead/Principal → score < 30, recommended: false.
2. TIER A (score 75–100): True entry-level, junior, associate, graduate, intern roles that directly match candidate's stack. Auto-apply.
3. TIER B (score 50–74): Reasonable match with 1-2 minor gaps candidate could overcome. Apply with caution.
4. TIER C (score 0–49): Poor fit — wrong seniority, wrong stack, too much experience required, region-locked. Do not apply.
5. Extract salary/compensation from JD exactly as written, or "Not specified".
6. Summarise what the role does in 1-2 plain sentences.
7. If you detect a HARD GAP (e.g. mandatory certification, security clearance, specific degree not held, 2+ years required), note it in the reason field starting with "HARD GAP:".

Output JSON ONLY — no prose, no markdown, no explanation:
{
  "score": <int 0-100>,
  "match_tier": "<A|B|C>",
  "recommended": <bool>,
  "reason": "<1-line reason, start with HARD GAP: if applicable>",
  "experience_requirement_years": <int or 0>,
  "salary": "<extracted salary or 'Not specified'>",
  "summary": "<1-2 sentence plain-language role description>"
}"""


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key or ""
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


    def _call_nvidia_nim(self, system: str, user: str, max_tokens: int = 700) -> str | None:
        if not settings.nvidia_api_key:
            return None
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.nvidia_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": settings.nvidia_model or "meta/llama-3.2-11b-vision-instruct",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        for attempt in range(3):
            try:
                print(f"  [llm] Calling NVIDIA NIM ({settings.nvidia_model})...")
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                if resp.status_code in (404, 410):
                    print(f"  [llm] NVIDIA NIM model '{settings.nvidia_model}' returned HTTP {resp.status_code} (Model unavailable or deprecated).")
                    break
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    print(f"  [llm] NVIDIA NIM 429 rate limit — backing off {wait}s (attempt {attempt + 1}/3)")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"] or ""
                # Clean thinking process preamble by finding the LAST occurrence of "Dear " for email bodies
                dear_idx = content.rfind("Dear ")
                if dear_idx != -1:
                    content = content[dear_idx:].strip()
                elif "{" in content and "}" in content:
                    m = re.search(r"\{.*\}", content, re.DOTALL)
                    if m:
                        content = m.group(0)

                # Clean trailing self-reflection text if output by reasoning models
                gh_match = re.search(r'(https://github\.com/[^\s\n]+)', content)
                if gh_match:
                    content = content[:gh_match.end()].strip()

                return content

            except Exception as exc:
                print(f"  [llm] NVIDIA NIM attempt {attempt + 1}/3 warning: {exc}")
                time.sleep(2 * (attempt + 1))

        return None



    def _call_openrouter(self, model: str, system: str, user: str, max_tokens: int = 700, json_mode: bool = True) -> str | None:
        """OpenRouter fallback — used when NVIDIA NIM is unavailable."""
        if not self.api_key:
            return None
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            print(f"  [llm] Calling OpenRouter fallback ({model})...")
            resp = requests.post(
                API_URL,
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if "choices" not in data:
                # OpenRouter returns HTTP 200 with an error body for upstream 429s
                print(f"  [llm] OpenRouter {model}: {str(data.get('error'))[:160]}")
                return None
            content = data["choices"][0]["message"]["content"] or ""
            return content.strip()
        except Exception as exc:
            print(f"  [llm] OpenRouter fallback warning: {exc}")
            return None

    def chat(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 700,
        json_mode: bool = True,
    ) -> str:
        # ── PRIMARY: NVIDIA NIM ──
        nvidia_res = self._call_nvidia_nim(system, user, max_tokens)
        if nvidia_res:
            return nvidia_res

        # ── FALLBACK: OpenRouter ──
        # Try the requested model first, then the configured fallback. The free
        # pool rate-limits per-model, so a second model is the usual rescue.
        for or_model in dict.fromkeys([model, settings.openrouter_fallback_model]):
            if not or_model:
                continue
            or_res = self._call_openrouter(or_model, system, user, max_tokens, json_mode)
            if or_res:
                return or_res

        raise RuntimeError("Both NVIDIA NIM and OpenRouter are unavailable — check API keys and rate limits")




    def parse_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Reasoning models emit thinking prose first, so scan from each "{"
            # and keep the last one that decodes. Plain regex grabs braces from
            # the prose and fails.
            best = None
            for i, ch in enumerate(text):
                if ch != "{":
                    continue
                try:
                    best = json.JSONDecoder().raw_decode(text, i)[0]
                except ValueError:
                    continue
            if isinstance(best, dict):
                return best
            raise

    def score_job(self, job_title: str, job_desc: str, cv_text: str) -> dict[str, Any]:
        user = (
            "JOB TITLE:\n"
            f"{job_title}\n\n"
            "JOB DESCRIPTION (truncated):\n"
            f"{job_desc[:3000]}\n\n"
            "CANDIDATE CV:\n"
            f"{cv_text[:2500]}"
        )
        text = self.chat(settings.scoring_model, SCORE_SYSTEM, user, max_tokens=3000, json_mode=False)
        data = self.parse_json(text)
        sal = str(data.get("salary", "")).strip()
        if not sal or sal.lower() in ("not specified", "none", "null"):
            from .filters import extract_salary
            sal = extract_salary(job_desc)

        score = int(data.get("score", 0))
        # Derive tier from score if LLM didn't return it
        raw_tier = str(data.get("match_tier", "")).upper().strip()
        if raw_tier not in ("A", "B", "C"):
            if score >= 75:
                raw_tier = "A"
            elif score >= 50:
                raw_tier = "B"
            else:
                raw_tier = "C"

        return {
            "score": score,
            "match_tier": raw_tier,
            "recommended": bool(data.get("recommended", False)),
            "reason": str(data.get("reason", ""))[:200],
            "experience_requirement_years": data.get("experience_requirement_years"),
            "salary": sal or "Not specified",
            "summary": str(data.get("summary", ""))[:400],
        }



    def generate_cover_letter(
        self, company: str, job_title: str, job_desc: str, cv_text: str
    ) -> str:
        try:
            system = (
                "Write a 150-200 word tailored cover letter for a job application. "
                "The candidate is a junior software developer from Sri Lanka applying "
                "for a remote role. Use the real facts from the CV only - never invent "
                "skills, companies, or projects. Mention 2-3 of the candidate's genuine "
                "skills that match the job. Tone: professional, concise, enthusiastic. "
                "Write the letter body only, no subject line, no salutation, no sign-off."
            )
            user = (
                f"COMPANY: {company}\n"
                f"JOB TITLE: {job_title}\n\n"
                f"JOB DESCRIPTION (truncated):\n{job_desc[:2500]}\n\n"
                f"CANDIDATE CV:\n{cv_text[:2500]}"
            )
            return self.chat(
                settings.cover_letter_model, system, user, max_tokens=500, json_mode=False
            ).strip()
        except Exception as exc:
            print(f"  ⚠️ LLM call fallback for cover letter: {exc}")
            return (
                f"Dear Hiring Team at {company},\n\n"
                f"I am writing to express my enthusiastic interest in the {job_title} position. "
                f"As a Junior Software Engineer with hands-on experience in Python, React, JavaScript, "
                f"Node.js, and REST APIs, I am eager to apply my technical background to your engineering projects. "
                f"I bring strong problem-solving skills, experience with PostgreSQL and Git, and a passion for building "
                f"clean, reliable software solutions. My resume is attached for your review."
            )

    def generate_email_application(
        self,
        company: str,
        job_title: str,
        job_desc: str,
        cv_text: str,
        match_reason: str = "Matching candidate technical skills",
    ) -> dict[str, str]:
        """Generates a highly personalized, professional application email."""
        subject = f"Application for {job_title} — {settings.candidate_first_name} {settings.candidate_last_name}"
        fallback_body = f"""Dear Hiring Manager at {company},

I am writing to express my enthusiastic interest in the {job_title} position at {company}. As a Junior Software Engineer with practical experience building modern web applications and AI workflows, I am eager to contribute to {company}'s engineering projects.

My technical background directly aligns with your requirements:
- Full-Stack Web Development: Hands-on experience building scalable applications using Python (FastAPI/Flask), React.js, Next.js, and TypeScript.
- Backend & REST APIs: Skilled in designing clean RESTful APIs, WebSockets integration, and database management with PostgreSQL and SQL.
- Engineering Fundamentals: Proficient with Git version control, Docker containers, and Linux environments.

My complete resume is attached to this email. You can also view my live portfolio at https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/ and GitHub at https://github.com/sanjeev200009.

Thank you for your time and consideration. I look forward to discussing how my technical background aligns with {company}'s goals.

Sincerely,
{settings.candidate_first_name} {settings.candidate_last_name}
Email: {settings.email_user}
Phone: +94 753 883 167
Portfolio: https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/
GitHub: https://github.com/sanjeev200009
Location: Colombo, Sri Lanka"""

        # Determine job focus category for dynamic tailored pitch
        combined_desc = f"{job_title} {job_desc}".lower()
        if any(x in combined_desc for x in ("ai", "llm", "agent", "machine learning", "nlp", "automation", "generative", "product engineer")):
            category_focus = "AI_PRODUCT"
            focus_instruction = "SPECIALIZED FOCUS: AI / LLM / Product Engineering. Lead with your autonomous 13-stage AI recruitment pipeline (processing 115,000+ candidate profiles with 8 agents), Python FastAPI, and LLM workflow integrations."
        elif any(x in combined_desc for x in ("frontend", "react", "next.js", "nextjs", "ui", "ux", "tailwind", "typescript", "framer", "shadcn")):
            category_focus = "FRONTEND"
            focus_instruction = "SPECIALIZED FOCUS: Frontend / UI Development. Lead with your complete rebuild of the Career141 production Next.js 15 website from scratch using React.js, TypeScript, Tailwind CSS, and Framer Motion."
        elif any(x in combined_desc for x in ("backend", "node", "express", "api", "rest", "sql", "postgresql", "database", "cloud", "aws", "cloudflare", "microservice", "docker")):
            category_focus = "BACKEND_DEV"
            focus_instruction = "SPECIALIZED FOCUS: Backend & Cloud Engineering. Lead with your custom email delivery platform that cut costs by 78%, RESTful API microservices, PostgreSQL database design, Docker, and AWS/Cloudflare serverless infrastructure."
        else:
            category_focus = "GENERAL_SOFTWARE"
            focus_instruction = "SPECIALIZED FOCUS: General Software / Full-Stack Engineering. Provide a balanced pitch highlighting full-stack web development (Next.js 15, React, Python FastAPI) and production AI automation achievements."

        try:
            system = f"""You are a professional job application email writer. Write a compelling, 
personalized job application email body (2 to 3 paragraphs, 150-200 words) from a junior software developer to a recruiter.

{focus_instruction}

CANDIDATE PROFILE:
- Full Name: Sivasuthakaran Sanjeev
- Current Role: Associate Product & AI Engineer at Career141 (Global Executive Search Platform, Colombo, Sri Lanka)
- Location: Colombo, Sri Lanka (available for fully remote roles worldwide)
- Email: sanjaysanjeev2000@gmail.com
- Phone: +94 753 883 167
- Portfolio: https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/
- GitHub: https://github.com/sanjeev200009
- Education: BIT (Hons) in Networking & Mobile Computing, Horizon Campus
- Experience: Under 1 year (fresh/junior — recently promoted from Web Developer Intern to Associate Product & AI Engineer)

KEY PRODUCTION ACHIEVEMENTS AT CAREER141 (TAILOR BASED ON SPECIALIZED FOCUS):
- Built and owns an autonomous 13-stage AI recruitment pipeline processing 115,000+ candidate profiles
- Engineered a custom email automation platform that cut email delivery costs by 78%
- Rebuilt the Career141 Next.js 15 website from scratch (production, live)
- Integrated WhatsApp Business API automation workflows for recruiter communications
- Delivered LLM-powered AI workflows using Python, FastAPI, and cloud infrastructure (AWS, Cloudflare, Supabase, Convex)

CORE SKILLS: Python, FastAPI, React.js, Next.js 15, JavaScript, TypeScript, Node.js, PostgreSQL, REST APIs, WebSockets, Git, Docker, Linux, AWS, Cloudflare, Supabase, Convex, LLM integrations

RULES:
1. Write 2 to 3 body paragraphs explaining how the candidate's technical skills match the job description.
2. The email MUST be personalized to the SPECIFIC COMPANY NAME ({company}) and SPECIFIC JOB TITLE ({job_title}).
3. Identify 3-5 specific requirements from the job description that match the candidate's real skills.
4. Apply the {category_focus} specialization instructions provided above.
5. Use a professional but warm tone. Not robotic. Not generic.
6. DO NOT invent skills, fake projects, or false experience.
7. DO NOT mention salary, expected compensation, or notice period anywhere.
8. Include a note that CV/resume is attached to this email.
9. Output ONLY the 2-3 body paragraphs. DO NOT output any reasoning, thinking process, greetings, headers, subject lines, or sign-offs."""

            user = (
                f"COMPANY: {company}\n"
                f"JOB TITLE: {job_title}\n"
                f"MATCH REASON: {match_reason}\n\n"
                f"JOB DESCRIPTION:\n{job_desc[:3000]}\n\n"
                f"CANDIDATE CV:\n{cv_text[:2500]}"
            )
            raw = self.chat(
                settings.cover_letter_model, system, user, max_tokens=3000, json_mode=False
            ).strip()

            # 1. Anchor to the real opening. The anchor must start a line: the
            #    old word-boundary IGNORECASE pattern matched the word "with" inside the
            #    model's own thinking ("I should open with the production
            #    systems...") and sliced the letter mid-sentence, yielding
            #    "Dear Hiring Manager at X," + "with the production systems..".
            #    Take the LAST opening -- thinking often quotes a draft first.
            _openings = list(re.finditer(
                r"^\s*(I am writing|I'm writing|I write to|As a\b|With\b|My technical\b|Having\b)",
                raw,
                re.IGNORECASE | re.MULTILINE,
            ))
            text = raw[_openings[-1].start():] if _openings else raw

            # 2. Filter out any inline labels or numbered draft bullets
            lines = text.splitlines()
            clean_lines = []
            for line in lines:
                l_strip = line.strip()
                if not l_strip:
                    clean_lines.append("")
                    continue
                l_lower = l_strip.lower()
                if re.match(r'^\*?(paragraph\s+\d+|draft\s+\d+|drafting)\b', l_lower):
                    continue
                clean_lines.append(l_strip)

            body_text = "\n".join(clean_lines).strip()

            # 3. Strip any accidental greeting or signature the LLM outputted
            body_text = re.sub(r'^Dear\s+.*?\n+', '', body_text, flags=re.IGNORECASE).strip()
            body_text = re.sub(r'(Sincerely|Best regards|Thanks|Regards),?.*$', '', body_text, flags=re.IGNORECASE | re.DOTALL).strip()
            body_text = re.sub(r'\n{3,}', '\n\n', body_text).strip()

            if body_text and len(body_text) > 80:
                header = f"Dear Hiring Manager at {company},\n\n"
                signature = f"\n\nSincerely,\n{settings.candidate_first_name} {settings.candidate_last_name}\nEmail: {settings.email_user}\nPhone: +94 753 883 167\nPortfolio: https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/\nGitHub: https://github.com/sanjeev200009\nLocation: Colombo, Sri Lanka"
                return {"subject": subject, "body": f"{header}{body_text}{signature}"}



        except Exception as exc:
            print(f"  [llm] Fallback for email application: {exc}")

        return {"subject": subject, "body": fallback_body}