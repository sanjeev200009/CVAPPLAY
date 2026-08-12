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
- Name: Sivasuthakaran Sanjeev (Colombo, Sri Lanka — Remote applicant)
- Practical Experience: UNDER 1 YEAR (~0-1 year total experience).
- Core Stack: Python, FastAPI, Node.js, JavaScript, TypeScript, React.js, Next.js, REST APIs, PostgreSQL, Git, LiveKit, WebSockets.

STRICT SCREENING RULES:
1. EXPERIENCE HARD CEILING: If the JD requires 2+, 3+, 4+, or 5+ years of experience, or is a Mid/Senior/Staff/Lead/Principal role, you MUST give score < 30 and recommended: false.
2. HIGH SCORE (75-100): True entry-level, junior, associate, graduate, intern, or early-career roles (0-1 yr exp) that align with candidate's modern web/full-stack tech stack.
3. Extract salary/compensation mentioned in the JD (e.g. "$50,000 - $70,000", "€40k/yr", "$35/hr") or write "Not specified".
4. Write a 1-2 sentence concise plain-text summary of what the role actually entails.

Output JSON ONLY:
{
  "score": <int 0-100>,
  "recommended": <bool>,
  "reason": "<short 1-line reason>",
  "experience_requirement_years": <int>,
  "salary": "<extracted salary or 'Not specified'>",
  "summary": "<1-2 sentence plain-language description of what this job does>"
}"""


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
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
            "model": settings.nvidia_model or "nvidia/nemotron-3.5-lightning-30b-a3b",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        for attempt in range(2):
            try:
                print(f"  ⚡ Switching to NVIDIA NIM Fallback ({settings.nvidia_model})...")
                resp = requests.post(url, headers=headers, json=payload, timeout=90)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"] or ""
                # Clean thinking process preamble and instruction echo if output by reasoning models
                subj_match = re.search(r'(Subject:\s*Application for.*)', content, re.IGNORECASE | re.DOTALL)
                if subj_match:
                    content = subj_match.group(1).strip()
                elif "Dear " in content:
                    content = content[content.find("Dear "):].strip()
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
                print(f"  ⚠️ NVIDIA NIM attempt {attempt + 1} error: {exc}")
                time.sleep(2)

        return None



    def chat(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 700,
        json_mode: bool = True,
    ) -> str:
        # ── EXCLUSIVE PRIMARY ENGINE: NVIDIA NIM (Nemotron 3.5 Lightning 30B) ──
        nvidia_res = self._call_nvidia_nim(system, user, max_tokens)
        if nvidia_res:
            return nvidia_res

        raise RuntimeError("NVIDIA NIM service temporarily busy - using instant template generator")




    def parse_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
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
        text = self.chat(settings.scoring_model, SCORE_SYSTEM, user, max_tokens=400)
        data = self.parse_json(text)
        sal = str(data.get("salary", "")).strip()
        if not sal or sal.lower() in ("not specified", "none", "null"):
            from .filters import extract_salary
            sal = extract_salary(job_desc)

        return {
            "score": int(data.get("score", 0)),
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
        match_reason: str = "",
    ) -> dict[str, str]:
        subject = f"Application for {job_title} — Sivasuthakaran Sanjeev"
        fallback_body = f"""Dear Hiring Manager at {company},

I am writing to express my strong interest in the {job_title} position at {company}. As a Junior Software Engineer based in Colombo, Sri Lanka, with practical experience building modern web applications using Python, React, JavaScript, Node.js, and REST APIs, I am excited about the opportunity to contribute to your engineering team.

Key highlights of my qualifications include:
- Hands-on development experience building scalable backend APIs with Python (FastAPI/Flask) and Node.js.
- Frontend web development skills in React.js, Next.js, HTML5/CSS3, and responsive UI design.
- Proficiency in relational databases (PostgreSQL), Git version control, WebSockets, and Linux environments.

My complete CV/resume is attached to this email. You can also view my live portfolio at https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/ and my GitHub at https://github.com/sanjeev200009.

Thank you for your time and consideration. I look forward to the opportunity to discuss how my technical skills align with {company}'s goals.

Sincerely,
Sivasuthakaran Sanjeev
Email: sanjaysanjeev2000@gmail.com
Phone: +94 753 883 167
Portfolio: https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/
GitHub: https://github.com/sanjeev200009
Location: Colombo, Sri Lanka"""

        try:
            system = f"""You are a professional job application email writer. Write a compelling, 
personalized job application email from a junior software developer to a recruiter.

CANDIDATE PROFILE:
- Full Name: Sivasuthakaran Sanjeev
- Location: Colombo, Sri Lanka (available for fully remote roles worldwide)
- Email: sanjaysanjeev2000@gmail.com
- Phone: +94 753 883 167
- Portfolio: https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/
- GitHub: https://github.com/sanjeev200009
- Experience: Under 1 year (fresh/junior developer)
- Core Skills: Python, FastAPI, React.js, Next.js, JavaScript, TypeScript, Node.js, PostgreSQL, REST APIs, WebSockets, Git, Docker basics, Linux

RULES:
1. Write a COMPLETE email - subject line on the first line as "Subject: [subject]", then a blank line, then the full body.
2. The email MUST be personalized to the SPECIFIC COMPANY NAME and SPECIFIC JOB TITLE.
3. Identify 3-5 specific requirements from the job description that match the candidate's real skills.
4. Use a professional but warm tone. Not robotic. Not generic.
5. Keep the body between 180-250 words.
6. End with FULL contact info block (name, email, phone, portfolio, GitHub).
7. DO NOT invent skills, fake projects, or false experience.
8. DO NOT mention salary, expected compensation, or notice period anywhere in the email.
9. Always attach a note that CV/resume is attached to this email.

OUTPUT FORMAT (exactly):
Subject: [your subject line]

[full email body starting with Dear...]"""


            user = (
                f"COMPANY: {company}\n"
                f"JOB TITLE: {job_title}\n"
                f"MATCH REASON: {match_reason}\n\n"
                f"JOB DESCRIPTION:\n{job_desc[:3000]}\n\n"
                f"CANDIDATE CV:\n{cv_text[:2500]}"
            )
            raw = self.chat(
                settings.cover_letter_model, system, user, max_tokens=800, json_mode=False
            ).strip()

            # Clean out any thinking preamble if present
            if "Dear " in raw:
                dear_idx = raw.find("Dear ")
                body_candidate = raw[dear_idx:].strip()
                # Check for Subject before Dear
                header_part = raw[:dear_idx]
                for line in header_part.splitlines():
                    if line.lower().startswith("subject:"):
                        subject = line[8:].strip()
                        break
                if body_candidate:
                    return {"subject": subject, "body": body_candidate}

            lines = raw.splitlines()
            body_lines = lines
            for i, line in enumerate(lines):
                if line.lower().startswith("subject:"):
                    subject = line[8:].strip()
                    body_lines = lines[i + 1:]
                    break

            body = "\n".join(body_lines).strip()
            if body and len(body) > 100:
                return {"subject": subject, "body": body}
        except Exception as exc:
            print(f"  ⚠️ LLM call fallback for email application: {exc}")

        return {"subject": subject, "body": fallback_body}