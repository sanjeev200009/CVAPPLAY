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

        try:
            system = f"""You are a professional job application email writer. Write a compelling, 
personalized job application email body (2 to 3 paragraphs, 150-200 words) from a junior software developer to a recruiter.

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
1. Write 2 to 3 body paragraphs explaining how the candidate's technical skills match the job description.
2. The email MUST be personalized to the SPECIFIC COMPANY NAME ({company}) and SPECIFIC JOB TITLE ({job_title}).
3. Identify 3-5 specific requirements from the job description that match the candidate's real skills.
4. Use a professional but warm tone. Not robotic. Not generic.
5. DO NOT invent skills, fake projects, or false experience.
6. DO NOT mention salary, expected compensation, or notice period anywhere.
7. Include a note that CV/resume is attached to this email.
8. Output ONLY the 2-3 body paragraphs. DO NOT output any reasoning, thinking process, greetings, headers, subject lines, or sign-offs."""

            user = (
                f"COMPANY: {company}\n"
                f"JOB TITLE: {job_title}\n"
                f"MATCH REASON: {match_reason}\n\n"
                f"JOB DESCRIPTION:\n{job_desc[:3000]}\n\n"
                f"CANDIDATE CV:\n{cv_text[:2500]}"
            )
            raw = self.chat(
                settings.cover_letter_model, system, user, max_tokens=700, json_mode=False
            ).strip()

            # Filter raw output by paragraphs, dropping reasoning / thinking thoughts
            paragraphs = raw.split("\n\n")
            real_paragraphs = []
            for p in paragraphs:
                p_str = p.strip()
                if not p_str:
                    continue
                p_lower = p_str.lower()
                if any(k in p_lower for k in ("thinking process", "analyze the request", "candidate has:", "jd says:", "candidate profile:", "rules:", "- **role:", "- **output:", "- **candidate:", "- **skills:", "- **company:", "- **job title:", "- **rules:")):
                    continue
                if p_str.startswith(("- **", "* **", "1. **", "2. **", "3. **")):
                    continue
                real_paragraphs.append(p_str)

            body_text = "\n\n".join(real_paragraphs).strip()

            # Strip any accidental greeting or signature the LLM outputted
            body_text = re.sub(r'^Dear\s+.*?\n+', '', body_text, flags=re.IGNORECASE).strip()
            body_text = re.sub(r'(Sincerely|Best regards|Thanks|Regards),?.*$', '', body_text, flags=re.IGNORECASE | re.DOTALL).strip()

            if body_text and len(body_text) > 80:
                header = f"Dear Hiring Manager at {company},\n\n"
                signature = f"\n\nSincerely,\n{settings.candidate_first_name} {settings.candidate_last_name}\nEmail: {settings.email_user}\nPhone: +94 753 883 167\nPortfolio: https://sanjeev200009.github.io/Sivasuthakaran-Sanjeev-Portfolio/\nGitHub: https://github.com/sanjeev200009\nLocation: Colombo, Sri Lanka"
                return {"subject": subject, "body": f"{header}{body_text}{signature}"}


        except Exception as exc:
            print(f"  ⚠️ LLM call fallback for email application: {exc}")

        return {"subject": subject, "body": fallback_body}